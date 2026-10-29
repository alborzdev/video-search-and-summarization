#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare two prediction sets using the same simple per-camera IoU tracker.

The frame manifest is {"frames": [{"image_id": int, "source_id": str,
"frame_index": int, "timestamp_ns": int}, ...]}. Frame indices must be
consecutive within each source. Each prediction file is {"processed_image_ids":
[int, ...], "predictions": [{"image_id": int, "category_id": int, "bbox":
[x,y,w,h], "score": float}, ...]}; explicit processed IDs distinguish empty
frames from missing inference. IDs must refer to the exact same source pixels.

This is a model-to-model diagnostic, not a physical-object tracking benchmark.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics


def load(path):
    data = path.read_bytes()
    return json.loads(data), hashlib.sha256(data).hexdigest()


def validate_manifest(manifest):
    frames = manifest['frames']
    if not frames:
        raise ValueError('Frame manifest is empty')
    ids, by_source = set(), defaultdict(list)
    for f in frames:
        image_id, source, frame_index, timestamp = (f[k] for k in ('image_id', 'source_id', 'frame_index', 'timestamp_ns'))
        if (isinstance(image_id, bool) or not isinstance(image_id, int) or image_id in ids or
            not isinstance(source, str) or not source or isinstance(frame_index, bool) or
            not isinstance(frame_index, int) or frame_index < 0 or isinstance(timestamp, bool) or
            not isinstance(timestamp, int) or timestamp < 0):
            raise ValueError('Invalid or duplicate frame identity')
        ids.add(image_id); by_source[source].append(f)
    for rows in by_source.values():
        rows.sort(key=lambda x: x['frame_index'])
        for a, b in zip(rows, rows[1:]):
            if b['frame_index'] != a['frame_index'] + 1 or b['timestamp_ns'] <= a['timestamp_ns']:
                raise ValueError('Each source requires consecutive frames and increasing timestamps')
    return ids, dict(by_source)


def validate_predictions(document, ids, supported):
    if not supported:
        raise ValueError('Declare at least one supported category')
    covered = document['processed_image_ids']
    if len(covered) != len(set(covered)) or set(covered) != ids:
        raise ValueError('Processed image IDs must exactly cover the frame manifest')
    predictions = document['predictions']
    for p in predictions:
        if p['image_id'] not in ids or p['category_id'] not in supported:
            raise ValueError('Unknown image or unsupported category in predictions')
        bbox, score = p['bbox'], p['score']
        if (len(bbox) != 4 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in bbox)
            or bbox[2] <= 0 or bbox[3] <= 0 or not isinstance(score, (int, float))
            or not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError('Invalid bbox or score')


def box_iou(a, b):
    w = max(0., min(a[0]+a[2], b[0]+b[2]) - max(a[0], b[0]))
    h = max(0., min(a[1]+a[3], b[1]+b[3]) - max(a[1], b[1]))
    intersection = w * h
    return intersection / (a[2]*a[3] + b[2]*b[3] - intersection)


def track(by_source, predictions, categories, min_score, min_iou, max_gap):
    grouped = defaultdict(list)
    for p in predictions:
        if p['category_id'] in categories and p['score'] >= min_score:
            grouped[p['image_id']].append(p)
    result = {}
    for source, frames in sorted(by_source.items()):
        tracks, assignments = [], []
        for f in frames:
            index = f['frame_index']
            detections = grouped[f['image_id']]
            candidates = []
            for ti, t in enumerate(tracks):
                if index - t['lastFrame'] > max_gap + 1:
                    continue
                for di, d in enumerate(detections):
                    if t['categoryId'] == d['category_id']:
                        overlap = box_iou(t['lastBox'], d['bbox'])
                        if overlap >= min_iou:
                            candidates.append((overlap, ti, di))
            candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
            used_tracks, used_detections = set(), set()
            chosen = {}
            for _, ti, di in candidates:
                if ti in used_tracks or di in used_detections:
                    continue
                used_tracks.add(ti); used_detections.add(di); chosen[di] = ti
            for di, d in enumerate(detections):
                if di not in chosen:
                    chosen[di] = len(tracks)
                    tracks.append({'id': len(tracks)+1, 'categoryId': d['category_id'], 'firstFrame': index,
                                   'lastFrame': index, 'firstNs': f['timestamp_ns'], 'lastNs': f['timestamp_ns'],
                                   'lastBox': d['bbox'], 'observations': 0, 'missedFramesInsideTrack': 0,
                                   'gapReacquisitions': 0})
                t = tracks[chosen[di]]
                if t['observations']:
                    gap = index - t['lastFrame'] - 1
                    t['missedFramesInsideTrack'] += gap
                    t['gapReacquisitions'] += int(gap > 0)
                t['lastFrame'], t['lastNs'], t['lastBox'] = index, f['timestamp_ns'], d['bbox']
                t['observations'] += 1
                assignments.append({'imageId': f['image_id'], 'detectionIndex': di, 'trackId': t['id'],
                                    'categoryId': d['category_id'], 'bbox': d['bbox'], 'score': d['score']})
        per_class = {}
        for category in sorted(categories):
            selected = [t for t in tracks if t['categoryId'] == category]
            sizes = [t['observations'] for t in selected]
            durations = [(t['lastNs']-t['firstNs'])/1e9 for t in selected]
            per_class[str(category)] = {'tracks': len(selected), 'observations': sum(sizes),
                'medianObservationsPerTrack': statistics.median(sizes) if sizes else None,
                'medianObservedDurationSeconds': statistics.median(durations) if durations else None,
                'missedFramesInsideTracks': sum(t['missedFramesInsideTrack'] for t in selected),
                'gapReacquisitions': sum(t['gapReacquisitions'] for t in selected)}
        result[source] = {'frameCount': len(frames), 'perCategory': per_class, 'assignments': assignments,
                          'tracks': [{k: v for k, v in t.items() if k != 'lastBox'} for t in tracks]}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=Path, required=True)
    p.add_argument('--a', type=Path, required=True)
    p.add_argument('--b', type=Path, required=True)
    p.add_argument('--a-categories', type=int, nargs='+', required=True)
    p.add_argument('--b-categories', type=int, nargs='+', required=True)
    p.add_argument('--minimum-score', type=float, default=.3)
    p.add_argument('--minimum-iou', type=float, default=.5)
    p.add_argument('--max-gap-frames', type=int, default=1)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 0 <= args.minimum_score <= 1 or not 0 < args.minimum_iou <= 1 or args.max_gap_frames < 0:
        p.error('Score must be in [0,1], IoU in (0,1], and max-gap-frames nonnegative')
    manifest, manifest_hash = load(args.frames)
    a, a_hash = load(args.a); b, b_hash = load(args.b)
    ids, by_source = validate_manifest(manifest)
    categories_a, categories_b = set(args.a_categories), set(args.b_categories)
    validate_predictions(a, ids, categories_a); validate_predictions(b, ids, categories_b)
    common = categories_a & categories_b
    if not common:
        raise ValueError('Models have no common supported categories')
    receipt = {'schemaVersion': 'city.detector-continuity-diagnostic.v1',
        'inputSha256': {'frames': manifest_hash, 'a': a_hash, 'b': b_hash,
                        'evaluator': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        'supportedCategories': {'a': sorted(categories_a), 'b': sorted(categories_b), 'compared': sorted(common)},
        'parameters': {'minimumScore': args.minimum_score, 'minimumIoU': args.minimum_iou,
                       'maxGapFrames': args.max_gap_frames, 'matcher': 'per-camera, same-class greedy highest IoU'},
        'scope': 'Temporary per-camera IoU tracks on declared common classes; counts, lengths and gaps are diagnostics, not physical-object fragmentation, ID switches, detection/tracking accuracy or cross-camera identity. Inputs do not independently verify identical pixels or honest inference coverage.',
        'a': track(by_source, a['predictions'], common, args.minimum_score, args.minimum_iou, args.max_gap_frames),
        'b': track(by_source, b['predictions'], common, args.minimum_score, args.minimum_iou, args.max_gap_frames)}
    with args.output.open('x') as out:
        json.dump(receipt, out, indent=2, allow_nan=False); out.write('\n')
    print(f'Wrote diagnostic receipt: {args.output}')


if __name__ == '__main__':
    main()
