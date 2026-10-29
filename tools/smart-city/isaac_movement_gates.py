#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare an operator-preserving movement-gate migration. Never call services.

Read a full GET site/rules/mobility snapshot and the matching static camera
export. Write a fresh review directory. This tool has no apply operation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from isaac_site import northbound_entry_geometry, invert3, project
from isaac_mobility import right_exit_points

ENTRY = 'cam_sw-northbound-line'
OLD_EXIT = 'mobility-isaac-east-exit'
RIGHT_EXIT = 'mobility-isaac-east-right-exit'
RIGHT_MOVEMENT = 'northbound-right'
CURRENT_REVISION_PLACEHOLDER = 'REPLACE_WITH_CURRENT_REVISION_FROM_GET'


def require(value, message):
    if not value:
        raise ValueError(message)


def same(a, b):
    if isinstance(b, dict):
        return isinstance(a, dict) and a.keys() == b.keys() and all(same(a[k], v) for k, v in b.items())
    if isinstance(b, list):
        return isinstance(a, list) and len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if type(b) in (int, float):
        return type(a) in (int, float) and math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def prepare(snapshot, package):
    """Return candidate bodies and evidence; leave every input unchanged."""
    site, saved_rules, mobility = (deepcopy(snapshot[k]) for k in ('site', 'rules', 'mobility'))
    config = mobility['config']
    require(site.get('id') == 'isaac-intersection-a', 'Expected Intersection A')
    require(package.get('cameraOrder') == ['cam_SW', 'cam_NE'], 'Expected the exact two-camera export')
    require(type(saved_rules.get('revision')) is int and type(config.get('revision')) is int, 'Missing optimistic revisions')
    require(len(site['sources']) == 2 and [s['name'] for s in site['sources']] ==
            ['isaac-intersection-southwest', 'isaac-intersection-northeast'], 'Source order or identity changed')
    require(len({source['id'] for source in site['sources']}) == 2, 'Duplicate source identity')
    require(same(site['map']['roads'], package['map']['roads']), 'Exported roads differ from current site')
    for source, name in zip(site['sources'], package['cameraOrder']):
        require(source.get('calibrationRevision') == package.get('calibrationRevision'), 'Calibration revision changed')
        camera = package['cameras'][name]
        for key in ('width', 'height', 'imageToGroundHomography', 'validGroundPolygon',
                    'projectionMatrix3x4', 'classImageToGroundHomographies'):
            require(key in source and key in camera and same(source[key], camera[key]), 'Camera geometry differs: ' + key)
    sw = site['sources'][0]
    by_id = {r['id']: r for r in saved_rules['rules']}
    require(len(by_id) == len(saved_rules['rules']), 'Duplicate rule identity')
    require(ENTRY in by_id and OLD_EXIT in by_id, 'Known movement gates are missing')
    entry, east = by_id[ENTRY], by_id[OLD_EXIT]
    for rule in (entry, east):
        require(rule['sourceId'] == sw['id'] and rule['kind'] == 'line-crossing'
                and rule.get('enabled') is True, 'Movement gate owner, type or enabled state changed')
        require(rule.get('calibrationRevision') == package['calibrationRevision'], 'Gate calibration changed')
    new_entry = northbound_entry_geometry(package, package['cameras']['cam_SW'])
    south = next(c['polygon'] for c in package['crosswalks'] if c['id'] == 'XW_S')
    old_entry = northbound_entry_geometry(package, package['cameras']['cam_SW'],
                                           line_y=max(p[1] for p in south) + .8, include_anchor_margin=False)
    old_early_entry = northbound_entry_geometry(package, package['cameras']['cam_SW'], include_anchor_margin=False)
    require(any(same(entry['geometry'], known) for known in (old_entry, old_early_entry, new_entry)),
            'Operator changed entry geometry; review it explicitly instead of overwriting')
    right_geometry = {'space': 'site-metres', 'points': right_exit_points(package), 'direction': [1., 0.]}
    matrix = invert3(package['cameras']['cam_SW']['imageToGroundHomography'])
    right_pixels = [project(matrix, point) for point in right_geometry['points']]
    require(all(0 <= u <= sw['width'] and 0 <= v <= sw['height'] for u, v in right_pixels),
            'Right exit is outside its owner camera')
    movements = [m for m in config['movements'] if m['id'] == RIGHT_MOVEMENT]
    require(len(movements) == 1, 'Operator movement selection has no unique northbound-right')
    movement = movements[0]
    require(movement['entryRuleId'] == ENTRY and movement['exitRuleId'] in (OLD_EXIT, RIGHT_EXIT),
            'Operator changed the right-turn references; do not retarget custom gates')
    changed_entry = not same(entry['geometry'], new_entry)
    add_right = RIGHT_EXIT not in by_id
    if add_right:
        # Preserve the actual current class/condition/enable policy, including
        # operator sensitivity, rather than regenerate the whole rule set.
        right_rule = {**deepcopy(east), 'id': RIGHT_EXIT, 'name': 'Northbound right · outer east gate',
                      'geometry': right_geometry, 'purpose': 'mobility-measurement'}
        saved_rules['rules'].append(right_rule)
    else:
        right_rule = by_id[RIGHT_EXIT]
        require(right_rule['sourceId'] == sw['id'] and right_rule['kind'] == 'line-crossing'
                and right_rule.get('enabled') is True and right_rule.get('calibrationRevision') == package['calibrationRevision']
                and same(right_rule['geometry'], right_geometry), 'Dedicated right-exit ID has conflicting operator geometry or policy')
    entry['geometry'] = new_entry
    previous_exit = movement['exitRuleId']
    changed_reference = previous_exit != RIGHT_EXIT
    movement['exitRuleId'] = RIGHT_EXIT
    rules_put = {'rules': saved_rules['rules'], 'expectedRevision': snapshot['rules']['revision']}
    mobility_put = {**config, 'expectedRevision': snapshot['mobility']['config']['revision']}
    changes_required = changed_entry or add_right or changed_reference
    summary = {'schemaVersion': 'city.isaac-movement-gate-migration.v1', 'candidateOnly': True, 'runtimeChanged': False,
        'changesRequired': changes_required, 'rulesChangeRequired': changed_entry or add_right,
        'mobilityChangeRequired': changed_reference, 'siteRevision': site['revision'],
        'calibrationRevision': package['calibrationRevision'], 'cameraAndSiteUpdateRequired': False,
        'expectedRulesRevision': rules_put['expectedRevision'], 'expectedMobilityRevision': mobility_put['expectedRevision'],
        'entryRule': {'id': ENTRY, 'geometryChanged': changed_entry, 'before': snapshot['rules']['rules'][next(
            i for i, r in enumerate(snapshot['rules']['rules']) if r['id'] == ENTRY)]['geometry'], 'after': new_entry},
        'addedRightExit': {'id': RIGHT_EXIT, 'newRule': add_right, 'geometry': right_geometry, 'imagePx': right_pixels,
                          'conditionsInheritedFrom': OLD_EXIT if add_right else 'existing dedicated rule'},
        'retargetedMovement': {'id': RIGHT_MOVEMENT, 'field': 'exitRuleId', 'before': previous_exit,
                               'after': RIGHT_EXIT},
        'preserved': ['site and both camera calibrations', 'old east exit and north/west exits',
                      'all existing rule conditions/classes/enable flags', 'all unrelated rules and measurements',
                      'operator names and extra fields', 'queue, crossing and curb configuration'],
        'applyOrder': ['keep both sources admitted and active; finish or cancel scenarios, and avoid Ask/index requests during cutover',
                      'read current site/rules/mobility and re-prepare if revisions or input fingerprints differ',
                      'PUT rules with expectedRevision, then wait for the matching native analytics acknowledgement',
                      'PUT mobility/config with expectedRevision only when its reference changes',
                      'verify independent camera-derived left/straight/right journeys from the new measurement window'],
        'pauseConstraint': 'Do not use normal Agent source-pause before rules replacement: it removes source owners and archives their rules, so a full two-camera PUT would reference unknown owners.',
        'liveSideEffects': ['Rules replacement marks active events unknown, clears metric/rule state and resets mobility history.',
                            'Mobility config replacement resets its history. Existing durable events remain; no clear is fabricated.',
                            'The API assigns a new global rule revision to all saved rules; semantic operator settings remain preserved.'],
        'rollback': ['Keep before.json and both rollback templates. They contain the complete pre-migration operator configuration.',
                     'Keep both source owners admitted, GET current revisions, then replace the invalid expectedRevision placeholder in each template.',
                     'PUT rollback rules first, await native acknowledgement, then PUT rollback mobility/config.',
                     'Rollback resets metric/history state again. Refuse it if camera calibration or unrelated operator settings changed; merge explicitly.'],
        'limits': ['Static route and camera coverage are geometry evidence, not live detector/track/anchor completeness.',
                   'This tool never contacts an API and has no activation operation. Do not blindly replay stale PUT bodies.']}
    return {'summary': summary, 'rulesPut': rules_put, 'mobilityPut': mobility_put,
            'before': deepcopy(snapshot), 'site': site}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True, help='Object containing full GET site, rules and mobility responses')
    parser.add_argument('--camera-export', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(json.loads(args.snapshot.read_text()), json.loads(args.camera_export.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    documents = {'before.json': result['before'], 'rules-put.json': result['rulesPut'],
                 'mobility-put.json': result['mobilityPut'], 'unchanged-site.json': result['site'],
                 # These deliberately invalid placeholders force an operator
                 # to supply fresh guards; the optional API field must never
                 # be omitted and accidentally become an unconditional PUT.
                 'rollback-rules-template.json': {'rules': result['before']['rules']['rules'],
                                                  'expectedRevision': CURRENT_REVISION_PLACEHOLDER},
                 'rollback-mobility-template.json': {**{key: value for key, value in result['before']['mobility']['config'].items()
                                                       if key not in ('revision', 'expectedRevision')},
                                                     'expectedRevision': CURRENT_REVISION_PLACEHOLDER}}
    hashes = {}
    for name, value in documents.items():
        data = encoded(value); (args.output / name).write_bytes(data); hashes[name] = hashlib.sha256(data).hexdigest()
    summary = {**result['summary'], 'inputSha256': {'snapshot': hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
               'cameraExport': hashlib.sha256(args.camera_export.read_bytes()).hexdigest()}, 'outputSha256': hashes}
    (args.output / 'manifest.json').write_bytes(encoded(summary))
    print(json.dumps({'candidateOnly': True, 'runtimeChanged': False, 'changesRequired': summary['changesRequired'],
                      'directory': str(args.output), 'changedRuleIds': [ENTRY, RIGHT_EXIT]}))


if __name__ == '__main__':
    main()
