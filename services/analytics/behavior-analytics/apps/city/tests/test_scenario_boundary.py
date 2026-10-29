# SPDX-License-Identifier: Apache-2.0
"""Synthetic image-observation boundary tests; these do not qualify AI accuracy."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from apps.city.engine import CityEngine, ConflictError
from apps.city.models import Observation, RuleSet, Site
from apps.city.preview import PreviewStore
from apps.city.scenario_boundary import ScenarioBoundary
from apps.city.store import CityStore

BASE = 1_700_000_000_000_000_000


class Clock:
    value = 100.
    def __call__(self):
        return self.value


def setup(tmp_path, sources=('cam-1',)):
    clock = Clock()
    engine = CityEngine(clock=clock)
    engine.put_site(Site.model_validate({'id': 'test', 'mode': 'fixture-replay', 'sources': [
        {'id': source, 'width': 100, 'height': 100, 'imageToGroundHomography': [[.1, 0, 0], [0, .1, 0], [0, 0, 1]], 'calibrationRevision': 'fixture'} for source in sources]}))
    engine.put_rules(RuleSet.model_validate({'rules': [{'id': 'cross', 'sourceId': 'cam-1', 'name': 'Line', 'kind': 'line-crossing', 'classes': ['car'], 'geometry': {'space': 'image-normalized', 'points': [[.5, .1], [.5, .9]], 'direction': [1, 0]}}]}))
    boundary = ScenarioBoundary(engine, tmp_path, wall_ns=lambda: BASE + round((clock.value - 100) * 1e9))
    return engine, boundary, clock


def ingest(engine, seconds, x=30, epoch=None, source='cam-1', seq=None, architecture=None):
    return engine.ingest(Observation.model_validate({'siteId': 'test', 'sourceId': source,
        'sourceSessionId': 'unchanged', 'sequence': str(seq if seq is not None else round(seconds * 100)),
        'sourceTimeNs': str(BASE + round(seconds * 1e9)), 'timestampBasis': 'fixture-epoch-plus-pts',
        'trackingEpoch': epoch, 'trackingArchitecture': architecture, 'mediaTimeSeconds': seconds, 'image': {'width': 100, 'height': 100},
        'objects': [{'localTrackId': '1', 'class': 'car', 'confidence': .9, 'bboxPx': [x - 5, 30, 10, 10]}]}))


def command(boundary, action, run='run-a'):
    return boundary.command({'action': action, 'runId': run, 'scenarioId': 'queue-buildup'})


def settle(engine, boundary, clock, tmp_path, start=2.):
    clock.value = 100 + start
    status = command(boundary, 'settle')
    epoch = status['trackingEpoch']
    (tmp_path / 'scenario-boundary-ack.json').write_text(json.dumps({'trackingEpoch': epoch,
        'status': 'applied', 'trackerStages': 2, 'sourceIds': list(engine._site_sources())}))
    for seconds in (start, start + .5, start + 1.):
        clock.value = 100 + seconds
        for source in engine._site_sources():
            assert ingest(engine, seconds, 70, epoch, source)['analyticsSuppressed']
    assert boundary.status()['state'] == 'ready'
    return epoch


def test_teleport_never_counts_or_creates_speed_trails_events_or_map_joins(tmp_path):
    engine, boundary, clock = setup(tmp_path)
    ingest(engine, 0, 30)
    ingest(engine, .2, 70)
    assert engine.metrics['cross']['totalCrossings'] == 1
    old_event = next(iter(engine.events.values())).copy()
    original_session = engine.sources['cam-1']['sessionId']
    command(boundary, 'prepare')
    assert not engine.snapshot()['tracks']
    assert not engine.metrics
    result = ingest(engine, 1, 90)
    assert result['analyticsSuppressed'] and result['trackCount'] == 0
    assert not engine.tracks
    assert not engine.metrics
    assert engine.histories['cam-1'][-1]['events'] == []
    assert engine.histories['cam-1'][-1]['tracks'] == []
    assert next(iter(engine.events.values())) == old_event
    epoch = settle(engine, boundary, clock, tmp_path)
    clock.value = 103.5
    command(boundary, 'play')
    # Already queued capture before Play is accepted for exact pixels, excluded from evidence.
    result = ingest(engine, 3.1, 20, epoch)
    assert result['accepted'] and result['analyticsSuppressed']
    assert not engine.tracks and not engine.metrics
    ingest(engine, 3.6, 20, epoch)
    ingest(engine, 3.8, 70, epoch)
    # Genuine post-boundary movement can count; it cannot connect with preparation.
    assert engine.metrics['cross']['totalCrossings'] == 1
    assert engine.sources['cam-1']['sessionId'] == original_session
    assert engine.sources['cam-1']['lastSequence'] == 380
    assert all(track['sourceSessionId'] == original_session for track in engine.tracks.values())
    command(boundary, 'normal')
    assert not engine.tracks and not engine.metrics
    history = engine.store.get('analytics-scopes:test')
    assert any(scope['kind'] == 'scenario' and scope['metrics'][0]['totalCrossings'] == 1 for scope in history)
    assert old_event in list(engine.events.values())
    ingest(engine, 3.9, 20, epoch)
    assert engine.metrics['cross']['totalCrossings'] == 0
    track = next(iter(engine.tracks.values()))
    assert track['speedMps'] is None and len(track['trail']) == 1


def test_same_identity_teleport_on_play_does_not_cross_or_inherit_motion(tmp_path):
    engine, boundary, clock = setup(tmp_path)
    ingest(engine, 0, 20)
    command(boundary, 'prepare')
    epoch = settle(engine, boundary, clock, tmp_path)
    command(boundary, 'play')
    ingest(engine, 3.1, 90, epoch)
    track = next(iter(engine.tracks.values()))
    assert engine.metrics['cross']['totalCrossings'] == 0
    assert track['speedMps'] is None and len(track['trail']) == 1
    assert len(engine.events) == 0


def test_settling_requires_both_cameras_epoch_capture_floor_ack_and_duration(tmp_path):
    engine, boundary, clock = setup(tmp_path, ('cam-1', 'cam-2'))
    command(boundary, 'prepare')
    clock.value = 102
    status = command(boundary, 'settle')
    epoch = status['trackingEpoch']
    for seconds in (0, .5, 1.):
        ingest(engine, seconds, epoch=epoch)
    assert not boundary.samples
    for seconds in (2, 2.5, 3):
        ingest(engine, seconds, epoch=epoch)
        ingest(engine, seconds, epoch='wrong-epoch', source='cam-2')
    assert boundary.status()['state'] == 'settling'
    for seconds in (3.1, 3.6, 4.1):
        ingest(engine, seconds, epoch=epoch, source='cam-2')
    assert boundary.status()['state'] == 'settling'
    (tmp_path / 'scenario-boundary-ack.json').write_text(json.dumps({'trackingEpoch': epoch,
        'status': 'applied', 'trackerStages': 2, 'sourceIds': ['cam-1', 'cam-2']}))
    assert boundary.status()['state'] == 'ready'
    assert not engine.events and not engine.metrics and not engine.tracks


@pytest.mark.parametrize('architectures,stages,expected', [
    (('mv3dt-native-v1', 'mv3dt-native-v1'), 1, 'ready'),
    (('nvdcf-local-then-mv3dt-v1', 'nvdcf-local-then-mv3dt-v1'), 2, 'ready'),
    (('mv3dt-native-v1', 'mv3dt-native-v1'), 2, 'settling'),
    (('nvdcf-local-then-mv3dt-v1', 'nvdcf-local-then-mv3dt-v1'), 1, 'settling'),
    (('mv3dt-native-v1', 'nvdcf-local-then-mv3dt-v1'), 1, 'settling'),
    (('mv3dt-native-v1', 'nvdcf-local-then-mv3dt-v1'), 2, 'settling'),
    (('mv3dt-native-v1', None), 1, 'settling'),
    ((None, None), 2, 'settling'),
])
def test_map_tracker_reset_matches_every_current_camera_architecture(tmp_path, monkeypatch, architectures, stages, expected):
    engine, boundary, clock = setup(tmp_path, ('cam-1', 'cam-2'))
    monkeypatch.setattr(engine, '_map_demo_approved', lambda: True)
    command(boundary, 'prepare')
    clock.value = 102
    epoch = command(boundary, 'settle')['trackingEpoch']
    (tmp_path / 'scenario-boundary-ack.json').write_text(json.dumps({'trackingEpoch': epoch,
        'status': 'applied', 'trackerStages': stages, 'sourceIds': ['cam-1', 'cam-2']}))
    for seconds in (2, 2.5, 3):
        clock.value = 100 + seconds
        for source, architecture in zip(('cam-1', 'cam-2'), architectures):
            assert ingest(engine, seconds, epoch=epoch, source=source, architecture=architecture)['analyticsSuppressed']
    assert boundary.status()['state'] == expected
    assert not engine.tracks and not engine.metrics
    if expected == 'ready':
        assert command(boundary, 'play')['state'] == 'running'


def test_failure_recovery_is_bounded_idempotent_and_persisted(tmp_path):
    engine, boundary, clock = setup(tmp_path)
    command(boundary, 'prepare')
    assert command(boundary, 'prepare')['state'] == 'preparing'
    with pytest.raises(ConflictError):
        command(boundary, 'prepare', 'other')
    status = command(boundary, 'settle')
    assert command(boundary, 'settle')['trackingEpoch'] == status['trackingEpoch']
    clock.value += 21
    assert boundary.status()['state'] == 'failed'
    assert engine.analytics_suppressed
    with pytest.raises(ConflictError):
        command(boundary, 'normal')
    restarted = ScenarioBoundary(engine, tmp_path, wall_ns=lambda: BASE + 21_000_000_000)
    assert restarted.status()['state'] == 'failed' and engine.analytics_suppressed
    assert command(restarted, 'recover')['state'] == 'recovering'
    assert command(restarted, 'recover')['state'] == 'recovering'
    epoch = settle(engine, restarted, clock, tmp_path, start=22)
    assert command(restarted, 'normal')['state'] == 'normal'
    assert command(restarted, 'normal')['state'] == 'normal'
    assert not engine.analytics_suppressed and engine.required_tracking_epoch == epoch


def test_cancel_recovery_invalidates_exact_preview_generation_and_preserves_history(tmp_path):
    engine, boundary, clock = setup(tmp_path)
    command(boundary, 'prepare')
    epoch = settle(engine, boundary, clock, tmp_path)
    command(boundary, 'play')
    ingest(engine, 3.1, 30, epoch)
    sample = engine.histories['cam-1'][-1]
    generation = engine.frame_generation
    command(boundary, 'recover')
    assert engine.frame_generation > generation
    assert sample['analyticsScope']['kind'] == 'scenario'
    assert sample['context']['generation'] == generation
    assert not engine.tracks
    ingest(engine, 3.2, 90, epoch)
    assert not engine.metrics and not engine.events
    assert engine.histories['cam-1'][-1]['analyticsScope']['kind'] == 'recovering'


def test_historical_scope_is_not_relabelled_after_next_visitor(tmp_path):
    engine, boundary, clock = setup(tmp_path)
    ingest(engine, 0, 20)
    old_scope = engine.scope_json()
    command(boundary, 'prepare')
    past = engine.snapshot('cam-1', media_time=0)
    assert past['analyticsScope'] == old_scope
    assert past['sources'][0]['analyticsScope'] == old_scope
    assert engine.scope_json()['kind'] == 'preparing'


def test_ready_can_wait_for_operator_while_fresh_frames_continue(tmp_path):
    engine, boundary, clock = setup(tmp_path)
    command(boundary, 'prepare')
    epoch = settle(engine, boundary, clock, tmp_path)
    for seconds in range(4, 10):
        clock.value = 100 + seconds
        ingest(engine, seconds, epoch=epoch)
    assert command(boundary, 'play')['state'] == 'running'
    command(boundary, 'recover')
    settle(engine, boundary, clock, tmp_path, start=10)
    clock.value = 114
    with pytest.raises(ConflictError, match='stale'):
        command(boundary, 'play')
    assert engine.analytics_suppressed


@pytest.mark.parametrize("change", ["session", "epoch", "source-set"])
def test_ready_revalidates_current_camera_identity_before_play(tmp_path, change):
    engine, boundary, clock = setup(tmp_path)
    command(boundary, 'prepare')
    epoch = settle(engine, boundary, clock, tmp_path)
    if change == 'session':
        # A new source can emit one fresh frame with the same tracking epoch;
        # that is insufficient to replace the prior source's settling proof.
        payload = {'siteId': 'test', 'sourceId': 'cam-1', 'sourceSessionId': 'new-session',
            'sequence': '0', 'sourceTimeNs': str(BASE + 3_100_000_000), 'trackingEpoch': epoch,
            'timestampBasis': 'fixture-epoch-plus-pts', 'image': {'width': 100, 'height': 100}, 'objects': []}
        engine.ingest(Observation.model_validate(payload))
    elif change == 'epoch':
        ingest(engine, 3.1, epoch='unexpected-worker-epoch')
    else:
        site = engine.site.model_copy(deep=True)
        site.sources.append(site.sources[0].model_copy(update={'id': 'new-camera'}))
        engine.put_site(site)
    with pytest.raises(ConflictError):
        command(boundary, 'play')
    assert boundary.status()['state'] == 'failed'
    assert engine.analytics_suppressed and not engine.tracks
