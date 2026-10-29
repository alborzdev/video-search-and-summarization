#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Score native tracking using independent raw-image correspondences.

Reference poses never enter inference. A correspondence requires exactly one
projected reference body/foot probe in the ORIGINAL detector box, independent
of the estimated ground position. Occlusion/visibility is not fully annotated;
ambiguous and unregistered actors remain unknown. This is not HOTA/IDF1.
"""
from bisect import bisect_left
from collections import Counter, defaultdict
import argparse
import hashlib
import json
import math
from pathlib import Path

from audit_live_tail import stats

CLASSES = ('person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler')
OFFSETS_MS = (-100, -50, 0, 50, 100)


def family(name):
    return 'vehicle' if name in ('car', 'truck', 'bus') else name


def midpoint(sample):
    return (int(sample['sampleStartUnixNs'])+int(sample['sampleEndUnixNs']))//2


def epoch(sample):
    return tuple(sample[key] for key in ('stageId', 'vehicleGeneration', 'trafficGeneration', 'peopleGeneration'))


class Reference:
    def __init__(self, samples, camera_export, geometry):
        self.samples = samples
        self.times = [midpoint(sample) for sample in samples]
        if len(samples) < 2 or any(b <= a for a, b in zip(self.times, self.times[1:])):
            raise ValueError('Strictly increasing reference clock required')
        self.cameras = camera_export['cameras']
        self.ground = camera_export['groundWorldZM']
        self.heights = {item['class']: item['heightM'] for item in geometry}
        self.prim_heights = {path: dimensions[2] for item in geometry for path, dimensions in item['measurements']}

    def actors(self, timestamp):
        index = bisect_left(self.times, timestamp)
        if not 0 < index < len(self.samples):
            return None
        a, b = self.samples[index-1:index+1]
        dt = self.times[index]-self.times[index-1]
        if dt > 500_000_000 or epoch(a) != epoch(b):
            return None
        for sample in (a, b):
            if (sample['errors'] or not sample['playing'] or sample['scenario']['active']
                    or sample['scenario']['state'] != 'idle'
                    or any(obj.get('controllerToActualErrorM', 0) > 1e-5 for obj in sample['objects'])):
                return None
        aa = {obj['referenceId']: obj for obj in a['objects']}
        bb = {obj['referenceId']: obj for obj in b['objects']}
        fraction = (timestamp-self.times[index-1])/dt
        result = []
        for identity in aa.keys() & bb.keys():
            x, y = aa[identity], bb[identity]
            if (x['primPath'], x['className'], x.get('asset')) != (y['primPath'], y['className'], y.get('asset')):
                continue
            if math.dist(x['worldPositionM'], y['worldPositionM'])/(dt/1e9) > 25:
                continue
            point = [v+(w-v)*fraction for v, w in zip(x['worldPositionM'], y['worldPositionM'])]
            result.append({**x, 'worldPositionM': point})
        return result

    def probes(self, camera_name, actors):
        projection = self.cameras[camera_name]['projectionMatrix3x4']
        result = []
        for actor in actors:
            x, y, z = actor['worldPositionM']
            height = self.prim_heights.get(actor['primPath'], self.heights[actor['className']])
            points = []
            for vertical in (z-self.ground, z-self.ground+height*.45):
                value = [sum(a*b for a, b in zip(row, (x, y, vertical, 1))) for row in projection]
                if value[2] <= 0 or not all(math.isfinite(v) for v in value):
                    break
                points.append([value[0]/value[2], value[1]/value[2]])
            if len(points) == 2:
                result.append((actor, points))
        return result


def image_assignment(box, name, probes):
    x, y, w, h = box
    if not all(math.isfinite(value) for value in box) or min(w, h) <= 0:
        return None, 'invalid-detector-box'
    # A small allowance for contact-point annotation/detector edges. These
    # fixed image gates never inspect the SDK world position or target ID.
    def inside(point, padding):
        return x-w*padding <= point[0] <= x+w*(1+padding) and y-h*padding <= point[1] <= y+h*(1+padding)
    candidates = [actor for actor, (foot, body) in probes if inside(body, .02) and inside(foot, .12)]
    if len(candidates) != 1:
        return None, 'ambiguous-image' if candidates else 'no-registered-image-reference'
    if family(candidates[0]['className']) != family(name):
        return None, 'image-class-family-mismatch'
    return candidates[0], None


def frame_assignments(row, reference, camera_name, offset_ms):
    actors = reference.actors(int(row['sourceTimeNs'])+offset_ms*1_000_000)
    if actors is None:
        return {}, Counter({'unavailable-reference-frame': 1}), 0
    audit = row['detectorTrackerAudit']
    if not audit['inputSnapshotComplete']:
        raise ValueError('Complete pre-tracker detector snapshot required')
    probes = reference.probes(camera_name, actors)
    assigned = defaultdict(list)
    rejected = Counter()
    output_counts = Counter(obj['localTrackId'] for obj in row['objects'])
    output_objects = {obj['localTrackId']: obj for obj in row['objects'] if output_counts[obj['localTrackId']] == 1 and obj['observedThisFrame']}
    exact = defaultdict(list)
    for output in audit['outputs']:
        if output['currentDetectorStamp'] and not output['untracked'] and not output['idRejectedAsAmbiguous']:
            exact[output['inputOrdinal']].append(output['sdkTargetId'])
    for item in audit['inputs']:
        name = CLASSES[item['sdkClassId']]
        actor, reason = image_assignment(item['bboxPx'], name, probes)
        if actor is None:
            rejected[reason] += 1
            continue
        candidates = exact[item['ordinal']]
        tracked = output_objects.get(candidates[0]) if len(candidates) == 1 else None
        assigned[actor['referenceId']].append(dict(actor=actor, rawClass=name, tracked=tracked))
    rejected['same-camera-duplicate-detections'] = sum(len(items)-1 for items in assigned.values())
    return {identity: values[0] for identity, values in assigned.items() if len(values) == 1}, rejected, audit['inputDetectionCount']


def evaluate(rows, samples, camera_export, package, source_camera_names, *, clock_basis='recorded-native-sei'):
    if clock_basis not in ('recorded-native-sei', 'source-native-sei'):
        raise ValueError('Explicit native capture clock required')
    if (len(source_camera_names) != 2 or len({row.get('fusionEpoch') for row in rows}) != 1
            or any(not isinstance(row.get('fusionEpoch'),str) or not row['fusionEpoch'] for row in rows)):
        raise ValueError('One shared replay epoch and exactly two fixed cameras required')
    for source in source_camera_names:
        values = [row for row in rows if row['sourceId'] == source]
        if not values or len({row['sourceSessionId'] for row in values}) != 1:
            raise ValueError('Single source session required')
        if any(int(b['sourceTimeNs']) <= int(a['sourceTimeNs']) for a, b in zip(values, values[1:])):
            raise ValueError('Replay capture clocks must strictly increase')
        for row in values:
            evidence = row.get('sourceClockEvidence') or {}
            if (row['timestampBasis'] != clock_basis or evidence.get('captureTimeNs') != row['sourceTimeNs']
                    or evidence.get('auPtsNs') != row['rawSourcePtsNs']):
                raise ValueError('Original exact-AU recorded capture evidence required')
    reference = Reference(samples, camera_export, package['classGeometry'])
    sources = list(source_camera_names)
    first, second = [[row for row in rows if row['sourceId'] == source] for source in sources]
    times = [int(row['sourceTimeNs']) for row in second]
    pairs = []
    for row in first:
        timestamp = int(row['sourceTimeNs'])
        if not times[0] <= timestamp <= times[-1]:
            continue
        index = bisect_left(times, timestamp)
        nearest = min((i for i in (index-1, index) if 0 <= i < len(times)), key=lambda i: abs(times[i]-timestamp))
        if abs(times[nearest]-timestamp) <= 50_000_000:
            pairs.append((row, second[nearest]))
    result = dict(schemaVersion='city.tracking-quality.v1', referenceBasis='Unique raw detector image/probe correspondence; independent of predicted world position. Actual registered actors only; unregistered/ambiguous image objects are unknown. Exposure delay is unmeasured. Not HOTA/IDF1.',
        clockBasis=clock_basis, framePairs=len(pairs), sourceRows=dict(Counter(row['sourceId'] for row in rows)), offsetsMs={})
    for offset in OFFSETS_MS:
        counts = defaultdict(Counter)
        errors = defaultdict(list)
        residual_steps = defaultdict(list)
        frames = {}
        rejection = Counter()
        previous = {}
        previous_reference_by_id = {}
        previous_position = {}
        for row in rows:
            source = row['sourceId']
            assigned, rejected, raw_count = frame_assignments(row, reference, source_camera_names[source], offset)
            frames[(source, row['sourceFrameId'])] = assigned
            rejection.update(rejected)
            for identity, item in assigned.items():
                name = item['actor']['className']
                record = counts[name]
                record['rawReferenceDetections'] += 1
                tracked = item['tracked']
                if not tracked:
                    record['missingObservedTrack'] += 1
                    continue
                record['observedTracks'] += 1
                key = (source, identity)
                target = tracked['localTrackId']
                identity_key = (source, target)
                if identity_key in previous_reference_by_id:
                    previous_time, previous_reference = previous_reference_by_id[identity_key]
                    if int(row['sourceTimeNs'])-previous_time <= 1_000_000_000 and previous_reference != identity:
                        counts['all']['withinCameraReferenceSwitches'] += 1
                previous_reference_by_id[identity_key] = (int(row['sourceTimeNs']), identity)
                if key in previous:
                    old_time, old_id = previous[key]
                    if int(row['sourceTimeNs'])-old_time <= 1_000_000_000 and old_id != target:
                        record['nativeIdChanges'] += 1
                previous[key] = (int(row['sourceTimeNs']), target)
                native = tracked.get('native3D')
                if native and len(native.get('worldPositionM', [])) == 2 and all(math.isfinite(v) for v in native['worldPositionM']):
                    distance = math.dist(native['worldPositionM'], item['actor']['worldPositionM'][:2])
                    errors[name].append(distance)
                    residual = [x-y for x,y in zip(native['worldPositionM'], item['actor']['worldPositionM'][:2])]
                    if key in previous_position:
                        old_time, old_residual = previous_position[key]
                        if 0 < int(row['sourceTimeNs'])-old_time <= 250_000_000:
                            step = math.dist(residual, old_residual)
                            residual_steps[name].append(step)
                            if step > 1:
                                record['residualStepsOver1m'] += 1
                    previous_position[key] = (int(row['sourceTimeNs']), residual)
                    record['nativePositions'] += 1
                    if native.get('visibility') is not None and native['visibility'] >= .25:
                        record['qualifiedPositions'] += 1
                else:
                    record['missingNativePosition'] += 1
        false_examples = []
        for a, b in pairs:
            aa, bb = [frames[(row['sourceId'], row['sourceFrameId'])] for row in (a, b)]
            for identity in aa.keys() & bb.keys():
                x, y = aa[identity], bb[identity]
                name = x['actor']['className']
                record = counts[name]
                record['coDetectedActorPairs'] += 1
                xa, ya = x['tracked'], y['tracked']
                if not xa or not ya:
                    record['pairMissingObservedTrack'] += 1
                elif xa['localTrackId'] == ya['localTrackId']:
                    record['sameNativeIdPairs'] += 1
                    if xa['class'] == ya['class']:
                        record['sameIdSameFineClassPairs'] += 1
                    nx, ny = xa.get('native3D'), ya.get('native3D')
                    if nx and ny and all(n.get('visibility') is not None and n['visibility'] >= .25 for n in (nx, ny)) and math.dist(nx['worldPositionM'], ny['worldPositionM']) <= 1:
                        record['sameIdQualifiedWithin1m'] += 1
                else:
                    record['differentNativeIdPairs'] += 1
            by_id = [{item['tracked']['localTrackId']: identity for identity, item in assigned.items() if item['tracked']} for assigned in (aa, bb)]
            for native_id in by_id[0].keys() & by_id[1].keys():
                if by_id[0][native_id] != by_id[1][native_id]:
                    counts['all']['wrongSharedIdPairs'] += 1
                    if len(false_examples) < 8:
                        false_examples.append(dict(targetId=native_id, references=[by_id[0][native_id], by_id[1][native_id]], sourceFrames=[a['sourceFrameId'], b['sourceFrameId']]))
        result['offsetsMs'][str(offset)] = dict(byClass={name: dict(value) for name, value in counts.items()},
            nativePositionErrorM={name: stats(values) for name, values in errors.items()},
            nativePositionResidualStepM={name: stats(values) for name, values in residual_steps.items()},
            unmatchedReasons=dict(rejection), wrongSharedIdExamples=false_examples)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live-native', action='store_true', help='Score a frozen bounded live window without relabeling its capture clock')
    options = parser.parse_args()
    receipt_path = options.observations.parent/'receipt.json'
    if not receipt_path.is_file() or json.loads(receipt_path.read_text()).get('result') != 'complete':
        raise ValueError('Score a completed bounded trial, never a growing observation file')
    if options.live_native and json.loads(receipt_path.read_text()).get('schemaVersion') != 'city.live-tracking-window.v1':
        raise ValueError('A completed live-window collection receipt is required')
    rows = [json.loads(line) for line in options.observations.read_text().splitlines()]
    samples = [json.loads(line) for line in (options.capture/'reference.ndjson').read_text().splitlines()]
    export = json.loads(options.export.read_text())
    package = json.loads(options.package.read_text())
    sources = json.loads((options.capture/'manifest.json').read_text())['cameraOrder']
    result = evaluate(rows, samples, export, package, dict(zip(sources, export['cameraOrder'])),
        clock_basis='source-native-sei' if options.live_native else 'recorded-native-sei')
    result['evaluatorSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['inputSha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (options.observations, options.capture/'reference.ndjson', options.export, options.package)}
    options.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['offsetsMs']['0'], indent=2))
