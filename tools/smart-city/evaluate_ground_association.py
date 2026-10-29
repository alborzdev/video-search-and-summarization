#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Replay image detections, then score separately against held-out actor labels.

Actor labels enter only score(); replay() has no ground-truth argument.
This is a bounded simulator check, not HOTA/IDF1 or field qualification.
"""
from __future__ import annotations
import argparse
import bisect
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'services/analytics/behavior-analytics/apps'))
from experimental_ground_association import GroundAssociator, METHOD
from city.geometry import project as checked_project
from evaluate_mv3dt_probe import assignment, percentile


def replay(rows, package):
    cameras = {camera['sourceId']: camera for camera in package['cameras']}
    tracks = {}
    associator = GroundAssociator()
    newest = 0
    for row in rows:
        source = row['sourceId']
        camera = cameras[source]
        ns = int(row['sourceTimeNs'])
        newest = max(newest, ns)
        current = set()
        output = json.loads(json.dumps(row))
        for obj in output['objects']:
            identity = f"{source}:{row['sourceSessionId']}:{obj['localTrackId']}"
            box = obj['bboxPx']
            point, _ = checked_project([box[0] + box[2] / 2, box[1] + box[3]],
                camera['imageToGroundHomography'], camera.get('validGroundPolygon'), package.get('mapBoundsM'))
            obj['groundPositionM'] = point
            tracks[identity] = {**obj, 'id': identity, 'sourceId': source, 'sourceTimeNs': str(ns),
                'timestampBasis': row['timestampBasis'], 'imageSize': [camera['width'], camera['height']],
                'positionM': point, 'stale': not obj['observedThisFrame']}
            current.add(identity)
        for identity, track in list(tracks.items()):
            if newest - int(track['sourceTimeNs']) > 2_000_000_000:
                tracks.pop(identity)
            elif track['sourceId'] == source and identity not in current:
                track['observedThisFrame'] = False
        assigned = associator.update(list(tracks.values()), source, row['sourceSessionId'], newest)
        for obj in output['objects']:
            identity = f"{source}:{row['sourceSessionId']}:{obj['localTrackId']}"
            obj['globalTrackId'] = assigned.get(identity)
            obj['associationMethod'] = METHOD if obj['globalTrackId'] else None
        yield output


def score(rows, gt_path, package):
    with gt_path.open() as handle:
        header = json.loads(next(handle))
        if header.get('kind') != 'simulator-ground-truth-evaluation-only':
            raise ValueError('Separate evaluation-only labels required')
        gt = [json.loads(line) for line in handle]
    times = [int(row['captureUnixNs']) for row in gt]
    cameras = {camera['sourceId']: camera for camera in package['cameras']}
    truth_by_group = {}
    false_pairings = []
    errors = []
    all_errors = []
    scored = {source: [] for source in cameras}
    first = min(int(row['sourceTimeNs']) for row in rows if row['timestampBasis'] == 'source-rtcp')
    names = set()
    unmatched = 0
    for row in rows:
        at = int(row['sourceTimeNs'])
        if row['timestampBasis'] != 'source-rtcp' or at - first < 10e9:
            continue
        index = bisect.bisect_left(times, at)
        choices = [i for i in (index - 1, index) if 0 <= i < len(times)]
        index = min(choices, key=lambda i: abs(times[i] - at))
        if abs(times[index] - at) > 250_000_000:
            continue
        camera = cameras[row['sourceId']]
        labels = []
        for name, world in gt[index]['peopleWorldM'].items():
            point = [world[0], world[1], world[2] - package['groundWorldZM'], 1.]
            q = [sum(a * b for a, b in zip(line, point)) for line in camera['projectionMatrix3x4']]
            if q[2] > 0:
                pixel = [q[0] / q[2], q[1] / q[2]]
                if 0 <= pixel[0] <= camera['width'] and 0 <= pixel[1] <= camera['height']:
                    labels.append((name, world[:2], pixel))
        objects = [obj for obj in row['objects'] if obj['class'] == 'person' and obj['observedThisFrame']
                   and obj.get('groundPositionM') is not None and (obj.get('confidence') or 0) >= .55]
        costs = []
        for obj in objects:
            x, y, width, height = obj['bboxPx']
            costs.append([math.hypot((pixel[0] - x - width / 2) / max(width, 10.),
                (pixel[1] - y - height) / max(height, 20.)) for _, _, pixel in labels])
        selected = assignment(costs)
        unmatched += len(objects) - len(selected)
        matched = {}
        for oi, li in selected:
            obj = objects[oi]
            name, world, _ = labels[li]
            names.add(name)
            error = math.dist(obj['groundPositionM'], world)
            all_errors.append(error)
            group = obj.get('globalTrackId')
            if group:
                errors.append(error)
                truth_by_group.setdefault(group, set()).add(name)
            matched[name] = {'group': group, 'localId': obj['localTrackId']}
        # Independent image-space labels may be ambiguous under occlusion; retain
        # any disagreement as a failed gate rather than silently discarding it.
        group_names = {}
        for name, item in matched.items():
            if item['group']:
                group_names.setdefault(item['group'], set()).add(name)
        false_pairings.extend({'timeNs': at, 'group': group, 'labels': sorted(values)}
            for group, values in group_names.items() if len(values) > 1)
        scored[row['sourceId']].append({'timeNs': at, 'matched': matched})
    a, b = (scored[source] for source in cameras)
    bt = [row['timeNs'] for row in b]
    skew = []
    opportunities = associated = wrong = 0
    for row in a:
        index = bisect.bisect_left(bt, row['timeNs'])
        choices = [i for i in (index - 1, index) if 0 <= i < len(b)]
        if not choices:
            continue
        other = b[min(choices, key=lambda i: abs(bt[i] - row['timeNs']))]
        delta = abs(other['timeNs'] - row['timeNs']) / 1e6
        skew.append(delta)
        if delta > 50:
            continue
        for name in set(row['matched']) & set(other['matched']):
            opportunities += 1
            group = row['matched'][name]['group']
            associated += bool(group and group == other['matched'][name]['group'])
        for name, item in row['matched'].items():
            if item['group']:
                wrong += any(other_name != name and target['group'] == item['group']
                    for other_name, target in other['matched'].items())
    merged = {group: sorted(values) for group, values in truth_by_group.items() if len(values) > 1}
    metrics = {'observationCount': len(rows), 'distinctMatchedPeople': len(names),
        'associatedPersonObservations': len(errors), 'unmatchedEligiblePersonDetections': unmatched,
        'positionMedianM': percentile(errors, .5), 'positionP95M': percentile(errors, .95),
        'allGroundAnchorMedianM': percentile(all_errors, .5), 'allGroundAnchorP95M': percentile(all_errors, .95),
        'sourceClockSkewP95Ms': percentile(skew, .95), 'pairedSamples': len(skew),
        'crossViewOpportunities': opportunities, 'sameIdCrossViewMatches': associated,
        'duplicateReductionFraction': associated / opportunities if opportunities else 0,
        'falseMergedGroups': len(merged), 'simultaneousWrongCrossViewMatches': wrong}
    checks = {'duration': (max(int(row['sourceTimeNs']) for row in rows) - first) / 1e9 >= 120,
        'samples': len(skew) >= 100, 'clock': metrics['sourceClockSkewP95Ms'] is not None and metrics['sourceClockSkewP95Ms'] <= 50,
        'positionMedian': metrics['positionMedianM'] is not None and metrics['positionMedianM'] <= .5,
        'positionP95': metrics['positionP95M'] is not None and metrics['positionP95M'] <= 1.,
        'matchedPeople': len(names) >= 5, 'falseMerges': not merged and not wrong and not false_pairings,
        'duplicateReduction': metrics['duplicateReductionFraction'] >= .5}
    return {'passed': all(checks.values()), 'method': METHOD, 'checks': checks, 'metrics': metrics,
        'falseMergeDetails': merged, 'withinViewConflicts': false_pairings,
        'qualification': 'Bounded simulator image-space label comparison. Not HOTA/IDF1, occlusion, vehicle fusion or real-city accuracy.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--ground-truth', type=Path, required=True)
    args = parser.parse_args()
    package = json.loads(args.package.read_text())
    rows = [json.loads(line) for line in (args.run / 'observations.ndjson').read_text().splitlines()]
    replayed = list(replay(rows, package))
    with (args.run / 'associated-observations.ndjson').open('w') as handle:
        for row in replayed:
            handle.write(json.dumps(row) + '\n')
    result = score(replayed, args.ground_truth, package)
    result['inputHashes'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (args.run / 'observations.ndjson', args.package, args.ground_truth)}
    (args.run / 'engineering-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('passed', 'checks', 'metrics')}, indent=2))
