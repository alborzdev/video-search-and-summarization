#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Configure visible measurement zones from the exported static intersection.

This reads camera calibration, crosswalks and roads only. Simulator actors,
identities, movements and signal phases never enter the analytics input.
"""
from __future__ import annotations

import argparse
import json
import math
import runpy
from pathlib import Path
from isaac_site import invert3, project, request

PREFIX = 'mobility-isaac-'
VEHICLES = ['car', 'bus', 'truck', 'motorcycle', 'bicycle']


def right_exit_points(package):
    """Outer eastbound lane, one full width right of the exported inner lane.

    The static export contains through lanes. The right turn uses the adjacent
    outer lane; a perpendicular width offset preserves the measured slope.
    This is static road geometry, never an actor trajectory or AI result.
    """
    crossing = next(c['polygon'] for c in package['crosswalks'] if c['id'] == 'XW_E')
    x = max(p[0] for p in crossing) + 1.7
    lane = next(road for road in package['map']['roads'] if road['id'] == 'EB_1')
    a, b = next((a, b) for a, b in zip(lane['points'], lane['points'][1:]) if a[0] <= x <= b[0])
    if b[0] - a[0] <= 1e-8 or not math.isfinite(lane['width']) or lane['width'] <= 0:
        raise ValueError('Outer eastbound exit needs a finite eastbound lane and width')
    slope = (b[1] - a[1]) / (b[0] - a[0])
    inner_y = a[1] + (x - a[0]) * slope
    outer_y = inner_y - lane['width'] * math.hypot(1, slope)
    return [[x, outer_y - lane['width'] / 2], [x, outer_y + lane['width'] / 2]]


def build(package, site, saved_rules):
    if site['id'] != 'isaac-intersection-a' or package.get('cameraOrder') != ['cam_SW', 'cam_NE']:
        raise ValueError('This preset requires the prepared two-camera intersection')
    sources = {source['name']: source for source in site['sources']}
    sw, ne = sources['isaac-intersection-southwest'], sources['isaac-intersection-northeast']
    if any(source.get('calibrationRevision') != package['calibrationRevision'] for source in (sw, ne)):
        raise ValueError('Camera export does not match the current site calibration')
    crosswalks = {item['id']: item['polygon'] for item in package['crosswalks']}
    north_y = max(point[1] for point in crosswalks['XW_N']) + 1.6
    south_y = min(point[1] for point in crosswalks['XW_S'])
    west_x = max(point[0] for point in crosswalks['XW_W']) + 1.4
    east_x = max(point[0] for point in crosswalks['XW_E']) + 1.7
    lanes = {road['id']: road for road in package['map']['roads']}

    def x_at_y(lane, y):
        for a, b in zip(lane['points'], lane['points'][1:]):
            if min(a[1], b[1]) <= y <= max(a[1], b[1]) and abs(b[1] - a[1]) > 1e-8:
                return a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0])
        raise ValueError('Measurement point is outside the authored lane')

    def y_at_x(lane, x):
        for a, b in zip(lane['points'], lane['points'][1:]):
            if min(a[0], b[0]) <= x <= max(a[0], b[0]) and abs(b[0] - a[0]) > 1e-8:
                return a[1] + (x - a[0]) / (b[0] - a[0]) * (b[1] - a[1])
        raise ValueError('Measurement point is outside the authored lane')

    rules = []
    previous = {rule['id']: rule for rule in saved_rules['rules']}

    def rule(key, name, source, points, kind='occupancy-threshold', classes=None, direction=None, conditions=None):
        camera = package['cameras']['cam_SW' if source is sw else 'cam_NE']
        matrix = camera.get('classImageToGroundHomographies', {}).get('person', camera['imageToGroundHomography']) if classes == ['person'] else camera['imageToGroundHomography']
        inverse = invert3(matrix)
        for point in points:
            u, v = project(inverse, point)
            if not (0 <= u <= camera['width'] and 0 <= v <= camera['height']):
                raise ValueError(f'{name} is outside its owner camera; adjust the zone before use')
        identifier = PREFIX + key
        item = {'id': identifier, 'name': name, 'kind': kind, 'sourceId': source['id'], 'classes': classes or VEHICLES,
                'geometry': {'space': 'site-metres', 'points': points, **({'direction': direction} if direction else {})},
                'conditions': {'countThreshold': 10000, 'maximumObservationGapMs': 1000, **(conditions or {})},
                'enabled': True, 'revision': previous.get(identifier, {}).get('revision', 0) + 1,
                'calibrationRevision': package['calibrationRevision'], 'purpose': 'mobility-measurement'}
        rules.append(item)
        return identifier

    nx, nw = x_at_y(lanes['NB_1'], north_y), lanes['NB_1']['width'] / 2
    north = rule('north-exit', 'Northbound · north gate', sw, [[nx - nw, north_y], [nx + nw, north_y]], 'line-crossing', direction=[0, 1], conditions={'countThreshold': 1})
    wy, ww = y_at_x(lanes['WB_1'], west_x), lanes['WB_1']['width'] / 2
    west = rule('west-exit', 'Westbound · exit gate', sw, [[west_x, wy - ww], [west_x, wy + ww]], 'line-crossing', direction=[-1, 0], conditions={'countThreshold': 1})
    ey, ew = y_at_x(lanes['EB_1'], east_x), lanes['EB_1']['width'] / 2
    rule('east-exit', 'Eastbound · exit gate', sw, [[east_x, ey - ew], [east_x, ey + ew]], 'line-crossing', direction=[1, 0], conditions={'countThreshold': 1})
    right = rule('east-right-exit', 'Northbound right · outer east gate', sw,
                 right_exit_points(package), 'line-crossing', direction=[1, 0], conditions={'countThreshold': 1})
    stop_y, upstream_y = south_y - 1, south_y - 14.8
    stop_x, upstream_x = x_at_y(lanes['NB_1'], stop_y), x_at_y(lanes['NB_1'], upstream_y)
    width = lanes['NB_1']['width'] / 2
    stop_line = [[stop_x - width, stop_y], [stop_x + width, stop_y]]
    queue_zone = rule('northbound-queue', 'Northbound approach · queue', ne,
                      [[upstream_x - width, upstream_y], [upstream_x + width, upstream_y], stop_line[1], stop_line[0]], 'queue',
                      conditions={'countThreshold': 2, 'minimumDurationMs': 1500, 'speedBelowMps': .35})
    south = crosswalks['XW_S']
    x0, y0, y1 = min(p[0] for p in south), min(p[1] for p in south), max(p[1] for p in south)
    waiting = rule('south-waiting-west', 'South crossing · west waiting area', ne,
                   [[x0 - 4, y0], [x0, y0], [x0, y1], [x0 - 4, y1]], classes=['person'])
    # Count road traversals in a visible corridor around the markings. Keep
    # the original painted-crossing obstruction rules unchanged. The 1.5 m
    # side buffer is an operator measurement choice, not an accuracy claim.
    x1 = max(point[0] for point in south)
    corridor = [[x0, y0 - 1.5], [x1, y0 - 1.5], [x1, y1 + 1.5], [x0, y1 + 1.5]]
    crossing = rule('south-crossing-measurement', 'South crossing · pedestrian corridor', ne, corridor, classes=['person'])
    east_waiting = rule('south-waiting-east', 'South crossing · east approach area', ne,
                        [[x1, y0 - 4], [x1 + 4, y0 - 4], [x1 + 4, y1 + 1.5], [x1, y1 + 1.5]], classes=['person'])
    # This is a curbside traffic-lane observation zone, not a declared parking
    # bay or bus stop. Its role stays general until an operator assigns one.
    curb_y0, curb_y1 = north_y + 2, north_y + 12
    curb_x0, curb_x1 = x_at_y(lanes['NB_1'], curb_y0), x_at_y(lanes['NB_1'], curb_y1)
    curb = rule('north-curbside-lane', 'North arm · curbside lane', sw,
                [[curb_x0 - nw, curb_y0], [curb_x0 + nw, curb_y0],
                 [curb_x1 + nw, curb_y1], [curb_x1 - nw, curb_y1]],
                classes=['car', 'bus', 'truck', 'motorcycle'])
    if 'cam_sw-northbound-line' not in previous:
        raise ValueError('The prepared northbound entry gate is missing')
    config = {
        'movements': [{'id': 'northbound-' + key, 'name': name, 'entryRuleId': 'cam_sw-northbound-line', 'exitRuleId': exit_id, 'classes': VEHICLES}
                      for key, name, exit_id in [('through', 'Northbound · straight', north), ('left', 'Northbound · left', west), ('right', 'Northbound · right', right)]],
        'queues': [{'id': 'northbound-queue', 'name': 'Northbound approach', 'zoneRuleId': queue_zone, 'stopLine': stop_line,
                    'upstreamPoint': [upstream_x, upstream_y], 'spillbackDistanceM': 10,
                    'minimumDurationMs': 1500, 'maxAnchorGapM': 8, 'stopLineReachM': 8}],
        'crossings': [
            {'id': 'south-crossing-west-east', 'name': 'South crossing · west to east', 'waitingRuleId': waiting, 'crossingRuleId': crossing},
            {'id': 'south-crossing-east-west', 'name': 'South pedestrian corridor · east to west', 'waitingRuleId': east_waiting, 'crossingRuleId': crossing}],
        'curbs': [{'id': 'north-curbside-access', 'name': 'North arm · curbside access', 'zoneRuleId': curb,
                   'role': 'general', 'dwellThresholdMs': 30000, 'maximumObservationGapMs': 1000}],
    }
    # Namespace membership does not establish preset ownership. In particular,
    # the separately reviewed physical East-crossing rules share this prefix.
    # Replace only IDs this generator actually emits and retain all other
    # operator rules byte-for-value, including disabled/custom measurements.
    generated_ids = {r['id'] for r in rules}
    return [r for r in saved_rules['rules'] if r['id'] not in generated_ids] + rules, config


def validate_saved_mobility_references(config, rules):
    """Refuse a preset PUT before any mutation if a saved reference is lost."""
    available = {rule['id'] for rule in rules}
    fields = {'movements': ('entryRuleId', 'exitRuleId'), 'crossings': ('waitingRuleId', 'crossingRuleId'),
              'queues': ('zoneRuleId',), 'curbs': ('zoneRuleId',)}
    missing = [f"{kind}/{item['id']}: {item[field]}"
               for kind, references in fields.items() for item in config.get(kind, [])
               for field in references if item[field] not in available]
    if missing:
        raise ValueError('Refusing preset apply: saved mobility references missing rules: ' + ', '.join(missing)
                         + '. Keep the saved configuration and use a reviewed migration that preserves its rules; '
                           'prepare_east_pedestrian_story.py prepares the physical XW_E story without contacting services.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = runpy.run_path(str(Path(__file__).with_name('isaac_workspace.py')))['runtime_root']()
    parser.add_argument('--camera-package', type=Path, default=root / 'logs/vss-integration/camera-map-export.json')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--add-curb', action='store_true', help='Add the prepared curb measurement if none is saved; preserve other measurements')
    parser.add_argument('--add-east-crossing', action='store_true',
                        help='Add the South crossing\'s east waiting direction if absent; does not create the physical XW_E story')
    args = parser.parse_args()
    package = json.loads(args.camera_package.read_text())
    site, saved = request('site'), request('rules')
    rules, config = build(package, site, saved)
    if not args.apply:
        print(json.dumps({'rules': rules, 'mobility': config}, indent=2)); return
    current = request('mobility')['config']
    validate_saved_mobility_references(current, rules)
    # Preserve an operator's saved measurement selection. Restore deterministic
    # geometry after the normal site launcher refreshes its base scene rules.
    request('rules', {'rules': rules, 'expectedRevision': saved['revision']})
    existing = any(current.get(key) for key in ('movements', 'queues', 'crossings', 'curbs'))
    if not existing:
        request('mobility/config', {**config, 'expectedRevision': current['revision']})
    else:
        updated = dict(current)
        if args.add_curb and not current.get('curbs'):
            updated['curbs'] = config['curbs']
        east_config = config['crossings'][1]
        if args.add_east_crossing and not any(row['id'] == east_config['id'] or row['waitingRuleId'] == east_config['waitingRuleId'] for row in current.get('crossings', [])):
            updated['crossings'] = [*current.get('crossings', []), east_config]
        if updated != current:
            request('mobility/config', {**updated, 'expectedRevision': current['revision']})
    print(json.dumps({'status': 'configured', 'rules': len(rules), 'measurements': 'existing selection preserved; requested missing presets added' if existing else 'three turns, one queue, two crossing directions, one curb', 'basis': 'static scene geometry; video detections only'}))


if __name__ == '__main__':
    main()
