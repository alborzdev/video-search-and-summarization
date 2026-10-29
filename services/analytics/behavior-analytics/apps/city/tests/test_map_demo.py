# SPDX-License-Identifier: Apache-2.0
"""CPU contract for experimental map hints; analytics remain camera-local."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.city.engine import CityEngine
from apps.city.models import Observation, RuleSet, Site
from apps.city.preview import PreviewStore


class Clock:
    value = 100.

    def __call__(self):
        return self.value


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv('CITY_MV3DT_DEMO_ENABLED', 'true')
    monkeypatch.setenv('CITY_MV3DT_DEMO_SITE_ID', 'isaac-demo')
    monkeypatch.setenv('CITY_MV3DT_DEMO_CAMERA_CALIBRATIONS', json.dumps({'a': 'cal-a', 'b': 'cal-b'}))
    clock = Clock()
    engine = CityEngine(clock=clock)
    engine.put_site(Site.model_validate({'id': 'isaac-demo', 'mode': 'live', 'sources': [
        {'id': source, 'width': 100, 'height': 100, 'calibrationRevision': f'cal-{source}',
         'imageToGroundHomography': [[.1, 0, 0], [0, .1, 0], [0, 0, 1]]} for source in ('a', 'b')],
        'map': {'bounds': [0, 0, 10, 10]}}))
    return engine, clock


def frame(source='a', sequence=1, epoch='epoch-1', session=None):
    return {'siteId': 'isaac-demo', 'sourceId': source, 'sourceSessionId': session or f'session-{source}',
        'sequence': str(sequence), 'sourceTimeNs': str(1_790_000_000_000_000_000 + sequence * 100_000_000),
        'timestampBasis': 'source-rtcp', 'trackingMode': 'mv3dt-demo', 'fusionEpoch': epoch,
        'image': {'width': 100, 'height': 100}, 'objects': [{'localTrackId': '25', 'class': 'person',
            'confidence': .9, 'observedThisFrame': True, 'bboxPx': [25, 30, 10, 10],
            'globalTrackId': f'mv3dt-demo:{epoch}:25', 'associationMethod': 'mv3dt-demo',
            'native3D': {'method': 'nvidia-mv3dt-9.2', 'targetId': '25', 'calibrationRevision': f'cal-{source}',
                'worldPositionM': [99, 99], 'imageFootPx': [31, 41], 'visibility': .8, 'state': 'observed'}}]}


def ingest(engine, value):
    return engine.ingest(Observation.model_validate(value))


def test_demo_exposes_only_typed_hint_and_keeps_homography_local_ids(demo):
    engine, _ = demo
    for source in ('a', 'b'):
        ingest(engine, frame(source))
    snapshot = engine.snapshot()
    assert len(snapshot['tracks']) == 2
    assert len({track['id'] for track in snapshot['tracks']}) == 2
    for track in snapshot['tracks']:
        assert track['positionM'] == [3., 4.]
        assert track['globalTrackId'] is None and track['associationMethod'] is None
        assert track['mapAssociation'] == {'method': 'mv3dt-demo', 'globalTrackId': 'mv3dt-demo:epoch-1:25',
            'targetId': '25', 'fusionEpoch': 'epoch-1', 'calibrationRevision': f"cal-{track['sourceId']}",
            'visibility': .8, 'sourceClockBasis': 'source-rtcp'}
    assert snapshot['association']['globalFusionEnabled'] is False
    assert snapshot['association']['mapFusion']['available'] is True
    assert snapshot['association']['mapFusion']['qualified'] is False
    assert engine.health_state()['association']['mapFusion']['experimental'] is True


def staged_frame(source='a', sequence=1, target='88'):
    sample = frame(source, sequence)
    sample['trackingArchitecture'] = 'nvdcf-local-then-mv3dt-v1'
    obj = sample['objects'][0]
    obj['localTrackId'] = '9223372036854775809'
    obj['globalTrackId'] = f'mv3dt-demo:epoch-1:{target}'
    obj['native3D'].update(targetId=target, localTargetId=obj['localTrackId'],
        localTrackingMethod='nvidia-nvdcf-first-stage-9.2')
    return sample


def test_staged_global_correction_preserves_local_track_and_separate_map_handle(demo):
    engine, _ = demo
    for sequence, target in [(1, '88'), (2, '9')]:
        assert ingest(engine, staged_frame(sequence=sequence, target=target))['accepted']
        tracks = engine.snapshot()['tracks']
        assert len(tracks) == 1
        assert tracks[0]['localTrackId'] == '9223372036854775809'
        assert tracks[0]['mapAssociation']['targetId'] == target
        assert tracks[0]['positionM'] == [3., 4.]
        source = engine.snapshot()['sources'][0]
        assert source['trackingArchitecture'] == 'nvdcf-local-then-mv3dt-v1'
        assert source['trackingMode'] == 'mv3dt-demo' and source['fusionEpoch'] == 'epoch-1'


@pytest.mark.parametrize('field,value', [
    ('trackingArchitecture', None), ('localTargetId', None), ('localTargetId', 'another-local'),
    ('localTrackingMethod', None),
])
def test_staged_association_requires_complete_explicit_local_provenance(demo, field, value):
    engine, _ = demo
    sample = staged_frame()
    target = sample if field == 'trackingArchitecture' else sample['objects'][0]['native3D']
    target[field] = value
    assert ingest(engine, sample)['accepted']
    track = engine.snapshot()['tracks'][0]
    assert track['mapAssociation'] is None
    assert track['localTrackId'] == '9223372036854775809'


def test_staged_missing_second_output_keeps_local_analytics(demo):
    engine, _ = demo
    sample = staged_frame()
    sample['objects'][0].update(native3D=None, globalTrackId=None, associationMethod=None)
    assert ingest(engine, sample)['accepted']
    track = engine.snapshot()['tracks'][0]
    assert track['mapAssociation'] is None and track['observedThisFrame']
    assert track['positionM'] == [3., 4.]


def test_actual_routes_keep_minimal_health_and_full_staged_snapshot_sources(demo):
    from fastapi.testclient import TestClient
    from apps.city.main import create_app
    engine, _ = demo
    for source in ('a', 'b'):
        ingest(engine, staged_frame(source=source))
    with TestClient(create_app(engine, media_registry={})) as client:
        health = client.get('/api/v1/city/health').json()
        snapshot = client.get('/api/v1/city/snapshot').json()
    assert all(set(source) == {'id', 'status'} for source in health['sources'])
    assert [source['id'] for source in snapshot['sources']] == ['a', 'b']
    for source in snapshot['sources']:
        assert source['trackingArchitecture'] == 'nvdcf-local-then-mv3dt-v1'
        assert source['trackingMode'] == 'mv3dt-demo' and source['fusionEpoch'] == 'epoch-1'
        assert source['sourceSessionId'] == f"session-{source['id']}"


def test_observe_only_source_clock_diagnostics_remain_compatible_with_actual_ingest_api(demo):
    from fastapi.testclient import TestClient
    from apps.city.main import create_app
    engine, _ = demo
    sample = staged_frame()
    sample['sourceClockDiagnostics'] = {'schemaVersion': 'city.source-clock-diagnostics.v1',
        'mode': 'observe-only', 'sdkNtpUnixNs': sample['sourceTimeNs'],
        'stages': {'beforeMux': {'referenceUnixNs': '1790000000000000000',
            'referenceCaps': 'timestamp/x-ntp', 'sdkMinusReferenceNs': '450000000'}}}
    sample['muxClockSettings'] = {'syncInputs': False, 'maxLatencyNs': 0, 'syncInputsNtpNs': 0}
    with TestClient(create_app(engine, media_registry={})) as client:
        result = client.post('/api/v1/city/observations', json=sample)
    assert result.status_code == 200 and result.json()['accepted']
    assert engine.snapshot()['sources'][0]['lastSourceTimeNs'] == sample['sourceTimeNs']
    assert engine.snapshot()['tracks'][0]['mapAssociation']['targetId'] == '88'


@pytest.mark.parametrize('scope,key,value', [
    ('frame', 'timestampBasis', 'recorded-pts'), ('frame', 'trackingMode', 'mv3dt-diagnostic'),
    ('frame', 'fusionEpoch', None), ('object', 'observedThisFrame', False), ('object', 'class', 'car'),
    ('object', 'globalTrackId', 'mv3dt-demo:other:25'), ('object', 'associationMethod', 'mv3dt'),
    ('native', 'visibility', .249), ('native', 'visibility', None), ('native', 'state', 'predicted-or-peer'),
    ('native', 'calibrationRevision', 'old-calibration'), ('native', 'targetId', 'different-id'),
    ('native', 'method', 'unapproved-model'),
])
def test_demo_rejects_ineligible_evidence_without_dropping_local_observation(demo, scope, key, value):
    engine, _ = demo
    sample = frame()
    target = sample if scope == 'frame' else (sample['objects'][0] if scope == 'object' else sample['objects'][0]['native3D'])
    target[key] = value
    assert ingest(engine, sample)['accepted'] is True
    track = engine.snapshot()['tracks'][0]
    assert track['mapAssociation'] is None
    assert track['globalTrackId'] is None
    assert track['positionM'] == [3., 4.]


def test_demo_rejects_nonfinite_native_feet_before_ingest():
    sample = frame()
    sample['objects'][0]['native3D']['worldPositionM'][0] = float('nan')
    with pytest.raises(ValidationError):
        Observation.model_validate(sample)


def test_demo_requires_server_flag_and_exact_site_calibration_allowlist(demo, monkeypatch):
    engine, _ = demo
    for field, value in [('map_demo_requested', False), ('map_demo_site', 'other-site'),
                         ('map_demo_calibrations', {'a': 'old', 'b': 'cal-b'})]:
        original = getattr(engine, field)
        setattr(engine, field, value)
        sample = frame(sequence=engine.sequence + 10)
        ingest(engine, sample)
        assert engine.snapshot()['tracks'][0]['mapAssociation'] is None
        setattr(engine, field, original)
    monkeypatch.setenv('CITY_MV3DT_DEMO_CAMERA_CALIBRATIONS', '{invalid')
    assert CityEngine().map_demo_calibrations == {}


def test_new_shared_epoch_retires_old_hints_without_resetting_local_tracks(demo):
    engine, _ = demo
    ingest(engine, frame('a'))
    ingest(engine, frame('b'))
    ingest(engine, frame('a', 2, epoch='epoch-2'))
    hints = {track['sourceId']: track['mapAssociation'] for track in engine.snapshot()['tracks']}
    assert hints['a']['fusionEpoch'] == 'epoch-2' and hints['b'] is None
    assert ingest(engine, frame('b', 2))['accepted'] is True
    assert engine.snapshot()['tracks'][1]['mapAssociation'] is None
    ingest(engine, frame('b', 3, epoch='epoch-2'))
    assert engine.snapshot()['association']['mapFusion']['available'] is True


def test_same_epoch_after_camera_session_reset_cannot_rejoin(demo):
    engine, _ = demo
    ingest(engine, frame('a'))
    ingest(engine, frame('b'))
    ingest(engine, frame('a', 2, session='restarted-a'))
    assert all(track['mapAssociation'] is None for track in engine.snapshot()['tracks'])
    assert engine.snapshot()['association']['mapFusion']['available'] is False
    ingest(engine, frame('a', 3, epoch='epoch-2', session='restarted-a'))
    ingest(engine, frame('b', 2, epoch='epoch-2'))
    assert engine.snapshot()['association']['mapFusion']['available'] is True


def test_missing_stale_and_class_changed_tracks_have_no_map_hint(demo):
    engine, clock = demo
    ingest(engine, frame())
    clock.value += engine.freshness + .1
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None
    sample = frame(sequence=2)
    sample['objects'] = []
    ingest(engine, sample)
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None
    sample = frame(sequence=3)
    sample['objects'][0]['class'] = 'bus'
    ingest(engine, sample)
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None


def test_exact_preview_preserves_its_frame_association_and_local_events(demo):
    engine, _ = demo
    engine.put_rules(RuleSet.model_validate({'rules': [{'id': source, 'sourceId': source, 'kind': 'occupancy-threshold',
        'classes': ['person'], 'geometry': {'space': 'image-normalized', 'points': [[.1, .1], [.9, .1], [.9, .9], [.1, .9]]},
        'conditions': {'countThreshold': 1}} for source in ('a', 'b')]}))
    ingest(engine, frame('a'))
    ingest(engine, frame('b'))
    snapshot = engine.snapshot()
    assert len(snapshot['events']) == 2
    assert len({event['sourceId'] for event in snapshot['events']}) == 2
    assert [metric['occupancy'] for metric in snapshot['metrics']] == [1, 1]
    sample = deepcopy(engine.histories['a'][-1])
    exact = PreviewStore(engine)._snapshot(sample)
    assert exact['tracks'][0]['mapAssociation'] == sample['tracks'][0]['mapAssociation']
    assert exact['association'] == sample['association']
    assert exact['association']['globalFusionEnabled'] is False
    assert exact['tracks'][0]['positionM'] == [3., 4.]


@pytest.mark.parametrize('class_name', ['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck', 'two-wheeler'])
def test_single_native_mv3dt_exposes_each_class_with_sdk_world_position(demo, class_name):
    engine, _ = demo
    sample = frame()
    sample['trackingArchitecture'] = 'mv3dt-native-v1'
    obj = sample['objects'][0]
    obj['class'] = class_name
    obj['native3D']['worldPositionM'] = [6., 7.]
    assert ingest(engine, sample)['accepted']
    track = engine.snapshot()['tracks'][0]
    assert track['mapAssociation']['positionM'] == [6., 7.]
    assert track['mapAssociation']['positionBasis'] == 'native-mv3dt-world-foot'
    assert track['mapAssociation']['targetId'] == track['localTrackId'] == '25'
    # Image-rule analytics keep their own camera anchor and no invented IDs.
    assert track['positionM'] == [3., 4.]


def test_native_family_policy_preserves_raw_classes_and_camera_analytics(demo):
    engine, _ = demo
    for source, cls in [('a', 'car'), ('b', 'truck')]:
        sample = frame(source)
        sample.update(trackingArchitecture='mv3dt-native-v1', trackingClassPolicy='car-truck-family-v1')
        sample['objects'][0]['class'] = cls
        sample['objects'][0]['native3D']['worldPositionM'] = [6., 7.]
        assert ingest(engine, sample)['accepted']
    tracks = engine.snapshot()['tracks']
    assert {track['class'] for track in tracks} == {'car', 'truck'}
    assert all(track['mapAssociation']['classPolicy'] == 'car-truck-family-v1' for track in tracks)
    assert all(track['positionM'] == [3., 4.] for track in tracks)
    assert engine.snapshot()['association']['globalFusionEnabled'] is False
    sample['trackingArchitecture'] = 'nvdcf-local-then-mv3dt-v1'
    with pytest.raises(ValidationError, match='Association class policy'):
        Observation.model_validate(sample)


@pytest.mark.parametrize('change', ['outside-world', 'outside-image', 'local-alias', 'wrong-id', 'prediction'])
def test_single_native_mv3dt_rejects_invalid_world_or_identity_evidence(demo, change):
    engine, _ = demo
    sample = frame()
    sample['trackingArchitecture'] = 'mv3dt-native-v1'
    obj = sample['objects'][0]
    obj['native3D']['worldPositionM'] = [6., 7.]
    if change == 'outside-world': obj['native3D']['worldPositionM'] = [99., 99.]
    if change == 'outside-image': obj['native3D']['imageFootPx'] = [101., 40.]
    if change == 'local-alias': obj['native3D']['localTargetId'] = obj['localTrackId']
    if change == 'wrong-id': obj['native3D']['targetId'] = '9'
    if change == 'prediction': obj['observedThisFrame'] = False
    ingest(engine, sample)
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None


def test_native_ground_validity_polygon_uses_image_feet_not_world_units(demo):
    engine, _ = demo
    engine.site.sources[0].validGroundPolygon = [[20, 20], [80, 20], [80, 80], [20, 80]]
    sample = frame()
    sample['trackingArchitecture'] = 'mv3dt-native-v1'
    sample['objects'][0]['native3D']['worldPositionM'] = [6., 7.]
    ingest(engine, sample)
    assert engine.snapshot()['tracks'][0]['mapAssociation']['positionM'] == [6., 7.]
    sample = frame(sequence=2)
    sample['trackingArchitecture'] = 'mv3dt-native-v1'
    sample['objects'][0]['native3D'].update(worldPositionM=[6., 7.], imageFootPx=[10., 10.])
    ingest(engine, sample)
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None


def test_public_track_snapshot_preserves_json_and_detaches_all_nested_values(demo):
    engine, clock = demo
    ingest(engine, frame())
    track = next(iter(engine.tracks.values()))
    # Representative mutable structures, including the full trail and native
    # map association, must never share storage with a saved frame.
    track['trail'] = [{'positionM': [1.25, 2.5], 'sourceTimeNs': '1790000000100000000'}]
    track['velocityMps'] = [0.1, 0.2]
    before = deepcopy(track)
    snapshot = engine._track_json(track, clock())
    expected = {key: value for key, value in before.items() if key not in {
        'received', 'lastObservedReceived', 'sourceTimeNsInt', 'lastObservedSourceTimeNsInt',
        'previousObservedSourceTimeNsInt', 'motionSamples'}}
    expected['stale'] = False
    assert snapshot == json.loads(json.dumps(expected))
    snapshot['bboxPx'][0] = -999
    snapshot['trail'][0]['positionM'][0] = -999
    snapshot['velocityMps'][0] = -999
    snapshot['mapAssociation']['positionM'] = [-999, -999]
    assert track == before
    later = engine._track_json(track, clock())
    track['trail'][0]['positionM'][0] = 999
    track['mapAssociation']['positionM'] = [999, 999]
    assert later['trail'][0]['positionM'] == [1.25, 2.5]
    assert later['mapAssociation'] == before['mapAssociation']
