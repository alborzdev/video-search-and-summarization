# SPDX-License-Identifier: Apache-2.0
"""Measured jitter, stop/start lag and observation-chain controls."""
import math
from apps.city.motion import MAX_SAMPLES, observed_velocity


def test_stationary_jitter_does_not_become_rapid_motion():
    samples = []
    speeds = []
    for i in range(90):
        p = [2 + .07 * (-1) ** i, 4 + .04 * math.sin(i * 2.1)]
        v, samples = observed_velocity(samples, i * 66_666_667, p, continuous=i > 0)
        if i > 20:
            speeds.append(math.hypot(*v))
    assert max(speeds) < .1
    assert len(samples) <= MAX_SAMPLES


def test_real_motion_and_stopping_are_preserved_with_bounded_lag():
    samples = []
    for i in range(61):
        t = i / 20
        p = [6 * min(t, 2), -2 * min(t, 2)]
        v, samples = observed_velocity(samples, round(t * 1e9), p, continuous=i > 0)
        if i == 30:
            assert abs(v[0] - 6) < 1e-9 and abs(v[1] + 2) < 1e-9
    assert math.hypot(*v) < 1e-9


def test_prediction_gap_or_reset_cannot_inherit_stationary_proof():
    history = [[0, 2, 3], [500_000_000, 2, 3]]
    v, samples = observed_velocity(history, 600_000_000, [2, 3], continuous=False)
    assert v is None and samples == [[600_000_000, 2, 3]]
    v, samples = observed_velocity(history, 2_000_000_000, [2, 3], continuous=True)
    assert v is None and len(samples) == 1
