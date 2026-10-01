import importlib.util
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('history_metadata', Path(__file__).with_name('history_metadata.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


class HistoryMetadataTests(unittest.TestCase):
    def test_capacity_requires_fresh_matching_active_guard_and_reads_current_memory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(h, 'STATE', Path(folder)):
            (Path(folder) / 'settings.json').write_text(json.dumps({'reserve_gib': 24}))
            for status, allowed in [({'floor_gib': 24, 'time': 99}, True),
                                    ({'floor_gib': 24, 'time': 90}, False),
                                    ({'floor_gib': 36, 'time': 99}, False),
                                    ({'floor_gib': 24, 'time': 101}, False)]:
                (Path(folder) / 'guard-status.json').write_text(json.dumps(status))
                with self.subTest(status=status), patch.object(h.time, 'time', return_value=100), \
                     patch.object(h.subprocess, 'run') as run, \
                     patch.object(h, 'Path', return_value=Mock(read_text=Mock(return_value='MemAvailable: 37748736 kB\n'))):
                    if allowed:
                        self.assertEqual(h.capacity_snapshot()['availableGiB'], 36)
                        self.assertEqual(run.call_args.kwargs['timeout'], 2)
                    else:
                        with self.assertRaises(RuntimeError): h.capacity_snapshot()
                        run.assert_not_called()
            (Path(folder) / 'guard-status.json').write_text(json.dumps({'floor_gib': 24, 'time': 99}))
            with patch.object(h.time, 'time', return_value=100), patch.object(h.subprocess, 'run',
                    side_effect=subprocess.CalledProcessError(3, ['systemctl'])):
                with self.assertRaises(subprocess.CalledProcessError): h.capacity_snapshot()

    def test_query_is_fixed_and_read_only(self):
        with patch.object(h.subprocess, 'run', return_value=Mock(stdout='[{"row_id": 10}]')) as run:
            self.assertEqual(h.recording_snapshot(), {'recordings': [{'row_id': 10}]})
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ['docker', 'exec', '-i', 'vss-vios-postgres', 'psql'])
        self.assertIn('BEGIN READ ONLY', kwargs['input'])
        self.assertNotIn('DELETE ', kwargs['input'])
        self.assertEqual(kwargs['timeout'], 30)

    def test_http_auth_and_rejected_mutations_do_not_call_snapshot(self):
        snapshot = Mock(return_value={'recordings': [{'row_id': 10}]})
        capacity = Mock(return_value={'guardActive': True, 'reserveGiB': 24, 'availableGiB': 36})
        server = ThreadingHTTPServer(('127.0.0.1', 0), h.handler_type('test-token', snapshot, capacity))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            for method, route, code in [('GET', '/recordings', 403), ('GET', '/capacity', 403), ('POST', '/capacity', 405), ('POST', '/recordings', 405), ('DELETE', '/recordings', 405), ('GET', '/recordings?sql=DROP', 404)]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(url + route, method=method), timeout=3)
                self.assertEqual(error.exception.code, code)
            snapshot.assert_not_called()
            capacity.assert_not_called()
            with urlopen(Request(url + '/capacity', headers={'X-History-Metadata-Token': 'test-token'}), timeout=3) as response:
                self.assertEqual(json.load(response), capacity.return_value)
            capacity.assert_called_once_with()
            with urlopen(Request(url + '/recordings', headers={'X-History-Metadata-Token': 'test-token'}), timeout=3) as response:
                self.assertEqual(json.load(response), snapshot.return_value)
            snapshot.assert_called_once_with()
            snapshot.side_effect = subprocess.CalledProcessError(1, ['private'], stderr='secret-error')
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url + '/recordings', headers={'X-History-Metadata-Token': 'test-token'}), timeout=3)
            self.assertNotIn('secret', error.exception.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_sidecar_is_local_cpu_only_and_reuses_cached_image(self):
        graph = {'services': {
            'vss-agent': {'image': 'cached-agent', 'environment': {}, 'volumes': [{'source': '/reports', 'target': '/vss-agent/agent_reports', 'type': 'bind'}], 'extra_hosts': ['host.docker.internal=host-gateway']},
            'lvs-server': {'environment': {'GRAPH_DB_HOST': '127.0.0.1', 'GRAPH_DB_HTTP_PORT': '7474', 'GRAPH_DB_USERNAME': 'test', 'GRAPH_DB_PASSWORD': 'test'}},
            'evidence-clip': {'environment': {}, 'volumes': [{'source': '/video', 'target': '/media', 'type': 'bind', 'read_only': True}]},
        }}
        service = h.compose_service(graph, Path('/repo'), token='test-token')
        self.assertEqual(service['image'], 'cached-agent')
        self.assertEqual(service['runtime'], 'runc')
        self.assertEqual(service['restart'], 'no')
        self.assertEqual(service['environment']['HISTORY_SERVICE_HOST'], '127.0.0.1')
        self.assertEqual(service['mem_limit'], '512m')
        self.assertFalse(any('docker.sock' in mount['source'] for mount in service['volumes']))
        self.assertTrue(next(mount for mount in service['volumes'] if mount['target'] == '/data/vst-video')['read_only'])


if __name__ == '__main__':
    unittest.main()
