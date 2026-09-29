"""Diagnostic only: measure local question rewriting, without changing app behavior."""
import json
import time
import urllib.request
from pathlib import Path

CASES = [
    "Compare the person's position in E1 and E2. Describe only visible movement and where the person stands at the end of each clip.",
    "Did the worker put the box down in E1 or E2, or are they still holding it?",
    "How many forklifts enter the marked area in each clip? Count entries, not parked forklifts.",
    "In E1, does the person wear a helmet? In E2, is the aisle blocked?",
    "Is this the same person in E1 and E2?",
]
SYSTEM = """Translate an operator's multi-clip question into a focused visual inspection question for each supplied clip label. Each inspection sees ONLY its own clip. Preserve the operator's requested actions, counts, negations, time bounds, and final-state checks. Remove cross-clip comparison language. Apply label-specific requests only to their matching label. Do not answer the question, assume any visual facts, or add general scene inventory. Cross-clip identity cannot be established: for identity questions ask for observable appearance only, without claiming identity. Return questions for E1 and E2."""

def available_gib():
    line = next(line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    return int(line.split()[1]) / 1024**2

def main():
    for question in CASES:
        before = available_gib()
        if before < 48.5:
            raise RuntimeError(f'Insufficient diagnostic margin: {before:.2f} GiB')
        body = {
            'model': 'nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8',
            'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': question}],
            'temperature': 0, 'max_tokens': 220,
            'chat_template_kwargs': {'enable_thinking': False},
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'clip_questions', 'strict': True, 'schema': {
                    'type': 'object', 'properties': {key: {'type': 'string'} for key in ('E1', 'E2')},
                    'required': ['E1', 'E2'], 'additionalProperties': False,
                }}},
        }
        start = time.monotonic()
        request = urllib.request.Request('http://127.0.0.1:30081/v1/chat/completions',
                                         data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        content = result['choices'][0]['message']['content']
        print(json.dumps({'question': question, 'questions': json.loads(content),
                          'seconds': round(time.monotonic()-start, 3),
                          'finish_reason': result['choices'][0]['finish_reason'],
                          'available_gib_before': round(before, 3),
                          'available_gib_after': round(available_gib(), 3)}), flush=True)

if __name__ == '__main__':
    main()
