#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded, CPU-only audit of existing observation tail; no service requests.

Same SDK IDs are candidate correspondences, not accuracy ground truth. Current
production rects are post-tracker boxes; independent detector geometry requires
the optional tracker-diagnostics export. Does not alter any IDs/anchors/guards.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parents[2]
CLASSES = ('person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck')


def stats(values):
    values = sorted(values)
    if not values:
        return None
    return {'count': len(values), 'min': round(values[0], 5), 'p50': round(statistics.median(values), 5),
            'p90': round(values[math.ceil(len(values) * .9) - 1], 5), 'max': round(values[-1], 5)}


def read_tail(path, maximum_bytes=4 * 1024 * 1024, maximum_rows=500):
    before = time.time_ns()
    with path.open('rb') as source:
        stat = os.fstat(source.fileno())
        offset = max(0, stat.st_size - maximum_bytes)
        source.seek(offset)
        data = source.read(maximum_bytes)
    if offset:
        data = data.split(b'\n', 1)[-1]
    lines = data.split(b'\n')[:-1][-maximum_rows:]
    tail = b'\n'.join(lines) + b'\n'
    after = time.time_ns()
    return [json.loads(row) for row in lines], tail, {'path': str(path), 'inode': stat.st_ino,
        'fileSizeBytes': stat.st_size, 'bytesRead': len(data), 'rowCount': len(lines),
        'readStartUnixNs': str(before), 'readEndUnixNs': str(after), 'tailSha256': hashlib.sha256(tail).hexdigest()}


def project(matrix, pixel):
    result = [sum(a * b for a, b in zip(row, [*pixel, 1])) for row in matrix]
    if not all(math.isfinite(x) for x in result) or abs(result[2]) < 1e-12:
        raise ValueError('Invalid projected anchor.')
    return [result[0] / result[2], result[1] / result[2]]


def anchor(row, obj, calibrations, kind):
    if kind == 'world':
        return obj['native3D']['worldPositionM']
    calibration = calibrations[row['sourceId']]
    matrix = calibration.get('classImageToGroundHomographies', {}).get(obj['class'], calibration['imageToGroundHomography'])
    if kind == 'imageFoot':
        pixel = obj['native3D']['imageFootPx']
    else:
        x, y, width, height = obj['bboxPx']
        pixel = [x + width / 2, y + height]
    return project(matrix, pixel)


def eligible(obj):
    native = obj.get('native3D') or {}
    return (obj.get('observedThisFrame') is True and native.get('visibility') is not None
            and .25 <= native['visibility'] <= 1 and native.get('targetId') == obj.get('localTrackId')
            and all(isinstance(native.get(k), list) and len(native[k]) == 2
                    and all(math.isfinite(v) for v in native[k]) for k in ('worldPositionM', 'imageFootPx')))


def analyze(rows, calibrations, read):
    latest = {row['sourceId']: row for row in rows}
    source_ids = sorted(latest)
    if len(source_ids) != 2:
        raise ValueError('Exactly two existing sources required in bounded tail.')
    # An epoch change in either source forbids pairing across that boundary.
    latest_epochs = {row.get('fusionEpoch') for row in latest.values()}
    epoch = next(iter(latest_epochs)) if len(latest_epochs) == 1 else None
    clock_bases = {row.get('timestampBasis') for row in latest.values()}
    basis = next(iter(clock_bases)) if len(clock_bases) == 1 else None
    if basis not in ('source-rtcp', 'source-native-sei'):
        basis = None
    current = [row for row in rows if epoch and basis and row.get('fusionEpoch') == epoch
               and row['sourceSessionId'] == latest[row['sourceId']]['sourceSessionId']
               and row['timestampBasis'] == basis]
    if basis == 'source-native-sei':
        for row in current:
            proof = row.get('sourceClockEvidence') or {}
            if not (proof.get('schemaVersion') == 'city.source-native-sei.v1'
                    and proof.get('method') == 'isaac-native-sei-wall-capture'
                    and proof.get('correlation') == 'exact-au-pts'
                    and all(isinstance(proof.get(key), str) and proof[key].isdigit()
                            for key in ('captureTimeNs', 'auPtsNs', 'frameCounter'))
                    and proof.get('captureTimeNs') == row['sourceTimeNs']
                    and proof.get('auPtsNs') == row.get('rawSourcePtsNs')):
                raise ValueError('Native SEI clock lacks exact-AU capture evidence.')
    grouped = {source: [row for row in current if row['sourceId'] == source] for source in source_ids}
    result = {'schemaVersion': 'city.live-tail-audit.v1', 'read': read, 'fusionEpoch': epoch, 'timestampBasis': basis,
              'limitations': 'Same SDK IDs, not independently labelled physical identities; post-tracker rect boxes. No interpolation or threshold changes.',
              'sources': {}, 'pairing': {}, 'classes': {name: {} for name in CLASSES}}
    snapshots, last = [], {}
    for row in current:
        last[row['sourceId']] = row
        if len(last) == 2:
            snapshots.append(abs(int(last[source_ids[0]]['sourceTimeNs']) - int(last[source_ids[1]]['sourceTimeNs'])) / 1e6)
    result['latestPerSourceSkewMs'] = stats(snapshots)
    result['latestPerSourceWithin150Ms'] = sum(value <= 150 for value in snapshots)
    for source, records in grouped.items():
        if not records:
            continue
        timestamps = [int(row['sourceTimeNs']) for row in records]
        result['sources'][source] = {'rows': len(records), 'sessionId': latest[source]['sourceSessionId'],
            'lastSourceTimeNs': str(timestamps[-1]), 'sourceMinusReadEndMs': (timestamps[-1] - int(read['readEndUnixNs'])) / 1e6,
            'sourceDurationSeconds': (timestamps[-1] - timestamps[0]) / 1e9,
            'intervalMs': stats([(b-a)/1e6 for a, b in zip(timestamps, timestamps[1:])]),
            'nonIncreasingClockCount': sum(b <= a for a, b in zip(timestamps, timestamps[1:])),
            'diagnosticRows': sum('trackerDiagnostics' in row for row in records),
            'sdkAmbiguityFrames': sum((row.get('nativeTrackAmbiguity') or {}).get('omittedObjectCount', 0) > 0 for row in records),
            'sdkAmbiguityOmittedObjects': sum((row.get('nativeTrackAmbiguity') or {}).get('omittedObjectCount', 0) for row in records),
            'observedNativeObjectsByClass': dict(Counter(obj['class'] for row in records for obj in row['objects'] if eligible(obj)))}
    if not all(grouped.values()):
        return result
    a, b = [grouped[source] for source in source_ids]
    times = [int(row['sourceTimeNs']) for row in b]
    low, high = max(int(a[0]['sourceTimeNs']), times[0]), min(int(a[-1]['sourceTimeNs']), times[-1])
    frames = []
    for row in a:
        timestamp = int(row['sourceTimeNs'])
        if not low <= timestamp <= high:
            continue
        index = bisect_left(times, timestamp)
        index = min((i for i in (index-1, index) if 0 <= i < len(times)), key=lambda i: abs(times[i]-timestamp))
        frames.append((row, b[index], abs(times[index]-timestamp)/1e6))
    result['pairing'] = {'direction': source_ids, 'basis': f'nearest {basis} within current session/shared epoch common window',
                         'nearestSkewMs': stats([skew for _, _, skew in frames])}
    for bound in (50, 150):
        candidates = defaultdict(list)
        cross_class = Counter()
        for ar, br, skew in frames:
            if skew > bound:
                continue
            ac = Counter(obj['native3D']['targetId'] for obj in ar['objects'] if eligible(obj))
            bc = Counter(obj['native3D']['targetId'] for obj in br['objects'] if eligible(obj))
            aa = {obj['native3D']['targetId']: obj for obj in ar['objects'] if eligible(obj) and ac[obj['native3D']['targetId']] == 1}
            bb = {obj['native3D']['targetId']: obj for obj in br['objects'] if eligible(obj) and bc[obj['native3D']['targetId']] == 1}
            for target in aa.keys() & bb.keys():
                ao, bo = aa[target], bb[target]
                if ao['class'] != bo['class']:
                    cross_class[(ao['class'], bo['class'])] += 1
                    continue
                if any(obj['native3D'].get('calibrationRevision') != calibrations[row['sourceId']]['calibrationRevision']
                       for row, obj in ((ar, ao), (br, bo))):
                    continue
                item = {'targetId': target}
                for kind in ('rect', 'world', 'imageFoot'):
                    item[kind] = math.dist(anchor(ar, ao, calibrations, kind), anchor(br, bo, calibrations, kind))
                candidates[ao['class']].append(item)
        result['pairing'][f'within{bound}MsFrames'] = sum(skew <= bound for _, _, skew in frames)
        result['pairing'][f'crossClassSameSdkId{bound}Ms'] = {f'{a}/{b}': count for (a, b), count in cross_class.items()}
        for name in CLASSES:
            pairs = candidates[name]
            result['classes'][name][str(bound)] = {'candidatePairs': len(pairs),
                'uniqueSdkIds': sorted({pair['targetId'] for pair in pairs}),
                **{kind + 'DisagreementM': stats([pair[kind] for pair in pairs]) for kind in ('rect', 'world', 'imageFoot')},
                **{kind + 'Within1M': sum(pair[kind] <= 1 for pair in pairs) for kind in ('rect', 'world', 'imageFoot')}}
    return result


if __name__ == '__main__':
    rows, tail, read = read_tail(ROOT / '.spark/city/state/live-observations.ndjson')
    calibrations = json.loads((ROOT / '.spark/city/controller-calibrations.json').read_text())
    print(json.dumps(analyze(rows, calibrations, read), indent=2))
