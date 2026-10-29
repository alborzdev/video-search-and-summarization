# SPDX-License-Identifier: Apache-2.0
"""CPU-only clock provenance, admission and exact-preview contracts."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.city.engine import CityEngine
from apps.city.main import create_app
from apps.city.models import Observation, RuleSet, Site
from apps.city.preview import FrameIdentity, PreviewStore
from test_map_demo import Clock, staged_frame
from test_preview import JPEG


def configured(monkeypatch, *, mode='source-native-sei', sources=('a', 'b'), site_id='isaac-intersection-a'):
    monkeypatch.setenv('CITY_MV3DT_DEMO_ENABLED', 'true')
    monkeypatch.setenv('CITY_MV3DT_DEMO_SITE_ID', site_id)
    monkeypatch.setenv('CITY_MV3DT_DEMO_CAMERA_CALIBRATIONS', json.dumps({'a': 'cal-a', 'b': 'cal-b'}))
    monkeypatch.setenv('CITY_SOURCE_CLOCK_MODE', mode)
    clock = Clock()
    engine = CityEngine(clock=clock)
    engine.put_site(Site.model_validate({'id': site_id, 'mode': 'live', 'sources': [
        {'id': source, 'width': 100, 'height': 100, 'calibrationRevision': f'cal-{source}',
            'browserClockVerified': True, 'imageToGroundHomography': [[.1, 0, 0], [0, .1, 0], [0, 0, 1]]}
        for source in sources], 'map': {'bounds': [0, 0, 10, 10]}}))
    return engine, clock


def native_frame(source='a', sequence=1, **changes):
    row = staged_frame(source, sequence)
    row.update(siteId='isaac-intersection-a', timestampBasis='source-native-sei',
        modelRevision='pinned-native-model', rawSourcePtsNs=str(sequence * 100_000_000))
    row['sourceClockEvidence'] = {'schemaVersion': 'city.source-native-sei.v1',
        'method': 'isaac-native-sei-wall-capture', 'correlation': 'exact-au-pts',
        'captureTimeNs': row['sourceTimeNs'], 'auPtsNs': row['rawSourcePtsNs'], 'frameCounter': str(sequence)}
    row.update(changes)
    return row


def ingest(engine, row):
    return engine.ingest(Observation.model_validate(row))


def test_recorded_native_capture_is_never_an_operational_observation():
    for proof in (None, native_frame()['sourceClockEvidence']):
        row = native_frame(timestampBasis='recorded-native-sei', sourceClockEvidence=proof)
        with pytest.raises(ValidationError, match='Offline native capture replay'):
            Observation.model_validate(row)


def test_actual_api_preserves_native_basis_and_typed_proof_without_enabling_browser_clock(monkeypatch):
    engine, _ = configured(monkeypatch)
    with TestClient(create_app(engine, media_registry={})) as client:
        for source in ('a', 'b'):
            assert client.post('/api/v1/city/observations', json=native_frame(source)).json()['accepted']
        snapshot = client.get('/api/v1/city/snapshot').json()
    for source in snapshot['sources']:
        assert source['timestampBasis'] == source['sourceClockMode'] == 'source-native-sei'
        assert source['sourceClockEvidence']['captureTimeNs'] == source['lastSourceTimeNs']
        assert source['sourceClockEvidence']['auPtsNs'] == source['rawSourcePtsNs']
        assert source['sourceClockAgeSeconds'] is not None
        assert source['browserClockVerified'] is False
    assert all(source['browserClockVerified'] is False for source in engine.site_json()['sources'])
    assert all(track['mapAssociation']['sourceClockBasis'] == 'source-native-sei' for track in snapshot['tracks'])
    assert snapshot['association']['mapFusion']['qualified'] is False
    assert snapshot['association']['globalFusionEnabled'] is False


def test_native_clock_single_then_pair_uses_no_rtcp_transient_or_single_shared_ids(monkeypatch):
    engine, _ = configured(monkeypatch, sources=('a',))
    first = native_frame()
    first.update(trackingArchitecture=None, trackingMode='nvdcf')
    first['objects'][0].update(native3D=None, globalTrackId=None, associationMethod=None)
    assert ingest(engine, first)['accepted']
    assert engine.snapshot()['sources'][0]['timestampBasis'] == 'source-native-sei'
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None
    assert engine.snapshot()['association']['mapFusion']['enabled'] is False
    rtcp = deepcopy(first); rtcp.update(timestampBasis='source-rtcp', sourceClockEvidence=None, sequence='2')
    with pytest.raises(ValueError, match='cannot fall back'):
        ingest(engine, rtcp)
    site = engine.site_json()
    site['sources'].append({**site['sources'][0], 'id': 'b', 'calibrationRevision': 'cal-b'})
    engine.put_site(Site.model_validate(site))
    for source in ('a', 'b'):
        assert ingest(engine, native_frame(source))['accepted']
    assert engine.snapshot()['association']['mapFusion']['available'] is True


@pytest.mark.parametrize('scope', ['default-mode', 'other-site', 'disabled-map-profile', 'wrong-calibration', 'foreign-camera'])
def test_native_clock_requires_explicit_isaac_profile_scope(monkeypatch, scope):
    engine, _ = configured(monkeypatch, mode='source-rtcp' if scope == 'default-mode' else 'source-native-sei',
        site_id='other' if scope == 'other-site' else 'isaac-intersection-a')
    if scope == 'disabled-map-profile': engine.map_demo_requested = False
    if scope == 'wrong-calibration': engine.site.sources[0].calibrationRevision = 'old'
    if scope == 'foreign-camera': engine.site.sources[1].id = 'foreign'
    sample = native_frame(siteId=engine.site.id)
    with pytest.raises(ValueError, match='explicit pinned Isaac'):
        ingest(engine, sample)
    assert not engine.sources


@pytest.mark.parametrize('change', ['missing', 'wrong-capture', 'wrong-pts', 'ambiguous-extra', 'negative', 'overflow', 'wrong-method', 'wrong-correlation', 'numeric', 'unicode'])
def test_native_proof_rejects_missing_ambiguous_or_nonmatching_fields(change):
    row = native_frame()
    proof = row['sourceClockEvidence']
    if change == 'missing': row.pop('sourceClockEvidence')
    if change == 'wrong-capture': proof['captureTimeNs'] = str(int(row['sourceTimeNs']) + 1)
    if change == 'wrong-pts': proof['auPtsNs'] = '0'
    if change == 'ambiguous-extra': proof['offsetNs'] = 597_000_000
    if change == 'negative': proof['frameCounter'] = '-1'
    if change == 'overflow': proof['frameCounter'] = str(2**64)
    if change == 'wrong-method': proof['method'] = 'source-rtcp'
    if change == 'wrong-correlation': proof['correlation'] = 'nearest-time'
    if change == 'numeric': proof['frameCounter'] = 1
    if change == 'unicode': proof['frameCounter'] = '١'
    with pytest.raises(ValidationError):
        Observation.model_validate(row)


def test_native_proof_cannot_be_relabelled_as_rtcp():
    with pytest.raises(ValidationError, match='retain source-native-sei'):
        Observation.model_validate(native_frame(timestampBasis='source-rtcp'))


@pytest.mark.parametrize('change', ['counter', 'time', 'pts', 'reset-bypass'])
def test_same_session_native_time_counter_and_pts_must_advance_without_state_mutation(monkeypatch, change):
    engine, _ = configured(monkeypatch)
    ingest(engine, native_frame())
    before = deepcopy(engine.sources)
    row = native_frame(sequence=2)
    if change in {'counter', 'reset-bypass'}: row['sourceClockEvidence']['frameCounter'] = '1'
    if change == 'time':
        row['sourceTimeNs'] = native_frame()['sourceTimeNs']; row['sourceClockEvidence']['captureTimeNs'] = row['sourceTimeNs']
    if change == 'pts': row['rawSourcePtsNs'] = '0'; row['sourceClockEvidence']['auPtsNs'] = '0'
    if change == 'reset-bypass': row['reset'] = True
    with pytest.raises(ValueError, match='must advance'):
        ingest(engine, row)
    assert engine.sources == before


def test_new_worker_session_may_restart_counter_but_old_shared_epoch_is_not_reused(monkeypatch):
    engine, _ = configured(monkeypatch)
    ingest(engine, native_frame(sequence=3))
    row = native_frame(sequence=1, sourceSessionId='replacement')
    assert ingest(engine, row)['accepted']
    assert engine.snapshot()['tracks'][0]['mapAssociation'] is None


def test_exact_preview_and_source_time_lookup_retain_original_native_proof(monkeypatch):
    engine, _ = configured(monkeypatch)
    original = native_frame()
    ingest(engine, original)
    ingest(engine, native_frame(sequence=2))
    store = PreviewStore(engine)
    identity = FrameIdentity('a', original['sourceSessionId'], original['sequence'], original['sourceTimeNs'], 100, 100, original['modelRevision'])
    assert store.accept(identity, JPEG, (100, 100))['accepted'] is True
    body, _, status = store.get('a')
    assert status == 'ready'
    dto = json.loads(body[4:4 + int.from_bytes(body[:4], 'big')])
    assert dto['timestampBasis'] == 'source-native-sei'
    assert dto['sourceClockEvidence'] == original['sourceClockEvidence']
    assert dto['snapshot']['sources'][0]['sourceClockEvidence'] == original['sourceClockEvidence']
    assert dto['snapshot']['sources'][0]['sourceClockMode'] == 'source-native-sei'
    assert dto['provenance']['browserClockVerified'] is False
    selected = engine.snapshot(source_id='a', source_time_ns=int(original['sourceTimeNs']))
    source = selected['sources'][0]
    assert source['clockAligned'] is True
    assert source['sourceClockEvidence'] == original['sourceClockEvidence']
    assert source['timestampBasis'] == 'source-native-sei'


def test_generic_source_rtcp_unchanged(monkeypatch):
    engine, _ = configured(monkeypatch, mode='source-rtcp')
    row = native_frame(timestampBasis='source-rtcp', sourceClockEvidence=None)
    assert ingest(engine, row)['accepted']
    assert engine.snapshot()['tracks'][0]['mapAssociation']['sourceClockBasis'] == 'source-rtcp'


def test_native_gateway_startup_keeps_old_rtcp_records_readable_without_reingesting_them(monkeypatch):
    engine, clock = configured(monkeypatch, mode='source-rtcp')
    engine.put_rules(RuleSet.model_validate({'rules': [{'id': 'old-rule', 'sourceId': 'a', 'kind': 'area-entry',
        'geometry': {'space': 'image-normalized', 'points': [[0, 0], [1, 0], [1, 1], [0, 1]]}}]}))
    old = native_frame(timestampBasis='source-rtcp', sourceClockEvidence=None)
    ingest(engine, old)
    assert engine.events
    old_event = deepcopy(next(iter(engine.events.values())))
    old_history = deepcopy(engine.histories['a'][0])
    # Live frame caches are intentionally memory-only. An existing retained
    # media-history row is data, not an observation to replay through admission.
    old_history['mediaTimeSeconds'] = 1.
    engine.store.save_history('a', old_history['source']['sessionId'], old_history)
    monkeypatch.setenv('CITY_SOURCE_CLOCK_MODE', 'source-native-sei')
    restored = CityEngine(engine.store, clock=clock)
    assert not restored.sources and not restored.tracks
    assert restored.rules_revision == engine.rules_revision
    retained = restored.store.nearest_history('a', 1.)
    assert retained['source']['timestampBasis'] == 'source-rtcp'
    assert retained['source'].get('sourceClockEvidence') is None
    saved = restored.store.events(site_id=restored.site.id)[0]
    assert saved['id'] == old_event['id'] and saved['state'] == 'unknown'
    assert saved['stateReason'] == 'analytics-restarted'
    with TestClient(create_app(restored, media_registry={})) as client:
        assert client.get('/api/v1/city/events').status_code == 200
        assert client.get('/api/v1/city/snapshot').json()['awaitingObservations'] is True
        assert client.post('/api/v1/city/observations', json=old).status_code == 422
        assert client.post('/api/v1/city/observations', json=native_frame(sourceSessionId='new-worker', fusionEpoch='new-epoch')).json()['accepted'] is True
    assert restored.store.nearest_history('a', 1.)['source']['timestampBasis'] == 'source-rtcp'
