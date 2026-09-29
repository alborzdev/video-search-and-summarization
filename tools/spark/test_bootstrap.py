import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('spark_bootstrap', Path(__file__).with_name('bootstrap.py'))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BootstrapTests(unittest.TestCase):
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
                b.render('192.0.2.10', str(state / 'data'), '172.17.0.1')
                rendered = (state / 'compose.json').read_text()
                graph = json.loads(rendered)
                self.assertNotIn('test-credential-must-not-leak', rendered)
                self.assertNotIn('10.0.0.99', rendered)
                self.assertEqual((state / 'compose.json').stat().st_mode & 0o777, 0o600)
                services = graph['services']
                self.assertNotIn('tegrastats-exporter', services)
                self.assertNotIn('perception-2d-fusion', services)
                self.assertIn('-sbsa', services['rtvi-vlm']['build']['args']['BASE_IMAGE'])
                self.assertIn('-sbsa', services['lvs-server']['build']['args']['LVS_BASE_IMAGE'])
                self.assertEqual(services['rtvi-embed']['environment']['HF_HUB_OFFLINE'], '0')
                self.assertEqual(services['rtvi-embed']['environment']['KAFKA_ENABLED'], 'true')
                self.assertEqual(services['lvs-server']['environment']['LVS_EMB_DIMENSIONS'], '768')
                self.assertIn(state / 'data/data_log/kafka', b.data_roots(graph, state / 'data'))
                self.assertIn('/vss-agent/deploy/docker/', services['vss-va-mcp']['command'][3])
                self.assertIn('services/ui/Dockerfile', services['vss-ui']['build']['dockerfile'])
                self.assertTrue(all(s['restart'] == 'no' for s in services.values()))
                self.assertFalse(any(v.get('external') for v in graph['volumes'].values()))
                for s in services.values():
                    for mount in s.get('volumes', []):
                        if mount.get('type') == 'bind' and '/data/' in mount['source'] and mount['source'].startswith(temp):
                            self.assertFalse(mount['bind']['create_host_path'])

if __name__ == '__main__':
    unittest.main()
