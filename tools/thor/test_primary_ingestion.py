import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import primary_ingestion as p


class IngestionTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(p.b, 'require_guard')
        self.guard = guard.start()
        self.addCleanup(guard.stop)
        self.startup = p.Startup('camera')
        self.camera = {'camera': {'state': 'online', 'name': 'Main camera'}}
        # This is the failing run: generation works, but timestamp freshness
        # makes the aggregate analysisActive flag false.
        self.analysis = {'analysisActive': False, 'state': 'partial',
                         'steps': {'embedding_resource': True, 'embedding': True}}

    def samples(self, second, count):
        return [self.camera, self.analysis, {'recordingStatus': 'user'},
                [{'endTime': f'2026-10-09T18:38:{second:02d}Z'}],
                {'lastSemanticAt': f'2026-10-09T18:38:{second:02d}Z',
                 'semanticSegments': count, 'semanticFresh': False, 'indexingDelaySeconds': 62}]

    def test_arrivals_pass_despite_clock_lag_without_restarting_working_embeddings(self):
        with patch.object(p, 'local_json', side_effect=self.samples(35, 34) + self.samples(40, 35)) as request:
            self.assertEqual(self.startup.step(), 'waiting-for-progress')
            self.assertEqual(self.startup.step(), 'active')
        self.assertTrue(all(len(call.args) == 1 for call in request.call_args_list))

    def test_static_stored_data_cannot_pass(self):
        with patch.object(p, 'local_json', side_effect=self.samples(35, 34) * 2):
            self.assertEqual(self.startup.step(), 'waiting-for-progress')
            self.assertEqual(self.startup.step(), 'waiting-for-progress')

    def test_recording_without_index_progress_cannot_pass(self):
        samples = self.samples(40, 34)
        samples[-1]['lastSemanticAt'] = '2026-10-09T18:38:35Z'
        with patch.object(p, 'local_json', side_effect=self.samples(35, 34) + samples):
            self.startup.step()
            self.assertEqual(self.startup.step(), 'waiting-for-progress')

    def test_offline_camera_retries_then_recovers_without_stack_operations(self):
        with patch.object(p, 'local_json', side_effect=[{}] + self.samples(35, 34) + self.samples(40, 35)):
            self.assertEqual(self.startup.step(), 'waiting-for-camera')
            self.assertEqual(self.startup.step(), 'waiting-for-progress')
            self.assertEqual(self.startup.step(), 'active')

    def test_resume_and_reset_only_selected_camera(self):
        replies = [self.camera, {'state': 'paused'}, {'state': 'partial'},
                   {'recordingStatus': 'error'}, {}, {}, [], {}]
        with patch.object(p, 'local_json', side_effect=replies) as request:
            self.assertEqual(self.startup.step(), 'waiting-for-progress')
        writes = [call.args for call in request.call_args_list if len(call.args) > 1]
        self.assertEqual(writes, [('/api/v1/rtsp-streams/camera/analysis',
                                  {'action': 'resume', 'name': 'Main camera'}),
                                 ('/vst/api/v1/record/camera/stop', {}),
                                 ('/api/vision/live-capture', {'streamId': 'camera', 'action': 'start'})])

    def test_operator_pause_after_start_is_preserved(self):
        with patch.object(p, 'local_json', side_effect=self.samples(35, 34) +
                          [self.camera, {'state': 'paused'}]) as request:
            self.startup.step()
            self.assertEqual(self.startup.step(), 'paused')
        self.assertTrue(all(len(call.args) == 1 for call in request.call_args_list))

    def test_guard_failure_prevents_ingestion_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'desktop-config.json').write_text(json.dumps({
                'auto_primary_ingestion': True, 'primary_stream_id': 'camera'}))
            self.guard.side_effect = RuntimeError('guard stopped')
            with patch.object(p.b, 'STATE', state), patch.object(p, 'local_json') as request:
                p.serve()
            request.assert_not_called()
            self.assertEqual(json.loads((state / 'primary-ingestion.json').read_text())['state'],
                             'guard-unavailable')

    def test_worker_retries_transient_api_failure_then_exits_after_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'desktop-config.json').write_text(json.dumps({
                'auto_primary_ingestion': True, 'primary_stream_id': 'camera'}))
            with patch.object(p.b, 'STATE', state), \
                    patch.object(p, 'local_json', side_effect=[OSError('offline')] +
                                 self.samples(35, 34) + self.samples(40, 35)), \
                    patch.object(p.time, 'sleep') as sleep:
                p.serve()
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(json.loads((state / 'primary-ingestion.json').read_text())['state'], 'active')

    def test_helper_unit_is_started_only_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(p.Path, 'home', return_value=Path(directory)), \
                    patch.object(p.subprocess, 'run') as run:
                p.start()
            unit = Path(directory) / '.config/systemd/user' / p.UNIT
            contents = unit.read_text()
            self.assertIn(str(Path(p.__file__).resolve()), contents)
            self.assertIn('Restart=no', contents)
            self.assertNotIn('[Install]', contents)
            self.assertEqual([call.args[0] for call in run.call_args_list], [
                ['systemctl', '--user', 'daemon-reload'], ['systemctl', '--user', 'start', p.UNIT]])


if __name__ == '__main__':
    unittest.main()
