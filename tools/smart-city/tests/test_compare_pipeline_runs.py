import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('pipeline_comparison', Path(__file__).parents[1] / 'compare_pipeline_runs.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def row(frame, objects, *, ran=True, source='camera'):
    return {'sourceId': source, 'sourceFrameId': str(frame), 'rawSourcePtsNs': str(frame*100_000_000),
            'image': {'width': 960, 'height': 540}, 'objects': objects, 'detectorRan': ran}


def obj(identity='a', cls='person', x=0):
    return {'localTrackId': identity, 'class': cls, 'bboxPx': [x, 0, 20, 30]}


def keyed(rows):
    return {comparison.frame_key(value): value for value in rows}


def test_tracker_only_frames_are_compared_without_claiming_detection():
    baseline = keyed([row(0, [obj()]), row(1, [obj()])])
    candidate = keyed([row(0, [obj('other')]), row(1, [obj('other')], ran=False)])
    result = comparison.compare(baseline, candidate)
    assert result['inferredFrames'] == 1 and result['trackerOnlyFrames'] == 1
    assert result['baselineBoxAgreement'] == result['smallBaselineBoxAgreement'] == 1
    assert result['baselineIdentityPairChanges'] == 0


def test_one_box_cannot_match_multiple_objects_and_identity_delay_is_explicit():
    baseline = keyed([row(0, [obj(), obj('b', x=50)]), row(1, [obj(), obj('b', x=50)])])
    candidate = keyed([row(0, []), row(1, [obj('c', cls='car'), obj('d', x=50)])])
    result = comparison.compare(baseline, candidate)
    assert result['baselineBoxAgreement'] == .5
    assert result['firstBaselineIdentityMatchDelayMsP95'] == 100
    assert result['matches']['classDisagreements'] == 1
    assert len(comparison.matched_boxes([obj(), obj('b')], [obj('c')])) == 1


def test_mismatched_frames_or_geometry_fail_closed():
    with pytest.raises(ValueError, match='No exact'):
        comparison.compare(keyed([row(0, [])]), keyed([row(1, [])]))
    candidate = row(0, []);candidate['image']['width'] = 640
    with pytest.raises(ValueError, match='geometry'):
        comparison.compare(keyed([row(0, [])]), keyed([candidate]))
