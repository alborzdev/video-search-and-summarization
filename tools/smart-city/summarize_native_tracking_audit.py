#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit exact detector-to-SDK provenance; continuity counts are not accuracy.

Consumes --tracker-diagnostics output from the native MV3DT worker. It refuses
partial snapshots and ambiguous input ordinals. A detector input omitted by the
tracker can be normal late activation, shadow tracking, or association filtering;
its absence is not proof of a false detection or a lost physical target.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics


def summarize(records):
    cameras = {}
    seen_frames = set()
    for row in records:
        audit = row.get('detectorTrackerAudit')
        if not audit or audit.get('schemaVersion') != 'city.detector-tracker-audit.v1':
            raise ValueError('Missing native detector/tracker provenance audit')
        if audit.get('inputSnapshotComplete') is not True or audit.get('outputSnapshotComplete') is not True:
            raise ValueError('Incomplete diagnostic snapshot cannot support provenance conclusions')
        inputs, outputs = audit['inputs'], audit['outputs']
        count = audit['inputDetectionCount']
        if len(inputs) != count or {v['ordinal'] for v in inputs} != set(range(1, count + 1)):
            raise ValueError('Input ordinals must cover the declared inputs exactly once')
        if len(outputs) != audit['rawSdkOutputCount']:
            raise ValueError('SDK output count differs from snapshot')
        source, session = row['sourceId'], row['sourceSessionId']
        sequence = int(row['sequence'])
        identity = (source, session, row.get('trackingEpoch'), row.get('fusionEpoch'), row['modelRevision'])
        frame = (*identity, sequence)
        if frame in seen_frames:
            raise ValueError('Duplicate source/session/frame')
        seen_frames.add(frame)
        ns = int(row['sourceTimeNs'])
        c = cameras.setdefault(source, {'frames': 0, 'counts': Counter({name: 0 for name in (
            'detectorInputs', 'sdkOutputs', 'currentDetectorOutputs', 'sdkConfidenceWithoutCurrentStamp',
            'sdkPredictionOutputs', 'currentStampWithoutSdkConfidence', 'ambiguousSdkOutputs',
            'untrackedSdkOutputs', 'duplicateCurrentOrdinals', 'inputsNotReturnedAsCurrentSdkObject',
            'publishedObjects', 'publishedUnobservedObjects')}), 'classes': defaultdict(Counter),
            'firstNs': ns, 'lastNs': ns, 'tracks': defaultdict(list), 'lastSequences': {}, 'epochs': set()})
        previous = c['lastSequences'].get(identity)
        if previous and (sequence <= previous[0] or ns <= previous[1]):
            raise ValueError('Source sequence/time must increase within an epoch')
        c['lastSequences'][identity] = (sequence, ns)
        c['firstNs'], c['lastNs'] = min(c['firstNs'], ns), max(c['lastNs'], ns)
        c['epochs'].add(identity); c['frames'] += 1
        counts = c['counts']
        counts['detectorInputs'] += count
        counts['sdkOutputs'] += len(outputs)
        for item in inputs:
            cls = c['classes'][str(item['sdkClassId'])]
            cls['detectorInputs'] += 1
            cls['inputsBelow035'] += item['confidence'] < .35
            cls['inputBoxUnder30PxHigh'] += bool(item['bboxPx'] and item['bboxPx'][3] < 30)
        associated = set()
        for item in outputs:
            cls = c['classes'][str(item['sdkClassId'])]
            cls['sdkOutputs'] += 1
            exact = item['currentDetectorStamp'] is True
            confidence = item['sdkDetectorConfidencePresent'] is True
            counts['sdkConfidenceWithoutCurrentStamp'] += confidence and not exact
            counts['sdkPredictionOutputs'] += not confidence and not exact
            counts['currentStampWithoutSdkConfidence'] += exact and not confidence
            counts['ambiguousSdkOutputs'] += item['idRejectedAsAmbiguous'] is True
            counts['untrackedSdkOutputs'] += item['untracked'] is True
            if exact:
                ordinal = item['inputOrdinal']
                if ordinal not in range(1, count + 1) or inputs[ordinal-1]['sdkClassId'] != item['sdkClassId']:
                    raise ValueError('Output references an invalid detector ordinal/class')
                counts['duplicateCurrentOrdinals'] += ordinal in associated
                associated.add(ordinal)
                counts['currentDetectorOutputs'] += 1; cls['currentDetectorOutputs'] += 1
        counts['inputsNotReturnedAsCurrentSdkObject'] += count - len(associated)
        counts['publishedObjects'] += len(row['objects'])
        frame_ids = set()
        for item in row['objects']:
            if item.get('observedThisFrame') is not True:
                counts['publishedUnobservedObjects'] += 1
                continue
            key = (*identity, item['class'], item['localTrackId'])
            if key in frame_ids:
                raise ValueError('Duplicate published same-camera identity/class in a frame')
            frame_ids.add(key)
            c['classes'][item['class']]['publishedObservedObjects'] += 1
            c['tracks'][key].append((sequence, ns))
    result = {}
    for source, c in cameras.items():
        gaps, missing, appearances = [], 0, []
        for values in c['tracks'].values():
            appearances.append(len(values))
            for a, b in zip(values, values[1:]):
                if b[0] > a[0] + 1:
                    missing += b[0] - a[0] - 1
                    gaps.append((b[1] - a[1]) / 1e6)
        result[source] = {'frames': c['frames'], 'epochCount': len(c['epochs']),
            'sourceTimeSpanSeconds': (c['lastNs'] - c['firstNs']) / 1e9,
            'counts': dict(c['counts']), 'perClass': {k: dict(v) for k, v in c['classes'].items()},
            'continuityDiagnostic': {'distinctPublishedIdClassEpochKeys': len(appearances),
                'medianAppearancesPerKey': statistics.median(appearances) if appearances else None,
                'returnGapCount': len(gaps), 'missingSequencePositionsInsideReturnedKeys': missing,
                'returnGapMedianMs': statistics.median(gaps) if gaps else None,
                'returnGapsWithin350Ms': sum(g <= 350 for g in gaps)}}
    return {'schemaVersion': 'city.native-tracking-audit-summary.v1', 'sources': result,
        'scope': 'Exact detector provenance and SDK export diagnostics. Unreturned inputs may be ordinary tracker lifecycle filtering. Published-ID gaps do not measure detector recall, physical-object fragmentation, ID switches, global-ID correctness or tracking accuracy. No ground-truth identities are used.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observations', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    digest = hashlib.sha256()
    def records():
        with args.observations.open('rb') as stream:
            for line in stream:
                digest.update(line)
                if line.strip(): yield json.loads(line)
    result = summarize(records())
    result['observationsSha256'] = digest.hexdigest()
    result['summarizerSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
