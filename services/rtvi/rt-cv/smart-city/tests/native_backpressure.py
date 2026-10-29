#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded native GPU integration test with a deliberately slow HTTP consumer.
Run explicitly inside the qualified DS container; not a default CPU unit test.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--worker', default='/opt/city/city-worker')
parser.add_argument('--config-dir', default='/opt/city/configs')
parser.add_argument('--video', default='file:///media/traffic-sample.mp4')
parser.add_argument('--state-dir', type=Path, default=Path('/state'))
args = parser.parse_args()
rows = []


class Consumer(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        rows.append(body)
        time.sleep(.075)  # Slower than unpaced native inference; capacity four.
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        if body['sequence'] == '5':
            self.wfile.write(b'{"accepted":false,"reason":"duplicate-or-out-of-order"}')
        else:
            self.wfile.write(b'{"accepted":true}')

    def log_message(self, *_args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Consumer)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
start = time.monotonic()
args.state_dir.mkdir(parents=True, exist_ok=True)
output = args.state_dir / 'native-backpressure.ndjson'
result = subprocess.run([args.worker, '--source', f'backpressure-test={args.video}',
    '--config-dir', args.config_dir, '--output', str(output), '--post-url',
    f'http://127.0.0.1:{server.server_port}/api/v1/city/observations',
    '--frames', '30', '--cpu-decode', '--unpaced', '--publisher-queue-size', '4'],
    capture_output=True, text=True, timeout=35)
server.shutdown();thread.join()
observations = [json.loads(line) for line in output.read_text().splitlines()]
(args.state_dir / 'native-backpressure.log').write_text(result.stdout + result.stderr)
summary = next(json.loads(line.split(': ', 1)[1]) for line in result.stderr.splitlines()
               if line.startswith('City publisher summary: '))
assert result.returncode == 0, result.stderr
assert len(rows) == len(observations) == 30, (len(rows), len(observations))
assert [r['sequence'] for r in rows] == [str(i) for i in range(30)]
assert summary['enqueued'] == summary['published'] == 30
assert summary['peakQueue'] <= 4 and summary['backpressureWaits'] > 0
assert any(r['objects'] for r in observations)
receipt = {'test': 'native-unpaced-file-backpressure', 'exitCode': result.returncode,
           'wallSeconds': time.monotonic() - start, 'paced': False, 'observations': len(rows),
           'publisher': summary, 'duplicateResponseHandledIdempotently': True,
           'output': str(output), 'consumer': 'deliberately slow local HTTP test consumer, no VSS state changed'}
(args.state_dir / 'native-backpressure-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
