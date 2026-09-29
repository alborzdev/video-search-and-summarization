# SPDX-License-Identifier: MIT
"""Bounded diagnostic for the visually deformed simulation carton, not a general evaluator."""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--start-time', default='2025-01-01T00:00:00Z')
parser.add_argument('--question', default="Describe the box's shape.")
args = parser.parse_args()
payload = {
    'query': 'crumpled cardboard box on a conveyor',
    'question': args.question,
    'evidence': [{
        'client_id': 'package-condition-diagnostic',
        'sensor_id': 'ebb07ef6-8d22-479f-84b7-ccd77c45ebd4',
        'source_name': 'conveyor-package-review-demo',
        'start_time': args.start_time,
        'end_time': '2025-01-01T00:00:05Z',
        'match_type': 'Semantic Match',
        'search_description': 'Crumpled cardboard box on a conveyor',
    }],
}
request = urllib.request.Request(args.base_url.rstrip('/') + '/api/vision/evidence-analysis',
    data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}, method='POST')
started = time.monotonic()
with urllib.request.urlopen(request, timeout=60) as response:
    result = json.load(response)
answer = result.get('summary', '')
# A useful response must mention deformation. A keyword hit still requires human review.
mentions_deformation = bool(re.search(r'crumpl|crush|deform|dent|collaps|squash|wrinkl|irregular|distort|bent|buckl', answer, re.I))
receipt = {'request': payload, 'response': result, 'elapsed_seconds': round(time.monotonic()-started, 3),
           'mentions_visible_deformation': mentions_deformation}
Path(args.output).write_text(json.dumps(receipt, indent=2)+'\n')
print(('CANDIDATE PASS (review required)' if mentions_deformation else 'FAIL (missed visible deformation)') + ': ' + answer)
print('Elapsed:', receipt['elapsed_seconds'])
raise SystemExit(0 if mentions_deformation else 1)
