import json
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import desktop as d


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.object(d.b, 'STATE', Path(self.directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_host_prerequisite_failure_precedes_any_startup_command(self):
        progress = Mock()
        with patch.object(d.b, 'doctor', side_effect=RuntimeError('net/core/rmem_max too small')) as doctor, \
                patch.object(d.b, 'settings') as settings:
            with self.assertRaisesRegex(RuntimeError, 'rmem_max'):
                d.preflight(progress)
        doctor.assert_called_once_with()
        settings.assert_not_called()
        progress.execute.assert_not_called()

    def graph(self):
        names = {'thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception', 'centralizedb',
                 'lvs-server', 'alert-bridge', 'vss-agent', 'vss-va-mcp', 'history-maintenance',
                 'vss-ui', 'vss-haproxy-ingress', 'streamprocessing-ms'}
        graph = {'services': {name: {'image': 'cached-' + name, 'environment': {}} for name in names}}
        for name in ('thor-llm', 'rtvi-embed', 'rtvi-vlm', 'vss-agent', 'vss-va-mcp'):
            graph['services'][name]['environment'].update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', RTVI_OFFLINE='true')
        graph['services']['streamprocessing-ms']['environment']['VST_INSTALL_ADDITIONAL_PACKAGES'] = 'false'
        return graph

    def test_offline_mode_rejects_downloads_credentials_and_online_video_installer(self):
        graph = self.graph()
        self.assertEqual(len(d.validate_offline({'cached_models': True}, graph)), len(graph['services']))
        for name, key, value in [('thor-llm', 'HF_HUB_OFFLINE', '0'),
                                 ('rtvi-vlm', 'NGC_API_KEY', 'credential'),
                                 ('rtvi-embed', 'RTVI_OFFLINE', 'false'),
                                 ('streamprocessing-ms', 'VST_INSTALL_ADDITIONAL_PACKAGES', 'true')]:
            graph = self.graph()
            graph['services'][name]['environment'][key] = value
            with self.subTest(name=name, key=key), self.assertRaises(RuntimeError):
                d.validate_offline({'cached_models': True}, graph)
        with self.assertRaises(RuntimeError):
            d.validate_offline({'cached_models': False}, self.graph())

    def test_stage_order_keeps_models_serial_and_includes_detector_and_all_services(self):
        graph = self.graph()
        plan = d.stage_plan(graph)
        self.assertEqual([stage for stage, _ in plan],
                         ['support', 'thor-llm', 'rtvi-embed', 'rtvi-vlm', 'thor-perception', 'app'])
        selected = [name for _, group in plan for name in group]
        self.assertEqual(set(selected), set(graph['services']))
        self.assertEqual(len(selected), len(set(selected)))
        del graph['services']['thor-perception']
        self.assertNotIn('thor-perception', [stage for stage, _ in d.stage_plan(graph)])

    def test_connection_does_not_interrupt_an_active_camera(self):
        progress = Mock()
        with patch.object(d.subprocess, 'check_output', return_value='camera\nlocal\n'):
            d.connect(progress, 'camera', 'Connect camera')
        progress.execute.assert_not_called()
        with patch.object(d.subprocess, 'check_output', return_value='local\n'):
            d.connect(progress, 'camera', 'Connect camera')
        self.assertEqual(progress.execute.call_args.args[0], ['nmcli', 'connection', 'up', 'uuid', 'camera'])

    def test_timeout_terminates_the_entire_startup_process_group(self):
        progress = d.Progress.__new__(d.Progress)
        progress.say = Mock()
        progress.log = Mock()
        process = Mock(pid=123, **{'poll.return_value': None})
        process.wait.side_effect = [subprocess.TimeoutExpired('startup', 1), 0]
        with patch.object(d.subprocess, 'Popen', return_value=process), patch.object(d.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                progress.execute(['startup'], 'Starting VSS', timeout=1)
        kill.assert_called_once_with(123, signal.SIGTERM)

    def test_readiness_requires_successful_init_and_healthy_running_services(self):
        rows = []
        for name, state in [('database', {'Status': 'running', 'Health': {'Status': 'healthy'}}),
                            ('warmup', {'Status': 'running', 'Health': {'Status': 'starting'}}),
                            ('success', {'Status': 'exited', 'ExitCode': 0}),
                            ('failed', {'Status': 'exited', 'ExitCode': 1})]:
            rows.append({'Config': {'Labels': {'com.docker.compose.service': name}}, 'State': state})
        with patch.object(d.b, 'run', side_effect=[Mock(stdout='container'), Mock(stdout=json.dumps(rows))]), \
                patch.object(d.b.shared, 'completed_services', return_value={'success', 'failed'}):
            self.assertEqual(d.ready_services({}), {'database', 'success'})


if __name__ == '__main__':
    unittest.main()
