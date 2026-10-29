#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read existing exact previews; record identity and identical observed boxes.

This observer never requests inference, changes a source, or merges detections.
Equal boxes are a diagnostic, not proof of equal RF-DETR query identity: the
public preview does not expose query indices, and different objects can overlap.
Use soak.py alongside this helper for runtime/clock/Ask qualification.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import time

from soak import (SoakFailure, ID, atomic_json, file_sha, origin,
                  parse_preview_envelope, preview_request, utc)

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def summarize_tracks(dto):
    """Only current observations count; predicted/stale tracks are excluded."""
    observed = [track for track in dto['snapshot']['tracks']
                if track.get('observedThisFrame') is True and track.get('stale') is False]
    boxes = defaultdict(list)
    for track in observed:
        boxes[tuple(track['bboxPx'])].append(track)
    groups = []
    for box, tracks in boxes.items():
        if len({track['id'] for track in tracks}) < 2:
            continue
        groups.append({'bboxPx': list(box), 'classes': sorted({track['class'] for track in tracks}),
                       'tracks': [{key: track.get(key) for key in
                                   ('id', 'localTrackId', 'class', 'confidence')}
                                  for track in tracks]})
    return {'observedTrackCount': len(observed),
            'classCounts': dict(sorted(Counter(track['class'] for track in observed).items())),
            'identicalObservedBoxGroups': groups,
            'identicalCrossClassBoxGroups': sum(len(group['classes']) > 1 for group in groups)}


def inspect_envelope(body, source_id, site_id, expected_revision):
    identity = parse_preview_envelope(body, source_id, site_id)
    if identity['modelRevision'] != expected_revision:
        raise SoakFailure('unexpected-preview-model-revision:' + source_id)
    length = struct.unpack('>I', body[:4])[0]
    dto = json.loads(body[4:4 + length])
    return {**identity, **summarize_tracks(dto)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vss-origin', type=origin, default='http://127.0.0.1:7782')
    parser.add_argument('--site-id', required=True)
    parser.add_argument('--source-id', action='append', required=True)
    parser.add_argument('--expected-model-revision', required=True)
    parser.add_argument('--duration-seconds', type=int, default=1200)
    parser.add_argument('--sample-every-seconds', type=int, default=10)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if len(args.source_id) != 2 or len(set(args.source_id)) != 2 or any(not ID.fullmatch(sid) for sid in args.source_id):
        parser.error('Provide exactly two distinct valid source IDs')
    if not ID.fullmatch(args.site_id) or not 1 <= len(args.expected_model_revision) <= 512:
        parser.error('Invalid site ID or model revision')
    if not 10 <= args.duration_seconds <= 3600 or not 5 <= args.sample_every_seconds <= 30:
        parser.error('Use 10–3600 seconds duration and 5–30 seconds sampling')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    samples_path = args.output_dir / 'samples.ndjson'
    started = time.monotonic()
    start_utc = utc()
    sources = {}
    failure = None
    iterations = 0
    try:
        with samples_path.open('x') as handle:
            while time.monotonic() - started < args.duration_seconds:
                iteration_started = time.monotonic()
                for source_id in args.source_id:
                    body = preview_request(args.vss_origin, source_id)
                    if body is None:
                        raise SoakFailure('preview-unavailable:' + source_id)
                    record = inspect_envelope(body, source_id, args.site_id, args.expected_model_revision)
                    state = sources.setdefault(source_id, {
                        'sessionId': record['sessionId'], 'sourceSessionId': record['sourceSessionId'],
                        'firstSequence': record['sequence'], 'lastSequence': record['sequence'],
                        'samples': 0, 'framesWithIdenticalObservedBoxes': 0,
                        'framesWithIdenticalCrossClassBoxes': 0,
                    })
                    if any(state[key] != record[key] for key in ('sessionId', 'sourceSessionId')):
                        raise SoakFailure('preview-session-changed:' + source_id)
                    if int(record['sequence']) < int(state['lastSequence']):
                        raise SoakFailure('preview-sequence-regressed:' + source_id)
                    state['lastSequence'] = record['sequence']
                    state['samples'] += 1
                    state['framesWithIdenticalObservedBoxes'] += bool(record['identicalObservedBoxGroups'])
                    state['framesWithIdenticalCrossClassBoxes'] += bool(record['identicalCrossClassBoxGroups'])
                    handle.write(json.dumps({'at': utc(), **record}, allow_nan=False) + '\n')
                    handle.flush()
                iterations += 1
                remaining = args.duration_seconds - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(min(remaining, max(0, args.sample_every_seconds - (time.monotonic() - iteration_started))))
            for source_id in args.source_id:
                state = sources.get(source_id, {})
                if state.get('samples', 0) < 2 or int(state['lastSequence']) <= int(state['firstSequence']):
                    raise SoakFailure('insufficient-advancing-previews:' + source_id)
    except (SoakFailure, OSError, ValueError, KeyError, TypeError) as exc:
        failure = str(exc) if isinstance(exc, SoakFailure) else type(exc).__name__
    except KeyboardInterrupt:
        failure = 'interrupted'
    receipt = {
        'schemaVersion': 'city.preview-duplicate-audit.v1',
        'status': 'failed' if failure else 'completed', 'failure': failure,
        'startedAt': start_utc, 'finishedAt': utc(), 'elapsedSeconds': time.monotonic() - started,
        'requestedDurationSeconds': args.duration_seconds, 'sampleEverySeconds': args.sample_every_seconds,
        'siteId': args.site_id, 'sourceIds': args.source_id, 'iterations': iterations,
        'expectedModelRevision': args.expected_model_revision, 'sources': sources,
        'samplesSha256': file_sha(samples_path), 'helperSourceSha256': SOURCE_SHA256,
        'scope': 'Read-only exact-preview observations; no inference or source-control request.',
        'limits': [
            'Identical boxes are diagnostic only: distinct model queries can legitimately overlap.',
            'Public previews do not expose query IDs; zero equal boxes does not prove zero duplicate objects.',
            'This does not assess classification accuracy or replace the integrated soak test.',
        ],
    }
    atomic_json(args.output_dir / 'receipt.json', receipt)
    print(json.dumps(receipt, indent=2))
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
