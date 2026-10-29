#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline simulator evaluator. Ground truth never enters operational inference.

Match visible root/foot probes to detector boxes in image space before scoring
world positions. This avoids choosing labels by the position being evaluated.
This bounded engineering check does not claim full HOTA/IDF1 benchmarking.
"""
from __future__ import annotations
import argparse
import bisect
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from isaac_site import project


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(2 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def gate_path(run: Path) -> Path:
    # New candidates snapshot their gates in the run; historical runs pin the parent.
    local = run / 'promotion-gates.json'
    return local if local.exists() else run.parent / 'promotion-gates.json'


def evaluation_time(row: dict) -> int:
    return int(row.get('evaluationTimeNs', row['sourceTimeNs']))


def recorded_clock_rows(rows: list[dict], run: Path, verification_path: Path,
                        camera_order: list[str], *, media_root: Path | None = None) -> tuple[list[dict], dict]:
    """Join exact recorded packet PTS to original RTCP; never rewrite inference clocks.

    This is an offline evaluator boundary. A shared packet-clock gate is also
    required because remapping output timestamps cannot repair the SDK's inputs.
    """
    if media_root is None:
        media_root = Path(__file__).resolve().parents[2] / '.spark/city/media'
    directory = verification_path.resolve().parent
    relative = directory.relative_to(media_root.resolve())
    verification = json.loads(verification_path.read_text())
    invocation = json.loads((run / 'invocation.json').read_text())
    verification_hash = file_sha256(verification_path)
    if invocation.get('recordedClockVerificationSha256') != verification_hash:
        raise ValueError('Recorded clock verification was not pinned by this replay invocation')
    if verification.get('schemaVersion') != 'city.encoded-pair-clock.v1':
        raise ValueError('Unsupported recorded clock verification schema')
    if verification.get('issues'):
        raise ValueError('Recorded clock verification contains unresolved issues')
    capture_path = directory / 'capture.json'
    if verification.get('captureManifestSha256') != file_sha256(capture_path):
        raise ValueError('Capture manifest changed since clock verification')
    capture = json.loads(capture_path.read_text())
    if capture.get('status') != 'complete' or capture.get('eosFinalized') is not True or capture.get('errors'):
        raise ValueError('Recorded clock requires a completed capture')
    if verification.get('captureId') != capture.get('captureId'):
        raise ValueError('Recorded clock capture identity mismatch')
    sources = verification.get('sources', [])
    replay_inputs = invocation.get('replayInputs', [])
    if ([s.get('sourceId') for s in sources] != camera_order or
            [s.get('sourceId') for s in replay_inputs] != camera_order or
            [s.get('sourceId') for s in capture.get('sources', [])] != camera_order):
        raise ValueError('Recorded source order differs from calibrated camera order')
    command = invocation.get('command', [])
    invoked_sources = [command[i + 1] for i, value in enumerate(command[:-1]) if value == '--source']
    expected_sources = [s['sourceId'] + '=' + s['containerUri'] for s in replay_inputs]
    if invoked_sources != expected_sources:
        raise ValueError('Recorded inputs differ from the actual replay source arguments')
    shared = verification.get('sharedClock', {})
    if shared.get('status') != 'verified-reference-offsets':
        raise ValueError('Recorded files do not have a verified shared SDK input clock')
    thresholds = json.loads(gate_path(run).read_text())
    maximum_skew_ns = int(thresholds['maximumSourceClockSkewP95Ms'] * 1_000_000)
    mappings, reference_offsets = {}, []
    total_prefix_packets = 0
    for source, replay, captured in zip(sources, replay_inputs, capture['sources']):
        if (source.get('packetCorrespondenceVerified') is not True or
                source.get('referenceMappingAvailable') is not True or
                source.get('referenceInteriorMissingPackets') != 0 or source.get('referenceIssues') or source.get('issues')):
            raise ValueError('Recorded packet/reference correspondence is not verified')
        for field, hash_field in [('file', 'fileSha256'), ('timingFile', 'timingSha256')]:
            name = source.get(field)
            if not isinstance(name, str) or Path(name).name != name or name != captured.get(field):
                raise ValueError('Recorded artifact name differs from the capture manifest')
            path = directory / name
            if path.resolve().parent != directory or file_sha256(path) != source.get(hash_field):
                raise ValueError('Recorded file or timing sidecar changed since verification')
        expected_uri = 'file:///media/' + (relative / source['file']).as_posix()
        if replay.get('containerUri') != expected_uri or replay.get('fileSha256') != source['fileSha256']:
            raise ValueError('Recorded file was not pinned by the replay invocation')
        packets = source.get('packets', [])
        if not packets or len(packets) != captured.get('accessUnits'):
            raise ValueError('Recorded packet mapping does not cover the captured access units')
        mapping, prefix, previous_pts, previous_reference = {}, 0, None, None
        for index, packet in enumerate(packets):
            if packet.get('index') != index or not packet.get('payloadSha256'):
                raise ValueError('Recorded packet identity/order is incomplete')
            pts = int(packet['filePtsNs'])
            if pts < 0 or (previous_pts is not None and pts <= previous_pts):
                raise ValueError('Recorded packet PTS must strictly increase')
            previous_pts = pts
            reference = packet.get('referenceUnixNs')
            if reference is None:
                if previous_reference is not None:
                    raise ValueError('Recorded source has an interior missing reference timestamp')
                prefix += 1
            else:
                reference = int(reference)
                if reference <= 0 or (previous_reference is not None and reference <= previous_reference):
                    raise ValueError('Recorded reference time must strictly increase')
                previous_reference = reference
                reference_offsets.append(reference - pts)
            mapping[pts] = reference
        if prefix != source.get('referencePrefixMissingPackets') or previous_reference is None:
            raise ValueError('Recorded reference coverage differs from its verified prefix')
        total_prefix_packets += prefix
        mappings[source['sourceId']] = mapping
    spread = max(reference_offsets) - min(reference_offsets)
    if spread > maximum_skew_ns or spread != int(shared['maximumOffsetSpreadNs']):
        raise ValueError('Recorded packet clocks exceed the unchanged cross-camera skew gate')
    aligned, skipped = [], 0
    for row in rows:
        if row.get('timestampBasis') != 'recorded-pts' or row.get('mediaTimeBasis') != 'gstreamer-segment-stream-time':
            raise ValueError('Recorded clock mapping requires unchanged recorded-pts observations')
        mapping = mappings.get(row['sourceId'])
        pts = int(row['rawSourcePtsNs'])
        if mapping is None or pts not in mapping:
            raise ValueError('Replay raw PTS has no exact verified stored-packet match; do not rebase or fit an offset')
        reference = mapping[pts]
        if reference is None:
            skipped += 1
            continue
        # Keep sourceTimeNs and timestampBasis exactly as emitted by the worker.
        aligned.append({**row, 'evaluationTimeNs': str(reference)})
    return aligned, {'mode': 'verified-recorded-packet-reference', 'qualified': True,
                     'verificationSha256': verification_hash, 'captureId': capture['captureId'],
                     'mappedObservations': len(aligned), 'prefixUnqualifiedObservations': skipped,
                     'prefixUnqualifiedPackets': total_prefix_packets, 'sharedFileClockOffsetSpreadNs': str(spread),
                     'inferenceTimestampBasis': 'recorded-pts', 'sourceTimestampRewritten': False,
                     'qualification': 'Exact raw replay PTS to verified encoded-packet reference time; no retiming or fitted per-camera offset.'}


def read_ndjson(path: Path) -> list[dict]:
    """An incomplete diagnostic capture is evidence of a failed capture, not a subset."""
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path.name}: invalid NDJSON record at line {number}') from exc
        if not isinstance(row, dict):
            raise ValueError(f'{path.name}: record at line {number} must be an object')
        rows.append(row)
    return rows


def validate_scored_rows(rows: list[dict], cameras: dict) -> None:
    """Raw SDK IDs are comparable only within one uninterrupted diagnostic epoch."""
    previous = {}
    sessions = {}
    epochs = set()
    for row in rows:
        source = row['sourceId']
        if source not in cameras:
            raise ValueError('Observation source is not in the supplied camera package')
        at = evaluation_time(row)
        if source in previous and at <= previous[source]:
            raise ValueError('Scored source timestamps must strictly increase per camera')
        previous[source] = at
        session = row.get('sourceSessionId')
        epoch = row.get('fusionEpoch')
        if not session or not epoch:
            raise ValueError('Scored observations require explicit source and fusion epochs')
        if source in sessions and session != sessions[source]:
            raise ValueError('Evaluate each source session separately; SDK IDs may be reused')
        sessions[source] = session
        epochs.add(epoch)
        if len(epochs) > 1:
            raise ValueError('Evaluate each fusion epoch separately; SDK IDs may be reused')
    if rows and set(previous) != set(cameras):
        raise ValueError('Scored observations must include both calibrated cameras')


def verify_run_inputs(run: Path, package_path: Path) -> dict:
    """Refuse calibration/threshold drift when a saved invocation pins those files."""
    invocation_path = run / 'invocation.json'
    if not invocation_path.exists():
        return {'verified': False, 'reason': 'Missing saved invocation input hashes'}
    invocation = json.loads(invocation_path.read_text())
    hashes = invocation.get('inputHashes', {})
    paths = {'package.json': package_path, 'promotion-gates.json': gate_path(run)}
    if any(name not in hashes for name in paths):
        return {'verified': False, 'reason': 'Missing pinned calibration or promotion gates'}
    for name, path in paths.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]:
            raise ValueError(f'{name} changed since the diagnostic invocation')
    return {'verified': True, 'sha256': {name: hashes[name] for name in paths}}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    offset = (len(ordered) - 1) * fraction
    low = int(offset)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (offset - low)


def assignment(costs: list[list[float]], maximum: float = 1.) -> list[tuple[int, int]]:
    @lru_cache(None)
    def solve(index, used):
        if index == len(costs):
            return 0., ()
        remaining_cost, remaining = solve(index + 1, used)
        best = (remaining_cost + maximum, remaining)
        for target, cost in enumerate(costs[index]):
            if used & (1 << target) or cost >= maximum:
                continue
            tail_cost, tail = solve(index + 1, used | (1 << target))
            value = tail_cost + cost
            if value < best[0]:
                best = (value, ((index, target),) + tail)
        return best
    return list(solve(0, 0)[1])


def evaluate(run: Path, ground_truth: Path, package_path: Path, *, warmup_seconds: float = 10.,
             recorded_clock: Path | None = None) -> dict:
    package = json.loads(package_path.read_text())
    cameras = {camera['sourceId']: camera for camera in package['cameras']}
    if len(package['cameras']) != 2 or len(cameras) != 2:
        raise ValueError('Exactly two distinct calibrated cameras are required')
    if not math.isfinite(warmup_seconds) or warmup_seconds < 0:
        raise ValueError('Warm-up seconds must be finite and nonnegative')
    input_integrity = verify_run_inputs(run, package_path)
    gt = read_ndjson(ground_truth)
    if not gt or gt[0].get('kind') != 'simulator-ground-truth-evaluation-only':
        raise ValueError('A separate labelled simulator evaluation trace is required')
    gt = gt[1:]
    times = [int(row['captureUnixNs']) for row in gt]
    if not times or times != sorted(set(times)):
        raise ValueError('Ground truth capture times must strictly increase')
    rows = read_ndjson(run / 'observations.ndjson')
    if recorded_clock is not None:
        valid, clock_evidence = recorded_clock_rows(rows, run, recorded_clock, list(cameras))
    else:
        if any(row['timestampBasis'] == 'recorded-pts' for row in rows):
            raise ValueError('Recorded observations require --recorded-clock with pinned packet/reference evidence')
        valid = [row for row in rows if row['timestampBasis'] == 'source-rtcp']
        clock_evidence = {'mode': 'source-rtcp', 'sourceTimestampRewritten': False}
    first = min((evaluation_time(row) for row in valid), default=0)
    valid = [row for row in valid if evaluation_time(row) - first >= warmup_seconds * 1e9]
    validate_scored_rows(valid, cameras)
    scored = []
    errors = []
    baseline_errors = []
    by_source = {}
    truth_by_id = {}
    truth_names = set()
    unmatched = 0
    skipped_clock = 0
    for row in valid:
        at = evaluation_time(row)
        index = bisect.bisect_left(times, at)
        candidates = [value for value in (index - 1, index) if 0 <= value < len(times)]
        index = min(candidates, key=lambda value: abs(times[value] - at))
        if abs(times[index] - at) > 250_000_000:
            skipped_clock += 1
            continue
        camera = cameras[row['sourceId']]
        matrix = camera['projectionMatrix3x4']
        world_z = float(package.get('groundWorldZM', -.2))
        labels = []
        for name, world in gt[index]['peopleWorldM'].items():
            point = [world[0], world[1], world[2] - world_z, 1.]
            q = [sum(a * b for a, b in zip(line, point)) for line in matrix]
            if q[2] <= 0:
                continue
            pixel = [q[0] / q[2], q[1] / q[2]]
            if 0 <= pixel[0] <= camera['width'] and 0 <= pixel[1] <= camera['height']:
                labels.append((name, world[:2], pixel))
        objects = [obj for obj in row['objects'] if obj['class'] == 'person' and obj['observedThisFrame'] and obj.get('native3D')
                   and obj['native3D'].get('visibility') is not None and obj['native3D']['visibility'] >= .25]
        costs = []
        for obj in objects:
            x, y, width, height = obj['bboxPx']
            costs.append([math.hypot((pixel[0] - x - width / 2) / max(width, 10.),
                                     (pixel[1] - y - height) / max(height, 20.)) for _, _, pixel in labels])
        matched = {}
        selected = assignment(costs)
        unmatched += len(objects) - len(selected)
        for obj_index, target_index in selected:
            obj = objects[obj_index]
            name, world, _ = labels[target_index]
            point = obj['native3D']['worldPositionM']
            error = math.dist(point, world)
            errors.append(error)
            bbox = obj['bboxPx']
            baseline = project(camera['imageToGroundHomography'], [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3]])
            baseline_error = math.dist(baseline, world)
            baseline_errors.append(baseline_error)
            stats = by_source.setdefault(row['sourceId'], {'native': [], 'baseline': []})
            stats['native'].append(error)
            stats['baseline'].append(baseline_error)
            truth_by_id.setdefault(obj['localTrackId'], set()).add(name)
            truth_names.add(name)
            matched[name] = {'targetId': obj['localTrackId'], 'positionM': point, 'errorM': error}
        scored.append({'sourceId': row['sourceId'], 'timeNs': at, 'matched': matched})
    source_ids = list(cameras)
    a = [row for row in scored if row['sourceId'] == source_ids[0]]
    b = [row for row in scored if row['sourceId'] == source_ids[1]]
    b_times = [row['timeNs'] for row in b]
    skews = []
    opportunities = 0
    associated = 0
    for row in a:
        index = bisect.bisect_left(b_times, row['timeNs'])
        candidates = [value for value in (index - 1, index) if 0 <= value < len(b)]
        if not candidates:
            continue
        other = b[min(candidates, key=lambda value: abs(b_times[value] - row['timeNs']))]
        skew = abs(other['timeNs'] - row['timeNs']) / 1e6
        skews.append(skew)
        if skew > 50:
            continue
        for name in set(row['matched']) & set(other['matched']):
            opportunities += 1
            if row['matched'][name]['targetId'] == other['matched'][name]['targetId']:
                associated += 1
    runtime = json.loads((run / 'receipt.json').read_text()) if (run / 'receipt.json').exists() else {}
    thresholds = json.loads(gate_path(run).read_text())
    merged = {target: sorted(names) for target, names in truth_by_id.items() if len(names) > 1}
    duplicate_reduction = associated / opportunities if opportunities else None
    metrics = {'observationCount': len(rows), 'scoredObservationCount': len(scored), 'matchedPersonObservations': len(errors),
               'distinctMatchedPeople': len(truth_names), 'unmatchedEligiblePersonDetections': unmatched,
               'clockUnmatchedObservations': skipped_clock, 'sourceSkewPairs': len(skews),
               'sourceClockSkewP95Ms': percentile(skews, .95), 'personPositionMedianM': percentile(errors, .5),
               'personPositionP95M': percentile(errors, .95), 'falseMergedNativeIds': len(merged),
               'baselineGroundAnchorMedianM': percentile(baseline_errors, .5),
               'baselineGroundAnchorP95M': percentile(baseline_errors, .95),
               'positionByCamera': {source: {'nativeMedianM': percentile(values['native'], .5),
                   'nativeP95M': percentile(values['native'], .95), 'baselineMedianM': percentile(values['baseline'], .5),
                   'baselineP95M': percentile(values['baseline'], .95)} for source, values in by_source.items()},
               'crossViewOpportunities': opportunities, 'sameIdCrossViewMatches': associated,
               'duplicateReductionFraction': duplicate_reduction}
    checks = {'inputIntegrity': input_integrity['verified'],
              'runtimeCompleted': runtime.get('completedWithoutRuntimeError') is True,
              'duration': runtime.get('wallSeconds', 0) >= thresholds['minimumRunSeconds'],
              'memory': runtime.get('minimumAvailableGiB', 0) >= thresholds['minimumAvailableGiB'],
              'pairedSamples': len(skews) >= thresholds['minimumPairedSamples'],
              'sourceClockSkew': metrics['sourceClockSkewP95Ms'] is not None and metrics['sourceClockSkewP95Ms'] <= thresholds['maximumSourceClockSkewP95Ms'],
              'positionMedian': metrics['personPositionMedianM'] is not None and metrics['personPositionMedianM'] <= thresholds['maximumPersonPositionMedianM'],
              'positionP95': metrics['personPositionP95M'] is not None and metrics['personPositionP95M'] <= thresholds['maximumPersonPositionP95M'],
              'falseMerges': not merged, 'matchedPeople': len(truth_names) >= thresholds['minimumMatchedPeople'],
              'duplicateReduction': duplicate_reduction is not None and duplicate_reduction >= thresholds['minimumDuplicateReductionFraction']}
    return {'passed': all(checks.values()), 'checks': checks, 'metrics': metrics, 'runtime': runtime,
            'inputIntegrity': input_integrity,
            'clockEvidence': clock_evidence,
            'groundTruthSha256': hashlib.sha256(ground_truth.read_bytes()).hexdigest(),
            'observationsSha256': hashlib.sha256((run / 'observations.ndjson').read_bytes()).hexdigest(),
            'falseMergeDetails': merged, 'warmupSeconds': warmup_seconds,
            'qualification': 'Offline image-space label assignment and simulator-root position comparison. Not full detector recall, occlusion/HOTA/IDF1, vehicle geometry or real-city accuracy.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--ground-truth', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recorded-clock', type=Path,
                        help='Pinned city.encoded-pair-clock.v1 verification beside the capture files; never infers time from replay start')
    args = parser.parse_args()
    result = evaluate(args.run, args.ground_truth, args.package, recorded_clock=args.recorded_clock)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('passed', 'checks', 'metrics')}, indent=2))
