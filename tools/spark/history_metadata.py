#!/usr/bin/env python3
"""Read-only local recording metadata, using the already cached PostgreSQL CLI.

No caller supplies SQL, file paths, container names or credentials. This bridge
has no mutation endpoint. It is started explicitly with VSS, never at login.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.spark'
TOKEN_PATH = STATE / 'history-metadata-token'
UNIT = 'vss-spark-history-metadata.service'
QUERY = """BEGIN READ ONLY;
SET LOCAL statement_timeout = '20s';
SELECT COALESCE(json_agg(row_to_json(r)), '[]'::json) FROM (
 SELECT row_id,sensor_id,stream_id,start_time,file_duration,file_path,file_size,
        file_protection,modified_date_time
 FROM public.video_record_details ORDER BY row_id
) r;
COMMIT;
"""


def recording_snapshot():
    result = subprocess.run(
        ['docker', 'exec', '-i', 'vss-vios-postgres', 'psql', '-X', '-q', '-v',
         'ON_ERROR_STOP=1', '-U', 'vst', '-d', 'nvcentralizedb', '-tA'],
        input=QUERY, text=True, capture_output=True, check=True, timeout=30)
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError('Recording metadata was not a verified list.')
    return {'recordings': rows}


def capacity_snapshot():
    settings = json.loads((STATE / 'settings.json').read_text())
    guard = json.loads((STATE / 'guard-status.json').read_text())
    reserve = settings.get('reserve_gib')
    floor = guard.get('floor_gib')
    stamp = guard.get('time')
    if (isinstance(reserve, bool) or not isinstance(reserve, (int, float)) or not 24 <= reserve < 128
            or floor != reserve or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
            or not 0 <= time.time() - stamp <= 5):
        raise RuntimeError('Spark guard status is stale or inconsistent.')
    subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'vss-spark-guard.service'],
                   check=True, timeout=2, capture_output=True)
    available_kib = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))
    return {'hardwareProfile': 'DGX-SPARK', 'sampledAt': time.time(),
            'guardActive': True, 'reserveGiB': reserve, 'availableGiB': available_kib / 1048576}


def handler_type(token, snapshot=recording_snapshot, capacity=capacity_snapshot):
    gate = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log private metadata or authentication headers.

        def reply(self, code, body):
            payload = json.dumps(body, separators=(',', ':')).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            route = urlsplit(self.path)
            if route.path == '/health' and not route.query:
                return self.reply(200, {'status': 'ok'})
            if route.path not in ('/recordings', '/capacity') or route.query:
                return self.reply(404, {'error': 'Not found'})
            supplied = self.headers.get('X-History-Metadata-Token', '')
            if len(supplied) > 256 or not secrets.compare_digest(supplied, token):
                return self.reply(403, {'error': 'Forbidden'})
            if not gate.acquire(blocking=False):
                return self.reply(429, {'error': 'Recording snapshot is busy'})
            try:
                self.reply(200, capacity() if route.path == '/capacity' else snapshot())
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                self.reply(503, {'error': 'Recording metadata is unavailable'})
            finally:
                gate.release()

        def do_POST(self):
            self.reply(405, {'error': 'Read-only service'})

        do_DELETE = do_POST
        do_PUT = do_POST

    return Handler


def token_value(state=None):
    state = Path(state) if state is not None else STATE
    token_path = state / TOKEN_PATH.name
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not token_path.exists():
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(32))
    token_path.chmod(0o600)
    value = token_path.read_text().strip()
    if len(value) < 32:
        raise RuntimeError('Invalid local metadata token.')
    return value


def ensure_bridge():
    token_value()
    unit_path = Path.home() / '.config/systemd/user' / UNIT
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    if any(c in str(ROOT) for c in '\n"%'):
        raise RuntimeError('Unsupported service path characters.')
    content = f'''[Unit]
Description=VSS read-only recording metadata
[Service]
ExecStart=/usr/bin/python3 "{Path(__file__).resolve()}" serve
Restart=no
MemoryMax=128M
CPUQuota=100%
UMask=0077
'''
    if not unit_path.exists() or unit_path.read_text() != content:
        unit_path.write_text(content)
        unit_path.chmod(0o600)
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True, timeout=20)
    subprocess.run(['systemctl', '--user', 'start', UNIT], check=True, timeout=20)


def stop_bridge():
    subprocess.run(['systemctl', '--user', 'stop', UNIT], check=True, timeout=20)


def compose_service(graph, root=ROOT, token=None):
    agent = graph['services']['vss-agent']
    graph_env = graph['services']['lvs-server']['environment']
    env = agent['environment']
    evidence = graph['services']['evidence-clip']
    video_mount = next(mount for mount in evidence['volumes'] if mount['target'] == '/media')
    reports_mount = next(mount for mount in agent['volumes'] if mount['target'] == '/vss-agent/agent_reports')
    return {
        'image': agent['image'], 'container_name': 'vss-history-maintenance',
        'network_mode': 'host', 'runtime': 'runc', 'restart': 'no',
        'extra_hosts': agent.get('extra_hosts', {}),
        'user': '65532:1000', 'mem_limit': '512m', 'memswap_limit': '512m', 'cpus': 1,
        'entrypoint': ['/vss-agent/.venv/bin/python'],
        'command': ['/opt/vss-history/history-service.py'],
        'environment': {
            'PYTHONPATH': '/vss-agent/thor-local-src', 'PYTHONDONTWRITEBYTECODE': '1',
            'HISTORY_SERVICE_HOST': '127.0.0.1', 'HISTORY_SERVICE_PORT': '8101',
            'HISTORY_RECORDINGS_SNAPSHOT_URL': 'http://127.0.0.1:8102/recordings',
            'HISTORY_METADATA_TOKEN': token if token is not None else token_value(),
            'VST_INTERNAL_URL': env.get('VST_INTERNAL_URL', 'http://127.0.0.1:30888'),
            'ELASTIC_SEARCH_ENDPOINT': env.get('ELASTIC_SEARCH_ENDPOINT', 'http://127.0.0.1:9200'),
            'LVS_BACKEND_URL': env.get('LVS_BACKEND_URL', 'http://127.0.0.1:38111'),
            'VST_STREAMPROCESSOR_URL': 'http://127.0.0.1:30888',
            'HISTORY_EVIDENCE_URL': 'http://127.0.0.1:8098',
            'HISTORY_RECORDINGS_ROOT': '/data/vst-video',
            'HISTORY_RECORDINGS_PATH_PREFIX': evidence['environment'].get('VST_PATH_PREFIX', '/home/vst/vst_release/vst_video'),
            'HISTORY_AGENT_REPORTS_DIR': '/data/agent-reports',
            'GRAPH_DB_HTTP_URL': f"http://{graph_env['GRAPH_DB_HOST']}:{graph_env['GRAPH_DB_HTTP_PORT']}",
            'GRAPH_DB_USERNAME': graph_env['GRAPH_DB_USERNAME'],
            'GRAPH_DB_PASSWORD': graph_env['GRAPH_DB_PASSWORD'],
        },
        'volumes': [
            {'type': 'bind', 'source': str(root / 'services/agent/src'), 'target': '/vss-agent/thor-local-src', 'read_only': True},
            {'type': 'bind', 'source': str(root / 'deploy/docker/spark'), 'target': '/opt/vss-history', 'read_only': True},
            {**video_mount, 'target': '/data/vst-video', 'read_only': True},
            {**reports_mount, 'target': '/data/agent-reports'},
        ],
        'healthcheck': {
            'test': ['CMD', '/vss-agent/.venv/bin/python', '-c',
                     "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8101/health',timeout=3)"],
            'interval': '15s', 'timeout': '5s', 'retries': 3, 'start_period': '10s',
        },
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'start', 'stop'])
    args = parser.parse_args()
    if args.action == 'serve':
        server = ThreadingHTTPServer(('127.0.0.1', 8102), handler_type(token_value()))
        server.serve_forever()
    elif args.action == 'start':
        ensure_bridge()
    else:
        stop_bridge()
