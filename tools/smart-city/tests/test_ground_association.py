# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('ground_candidate', Path(__file__).parents[1] / 'experimental_ground_association.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def track(identity, source, timestamp, x=10., **changes):
    return {'id': identity, 'sourceId': source, 'sourceTimeNs': str(timestamp),
        'class': 'person', 'observedThisFrame': True, 'stale': False, 'timestampBasis': 'source-rtcp',
        'confidence': .9, 'bboxPx': [20., 20., 20., 40.], 'imageSize': [1280, 720],
        'positionM': [x, 20.], **changes}


def episode(extra=None, skew=0):
    a = m.GroundAssociator()
    assigned = {}
    for i in range(7):
        ns = 1_000_000_000 + i * 120_000_000
        left = track('one', 'a', ns)
        right = track('two', 'b', ns + skew, 10.1)
        a.update([left, right] + ([extra(ns)] if extra else []), 'a', 'epoch', ns + skew)
        assigned = a.update([left, right] + ([extra(ns)] if extra else []), 'b', 'epoch', ns + skew)
    return a, assigned, ns


def test_requires_temporal_evidence_and_a_mutual_unique_match():
    a, assigned, ns = episode()
    assert assigned['one'] == assigned['two']
    assert assigned['one'].startswith('ground:')
    assert a.update([track('one', 'a', ns + 100_000_000)], 'a', 'epoch', ns + 100_000_000)['one'] == assigned['one']


def test_ambiguous_neighbors_and_skew_stay_camera_local():
    assert episode(extra=lambda ns: track('rival', 'b', ns, 10.2))[1] == {}
    assert episode(skew=70_000_000)[1] == {}


def test_uncertain_or_unobserved_detections_never_enter():
    for changes in ({'observedThisFrame': False}, {'confidence': .3}, {'bboxPx': [0, 2, 20, 40]},
                    {'timestampBasis': 'arrival-pts-unsynchronized'}, {'class': 'car'}, {'stale': True}):
        assert not m.GroundAssociator.eligible(track('a', 'x', 1_000_000_000, **changes), 1_000_000_000)


def test_session_change_drops_established_aliases():
    a, assigned, ns = episode()
    assert assigned
    assert a.update([track('one', 'a', ns + 100_000_000)], 'a', 'different', ns + 100_000_000) == {}
    assert not a.groups
