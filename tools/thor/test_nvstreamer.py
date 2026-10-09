"""Admission and isolation checks for the optional mock camera server."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import nvstreamer as n


class NVStreamerTests(unittest.TestCase):
    def test_guard_failure_prevents_start(self):
        with patch.object(n.thor, 'require_guard', side_effect=RuntimeError('stale thermal')), \
                patch.object(n, 'render') as render, patch.object(n.thor, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'stale thermal'):
                n.start()
            render.assert_not_called()
            run.assert_not_called()

    def test_full_sidecar_budget_must_fit_above_floor(self):
        with patch.object(n.thor, 'require_guard'), patch.object(n.thor.shared, 'available', return_value=51.99), \
                patch.object(n.thor, 'memory_reserve', return_value=48), \
                patch.object(n, 'render') as render:
            with self.assertRaisesRegex(RuntimeError, 'plus 4 GiB'):
                n.start()
            render.assert_not_called()

    def test_build_refuses_running_ai_before_pull_or_build(self):
        with patch.object(n.thor, 'require_guard'), patch.object(n.thor.shared, 'available', return_value=100), \
                patch.object(n.shutil, 'disk_usage', return_value=Mock(free=300 * 1024**3)), \
                patch.object(n.thor, 'run', return_value=Mock(stdout='active-model\n')) as run:
            with self.assertRaisesRegex(RuntimeError, 'Stop AI'):
                n.stage()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], 'docker')
            self.assertIn('ps', run.call_args.args[0])

    def test_sidecar_is_guarded_and_does_not_reuse_vios_data(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with patch.object(n.thor, 'STATE', state), patch.object(n, 'GRAPH', state / 'compose.json'), \
                    patch.object(n.thor, 'settings', return_value={'host_ip': '192.0.2.1', 'data_dir': str(state / 'data')}), \
                    patch.object(n.thor, 'run', return_value=Mock(stdout=json.dumps([
                        {'Id': 'sha256:owned-image', 'Architecture': 'arm64'}]))):
                n.render()
                graph = json.loads(n.GRAPH.read_text())
                self.assertEqual(list(graph['services']), ['nvstreamer'])
                service = graph['services']['nvstreamer']
                self.assertEqual(service['image'], 'sha256:owned-image')
                self.assertEqual(service['restart'], 'no')
                self.assertEqual(service['mem_limit'], service['memswap_limit'])
                self.assertEqual(service['mem_limit'], '4g')
                volumes = '\n'.join(service['volumes'])
                self.assertIn('/data/nvstreamer/videos:', volumes)
                self.assertNotIn('/data_log/vst/', volumes)
                self.assertNotIn('down', n.compose('stop', 'nvstreamer'))
                self.assertIn('vss-thor', n.compose('stop', 'nvstreamer'))
                cfg = json.loads((state / 'nvstreamer-config.json').read_text())
                self.assertEqual(cfg['network']['stunurl_list'], [])
                self.assertEqual(cfg['network']['webrtc_port_range'], {'min': 32001, 'max': 32100})


if __name__ == '__main__':
    unittest.main()
