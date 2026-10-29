# SPDX-License-Identifier: Apache-2.0
"""Small deterministic geometry functions, with no simulator/runtime dependency."""
from __future__ import annotations

import math
from typing import Sequence

Point = Sequence[float]
EPS = 1e-9


def finite_point(point: Point) -> bool:
    return len(point) == 2 and all(math.isfinite(v) for v in point)


def cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(point: Point, a: Point, b: Point) -> bool:
    return abs(cross(a, b, point)) <= EPS and min(a[0], b[0]) - EPS <= point[0] <= max(a[0], b[0]) + EPS and min(a[1], b[1]) - EPS <= point[1] <= max(a[1], b[1]) + EPS


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    c1, c2, c3, c4 = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    # Compare orientations individually: their product has squared units and
    # its magnitude can fall below tolerance for clearly crossing small zones.
    if ((c1 > EPS and c2 < -EPS) or (c1 < -EPS and c2 > EPS)) and ((c3 > EPS and c4 < -EPS) or (c3 < -EPS and c4 > EPS)):
        return True
    return any((abs(v) <= EPS and on_segment(p, x, y)) for v, p, x, y in ((c1, c, a, b), (c2, d, a, b), (c3, a, c, d), (c4, b, c, d)))


def validate_polygon(points: Sequence[Point]) -> None:
    if not 3 <= len(points) <= 128 or any(not finite_point(p) for p in points):
        raise ValueError("polygon needs 3–128 finite points")
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, list(points[1:]) + [points[0]]))
    if abs(area) < EPS:
        raise ValueError("polygon must have nonzero area")
    n = len(points)
    for i in range(n):
        if math.dist(points[i], points[(i + 1) % n]) < EPS:
            raise ValueError("polygon has repeated adjacent points")
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if segments_intersect(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                raise ValueError("polygon must not self-intersect")


def point_in_polygon(point: Point, points: Sequence[Point]) -> bool:
    """Boundary points count as inside; rule hysteresis deals with edge jitter."""
    inside = False
    x, y = point
    for a, b in zip(points, list(points[1:]) + [points[0]]):
        if on_segment(point, a, b):
            return True
        if (a[1] > y) != (b[1] > y):
            at_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < at_x:
                inside = not inside
    return inside


def determinant(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix
    return a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])


def _normalized_homography(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix) or not all(math.isfinite(v) for row in matrix for v in row):
        raise ValueError("homography must be a finite 3×3 matrix")
    scale = max(abs(v) for row in matrix for v in row)
    if scale == 0:
        raise ValueError("homography is singular or unstable")
    normalized = [[v / scale for v in row] for row in matrix]
    if abs(determinant(normalized)) < 1e-12:
        raise ValueError("homography is singular or unstable")
    return normalized


def validate_homography(matrix: Sequence[Sequence[float]]) -> None:
    _normalized_homography(matrix)


def project(point: Point, matrix: Sequence[Sequence[float]] | None, valid_polygon: Sequence[Point] | None = None, bounds: Sequence[float] | None = None) -> tuple[list[float] | None, str]:
    if matrix is None:
        return None, "missing-calibration"
    if not finite_point(point):
        return None, "invalid-anchor"
    if valid_polygon and not point_in_polygon(point, valid_polygon):
        return None, "outside-valid-region"
    try:
        # Multiplying every coefficient by a nonzero scalar describes the
        # same projective map. Use the same normalization as validation so
        # exported matrix scale cannot cause a false horizon or overflow.
        normalized = _normalized_homography(matrix)
        h = [row[0] * point[0] + row[1] * point[1] + row[2] for row in normalized]
        if not math.isfinite(h[2]) or abs(h[2]) < EPS:
            return None, "unstable-projection"
        result = [h[0] / h[2], h[1] / h[2]]
        if not finite_point(result):
            return None, "unstable-projection"
        if bounds and not (bounds[0] <= result[0] <= bounds[2] and bounds[1] <= result[1] <= bounds[3]):
            return None, "outside-map-bounds"
        return result, "valid"
    except (ValueError, IndexError, TypeError):
        return None, "invalid-calibration"


def directed_crossing(previous: Point, current: Point, line: Sequence[Point], direction: Point, epsilon: float = 1e-7) -> bool:
    """A finite segment crossing in the explicit movement direction.

    Touching the line does not count until the anchor moves to its other side.
    The caller retains the last non-boundary point to avoid losing that crossing.
    """
    a, b = line
    before, after = cross(a, b, previous), cross(a, b, current)
    movement_dot = (current[0] - previous[0]) * direction[0] + (current[1] - previous[1]) * direction[1]
    return before * after < -epsilon * epsilon and movement_dot > epsilon and segments_intersect(previous, current, a, b)
