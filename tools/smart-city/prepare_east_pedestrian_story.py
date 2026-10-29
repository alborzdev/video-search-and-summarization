#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare a two-direction East crossing review bundle; never contact services.

Preserve all saved rules, replace only the known South crossing selection and
archive its full configuration. No actor truth enters observation analytics.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from isaac_movement_gates import CURRENT_REVISION_PLACEHOLDER, encoded, require, same
from isaac_site import invert3, project

SOUTH = ('south-crossing-west-east', 'south-crossing-east-west')
EAST = ('east-crossing-south-north', 'east-crossing-north-south')
WAIT_S = 'mobility-isaac-east-waiting-south'
CROSS = 'mobility-isaac-east-crossing-measurement'
WAIT_N = 'mobility-isaac-east-waiting-north'


def prepare(snapshot, package, survey, static_audit):
    original = deepcopy(snapshot)
    site, saved, config = (deepcopy(snapshot['site']), deepcopy(snapshot['rules']), deepcopy(snapshot['mobility']['config']))
    require(site.get('id') == 'isaac-intersection-a' and site.get('mode') == 'live', 'Expected live Intersection A')
    require(package.get('cameraOrder') == ['cam_SW', 'cam_NE'], 'Expected the prepared two-camera export')
    require(type(saved.get('revision')) is int and type(config.get('revision')) is int, 'Missing optimistic revisions')
    sources = site['sources']
    require(len(sources) == 2 and len({s['id'] for s in sources}) == 2 and [s['name'] for s in sources] ==
            ['isaac-intersection-southwest', 'isaac-intersection-northeast'], 'Source order/identity changed')
    for source, name in zip(sources, package['cameraOrder']):
        require(source['calibrationRevision'] == package['calibrationRevision'], 'Camera calibration revision changed')
        for key in ('width', 'height', 'imageToGroundHomography', 'classImageToGroundHomographies',
                    'validGroundPolygon', 'projectionMatrix3x4', 'cameraPositionWorldM'):
            require(key in source and key in package['cameras'][name] and same(source[key], package['cameras'][name][key]),
                    'Camera geometry differs: ' + key)
    exported = next((c for c in package['crosswalks'] if c['id'] == 'XW_E'), None)
    crossing = next((c for c in survey['crosswalks'] if c['id'] == 'XW_E'), None)
    if crossing is None or not same(crossing, exported):
        raise ValueError('Survey/export East crossing differs')
    require(same(crossing['polygon'], [[-13.2, 72.0], [-9.2, 72.0], [-9.2, 86.4], [-13.2, 86.4]])
            and crossing['ped_signal'] == 'ped_cross_EW' and crossing['conflicting_lanes'] == ['EB_1', 'WB_1'],
            'East crossing/signal geometry changed; review the preset')
    require(static_audit.get('schemaVersion') == 'city.pedestrian-pocket-static-audit.v1', 'Expected scoped static visibility audit')
    require(same(static_audit['cameras']['cam_SW']['eye'], sources[0]['cameraPositionWorldM']), 'Static visibility camera differs')
    names = {'east-south-wait', 'east-south-edge', 'east-midpoint', 'east-north-edge', 'east-north-wait'}
    rays = [r for r in static_audit['cameraRays'] if r.get('camera') == 'cam_SW' and r.get('name') in names]
    require({r['name'] for r in rays} == names and len(rays) == 5, 'Missing unique East SW visibility samples')
    require(all(len(r.get('samples', [])) == 3 and all(s.get('insideImage') is True and s.get('currentCityHits') == []
                    for s in r['samples']) for r in rays), 'East route has static occlusion/out-of-image samples')
    by_id = {r['id']: r for r in saved['rules']}
    require(len(by_id) == len(saved['rules']), 'Duplicate saved rule ID')
    template_ids = ['mobility-isaac-south-waiting-west', 'mobility-isaac-south-crossing-measurement', 'mobility-isaac-south-waiting-east']
    require(all(key in by_id for key in template_ids), 'Missing South templates; do not regenerate operator rules')
    for key in template_ids:
        rule = by_id[key]
        require(rule.get('enabled') is True and rule.get('classes') == ['person']
                and rule.get('calibrationRevision') == package['calibrationRevision']
                and rule.get('geometry', {}).get('space') == 'site-metres'
                and type(rule.get('conditions', {}).get('maximumObservationGapMs')) is int,
                'South template policy is not compatible with a person measurement')
    camera = package['cameras']['cam_SW']; inverse = invert3(camera['classImageToGroundHomographies']['person'])
    # The full south pad extends beyond SW's image. These are explicitly visible
    # 2 m waiting bands, not a claim of coverage of the whole sidewalk.
    geometries = [([[-12.2, 69.2], [-10.2, 69.2], [-10.2, 72.0], [-12.2, 72.0]], WAIT_S, 'East crossing · south waiting area'),
                  (crossing['polygon'], CROSS, 'East crossing · painted crossing'),
                  ([[-12.2, 86.4], [-10.2, 86.4], [-10.2, 90.4], [-12.2, 90.4]], WAIT_N, 'East crossing · north waiting area')]
    pixel_geometry = {}; added = []
    for (points, identifier, name), template_id in zip(geometries, template_ids):
        pixels = [project(inverse, point) for point in points]
        require(all(0 <= u <= camera['width'] and 0 <= v <= camera['height'] for u, v in pixels), 'East ROI outside SW image')
        pixel_geometry[identifier] = pixels
        candidate = {**deepcopy(by_id[template_id]), 'id': identifier, 'name': name, 'sourceId': sources[0]['id'],
                     'geometry': {'space': 'site-metres', 'points': deepcopy(points), 'direction': None},
                     'revision': 1, 'purpose': 'mobility-measurement'}
        if identifier in by_id:
            require(same({k: v for k, v in by_id[identifier].items() if k != 'revision'},
                         {k: v for k, v in candidate.items() if k != 'revision'}), 'Conflicting East operator rule: ' + identifier)
        else:
            saved['rules'].append(candidate); added.append(identifier)
    current = config.get('crossings', [])
    current_ids = tuple(item['id'] for item in current)
    east_configs = [
        {'id': EAST[0], 'name': 'East crossing · south to north', 'waitingRuleId': WAIT_S, 'crossingRuleId': CROSS},
        {'id': EAST[1], 'name': 'East crossing · north to south', 'waitingRuleId': WAIT_N, 'crossingRuleId': CROSS},
    ]
    if current_ids == SOUTH:
        require([(c['waitingRuleId'], c['crossingRuleId']) for c in current] ==
                [(template_ids[0], template_ids[1]), (template_ids[2], template_ids[1])],
                'South operator selection references custom rules; review manually')
        config['crossings'] = east_configs
    else:
        require(current_ids == EAST and same(current, east_configs), 'Custom crossing selection must be reviewed explicitly')
    route = [[-11.2, 70.0, 0], [-11.2, 79.2, 0], [-11.2, 88.4, 0]]
    binding = {'east-crossing': {'crosswalkId': 'XW_E', 'signalGroup': crossing['ped_signal'], 'points': route}}
    summary = {'schemaVersion': 'city.east-pedestrian-story-preparation.v1', 'candidateOnly': True, 'runtimeChanged': False,
               'siteRevision': site['revision'], 'calibrationRevision': package['calibrationRevision'],
               'rulesChangeRequired': bool(added), 'addedRuleIds': added, 'mobilityChangeRequired': config != snapshot['mobility']['config'],
               'selectedCrossingIds': list(EAST), 'preservedSouthRuleIds': template_ids,
               'expectedRulesRevision': saved['revision'], 'expectedMobilityRevision': config['revision'],
               'ownerSourceId': sources[0]['id'], 'ownerCamera': 'cam_SW', 'roiImagePx': pixel_geometry,
               'signalGroup': crossing['ped_signal'], 'conflictingLanes': crossing['conflicting_lanes'],
               'preserved': ['all existing rules byte-for-value, including South geometry and policy',
                             'site, protected cameras/calibration and model profiles', 'movement, queue and curb selections',
                             'full previous mobility selection in before/rollback material', 'one-second continuity (or the actual unchanged template value)'],
               'applyOrder': ['Finish/cancel scenarios and take a fresh snapshot; reprepare if any input changes.',
                             'Keep source owners registered. PUT rules with expectedRevision and wait for exact native acknowledgement.',
                             'PUT mobility/config with expectedRevision to select only the two East directional cards.',
                             'Reload reviewed scenario source using normal setup, not importlib.reload; no actor lease may be active.',
                             'Run a fresh finite owned approach, actual WALK-gated crossing and normal restoration; verify actual camera counts.'],
               'limits': ['Static render-ray samples exclude moving actors and some dressing; not a detector/identity guarantee.',
                          'The two waiting ROIs cover visible bands, not whole sidewalks. Both directional cards share current occupancy.',
                          'Completion still requires one actual camera-local handle through an observed far-side exit.',
                          'This preparer has no network or apply operation. Runtime controller must use explicit crosswalk/signal metadata.',
                          'East story requires owned booth phases; the legacy fixed-wait people.crossing API is not accepted for this explicit binding.']}
    return {'before': original, 'site': site, 'rulesPut': {'rules': saved['rules'], 'expectedRevision': saved['revision']},
            'mobilityPut': {**config, 'expectedRevision': config['revision']}, 'bindings': binding, 'summary': summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot', 'camera-export', 'survey', 'static-visibility-audit', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name.replace('-', '_')) for name in ('snapshot', 'camera-export', 'survey', 'static-visibility-audit')}
    values = [json.loads(p.read_text()) for p in paths.values()]
    result = prepare(*values)
    args.output.mkdir(parents=True, exist_ok=False)
    documents = {'before.json': result['before'], 'unchanged-site.json': result['site'], 'rules-put.json': result['rulesPut'],
                 'mobility-put.json': result['mobilityPut'], 'proposed-pedestrian-bindings.json': result['bindings'],
                 'previous-crossing-selection.json': result['before']['mobility']['config']['crossings'],
                 'rollback-rules-template.json': {'rules': result['before']['rules']['rules'], 'expectedRevision': CURRENT_REVISION_PLACEHOLDER},
                 'rollback-mobility-template.json': {**{k: v for k, v in result['before']['mobility']['config'].items() if k not in ('revision', 'expectedRevision')},
                                                     'expectedRevision': CURRENT_REVISION_PLACEHOLDER}}
    previous_crossings = result['before']['mobility']['config']['crossings']
    if tuple(item['id'] for item in previous_crossings) == SOUTH:
        documents['south-selection-archive.json'] = previous_crossings
    hashes = {}
    for name, value in documents.items():
        data = encoded(value); (args.output / name).write_bytes(data); hashes[name] = hashlib.sha256(data).hexdigest()
    manifest = {**result['summary'], 'inputSha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}, 'outputSha256': hashes}
    (args.output / 'manifest.json').write_bytes(encoded(manifest))
    print(json.dumps({'candidateOnly': True, 'runtimeChanged': False, 'directory': str(args.output), 'selectedCrossingIds': list(EAST)}))


if __name__ == '__main__':
    main()
