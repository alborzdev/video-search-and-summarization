#!/usr/bin/env python3
"""Bounded local Cosmos box-presence regression probe. No stream registration."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ORIGINAL = 'Is a box visible on the conveyor belt? Answer YES or NO only.'
ANY_FRAME = ('Does any frame in this video show a box on the conveyor belt? '
             'Answer YES if at least one frame shows a box, otherwise NO. Answer YES or NO only.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', choices=['original', 'any-frame'], default='any-frame')
    parser.add_argument('--repeats', type=int, choices=[1, 2, 3], default=1)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    fixtures = json.loads((root / 'fixtures.json').read_text())
    rows = []

    def request(route, body=None):
        req = urllib.request.Request('http://127.0.0.1:8018' + route,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=40) as response:
            return json.load(response)

    def available():
        return next(int(line.split()[1]) / 1048576 for line in
            Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))

    subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'vss-memory-budget'], check=True)
    assert request('/v1/stream/get-stream-info')['stream_count'] == 0, 'Stop live test workloads first'
    model = request('/v1/models')['data'][0]['id']
    for repeat in range(args.repeats):
        for fixture in fixtures:
            assert available() >= 49.3, 'Insufficient starting headroom for this bounded probe'
            raw = (root / 'clips' / fixture['file']).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == fixture['sha256'], 'Fixture changed; review ground truth again'
            prompt = ORIGINAL if args.prompt == 'original' else ANY_FRAME
            body = {'model': model, 'messages': [
                {'role': 'system', 'content': 'Answer yes or no'},
                {'role': 'user', 'content': [
                    {'type': 'video_url', 'video_url': {'url': 'data:video/mp4;base64,' + base64.b64encode(raw).decode()}},
                    {'type': 'text', 'text': prompt}]}],
                'max_tokens': 128, 'temperature': 0, 'seed': 42, 'chunk_duration': 0,
                'enable_audio': False, 'enable_reasoning': False,
                'num_frames_per_second_or_fixed_frames_chunk': 4, 'use_fps_for_chunking': False,
                'vlm_input_width': 512, 'vlm_input_height': 512}
            start = time.monotonic()
            response = request('/v1/chat/completions', body)
            answer = response['choices'][0]['message']['content']
            row = {'file': fixture['file'], 'repeat': repeat, 'prompt': prompt,
                'expected': fixture['expected'], 'answer': answer,
                'seconds': round(time.monotonic() - start, 3),
                'matched': answer.strip().upper().rstrip('.') == fixture['expected'],
                'available_gib_after': round(available(), 3)}
            rows.append(row)
            args.output.write_text(json.dumps(rows, indent=2))
            print(f"{fixture['file']}: {answer} / expected {fixture['expected']} ({row['seconds']}s)", flush=True)
    passed = all(row['matched'] for row in rows)
    print('PASS' if passed else 'FAIL: box-presence disagreement')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
