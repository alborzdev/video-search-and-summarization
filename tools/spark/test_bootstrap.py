import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spark_bootstrap', Path(__file__).with_name('bootstrap.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
guard_spec = importlib.util.spec_from_file_location('spark_guard', Path(__file__).with_name('guard.py'))
guard = importlib.util.module_from_spec(guard_spec)
with patch.dict(sys.modules, {'bootstrap': b}):
    guard_spec.loader.exec_module(guard)


class BootstrapTests(unittest.TestCase):
    def test_cache_advice_keeps_files_and_skips_escaping_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'candidate-cache'
            root.mkdir()
            weights = root / 'weights.bin'
            contents = b'x' * 1048576
            weights.write_bytes(contents)
            outside = Path(temp) / 'other-workload.bin'
            outside.write_bytes(contents)
            (root / 'outside-link.bin').symlink_to(outside)
            (root / 'config.json').write_text('{}')
            output = io.StringIO()
            with patch.object(sys, 'argv', ['cache-advice', str(root)]), \
                 patch.object(os, 'posix_fadvise') as advice, contextlib.redirect_stdout(output):
                exec(compile(b.CACHE_RECLAIM_SCRIPT, 'cache-advice', 'exec'), {})
            self.assertEqual(advice.call_count, 1)
            self.assertEqual(advice.call_args.args[1:], (0, 0, os.POSIX_FADV_DONTNEED))
            self.assertEqual(json.loads(output.getvalue())['advised_bytes'], len(contents))
            self.assertEqual(weights.read_bytes(), contents)
            self.assertEqual(outside.read_bytes(), contents)

    def test_guard_boundary_trip_and_recovery(self):
        writes = []
        with patch.object(guard, 'stop') as stop, patch.object(guard, 'memory_reserve', return_value=24), \
             patch.object(guard, 'available', side_effect=[24, 23.9, 22, 25, 23, 24]), \
             patch.object(guard, 'private_write', side_effect=lambda path, value: writes.append((path.name, json.loads(value)))), \
             patch.object(guard.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'candidate-a\ncandidate-b\n')) as run, \
             patch.object(guard, 'halt', return_value={'code': 0}) as halt:
            stop.wait.side_effect = [False] * 6 + [True]
            guard.main()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(halt.call_count, 4)
            self.assertTrue(all(call.args[0] in ['candidate-a', 'candidate-b'] for call in halt.call_args_list))
            self.assertTrue(all(call.args[0] == b.compose('ps', '-q') for call in run.call_args_list))
        trips = [value for name, value in writes if name == 'guard-trip.json']
        self.assertEqual([trip['available_gib'] for trip in trips], [23.9, 23])
        self.assertTrue(all(value['floor_gib'] == 24 for _, value in writes))

    def test_saved_reserve_and_model_admission(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b, 'STATE', Path(temp)):
            self.assertEqual(b.memory_reserve(), 48)
            settings = b.STATE / 'settings.json'
            settings.write_text(json.dumps({'reserve_gib': 24}))
            self.assertEqual(b.memory_reserve(), 24)
            self.assertEqual(b.model_admission_gib('spark-llm'), 48)
            self.assertEqual(b.model_admission_gib('rtvi-embed'), 44)
            self.assertEqual(b.model_admission_gib('rtvi-vlm'), 48)
            for invalid in [0, -1, True, '24', float('nan'), float('inf')]:
                with self.subTest(invalid=invalid):
                    settings.write_text(json.dumps({'reserve_gib': invalid}))
                    with self.assertRaises(RuntimeError):
                        b.memory_reserve()

    def test_dependency_order_and_cycle(self):
        services = {'api': {'depends_on': {'model': {}}}, 'model': {'depends_on': {'broker': {}}}, 'broker': {}}
        self.assertEqual(b.startup_order(services, ['broker'], ['model'], ['api']), ['broker', 'model', 'api'])
        services['broker'] = {'depends_on': {'api': {}}}
        with self.assertRaisesRegex(RuntimeError, 'cycle'):
            b.startup_order(services, ['broker'], ['model'], ['api'])

    def test_host_guard_refuses_thor(self):
        with patch.object(b.platform, 'machine', return_value='aarch64'), patch.object(b, 'run', return_value=subprocess.CompletedProcess([], 0, 'NVIDIA Thor\n')):
            with self.assertRaisesRegex(RuntimeError, 'not a DGX Spark'):
                b.doctor()

    def test_actual_compose_render_and_secret_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            with patch.object(b, 'STATE', state), patch.dict(b.os.environ, {'NGC_API_KEY': 'test-credential-must-not-leak', 'HOST_IP': '10.0.0.99'}):
                b.render('192.0.2.10', str(state / 'data'), '172.17.0.1', 'https://registry.yarnpkg.com', 24)
                rendered = (state / 'compose.json').read_text()
                graph = json.loads(rendered)
                self.assertNotIn('test-credential-must-not-leak', rendered)
                self.assertNotIn('10.0.0.99', rendered)
                self.assertEqual((state / 'compose.json').stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads((state / 'settings.json').read_text())['reserve_gib'], 24)
                services = graph['services']
                self.assertNotIn('tegrastats-exporter', services)
                self.assertNotIn('perception-2d-fusion', services)
                self.assertIn('-sbsa', services['rtvi-vlm']['build']['args']['BASE_IMAGE'])
                self.assertEqual(services['rtvi-vlm']['environment']['VLM_RECLAIM_MODEL_FILE_CACHE'], 'true')
                self.assertEqual(services['rtvi-vlm']['environment']['VLM_FILE_CACHE_RECLAIM_ROOT'], '/opt/nvidia/rtvi/.rtvi/ngc_model_cache')
                self.assertEqual(services['rtvi-embed']['build']['args']['BASE_IMAGE'], 'nvcr.io/nvidia/vss-core/vss-rt-embed:3.2.1-sbsa')
                self.assertIn('-sbsa', services['lvs-server']['build']['args']['LVS_BASE_IMAGE'])
                self.assertEqual(services['rtvi-embed']['environment']['HF_HUB_OFFLINE'], '0')
                self.assertEqual(services['rtvi-embed']['environment']['KAFKA_ENABLED'], 'true')
                self.assertEqual(services['lvs-server']['environment']['LVS_EMB_DIMENSIONS'], '768')
                self.assertIn(state / 'data/data_log/kafka', b.data_roots(graph, state / 'data'))
                self.assertIn('/vss-agent/deploy/docker/', services['vss-va-mcp']['command'][3])
                self.assertIn('services/ui/Dockerfile', services['vss-ui']['build']['dockerfile'])
                self.assertEqual(services['vss-ui']['build']['args']['NPM_CONFIG_REGISTRY'], 'https://registry.yarnpkg.com')
                models = ['spark-llm', 'rtvi-embed', 'rtvi-vlm']
                late = ['vss-agent', 'vss-ui', 'vss-haproxy-ingress', 'lvs-server', 'alert-bridge', 'vss-va-mcp']
                early = [name for name in services if name not in models + late]
                order = b.startup_order(services, early, models, late)
                self.assertLess(order.index('kafka-topic-init-container'), order.index('broker-health-check'))
                self.assertEqual(services['broker-health-check']['depends_on']['kafka-topic-init-container']['condition'], 'service_completed_successfully')
                cache_init = services['spark-llm-cache-init']
                self.assertEqual(cache_init['user'], '0:0')
                self.assertEqual(cache_init['volumes'], services['spark-llm']['volumes'])
                self.assertIn('chown 1000:1000 /opt/nim/.cache', cache_init['entrypoint'][2])
                self.assertEqual(services['spark-llm']['depends_on']['spark-llm-cache-init']['condition'], 'service_completed_successfully')
                self.assertLess(order.index('spark-llm-cache-init'), order.index('spark-llm'))
                self.assertEqual(services['spark-llm']['environment']['NIM_MAX_BATCH_SIZE'], '1')
                self.assertEqual(services['spark-llm']['environment']['NIM_GPU_MEM_FRACTION'], '0.11')
                self.assertEqual(services['spark-llm']['environment']['NIM_MAX_MODEL_LEN'], '32768')
                self.assertNotIn('MAX_NUM_SEQS', services['spark-llm']['environment'])
                self.assertEqual(services['vss-agent']['environment']['LLM_NAME'], 'nvidia/nemotron-nano-9b-v2')
                self.assertEqual(services['vss-haproxy-ingress']['environment']['VSS_AGENT_BACKEND_HOST'], '127.0.0.1')
                self.assertEqual(services['lvs-server']['environment']['LVS_LLM_MODEL_NAME'], 'nvidia/nemotron-nano-9b-v2')
                self.assertIn('"$${status}"', services['logstash']['healthcheck']['test'][1])
                self.assertTrue(all(s['restart'] == 'no' for s in services.values()))
                self.assertFalse(any(v.get('external') for v in graph['volumes'].values()))
                for s in services.values():
                    for mount in s.get('volumes', []):
                        if mount.get('type') == 'bind' and '/data/' in mount['source'] and mount['source'].startswith(temp):
                            self.assertFalse(mount['bind']['create_host_path'])
                b.render('192.0.2.10', str(state / 'data'), '172.17.0.1', 'https://registry.yarnpkg.com')
                self.assertEqual(b.memory_reserve(), 24)
                b.render('192.0.2.10', str(state / 'data'), '172.17.0.1', 'https://registry.yarnpkg.com', cached_models=True)
                cached = json.loads((state / 'compose.json').read_text())['services']
                for name in models:
                    self.assertEqual(cached[name]['environment']['NGC_API_KEY'], '')
                    self.assertEqual(cached[name]['environment']['HF_HUB_OFFLINE'], '1')
                self.assertEqual(cached['spark-llm']['environment']['NIM_DISABLE_MODEL_DOWNLOAD'], '1')
                self.assertFalse(cached['rtvi-vlm']['environment']['MODEL_PATH'].startswith('ngc:'))
                self.assertTrue(json.loads((state / 'settings.json').read_text())['cached_models'])

if __name__ == '__main__':
    unittest.main()
