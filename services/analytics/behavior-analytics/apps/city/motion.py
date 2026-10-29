# SPDX-License-Identifier: Apache-2.0
"""Bounded observed-position velocity, independent of simulator ground truth."""
from __future__ import annotations

import math

WINDOW_NS = 1_000_000_000
MAX_SAMPLES = 40


def observed_velocity(previous, ns, position, *, continuous):
    """Fit a trailing one-second line; never carry prediction/gap motion forward.

    Per-frame box jitter is a poor stationary test at high frame rates. This
    causal fit retains the current contact point and averages only its velocity.
    A real stop/start can take roughly half a window to settle.
    """
    samples = [list(row) for row in previous if 0 < ns - row[0] <= WINDOW_NS] if continuous else []
    samples = (samples + [[ns, *position]])[-MAX_SAMPLES:]
    if len(samples) < 2 or ns - samples[0][0] < 100_000_000:
        return None, samples
    origin = samples[0][0]
    times = [(row[0] - origin) / 1e9 for row in samples]
    mean_t = sum(times) / len(times)
    denominator = sum((t - mean_t) ** 2 for t in times)
    if denominator <= 0:
        return None, samples
    velocity = []
    for axis in (1, 2):
        mean_p = sum(row[axis] for row in samples) / len(samples)
        velocity.append(sum((t - mean_t) * (row[axis] - mean_p)
                            for t, row in zip(times, samples)) / denominator)
    if not all(math.isfinite(v) for v in velocity) or math.hypot(*velocity) > 100:
        return None, samples[-1:]
    return velocity, samples
