"""CPU-only audit controls; no service or model requests."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_preview_duplicates import inspect_envelope, summarize_tracks
from soak import SoakFailure
from test_soak_preview import envelope, frame


def track(identifier, label, box=None, **extra):
    return {'id': identifier, 'class': label, 'bboxPx': box or [10, 20, 30, 40],
            'observedThisFrame': True, 'stale': False, 'confidence': .8, **extra}


def summary(*tracks):
    return summarize_tracks({'snapshot': {'tracks': list(tracks)}})


def test_exact_cross_class_boxes_are_diagnostic_without_mutating_tracks():
    tracks = [track('one', 'truck'), track('two', 'bus')]
    original = deepcopy(tracks)
    result = summary(*tracks)
    assert result['observedTrackCount'] == 2
    assert result['classCounts'] == {'bus': 1, 'truck': 1}
    assert result['identicalCrossClassBoxGroups'] == 1
    assert result['identicalObservedBoxGroups'][0]['classes'] == ['bus', 'truck']
    assert tracks == original


def test_predicted_stale_and_unknown_observation_states_do_not_count():
    result = summary(track('one', 'truck'), track('two', 'bus', observedThisFrame=False),
                     track('three', 'car', stale=True), track('four', 'car', stale=None))
    assert result['observedTrackCount'] == 1
    assert result['identicalObservedBoxGroups'] == []


def test_nearby_boxes_are_not_rounded_and_same_class_coincidence_is_separate():
    result = summary(track('one', 'car'), track('two', 'car'),
                     track('three', 'bus', [10, 20, 30, 40.000001]))
    assert len(result['identicalObservedBoxGroups']) == 1
    assert result['identicalCrossClassBoxGroups'] == 0


def test_empty_snapshot_and_repeated_identity_do_not_invent_duplicate_objects():
    assert summary()['observedTrackCount'] == 0
    assert summary(track('one', 'car'), track('one', 'car'))['identicalObservedBoxGroups'] == []


def test_actual_model_revision_must_match_and_other_camera_is_rejected():
    body = envelope(frame('camera-one', 8))
    result = inspect_envelope(body, 'camera-one', 'cpu-control', 'model-engine-sha')
    assert result['sequence'] == '8'
    assert result['observedTrackCount'] == 0
    with pytest.raises(SoakFailure, match='unexpected-preview-model-revision'):
        inspect_envelope(body, 'camera-one', 'cpu-control', 'different-policy')
    with pytest.raises(SoakFailure, match='preview-source-or-schema-mismatch'):
        inspect_envelope(body, 'camera-two', 'cpu-control', 'model-engine-sha')
