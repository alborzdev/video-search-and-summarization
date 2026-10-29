#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a two-camera VSS site from a live Isaac camera readout and VSS IDs.

This consumes only static scene geometry. It never consumes simulator actor IDs
or trajectories. The camera package records its measured qualification scope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.request


def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request('http://127.0.0.1:9184/api/v1/city/' + path, data=body,
                                 method='GET' if payload is None else 'PUT',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def invert3(matrix: list[list[float]]) -> list[list[float]]:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) < 1e-15:
        raise ValueError('Singular calibration')
    return [[v / determinant for v in row] for row in
            [[e*i-f*h, c*h-b*i, b*f-c*e], [f*g-d*i, a*i-c*g, c*d-a*f], [d*h-e*g, b*g-a*h, a*e-b*d]]]


def project(matrix: list[list[float]], point: list[float]) -> list[float]:
    value = [row[0] * point[0] + row[1] * point[1] + row[2] for row in matrix]
    if value[2] <= 1e-10:
        raise ValueError('Point behind the camera')
    return [value[0] / value[2], value[1] / value[2]]


def clip_image_polygon(points: list[list[float]]) -> list[list[float]]:
    for axis, boundary, greater in ((0, 0., True), (0, 1., False), (1, 0., True), (1, 1., False)):
        result = []
        for previous, current in zip(points[-1:] + points[:-1], points):
            a = (previous[axis] - boundary) * (1 if greater else -1)
            b = (current[axis] - boundary) * (1 if greater else -1)
            if (a >= 0) != (b >= 0):
                fraction = a / (a - b)
                result.append([previous[i] + fraction * (current[i] - previous[i]) for i in range(2)])
            if b >= 0:
                result.append(current)
        points = result
    if len(points) < 3:
        raise ValueError('Rule has no visible camera area')
    return [[max(0., min(1., value)) for value in point] for point in points]


def northbound_entry_geometry(package: dict, camera: dict, *, line_y: float | None = None,
                              include_anchor_margin: bool = True) -> dict:
    """Use the common visible approach before the Intersection A turn split."""
    lane = next(road for road in package['map']['roads'] if road['id'] == 'NB_1')
    south = next(walk['polygon'] for walk in package['crosswalks'] if walk['id'] == 'XW_S')
    # The old north-of-crossing gate (69.6m) was after the right-turn branch.
    # 66.0m is visible at full lane width and precedes the physical turn arcs.
    line_y = min(point[1] for point in south) + 1.2 if line_y is None else line_y
    a, b = next((a, b) for a, b in zip(lane['points'], lane['points'][1:]) if a[1] <= line_y <= b[1])
    center_x = a[0] + (line_y - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
    matrix = invert3(camera['imageToGroundHomography'])
    # The camera's real bottom-centre vehicle anchors cross up to .61m west
    # of the nominal lane edge in the retained October26 observations. Cover
    # those anchors before the turn split; keep the opposite endpoint and all
    # direction, gap and hysteresis policies unchanged. The explicit false
    # form is for recognizing historical generated geometry, not activation.
    west_margin = .75 if include_anchor_margin else 0.
    pixels = [project(matrix, [center_x + offset, line_y])
              for offset in (-lane['width'] / 2 - west_margin, lane['width'] / 2)]
    normalized = [[u / camera['width'], v / camera['height']] for u, v in pixels]
    if any(not 0 <= value <= 1 for point in normalized for value in point):
        raise ValueError('Northbound counting line is outside the selected view')
    start, end = project(matrix, [center_x, line_y]), project(matrix, [center_x, line_y + 1])
    direction = [(end[i] - start[i]) / (camera['width'] if i == 0 else camera['height']) for i in range(2)]
    return {'space': 'image-normalized', 'points': normalized, 'direction': direction}


def build(package: dict, registration: dict) -> tuple[dict, dict]:
    order = package['cameraOrder']
    if not 1 <= len(order) <= 2 or len(set(order)) != len(order):
        raise ValueError('At most two distinct cameras are allowed')
    sources = []
    rules = []
    crosswalks = {item['id']: item['polygon'] for item in package['crosswalks']}
    for index, name in enumerate(order):
        camera = package['cameras'][name]
        source = registration[name]
        sources.append({**camera, 'id': source['id'], 'vssSensorId': source['id'], 'name': source['name'],
                        'calibrationRevision': package['calibrationRevision'],
                        'deepstreamStreamIndex': index, 'browserClockVerified': False})
        ground_to_image = invert3(camera['imageToGroundHomography'])
        def image_geometry(points):
            pixels = [project(ground_to_image, point) for point in points]
            normalized = [[u / camera['width'], v / camera['height']] for u, v in pixels]
            return {'space': 'image-normalized', 'points': clip_image_polygon(normalized)}
        crossing = crosswalks['XW_S' if name == 'cam_SW' else 'XW_N']
        prefix = name.lower()
        base = {'sourceId': source['id'], 'enabled': True, 'revision': 1,
                'calibrationRevision': package['calibrationRevision']}
        rules.append({**base, 'id': prefix + '-pedestrian-crossing', 'name': ('South' if name == 'cam_SW' else 'North') + ' crossing · person present',
                      'kind': 'area-entry', 'classes': ['person'], 'geometry': image_geometry(crossing),
                      'conditions': {'minimumDurationMs': 200, 'clearAfterMs': 700}})
        rules.append({**base, 'id': prefix + '-blocked-crossing', 'name': ('South' if name == 'cam_SW' else 'North') + ' crossing · stopped vehicle',
                      'kind': 'stopped-in-zone', 'classes': ['car', 'bus', 'truck', 'motorcycle'],
                      'geometry': image_geometry(crossing),
                      'conditions': {'minimumDurationMs': 4000, 'speedBelowMps': 0.35, 'clearAfterMs': 1000}})
        if name == 'cam_NE':
            west = max(point[0] for point in crosswalks['XW_W'])
            east = min(point[0] for point in crosswalks['XW_E'])
            south = max(point[1] for point in crosswalks['XW_S'])
            north = min(point[1] for point in crosswalks['XW_N'])
            rules.append({**base, 'id': prefix + '-intersection-occupancy', 'name': 'Intersection · vehicle occupancy',
                          'kind': 'occupancy-threshold', 'classes': ['car', 'bus', 'truck', 'motorcycle', 'bicycle'],
                          'geometry': image_geometry([[west, south], [east, south], [east, north], [west, north]]),
                          'conditions': {'countThreshold': 3, 'minimumDurationMs': 1500, 'clearAfterMs': 1000}})
            rules.append({**base, 'id': prefix + '-stopped-junction', 'name': 'Junction · stopped vehicle',
                          'kind': 'stopped-in-zone', 'classes': ['car', 'bus', 'truck', 'motorcycle'],
                          'geometry': image_geometry([[west, south], [east, south], [east, north], [west, north]]),
                          'conditions': {'minimumDurationMs': 4000, 'speedBelowMps': 0.35, 'clearAfterMs': 1000}})
        if name == 'cam_SW':
            rules.append({**base, 'id': prefix + '-northbound-line', 'name': 'Northbound vehicles · crossing count',
                          'kind': 'line-crossing', 'classes': ['car', 'bus', 'truck', 'motorcycle', 'bicycle'],
                          'geometry': northbound_entry_geometry(package, camera),
                          'conditions': {'maximumObservationGapMs': 1000}})
    site = {'id': 'isaac-intersection-a', 'name': 'Isaac Sim · Intersection A', 'revision': 1,
            'mode': 'live', 'sources': sources, 'map': package['map'],
            'inputQualification': 'live-isaac-sim-rtsp',
            'qualification': package['qualification'], 'groundWorldZM': package['groundWorldZM'],
            'fusion': {'enabled': False, 'reason': 'MV3DT and ground-association candidates failed the recorded promotion gates. Camera-local observations remain separate.'}}
    return site, {'rules': rules}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera-package', type=Path, required=True)
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    package = json.loads(args.camera_package.read_text())
    registration = json.loads(args.registration.read_text())
    site, rules = build(package, registration)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.apply:
        current_site = request('site')
        current_rules = request('rules')
        site['expectedRevision'] = current_site['revision']
        if site['id'] == current_site['id']:
            site['revision'] = current_site['revision'] + 1
        for name, previous in (('site', current_site), ('rules', current_rules)):
            backup = args.output / f'pre-apply-{name}.json'
            if not backup.exists():
                backup.write_text(json.dumps(previous, indent=2) + '\n')
    for name, value in (('site', site), ('rules', rules)):
        (args.output / f'isaac-{name}.json').write_text(json.dumps(value, indent=2) + '\n')
    if args.apply:
        request('site', site)
        rules['expectedRevision'] = request('rules')['revision']
        applied_rules = request('rules', rules)
        (args.output / 'applied-site.json').write_text(json.dumps(request('site'), indent=2) + '\n')
        (args.output / 'applied-rules.json').write_text(json.dumps(applied_rules, indent=2) + '\n')
    print(json.dumps({'sourceCount': len(site['sources']), 'ruleCount': len(rules['rules']),
                      'calibrationRevision': package['calibrationRevision'], 'applied': args.apply}))


if __name__ == '__main__':
    main()
