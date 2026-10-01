import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).parent))
import desktop as d
import offline


class DesktopTests(unittest.TestCase):
    def setUp(self):
        # Real launcher state carries the live source UUID. Isolate every test
        # so even a best-effort stop cannot reach the real recording API.
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        state_patcher = patch.object(d.b, 'STATE', Path(state.name))
        state_patcher.start()
        self.addCleanup(state_patcher.stop)
        # Metadata helper units are mocked: launcher tests must not touch the host.
        for name in ('ensure_bridge', 'stop_bridge'):
            patcher = patch.object(d.history_metadata, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_api_failure_keeps_bounded_backend_reason_in_startup_log(self):
        (d.b.STATE / 'desktop-offline.json').write_text('{}')
        error = d.urllib.error.HTTPError('http://local', 502, 'failed', {},
            io.BytesIO(json.dumps({'error': 'Cosmos captioning could not be resumed.'}).encode()))
        with patch.object(d.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 502.*Cosmos captioning could not be resumed'):
                d.api('/source-analysis')

    def test_api_failure_with_non_json_body_still_reports_original_http_error(self):
        (d.b.STATE / 'desktop-offline.json').write_text('{}')
        error = d.urllib.error.HTTPError('http://local', 502, 'failed', {}, io.BytesIO(b'<html>Gateway error</html>'))
        with patch.object(d.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'VSS could not complete /source-analysis .HTTP 502'):
                d.api('/source-analysis?sourceId=camera')

    def test_stale_camera_discovery_recovery_requires_fresh_recorded_footage(self):
        progress = Mock()
        offline_status = {'state': 'offline', 'errorCode': 'CameraNotFoundError'}
        with patch.object(d, 'api', return_value={'questionReady': False}), \
             patch.object(d, 'local_sim_published', return_value=False):
            self.assertFalse(d.recover_sensor_connection('camera', offline_status, progress))
        progress.execute.assert_not_called()
        with patch.object(d, 'api', return_value={'questionReady': True}), \
             patch.object(d.b, 'compose', return_value=['docker', 'compose', 'restart', 'sensor-ms']):
            self.assertTrue(d.recover_sensor_connection('camera', offline_status, progress))
        self.assertEqual(progress.execute.call_args.args[0][-2:], ['restart', 'sensor-ms'])
        with patch.object(d, 'api') as request:
            self.assertFalse(d.recover_sensor_connection('camera', {'state': 'online'}, progress))
            request.assert_not_called()

    def test_stale_camera_recovers_with_recording_off_when_local_video_is_published(self):
        progress = Mock()
        for recording in ({'questionReady': False}, OSError('recorder unavailable')):
            with self.subTest(recording=recording), \
                 patch.object(d, 'api', **({'side_effect': recording} if isinstance(recording, Exception)
                                         else {'return_value': recording})), \
                 patch.object(d, 'local_sim_published', return_value=True), \
                 patch.object(d.b, 'compose', return_value=['restart', 'sensor-ms']):
                self.assertTrue(d.recover_sensor_connection('camera',
                    {'state': 'offline', 'errorCode': 'CameraNotFoundError'}, progress))
                self.assertEqual(progress.execute.call_args.args[0], ['restart', 'sensor-ms'])

    def test_local_sim_probe_requires_complete_video_sdp(self):
        video = b'v=0\r\nm=video 0 RTP/AVP 96\r\n'
        def reply(body, code=b'200', content_type=b'application/sdp'):
            return (b'RTSP/1.0 ' + code + b' OK\r\nContent-Type: ' + content_type
                    + b'\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
        for payload, expected in [(reply(video), True), (reply(video, b'404'), False),
                                  (reply(b'v=0\r\nm=audio 0 RTP/AVP 0\r\n'), False),
                                  (reply(video)[:-5], False), (reply(video, content_type=b'text/plain'), False)]:
            with self.subTest(payload=payload):
                connection = Mock()
                connection.__enter__ = Mock(return_value=connection)
                connection.__exit__ = Mock(return_value=False)
                connection.recv.side_effect = [payload[:12], payload[12:], b'']
                with patch.object(d.socket, 'create_connection', return_value=connection) as connect:
                    self.assertEqual(d.local_sim_published(), expected)
                    connect.assert_called_once_with(('127.0.0.1', 8554), timeout=3)
                    self.assertTrue(connection.sendall.call_args.args[0].startswith(b'DESCRIBE '))

    def test_recovered_discovery_http_outage_is_retried(self):
        with patch.object(d, 'pause_rules'), \
             patch.object(d, 'read_url', side_effect=OSError('listener restarting')) as read, \
             patch.object(d.time, 'monotonic', side_effect=[0, 1, 2, 46]), \
             patch.object(d.time, 'sleep'):
            result = d.ready_sim({'sensor_id': 'camera'}, Mock(), False)
        self.assertEqual(read.call_count, 2)
        self.assertIn('VSS is running', result)

    def test_cold_start_pauses_saved_rules_even_when_the_sim_is_not_publishing_yet(self):
        with patch.object(d, 'pause_rules') as pause, \
             patch.object(d, 'api') as request, \
             patch.object(d.time, 'monotonic', side_effect=[0, 46]):
            result = d.ready_sim({'sensor_id': 'camera'}, Mock(), True)
        pause.assert_called_once_with()
        request.assert_called_once_with('/live-alert-rules?sourceId=camera', method='DELETE', timeout=75)
        self.assertIn('simulator stream is not available yet', result)

    def test_stale_online_discovery_without_publisher_does_not_start_capture_or_fail_the_loaded_app(self):
        progress = Mock()
        with patch.object(d, 'read_url', return_value={'state': 'online'}) as read, \
             patch.object(d, 'local_sim_published', return_value=False), \
             patch.object(d, 'api') as request, \
             patch.object(d.time, 'monotonic', side_effect=[0, 1, 46]), \
             patch.object(d.time, 'sleep'):
            result = d.ready_sim({'sensor_id': 'camera'}, progress, False)
        self.assertIn('VSS is running', result)
        self.assertIn('simulator stream is not available yet', result)
        read.assert_called_once()
        request.assert_not_called()
        progress.execute.assert_not_called()

    def test_late_publisher_is_accepted_after_stale_online_discovery(self):
        from datetime import datetime, timezone
        ready_state = {'analysisProfileId': 'warehouse-safety', 'detectionEnabled': True, 'analysisActive': True}
        progress = Mock()
        with patch.object(d, 'read_url', side_effect=[{'state': 'online'}, {'state': 'online'},
                {'name': 'Warehouse'}, ready_state, ready_state]), \
             patch.object(d, 'local_sim_published', side_effect=[False, True]) as published, \
             patch.object(d, 'api', side_effect=[{}, {'lastSemanticAt': datetime.now(timezone.utc).isoformat()},
                {'streamId': 'camera', 'questionReady': True}]) as request, \
             patch.object(d.time, 'monotonic', side_effect=range(20)), \
             patch.object(d.time, 'sleep'):
            result = d.ready_sim({'sensor_id': 'camera'}, progress, False)
        self.assertIn('VSS is ready', result)
        self.assertEqual(published.call_count, 2)
        self.assertEqual(request.call_args_list[0].args,
                         ('/live-capture', {'streamId': 'camera', 'action': 'start'}))
        progress.execute.assert_not_called()

    def test_fresh_indexing_waits_for_same_stream_playable_recording(self):
        from datetime import datetime, timezone
        ready_state = {'analysisProfileId': 'warehouse-safety', 'detectionEnabled': True, 'analysisActive': True}
        semantic = {'lastSemanticAt': datetime.now(timezone.utc).isoformat()}
        capture_states = [
            {'streamId': 'camera', 'questionReady': False},
            {'streamId': 'different-camera', 'questionReady': True},
            {'streamId': 'camera', 'questionReady': True},
        ]
        with patch.object(d, 'read_url', side_effect=[{'state': 'online'}, {'name': 'Warehouse'},
                ready_state, ready_state, ready_state, ready_state]), \
             patch.object(d, 'local_sim_published', return_value=True), \
             patch.object(d, 'api', side_effect=[{}, semantic, capture_states[0], semantic, capture_states[1], semantic, capture_states[2]]) as request, \
             patch.object(d.time, 'monotonic', side_effect=range(20)), \
             patch.object(d.time, 'sleep') as sleep:
            result = d.ready_sim({'sensor_id': 'camera'}, Mock(), False)
        self.assertIn('VSS is ready', result)
        self.assertIn('Existing monitoring settings are preserved', result)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([call.args[0] for call in request.call_args_list].count('/live-capture?streamId=camera'), 3)

    def test_unavailable_recording_readiness_retries_until_existing_deadline(self):
        from datetime import datetime, timezone
        ready_state = {'analysisProfileId': 'warehouse-safety', 'detectionEnabled': True, 'analysisActive': True}
        semantic = {'lastSemanticAt': datetime.now(timezone.utc).isoformat()}
        with patch.object(d, 'read_url', side_effect=[{'state': 'online'}, {'name': 'Warehouse'}, ready_state, ready_state]), \
             patch.object(d, 'local_sim_published', return_value=True), \
             patch.object(d, 'api', side_effect=[{}, semantic, RuntimeError('recorder warming up')]), \
             patch.object(d.time, 'monotonic', side_effect=[0, 1, 2, 3, 123]), \
             patch.object(d.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'playable live recording were not verified'):
                d.ready_sim({'sensor_id': 'camera'}, Mock(), False)
        sleep.assert_called_once_with(3)

    def test_cached_offline_prepare_upgrades_graph_without_render_or_restart(self):
        settings = {'host_ip': '172.17.0.1', 'gateway': '172.17.0.1'}
        marker = {'gateway': settings['gateway'], 'sensor_id': 'camera'}
        (d.b.STATE / 'desktop-offline.json').write_text(json.dumps(marker))
        graph = {'services': {'vss-behavior-analytics-thor-candidates': {
            'image': 'cached', 'environment': {'NO_DOWNLOAD': 'true'}, 'mem_limit': '1g'}}}
        path = d.b.STATE / 'compose.json'
        path.write_text(json.dumps(graph))
        execute = Mock()
        with patch.object(offline, 'local_gateway', return_value=settings['gateway']), \
             patch.object(d.b, 'render') as render:
            self.assertEqual(offline.prepare(settings, Mock(), execute), marker)
            once = path.read_text()
            self.assertEqual(offline.prepare(settings, Mock(), execute), marker)
            self.assertEqual(path.read_text(), once)
        execute.assert_not_called()
        render.assert_not_called()
        upgraded = json.loads(once)['services']['vss-behavior-analytics-thor-candidates']
        self.assertEqual(upgraded['environment'], {'NO_DOWNLOAD': 'true'})
        self.assertEqual(upgraded['mem_limit'], '1g')
        self.assertTrue(upgraded['volumes'][0]['read_only'])

    def test_offline_mode_refuses_credentials_and_download_enabled_models(self):
        settings = {'cached_models': True, 'detector_enabled': True}
        graph = {'services': {name: {'environment': {
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'NGC_API_KEY': '',
            'NIM_DISABLE_MODEL_DOWNLOAD': '1', 'RTVI_OFFLINE': 'true',
        }} for name in ('spark-llm', 'rtvi-embed', 'rtvi-vlm')}}
        graph['services']['streamprocessing-ms'] = {'entrypoint': ['launch_vst'],
            'environment': {'VST_INSTALL_ADDITIONAL_PACKAGES': 'false'}}
        graph['services']['vss-agent'] = {'image': 'cached-agent'}
        d.b.booth_runtime_safety(graph)
        offline.validate_graph(settings, graph)
        for name, key, value in [('spark-llm', 'NIM_DISABLE_MODEL_DOWNLOAD', '0'),
                                 ('rtvi-embed', 'NGC_API_KEY', 'private'),
                                 ('rtvi-vlm', 'HF_HUB_OFFLINE', '0')]:
            with self.subTest(name=name):
                changed = json.loads(json.dumps(graph))
                changed['services'][name]['environment'][key] = value
                with self.assertRaises(RuntimeError):
                    offline.validate_graph(settings, changed)

    def test_offline_graph_refuses_network_codec_installer_or_invalid_mount(self):
        settings = {'cached_models': True, 'detector_enabled': True}
        graph = {'services': {name: {'environment': {
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'NIM_DISABLE_MODEL_DOWNLOAD': '1', 'RTVI_OFFLINE': 'true',
        }} for name in ('spark-llm', 'rtvi-embed', 'rtvi-vlm')}}
        graph['services']['streamprocessing-ms'] = {'environment': {'VST_INSTALL_ADDITIONAL_PACKAGES': 'false'}}
        graph['services']['vss-agent'] = {}
        d.b.booth_runtime_safety(graph)
        for change in ('unset-wheel', 'download-retries', 'writable-wheel', 'missing-wheel-mount'):
            with self.subTest(change=change):
                changed = json.loads(json.dumps(graph))
                agent = changed['services']['vss-agent']
                if change == 'unset-wheel':
                    agent['environment'].pop('VSS_PROPRIETARY_CODECS_WHEEL')
                elif change == 'download-retries':
                    agent['environment']['VSS_PROPRIETARY_CODECS_MAX_RETRY_SECONDS'] = '1200'
                elif change == 'writable-wheel':
                    agent['volumes'][0]['read_only'] = False
                else:
                    agent['volumes'] = []
                with self.assertRaisesRegex(RuntimeError, 'offline codec'):
                    offline.validate_graph(settings, changed)

    def test_offline_codec_cache_rejects_missing_or_changed_wheel(self):
        path = d.b.STATE / 'offline-tools' / d.b.CODEC_WHEEL_NAME
        with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
            offline.verify_codec_cache()
        path.parent.mkdir(parents=True)
        path.write_bytes(b'partial-download')
        with self.assertRaisesRegex(RuntimeError, 'missing or changed'):
            offline.verify_codec_cache()

    def test_environment_does_not_forward_download_or_shell_credentials(self):
        with patch.dict(d.os.environ, {'NGC_API_KEY': 'private', 'HF_TOKEN': 'private',
                                      'NPM_TOKEN': 'private', 'BASH_ENV': '/unsafe'}):
            self.assertFalse(any(key in d.environment() for key in ('NGC_API_KEY', 'HF_TOKEN', 'NPM_TOKEN', 'BASH_ENV')))

    def test_browser_uses_existing_chromium_session_for_the_local_app(self):
        progress = Mock()
        for binary in ('chromium-browser', 'chromium'):
            with self.subTest(binary=binary), \
                 patch.object(d.shutil, 'which', side_effect=lambda name: '/browser/' + name if name == binary else None), \
                 patch.object(d.subprocess, 'Popen') as spawn:
                self.assertTrue(d.open_browser(progress))
                self.assertEqual(spawn.call_args.args[0], ['/browser/' + binary, '--new-tab', d.APP_URL])
                self.assertTrue(spawn.call_args.kwargs['start_new_session'])

    def test_missing_browser_is_reported_without_failing_a_ready_session(self):
        progress = Mock()
        with patch.object(d.shutil, 'which', return_value=None), patch.object(d.subprocess, 'Popen') as spawn:
            self.assertFalse(d.open_browser(progress))
            spawn.assert_not_called()
            self.assertIn(d.APP_URL, progress.say.call_args.args[0])

    def test_browser_spawn_failure_is_reported_without_stopping_vss(self):
        progress = Mock()
        with patch.object(d.shutil, 'which', return_value='/browser/chromium'), \
             patch.object(d.subprocess, 'Popen', side_effect=OSError('browser unavailable')):
            self.assertFalse(d.open_browser(progress))
            self.assertIn(d.APP_URL, progress.say.call_args.args[0])

    def test_second_start_is_refused_without_affecting_existing_operation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            first = d.lock('start', Mock())
            before = (Path(folder) / 'desktop-operation.json').read_bytes()
            try:
                with self.assertRaisesRegex(RuntimeError, 'already in progress'):
                    d.lock('start', Mock())
                self.assertEqual((Path(folder) / 'desktop-operation.json').read_bytes(), before)
            finally:
                first.close()

    def test_cancelled_start_does_not_launch_a_child(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)), \
             patch.object(d, 'wait_docker'), \
             patch.object(d.subprocess, 'Popen') as spawn:
            progress = d.Progress('start', False)
            d.cancelled.set()
            try:
                with self.assertRaises(d.Cancelled):
                    progress.execute(['docker', 'compose', 'up'], 'Starting')
                spawn.assert_not_called()
            finally:
                d.cancelled.clear()
                progress.log.close()

    def test_start_failure_reports_the_underlying_helper_error(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            progress = d.Progress('start', False)
            try:
                with self.assertRaisesRegex(RuntimeError, 'logstash exited'):
                    progress.execute([sys.executable, '-c',
                        'print("ERROR: logstash exited"); raise SystemExit(1)'], 'Starting cached VSS')
                self.assertIn('ERROR: logstash exited', progress.path.read_text())
            finally:
                progress.log.close()

    def test_gui_progress_does_not_require_a_terminal_output_pipe(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            progress = d.Progress('start', False)
            progress.gui = True
            try:
                with patch('builtins.print', side_effect=BrokenPipeError('desktop pipe closed')):
                    progress.say('Loading cached models')
                self.assertIn('Loading cached models', progress.path.read_text())
            finally:
                progress.log.close()

    def test_stop_still_stops_services_when_the_app_is_unavailable(self):
        progress = Mock()
        with patch.object(d, 'pause_rules', side_effect=OSError('app down')), \
             patch.object(d.b, 'run', return_value=Mock(stdout='')):
            result = d.stop(progress)
        command = progress.execute.call_args.args[0]
        self.assertIn('stop', command)
        self.assertNotIn('down', command)
        self.assertNotIn('rm', command)
        self.assertIn('simulator', result)

    def test_stop_still_stops_services_when_the_app_response_is_malformed(self):
        progress = Mock()
        with patch.object(d, 'pause_rules', side_effect=KeyError('id')), \
             patch.object(d.b, 'run', return_value=Mock(stdout='')):
            d.stop(progress)
        self.assertIn('stop', progress.execute.call_args.args[0])

    def test_check_cannot_interrupt_an_existing_start(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            first = d.lock('start', Mock())
            try:
                with patch.object(d.os, 'kill') as kill:
                    with self.assertRaisesRegex(RuntimeError, 'already in progress'):
                        d.lock('check', Mock())
                    kill.assert_not_called()
            finally:
                first.close()

    def test_stop_retries_start_metadata_publication_before_signaling(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            # Stop can arrive between flock acquisition and the metadata write.
            operation = Path(folder) / 'desktop-operation.json'
            def publish(_):
                operation.write_text(json.dumps({'pid': d.os.getpid(), 'action': 'start'}))
            with patch.object(d.fcntl, 'flock', side_effect=[BlockingIOError(), BlockingIOError(), None]), \
                 patch.object(d.time, 'sleep', side_effect=publish), \
                 patch.object(d.os, 'kill') as kill, \
                 patch.object(d.Path, 'read_bytes', return_value=str(Path(d.__file__).resolve()).encode()):
                handle = d.lock('stop', Mock())
                handle.close()
                kill.assert_called_once_with(d.os.getpid(), d.signal.SIGTERM)

    def test_preparation_failure_cleans_up_partial_services(self):
        progress = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)), \
             patch.object(d.offline, 'preflight', return_value=({'host_ip': '10.88.9.91', 'gateway': '172.17.0.1'}, {})), \
             patch.object(d.b, 'doctor'), \
             patch.object(d.offline, 'prepare', side_effect=RuntimeError('database setup failed')), \
             patch.object(d.subprocess, 'run') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'database setup failed'):
                d.start(progress)
            self.assertIn('stop', cleanup.call_args.args[0])

    def test_cleanup_timeout_preserves_original_startup_failure(self):
        with patch.object(d, 'wait_docker'), \
             patch.object(d.offline, 'preflight', return_value=({'host_ip': 'local', 'gateway': 'local'}, {})), \
             patch.object(d.b, 'doctor'), patch.object(d.offline, 'prepare', side_effect=RuntimeError('database setup failed')), \
             patch.object(d.subprocess, 'run', side_effect=d.subprocess.TimeoutExpired('cleanup', 120)):
            with self.assertRaisesRegex(RuntimeError, 'database setup failed'):
                d.start(Mock())

    def test_warm_ui_switch_preserves_rules_and_models_on_readiness_failure(self):
        progress = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            (Path(folder) / 'desktop-offline.json').write_text('{}')
            with patch.object(d.offline, 'preflight', return_value=({'host_ip': '172.17.0.1', 'gateway': '172.17.0.1'}, {})), \
                 patch.object(d, 'wait_docker'), \
                 patch.object(d.b, 'doctor'), patch.object(d.offline, 'prepare', return_value={'sensor_id': 'camera'}), \
                 patch.object(d.offline, 'load', return_value=({}, {})), \
                 patch.object(d, 'model_health', return_value=True), patch.object(d, 'stack_ready', return_value=True), \
                 patch.object(d.ui, 'current_mode', return_value='built'), patch.object(d, 'wait_app'), \
                 patch.object(d, 'ready_sim', side_effect=RuntimeError('source check failed')) as ready, \
                 patch.object(d.subprocess, 'run') as cleanup:
                with self.assertRaisesRegex(RuntimeError, 'source check failed'):
                    d.start(progress)
                ready.assert_called_once_with({'sensor_id': 'camera'}, progress, False)
                cleanup.assert_not_called()
                commands = [call.args[0] for call in progress.execute.call_args_list]
                self.assertTrue(any(command[-1] == 'dev' for command in commands))
                self.assertFalse(any('stop' in command for command in commands))

    def test_docker_reboot_delay_is_retried_without_starting_services(self):
        with patch.object(d.time, 'monotonic', side_effect=[0, 1, 2]), patch.object(d.time, 'sleep'), \
             patch.object(d.b, 'run', side_effect=[d.subprocess.CalledProcessError(1, ['docker']), Mock()]) as run:
            d.wait_docker(Mock())
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args[0][:2] == ['docker', 'info'] and call.kwargs['timeout'] == 3
                            for call in run.call_args_list))

    def test_docker_reboot_delay_has_a_deadline(self):
        with patch.object(d.time, 'monotonic', side_effect=[0, 1, 46]), patch.object(d.time, 'sleep'), \
             patch.object(d.b, 'run', side_effect=d.subprocess.TimeoutExpired('docker', 3)):
            with self.assertRaisesRegex(RuntimeError, '45 seconds'):
                d.wait_docker(Mock())

    def test_partial_model_session_is_cleaned_up_before_cold_admission(self):
        (d.b.STATE / 'desktop-offline.json').write_text('{}')
        progress = Mock()
        with patch.object(d, 'wait_docker'), \
             patch.object(d.offline, 'preflight', return_value=({'host_ip': 'local', 'gateway': 'local'}, {})), \
             patch.object(d.b, 'doctor'), patch.object(d.offline, 'prepare', return_value={'sensor_id': 'camera'}), \
             patch.object(d.offline, 'load', return_value=({}, {})), \
             patch.object(d, 'model_health', return_value=False), patch.object(d, 'models_running', return_value=True), \
             patch.object(d, 'stop') as stop, patch.object(d.ui, 'current_mode', return_value='dev'), \
             patch.object(d, 'wait_app'), patch.object(d, 'ready_sim', return_value='ready'), \
             patch.object(d.b, 'available', return_value=40), patch.object(d.b, 'memory_reserve', return_value=24):
            timeline = Mock()
            timeline.attach_mock(stop, 'stop')
            timeline.attach_mock(progress.execute, 'execute')
            self.assertEqual(d.start(progress), 'ready')
        calls = timeline.mock_calls
        stop_index = next(i for i, call in enumerate(calls) if call[0] == 'stop')
        up_index = next(i for i, call in enumerate(calls) if call[0] == 'execute' and call.args[0][-1] == 'up')
        self.assertLess(stop_index, up_index)

    def test_shutdown_finishes_recording_despite_monitoring_and_discovery_failures(self):
        progress = Mock()
        with tempfile.TemporaryDirectory() as folder, patch.object(d.b, 'STATE', Path(folder)):
            (Path(folder) / 'desktop-offline.json').write_text(json.dumps({'sensor_id': 'camera'}))
            with patch.object(d, 'pause_rules', side_effect=RuntimeError('rules unavailable')), \
                 patch.object(d, 'read_url', side_effect=OSError('discovery unavailable')), \
                 patch.object(d, 'api') as request, patch.object(d.b, 'compose', return_value=['docker', 'compose']), \
                 patch.object(d.b, 'run', return_value=Mock(stdout='')):
                result = d.stop(progress)
            request.assert_called_once_with('/live-capture', {'streamId': 'camera', 'action': 'stop'}, timeout=40)
            self.assertIn('VSS is stopped', result)

    def test_stack_readiness_requires_ui_and_data_services_but_allows_completed_jobs(self):
        graph = {'services': {'model': {'depends_on': {'init': {'condition': 'service_completed_successfully'}}},
                              'init': {}, 'ui': {}}}
        def row(name, status, code=0):
            return {'Config': {'Labels': {'com.docker.compose.service': name}},
                    'State': {'Status': status, 'ExitCode': code}}
        for rows, expected in [([row('model', 'running'), row('init', 'exited'), row('ui', 'running')], True),
                               ([row('model', 'running'), row('init', 'exited')], False),
                               ([row('model', 'running'), row('init', 'exited', 1), row('ui', 'running')], False)]:
            with self.subTest(expected=expected, rows=rows), patch.object(d.b, 'run', side_effect=[Mock(stdout='ids'), Mock(stdout=json.dumps(rows))]):
                self.assertEqual(d.stack_ready(graph), expected)

    def test_cache_check_rejects_truncated_tensor_data(self):
        import struct
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config.json').write_text('{}')
            (root / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'tensor': 'weights.safetensors'}}))
            header = json.dumps({'tensor': {'dtype': 'F32', 'shape': [2], 'data_offsets': [0, 8]}}).encode()
            weights = root / 'weights.safetensors'
            weights.write_bytes(struct.pack('<Q', len(header)) + header + b'1234')
            scope = {}
            # The separate cached-tool probe is exercised against the real
            # network-isolated image; this check targets model truncation.
            definitions = offline.CACHE_CHECK.split('def required(path):', 1)[1].split("model('/nim/")[0]
            exec('import json, struct\nfrom pathlib import Path\ndef required(path):' + definitions, scope)
            with self.assertRaisesRegex(RuntimeError, 'Truncated tensor data'):
                scope['model'](root, [])
            weights.write_bytes(struct.pack('<Q', len(header)) + header + b'12345678')
            scope['model'](root, [])

    def test_source_migration_preserves_identity_and_guards_both_updates(self):
        sid = '3688c328-7e71-493c-a1c7-011ad2fb3893'
        row = {'sensor_id': sid, 'stream_id': sid,
               'stream_live_url': 'rtsp://10.88.9.91:8554/digital-twin',
               'stream_proxy_url': f'rtsp://10.88.9.91:30554/live/{sid}',
               'stream_replay_url': f'rtsp://10.88.9.91:30564/vod/{sid}'}
        sensor = {'sensor_id': sid, 'device_id': 'device', 'type': 'sensor_rtsp', 'ipaddress': '10.88.9.91', 'url': ''}
        with tempfile.TemporaryDirectory() as folder, patch.object(offline.b, 'STATE', Path(folder)), \
             patch.object(offline, 'sql', side_effect=[json.dumps([row]), json.dumps(sensor), 'COMMIT']) as sql:
            self.assertEqual(offline.migrate_sim_urls('10.88.9.91', '172.17.0.1'), sid)
            transaction = sql.call_args.args[0]
            self.assertEqual(transaction.count('IF changed <> 1'), 2)
            self.assertIn('rtsp://127.0.0.1:8554/digital-twin', transaction)
            self.assertIn(f'rtsp://172.17.0.1:30554/live/{sid}', transaction)
            self.assertNotIn('DELETE', transaction)
            self.assertNotIn('TRUNCATE', transaction)
            self.assertNotIn('SET sensor_id', transaction)
            self.assertNotIn('SET stream_id', transaction)
            backup = Path(folder) / 'desktop-source-before.json'
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)

    def test_unrelated_remote_camera_cannot_be_migrated_as_sim(self):
        row = {'stream_live_url': 'rtsp://192.0.2.8:8554/digital-twin'}
        with patch.object(offline, 'sql', return_value=json.dumps([row])) as sql:
            with self.assertRaisesRegex(RuntimeError, 'Expected one registered local'):
                offline.migrate_sim_urls('10.88.9.91', '172.17.0.1')
            self.assertEqual(sql.call_count, 1)


if __name__ == '__main__':
    unittest.main()
