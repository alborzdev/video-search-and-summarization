"""CPU-only lifecycle tests; never create a real unit or start GPU workloads."""
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import local_vision as local
import test_safety


class LocalVisionTests(unittest.TestCase):
    def setUp(self):
        test_safety.install(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        self.settings = {'reserve_gib': 20, 'local_vision_enabled': True,
                         'vlm_precision': 'nvfp4', 'detector_enabled': False}
        (self.state / 'settings.json').write_text(json.dumps(self.settings))

    def test_explicit_selection_preserves_other_models_and_private_token(self):
        graph = {'services': {'vss-ui': {'environment': {'EXISTING': 'kept'}},
                              'rtvi-vlm': {'image': 'existing', 'mem_limit': 'unchanged'}}}
        (self.state / 'compose.json').write_text(json.dumps(graph))
        with patch.object(local.subprocess, 'run') as commands:
            local.select(True, self.state)
            first = json.loads((self.state / 'compose.json').read_text())
            token = local.token_value(self.state)
            local.select(True, self.state)
            local.select(False, self.state)
        commands.assert_not_called()
        self.assertEqual(first['services']['rtvi-vlm'], graph['services']['rtvi-vlm'])
        env = first['services']['vss-ui']['environment']
        self.assertEqual(env['LOCAL_VISION_API_TOKEN'], token)
        self.assertFalse(any(key.startswith('NEXT_PUBLIC_') for key in env))
        self.assertEqual((self.state / 'local-segmentation/service-token').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.state / 'compose.json').stat().st_mode & 0o777, 0o600)
        settings = json.loads((self.state / 'settings.json').read_text())
        self.assertEqual(settings, {**self.settings, 'local_vision_enabled': False})
        self.assertEqual(json.loads((self.state / 'compose.json').read_text()), graph)

    def test_saved_choice_is_explicit_boolean_and_cached_graph_matches(self):
        self.assertFalse(local.selected({}))
        for invalid in ('true', 1, None):
            with self.assertRaises(RuntimeError):
                local.selected({'local_vision_enabled': invalid})
        graph = {'services': {'vss-ui': {'environment': {}}}}
        local.configure_graph(graph, state=self.state)
        self.assertEqual(graph['services']['vss-ui']['environment']['LOCAL_VISION_API_URL'], local.URL)

    def test_unit_is_vss_owned_guard_bound_and_offline(self):
        content = local.unit_content(self.state)
        self.assertIn('BindsTo=vss-spark-guard.service', content)
        self.assertIn('After=vss-spark-guard.service', content)
        self.assertIn('Restart=no', content)
        self.assertIn('MemoryMax=16G', content)
        self.assertIn('MemorySwapMax=0', content)
        self.assertIn('--host 127.0.0.1 --port 8026', content)
        self.assertIn('HF_HUB_OFFLINE=1', content)
        self.assertNotIn('WantedBy=', content)
        self.assertNotIn('[Install]', content)
        self.assertIn(f'WorkingDirectory={local.ROOT}\n', content)
        self.assertNotIn('WorkingDirectory="', content)

    @unittest.skipUnless(shutil.which('systemd-analyze'), 'systemd parser unavailable')
    def test_generated_unit_passes_systemd_directive_parser_without_starting(self):
        python = self.state / 'moondream-photon/venv/bin/python'
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        unit_dir = self.state / 'units'
        unit_dir.mkdir()
        path = unit_dir / local.UNIT
        path.write_text(local.unit_content(self.state))
        (unit_dir / local.GUARD).write_text('[Service]\nExecStart=/usr/bin/true\n')
        result = subprocess.run(['systemd-analyze', '--user', '--generators=no', 'verify', str(path)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_higher_saved_reserve_and_guard_are_required(self):
        (self.state / 'settings.json').write_text('{"reserve_gib":28}')
        with patch.object(local, 'active', return_value=True), patch.object(local, 'available_gib', return_value=27.9):
            with self.assertRaisesRegex(RuntimeError, '28 GiB'):
                local.admission(self.state)
        with patch.object(local, 'active', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'guard'):
                local.admission(self.state)

    def test_five_gib_reserve_is_accepted_without_extra_startup_allowance(self):
        (self.state / 'settings.json').write_text('{"reserve_gib":5}')
        with patch.object(local, 'active', return_value=True), patch.object(local, 'available_gib', return_value=5):
            self.assertEqual(local.admission(self.state), 5)

    def test_zero_reserve_keeps_guard_requirement_without_memory_floor(self):
        (self.state / 'settings.json').write_text('{"reserve_gib":0}')
        with patch.object(local, 'active', return_value=True), patch.object(local, 'available_gib', return_value=0.5):
            self.assertEqual(local.admission(self.state), 0)
        with patch.object(local, 'active', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'guard'):
                local.admission(self.state)

    def test_disabled_start_does_not_install_or_run(self):
        (self.state / 'settings.json').write_text('{"reserve_gib":20,"local_vision_enabled":false}')
        with patch.object(local, 'install_unit') as install, patch.object(local, 'active', return_value=False) as active:
            self.assertFalse(local.ensure_service(self.state))
        install.assert_not_called()
        active.assert_called_once_with(local.UNIT)

    def test_disabled_choice_stops_previously_resident_service(self):
        (self.state / 'settings.json').write_text('{"reserve_gib":20,"local_vision_enabled":false}')
        with patch.object(local, 'active', return_value=True), patch.object(local, 'stop_service') as stop:
            self.assertFalse(local.ensure_service(self.state))
        stop.assert_called_once()

    def test_ui_private_env_comparison_detects_enable_disable_and_token_change(self):
        graph = {'services': {'vss-ui': {'container_name': 'vss-ui-test', 'environment': {
            'LOCAL_VISION_API_URL': local.URL, 'LOCAL_VISION_API_TOKEN': 'private-token'}}}}
        actual = ['LOCAL_VISION_API_URL=' + local.URL, 'LOCAL_VISION_API_TOKEN=private-token', 'UNRELATED=kept']
        with patch.object(local.subprocess, 'run', return_value=Mock(stdout=json.dumps(actual))):
            self.assertTrue(local.ui_configuration_matches(graph))
            graph['services']['vss-ui']['environment']['LOCAL_VISION_API_TOKEN'] = 'rotated'
            self.assertFalse(local.ui_configuration_matches(graph))
            graph['services']['vss-ui']['environment'] = {}
            self.assertFalse(local.ui_configuration_matches(graph))

    def test_ready_resident_service_is_reused_without_startup_headroom(self):
        with patch.object(local, 'install_unit', return_value=False), patch.object(local, 'active', return_value=True), \
                patch.object(local, 'available_gib', return_value=30), patch.object(local, 'ready_snapshot', return_value={}), \
                patch.object(local, 'admission') as admission, patch.object(local.subprocess, 'run') as commands:
            self.assertFalse(local.ensure_service(self.state))
        admission.assert_not_called()
        commands.assert_not_called()

    def test_new_service_failure_stops_only_its_own_unit(self):
        with patch.object(local, 'install_unit', return_value=False), patch.object(local, 'active', side_effect=[False, False]), \
                patch.object(local, 'admission'), patch.object(local.subprocess, 'run') as command, \
                patch.object(local, 'stop_service') as stop:
            with self.assertRaisesRegex(RuntimeError, 'stopped before readiness'):
                local.ensure_service(self.state)
        command.assert_called_once_with(['systemctl', '--user', 'start', local.UNIT], check=True, timeout=20)
        stop.assert_called_once()

    def test_readiness_requires_actual_model_identities(self):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(local.urllib.request, 'urlopen', return_value=response), \
                patch.object(local.json, 'load', return_value={'ready': True, 'status': 'ready', 'model': 'other', 'segmenter': 'sam2.1-tiny', 'runtime': 'photon'}):
            with self.assertRaisesRegex(RuntimeError, 'selected models'):
                local.ready_snapshot()


if __name__ == '__main__':
    unittest.main()
