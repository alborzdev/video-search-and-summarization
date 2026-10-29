"""Offline-only replay of the immutable retained first-NvDCF observations."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/home/sparkdev/vss')
sys.path.insert(0, str(ROOT / 'services/analytics/behavior-analytics'))
from apps.city.geometry import point_in_polygon, project
from apps.city.mobility_spatial import MobilitySpatial
from apps.city.models import Rule, Source


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    audit = ROOT / '.spark/city/runtime/east-pedestrian-v3-audit-20261026'
    old_path = audit / 'receipt.json'
    old = json.loads(old_path.read_text())
    raw = audit / 'observations.ndjson'
    scenario = Path(old['scenario'])
    assert sha(raw) == old['rawSubsetSha256']
    assert sha(scenario) == old['scenarioSha256']
    first = json.loads(scenario.open().readline())
    sources = {row['id']: Source.model_validate(row) for row in first['snapshot']['sources']}
    rules = [Rule.model_validate(row) for row in first['snapshot']['rules']]
    config = first['mobility']['config']
    site_path = ROOT / '.spark/city/runtime/pedestrian-pocket-live-20261026/applied-v3-site.json'
    site = json.loads(site_path.read_text())
    site = site.get('site', site)
    bounds = site.get('map', {}).get('bounds')
    source_id = '997d3a69-e052-45a4-a1ce-be1b046670c4'
    local_id = '5527462707671859204'
    crossing_id = 'east-crossing-north-south'
    measurement = next(rule for rule in rules if rule.id == 'mobility-isaac-east-crossing-measurement')
    timestamps = {1793003197704085667, 1793003197895063445, 1793003197949241222}
    observations = [json.loads(line) for line in raw.open()]
    observations.sort(key=lambda row: (int(row['sourceTimeNs']), row['sourceId'], int(row['sequence'])))
    engine = MobilitySpatial()
    outcomes, selected_frames, candidate_transitions = [], [], []
    frames = 0
    for observation in observations:
        if observation['sourceId'] != source_id:
            continue
        frames += 1
        ns = int(observation['sourceTimeNs'])
        session = observation['sourceSessionId']
        source = sources[source_id]
        tracks = []
        chosen = None
        for obj in observation['objects']:
            box = obj['bboxPx']
            anchor = [box[0] + box[2] / 2, box[1] + box[3]]
            position, status = project(anchor,
                source.classImageToGroundHomographies.get(obj['class'], source.imageToGroundHomography),
                source.validGroundPolygon, bounds)
            if not (0 <= anchor[0] <= source.width and 0 <= anchor[1] <= source.height):
                position, status = None, 'outside-image'
            item = {'id': f'{source_id}:{session}:{obj["localTrackId"]}', 'sourceId': source_id,
                'sessionId': session, 'class': obj['class'], 'anchorPx': anchor, 'positionM': position,
                'observedThisFrame': obj['observedThisFrame'], 'sourceTimeNsInt': ns,
                'lastObservedSourceTimeNsInt': ns if obj['observedThisFrame'] else None,
                'stale': not obj['observedThisFrame'], 'speedMps': None}
            tracks.append(item)
            if obj['localTrackId'] == local_id:
                chosen = {'bboxPx': box, 'anchorPx': anchor, 'positionM': position,
                    'projectionStatus': status, 'observedThisFrame': obj['observedThisFrame'],
                    'anchorInsideMeasurement': bool(position is not None and point_in_polygon(position, measurement.geometry.points))}
        old_lengths = {key: len(row['outcomes']) for key, row in
            engine.sources.get(source_id, {}).get('crossings', {}).items()}
        before = engine.sources.get(source_id, {}).get('crossings', {}).get(crossing_id, {}).get('tracks', {})
        identity = f'{source_id}:{session}:{local_id}'
        was_pending = deepcopy(before.get(identity, {}).get('pendingExit'))
        engine.update(source_id, session, ns, tracks, rules, source, config, emit_snapshot=False)
        for key, row in engine.sources[source_id]['crossings'].items():
            outcomes.extend({'crossingId': key, **outcome} for outcome in list(row['outcomes'])[old_lengths.get(key, 0):])
        row = engine.sources[source_id]['crossings'][crossing_id]
        state = row['tracks'].get(identity, {})
        if was_pending != state.get('pendingExit'):
            candidate_transitions.append({'sourceTimeNs': str(ns), 'sequence': observation['sequence'],
                'from': was_pending, 'to': deepcopy(state.get('pendingExit')),
                'phase': state.get('phase'), 'journey': state.get('journey'),
                'lastCrossingNs': str(state.get('lastCrossingNs')),
                'lastCrossingPoint': state.get('lastCrossingPoint')})
        if ns in timestamps:
            selected_frames.append({'sourceTimeNs': str(ns), 'sequence': observation['sequence'],
                'localTrackId': local_id, 'rawObservation': chosen,
                'temporalState': {key: deepcopy(state.get(key)) for key in
                    ('phase', 'journey', 'lastCrossingNs', 'lastCrossingPoint', 'pendingExit')},
                'currentCounts': {key: deepcopy(row['result'].get(key)) for key in
                    ('waitingCount', 'crossingCount', 'pendingExitTrackCount', 'status', 'qualityReasons')}})
    by_ns = {frame['sourceTimeNs']: frame for frame in selected_frames}
    spike = by_ns['1793003197895063445']
    recovered = by_ns['1793003197949241222']
    assert spike['rawObservation']['anchorInsideMeasurement'] is False
    assert spike['currentCounts']['crossingCount'] == 0
    assert spike['temporalState']['journey'] is True
    assert spike['temporalState']['pendingExit']['category'] == 'incomplete'
    assert recovered['rawObservation']['anchorInsideMeasurement'] is True
    assert recovered['temporalState']['pendingExit'] is None
    assert recovered['temporalState']['journey'] is True
    assert any(row['outcome'] == 'exit-candidate-recovered' and row['ns'] == 1793003197949241222
        and row['trackId'].endswith(':' + local_id) for row in outcomes)
    assert not any(row['outcome'] == 'incomplete' and row['ns'] == 1793003197895063445 for row in outcomes)
    assert not any(row['outcome'] == 'completed' for row in outcomes)
    snapshot = engine.snapshot()
    receipt = {'schemaVersion': 'city.pedestrian-pending-exit-offline-replay.v1', 'offlineOnly': True,
        'deployed': False, 'runtimeMutations': False,
        'inputs': [{'path': str(path), 'sha256': sha(path)} for path in (raw, scenario, site_path, old_path)],
        'source': [{'path': str(ROOT / path), 'sha256': sha(ROOT / path)} for path in
            ('services/analytics/behavior-analytics/apps/city/mobility_spatial.py',
             'services/analytics/behavior-analytics/apps/city/geometry.py',
             'services/analytics/behavior-analytics/apps/city/models.py')],
        'script': {'path': str(Path(__file__).resolve()), 'sha256': sha(Path(__file__))},
        'observationRows': len(observations), 'swFrames': frames,
        'sourceId': source_id, 'localTrackId': local_id,
        'maximumObservationGapMsUnchanged': 1000,
        'claims': {'singleLateralSpikeDoesNotTerminateJourney': True,
            'outsideAnchorNotCountedInOccupancy': True, 'sameIdActualReentryCancelsCandidate': True,
            'wholeEpisodeCompletedByAnalytics': False},
        'selectedFrames': selected_frames, 'candidateTransitions': candidate_transitions,
        'outcomes': outcomes, 'outcomeCounts': dict(Counter(row['outcome'] for row in outcomes)),
        'finalCrossings': snapshot['crossings'],
        'limits': ['This is a CPU replay of retained actual first-NvDCF boxes, not a live qualification.',
            'The separate observed SDK ID exchange is not repaired or joined; no completed journey is claimed.',
            'The pre-edit forensic receipt is historical evidence and has no pre-edit source hash.',
            'No actor positions, native3D coordinates, inferred aliases or simulator truth enter any replay calculation.',
            'The changed terminal contract adds one fresh sample of exit latency and intentionally leaves a one-sample exit followed by loss incomplete.']}
    output = Path(__file__).with_name('receipt.json')
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(output), 'swFrames': frames, 'claims': receipt['claims'],
        'outcomeCounts': receipt['outcomeCounts'], 'selectedFrames': selected_frames}, indent=2))


if __name__ == '__main__':
    main()
