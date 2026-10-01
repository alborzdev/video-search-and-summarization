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
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('spark_bootstrap', Path(__file__).with_name('bootstrap.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
guard_spec = importlib.util.spec_from_file_location('spark_guard', Path(__file__).with_name('guard.py'))
guard = importlib.util.module_from_spec(guard_spec)
with patch.dict(sys.modules, {'bootstrap': b}):
    guard_spec.loader.exec_module(guard)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        for module in (b, guard):
            patcher = patch.object(module, 'STATE', Path(state.name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_private_write_failure_preserves_previous_complete_settings(self):
        path = b.STATE / 'settings.json'
        b.private_write(path, '{"reserve_gib":24}')
        with patch.object(b.os, 'replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                b.private_write(path, '{"reserve_gib":25}')
        self.assertEqual(json.loads(path.read_text()), {'reserve_gib': 24})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(b.STATE.iterdir()), [path])

    def test_startup_readiness_docker_queries_have_deadlines(self):
        with patch.object(b, 'available', return_value=40), patch.object(b, 'memory_reserve', return_value=24), \
             patch.object(b, 'run', side_effect=[Mock(stdout='candidate'),
                Mock(stdout=json.dumps({'Status': 'running', 'Health': {'Status': 'healthy'}}))]) as run:
            b.await_service('service')
        self.assertTrue(all(call.kwargs['timeout'] == 15 for call in run.call_args_list))

    def test_completed_jobs_are_inferred_from_dependency_contract(self):
        graph = {'services': {'new-init': {'restart': 'no'},
            'consumer': {'depends_on': {'new-init': {'condition': 'service_completed_successfully'}}}}}
        self.assertIn('new-init', b.completed_services(graph))
        self.assertNotIn('consumer', b.completed_services(graph))

    def test_failed_or_dead_init_does_not_wait_an_hour(self):
        for state in ({'Status': 'dead'}, {'Status': 'exited', 'ExitCode': 1}):
            with self.subTest(state=state), patch.object(b, 'available', return_value=40), \
                 patch.object(b, 'memory_reserve', return_value=24), patch.object(b.time, 'sleep') as sleep, \
                 patch.object(b, 'run', side_effect=[Mock(stdout='candidate'), Mock(stdout=json.dumps(state)),
                     Mock(stdout='', stderr='')]):
                with self.assertRaises(RuntimeError):
                    b.await_service('init', one_shot=True)
                sleep.assert_not_called()

    def test_unhealthy_dependency_reports_last_probe_instead_of_waiting_an_hour(self):
        state = {'Status': 'running', 'Health': {'Status': 'unhealthy',
                 'Log': [{'Output': 'Connection refused'}]}}
        with patch.object(b, 'available', return_value=40), patch.object(b, 'memory_reserve', return_value=24), \
             patch.object(b.time, 'sleep') as sleep, \
             patch.object(b, 'run', side_effect=[Mock(stdout='candidate'), Mock(stdout=json.dumps(state))]):
            with self.assertRaisesRegex(RuntimeError, 'service failed.*Connection refused'):
                b.await_service('service')
            sleep.assert_not_called()

    def test_online_codec_staging_rejects_bad_download_without_replacing_existing_cache(self):
        path = b.STATE / 'offline-tools' / b.CODEC_WHEEL_NAME
        path.parent.mkdir()
        path.write_bytes(b'old-cache')
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = [b'invalid-download', b'']
        with patch.object(b.urllib.request, 'urlopen', return_value=response) as download:
            with self.assertRaisesRegex(RuntimeError, 'pinned uv.lock'):
                b.stage_codec_wheel()
            download.assert_called_once_with(b.CODEC_WHEEL_URL, timeout=60)
        self.assertEqual(path.read_bytes(), b'old-cache')
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_lvs_source_override_replaces_only_exact_target_and_is_idempotent(self):
        target = '/opt/nvidia/via/via-engine/via_stream_handler.py'
        llm_target = '/usr/local/lib/python3.13/site-packages/vss_ctx_rag/tools/llm/llm_handler.py'
        unrelated = {'type': 'bind', 'source': '/existing/config.yml', 'target': '/app/config.yaml', 'read_only': True}
        service = {'image': 'cached-lvs', 'environment': {'OFFLINE': 'true'}, 'mem_limit': '2g',
                   'volumes': [unrelated, {'source': '/stale/handler.py', 'target': target},
                               {'source': '/duplicate/handler.py', 'target': target},
                               {'source': '/stale/llm.py', 'target': llm_target},
                               {'source': '/duplicate/llm.py', 'target': llm_target}]}
        graph = {'services': {'lvs-server': service, 'model': {'image': 'cached-model'}}}
        b.booth_runtime_safety(graph)
        once = json.dumps(graph, sort_keys=True)
        b.booth_runtime_safety(graph)
        self.assertEqual(json.dumps(graph, sort_keys=True), once)
        self.assertEqual(service['image'], 'cached-lvs')
        self.assertEqual(service['environment'], {'OFFLINE': 'true'})
        self.assertEqual(service['mem_limit'], '2g')
        self.assertEqual(service['volumes'][0], unrelated)
        self.assertEqual(service['volumes'][1:], [{'type': 'bind',
            'source': str(b.ROOT / 'services/video-summarization/src/via_stream_handler.py'),
            'target': target, 'read_only': True, 'bind': {'create_host_path': False}}, {'type': 'bind',
            'source': str(b.ROOT / 'services/video-summarization/src/llm_handler.py'),
            'target': '/usr/local/lib/python3.13/site-packages/vss_ctx_rag/tools/llm/llm_handler.py',
            'read_only': True, 'bind': {'create_host_path': False}}])

    def test_agent_recreation_uses_pinned_local_codec_without_changing_budgets(self):
        unrelated = {'source': '/existing', 'target': '/config'}
        agent = {'image': 'cached-agent', 'mem_limit': '8g', 'environment': {'OTHER': 'preserved'},
                 'volumes': [unrelated, {'source': '/stale', 'target': b.CODEC_WHEEL_TARGET}]}
        graph = {'services': {'vss-agent': agent}}
        b.booth_runtime_safety(graph)
        once = json.dumps(graph, sort_keys=True)
        b.booth_runtime_safety(graph)
        self.assertEqual(json.dumps(graph, sort_keys=True), once)
        self.assertEqual(agent['image'], 'cached-agent')
        self.assertEqual(agent['mem_limit'], '8g')
        self.assertEqual(agent['environment']['OTHER'], 'preserved')
        self.assertEqual(agent['environment']['VSS_PROPRIETARY_CODECS_WHEEL'], b.CODEC_WHEEL_TARGET)
        self.assertEqual(agent['environment']['VSS_PROPRIETARY_CODECS_MAX_RETRY_SECONDS'], '0')
        self.assertEqual(agent['volumes'], [unrelated, {'type': 'bind',
            'source': str(b.STATE / 'offline-tools' / b.CODEC_WHEEL_NAME), 'target': b.CODEC_WHEEL_TARGET,
            'read_only': True, 'bind': {'create_host_path': False}}])

    def test_booth_overlay_is_idempotent_and_preserves_unrelated_configuration(self):
        target = '/usr/local/lib/python3.13/site-packages/mdx/analytics/core/stream/source/source_kafka.py'
        graph = {'services': {
            'behavior-analytics': {'image': 'cached', 'environment': {'MODEL': 'unchanged'},
                'volumes': [{'source': '/existing', 'target': '/config'}], 'mem_limit': '1g'},
            'vss-behavior-analytics-thor-candidates': {'image': 'candidate'},
            'vss-search-analytics-2d-fusion': {'image': 'cached-fusion', 'container_name': 'vss-behavior-analytics'},
            'ba': {'image': 'cached-ba', 'container_name': 'vss-behavior-analytics'},
            'model': {'environment': {'OFFLINE': '1'}, 'logging': {'driver': 'local',
                'options': {'max-size': '5m', 'max-file': '2', 'compress': 'true'}}},
            'journal': {'logging': {'driver': 'journald', 'options': {'tag': 'existing'}}},
            'default': {'logging': {'driver': 'json-file', 'options': {'labels': 'existing', 'max-size': '0'}}},
            'vss-ui': {'environment': {'UNRELATED': 'preserved'}},
            'evidence-clip': {'environment': {'HISTORY_METADATA_TOKEN': 'test-token'}},
        }, 'volumes': {'cache': {'name': 'existing-cache'}}}
        original = json.loads(json.dumps(graph))
        b.booth_runtime_safety(graph)
        once = json.dumps(graph, sort_keys=True)
        b.booth_runtime_safety(graph)
        self.assertEqual(json.dumps(graph, sort_keys=True), once)
        self.assertEqual(graph['services']['model'], original['services']['model'])
        self.assertEqual(graph['services']['journal'], original['services']['journal'])
        self.assertEqual(graph['volumes'], original['volumes'])
        for name in ('behavior-analytics', 'vss-behavior-analytics-thor-candidates', 'vss-search-analytics-2d-fusion', 'ba'):
            mounts = graph['services'][name]['volumes']
            kafka = [mount for mount in mounts if mount['target'] == target]
            self.assertEqual(len(kafka), 1)
            self.assertTrue(kafka[0]['read_only'])
            self.assertFalse(kafka[0]['bind']['create_host_path'])
        self.assertEqual(graph['services']['behavior-analytics']['environment'], {'MODEL': 'unchanged'})
        self.assertEqual(graph['services']['behavior-analytics']['mem_limit'], '1g')
        self.assertEqual(graph['services']['default']['logging']['options'],
            {'labels': 'existing', 'max-size': '20m', 'max-file': '3'})
        self.assertEqual(graph['services']['vss-ui']['environment'], {'UNRELATED': 'preserved',
            'HARDWARE_PROFILE': 'DGX-SPARK', 'SPARK_CAPACITY_URL': 'http://127.0.0.1:8102/capacity',
            'HISTORY_METADATA_TOKEN': 'test-token'})

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

    def test_guard_retries_docker_failure_during_same_low_memory_interval(self):
        with patch.object(guard, 'stop') as stop, patch.object(guard, 'memory_reserve', return_value=24), \
             patch.object(guard, 'available', return_value=23), patch.object(guard.time, 'monotonic', side_effect=[0, 11, 11]), \
             patch.object(guard, 'private_write') as write, \
             patch.object(guard.subprocess, 'run', side_effect=[subprocess.TimeoutExpired('docker', 15),
                 subprocess.CompletedProcess([], 0, 'candidate\n')]) as run, \
             patch.object(guard, 'halt', return_value={'code': 0}) as halt:
            stop.wait.side_effect = [False, False, True]
            guard.main()
        self.assertEqual(run.call_count, 2)
        halt.assert_called_once_with('candidate')
        trips = [json.loads(call.args[1]) for call in write.call_args_list if call.args[0].name == 'guard-trip.json']
        self.assertEqual(trips[0]['error'], 'TimeoutExpired')
        self.assertEqual(trips[1]['stops'], [{'code': 0}])

    def test_guard_stops_workloads_even_when_status_disk_is_full(self):
        with patch.object(guard, 'stop') as stop, patch.object(guard, 'memory_reserve', return_value=24), \
             patch.object(guard, 'available', return_value=23), patch.object(guard, 'private_write', side_effect=OSError('disk full')), \
             patch.object(guard.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'candidate\n')), \
             patch.object(guard, 'halt', return_value={'code': 0}) as halt:
            stop.wait.side_effect = [False, True]
            guard.main()
        halt.assert_called_once_with('candidate')

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
            thor_vst_path = b.ROOT / 'deploy/docker/thor-local/vios/vst_config.json'
            thor_vst_before = thor_vst_path.read_bytes()
            with patch.object(b, 'STATE', state), patch.dict(b.os.environ, {'NGC_API_KEY': 'test-credential-must-not-leak', 'HOST_IP': '10.0.0.99'}):
                b.render('192.0.2.10', str(state / 'data'), '172.17.0.1', 'https://registry.yarnpkg.com', 24)
                rendered = (state / 'compose.json').read_text()
                graph_logs = json.loads(rendered)['services']
                self.assertTrue(all(service['logging']['options'].get('max-size') not in (None, '0', '-1')
                    and service['logging']['options'].get('max-file') for service in graph_logs.values()
                    if service['logging'].get('driver') in ('json-file', 'local')))
                graph = json.loads(rendered)
                self.assertNotIn('test-credential-must-not-leak', rendered)
                self.assertNotIn('10.0.0.99', rendered)
                self.assertEqual((state / 'compose.json').stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads((state / 'settings.json').read_text())['reserve_gib'], 24)
                services = graph['services']
                lvs_mounts = [mount for mount in services['lvs-server']['volumes']
                              if mount.get('target') == '/opt/nvidia/via/via-engine/via_stream_handler.py']
                self.assertEqual(lvs_mounts, [{'type': 'bind',
                    'source': str(b.ROOT / 'services/video-summarization/src/via_stream_handler.py'),
                    'target': '/opt/nvidia/via/via-engine/via_stream_handler.py',
                    'read_only': True, 'bind': {'create_host_path': False}}])
                llm_mounts = [mount for mount in services['lvs-server']['volumes']
                              if mount.get('target') == '/usr/local/lib/python3.13/site-packages/vss_ctx_rag/tools/llm/llm_handler.py']
                self.assertEqual(llm_mounts, [{'type': 'bind',
                    'source': str(b.ROOT / 'services/video-summarization/src/llm_handler.py'),
                    'target': '/usr/local/lib/python3.13/site-packages/vss_ctx_rag/tools/llm/llm_handler.py',
                    'read_only': True, 'bind': {'create_host_path': False}}])
                self.assertEqual(services['vss-agent']['environment']['VSS_TRAFFIC_RTVI_CV_URL'], '')
                spark_vst_path = state / 'vst-config.json'
                self.assertTrue(json.loads(spark_vst_path.read_text())['network']['rtsp_streaming_over_tcp'])
                self.assertEqual(thor_vst_path.read_bytes(), thor_vst_before)
                for name in ('sensor-ms', 'streamprocessing-ms'):
                    config_mount = next(m for m in services[name]['volumes']
                                        if m['target'] == '/home/vst/vst_release/configs/vst_config.json')
                    self.assertEqual(config_mount['source'], str(spark_vst_path))
                    self.assertTrue(config_mount['read_only'])
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
                self.assertEqual(cached['streamprocessing-ms']['environment']['VST_INSTALL_ADDITIONAL_PACKAGES'], 'false')
                self.assertNotIn('user_additional_install.sh', ' '.join(cached['streamprocessing-ms']['entrypoint']))
                self.assertIn('launch_vst', ' '.join(cached['streamprocessing-ms']['entrypoint']))
                self.assertFalse(cached['rtvi-vlm']['environment']['MODEL_PATH'].startswith('ngc:'))
                self.assertTrue(json.loads((state / 'settings.json').read_text())['cached_models'])
                topics = cached['kafka-topic-init-container']
                self.assertEqual(topics['environment']['KAFKA_INIT_OFFLINE'], 'true')
                parser = next(m for m in topics['volumes'] if m['target'] == '/usr/local/bin/jq')
                self.assertTrue(parser['read_only'])
                self.assertFalse(parser['bind']['create_host_path'])
                loader = next(m for m in cached['logstash']['volumes']
                              if m['target'] == '/usr/share/logstash/lib/bootstrap/environment.rb')
                self.assertTrue(loader['read_only'])

if __name__ == '__main__':
    unittest.main()
