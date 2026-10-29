#!/usr/bin/env python3
"""Explicit GPU integration test of mixed-frame-rate recorded HTTP playback."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time

state = Path('/state')
rows = []


class Consumer(BaseHTTPRequestHandler):
    def do_POST(self):
        row = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        rows.append((time.monotonic(), row))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"accepted":true}')

    def log_message(self, *_):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Consumer)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
started = time.monotonic()
result = subprocess.run(['/opt/city/city-worker',
    '--source', 'traffic-cam-1=file:///media/traffic-sample.mp4',
    '--source', 'pedestrian-cam-2=file:///media/pedestrian-sample.mp4',
    '--config-dir', '/opt/city/configs', '--output', '/state/native-pacing.ndjson',
    '--post-url', f'http://127.0.0.1:{server.server_port}/api/v1/city/observations',
    '--cpu-decode', '--frames', '480'], capture_output=True, text=True, timeout=80)
finished = time.monotonic()
server.shutdown()
thread.join()
(state / 'native-pacing.log').write_text(result.stdout + result.stderr)
(state / 'native-pacing-receive.ndjson').write_text(''.join(json.dumps({
    'receivedMonotonicSeconds': wall, **row}) + '\n' for wall, row in rows))
summary = next((json.loads(line.split(': ', 1)[1]) for line in result.stderr.splitlines()
                if line.startswith('City publisher summary: ')), {})
sources = {}
for sid in sorted({r['sourceId'] for _, r in rows}):
    all_frames = [(wall, row) for wall, row in rows if row['sourceId'] == sid]
    steady = [(wall, row) for wall, row in all_frames if row['mediaTimeSeconds'] >= 2]
    first_wall, first = steady[0]
    last_wall, last = steady[-1]
    wall_span = last_wall - first_wall
    media_span = last['mediaTimeSeconds'] - first['mediaTimeSeconds']
    sources[sid] = {'frames': len(all_frames), 'steadyFrames': len(steady),
        'firstMediaSeconds': all_frames[0][1]['mediaTimeSeconds'],
        'lastMediaSeconds': last['mediaTimeSeconds'], 'warmupMediaSeconds': 2,
        'steadyWallSeconds': wall_span, 'steadyMediaSeconds': media_span,
        'mediaToWallRatio': media_span / wall_span,
        'receivedFps': (len(steady)-1) / wall_span,
        'endRelativeDriftMs': (wall_span-media_span)*1000}
receipt = {'test': 'native-mixed-fps-paced-http', 'exitCode': result.returncode,
    'wallSecondsIncludingStartup': finished-started, 'observations': len(rows),
    'publisher': summary, 'sources': sources,
    'consumer': 'fast local HTTP receiver, monotonic timestamps at request body receipt',
    'pacing': 'per-source identity sync; terminal fakesink sync disabled',
    'gpuTimingScope': 'native end-to-end file playback; engine-only timing is separate'}
(state / 'native-pacing-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2), flush=True)
assert result.returncode == 0, result.stderr
assert len(rows) == summary['enqueued'] == summary['published'] == 480
assert summary['failed'] is False
assert all(.90 <= v['mediaToWallRatio'] <= 1.10 for v in sources.values()), sources
