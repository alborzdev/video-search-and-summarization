#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare a resolution-only Isaac migration; never call APIs or modify runtime.

Inputs must include the full site/rules/mobility snapshot taken before pausing
sources, and a fresh static camera export. Output is a new review directory.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import yaml

CAMERAS = ('cam_SW', 'cam_NE')
PREFIX = 'native/mv3dt-demo/'


def require(value, message):
    if not value:
        raise ValueError(message)


def close(actual, expected, label):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and actual.keys() == expected.keys(), label + ': fields changed')
        for key in expected:
            close(actual[key], expected[key], label + '.' + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), label + ': shape changed')
        for index, (a, b) in enumerate(zip(actual, expected)):
            close(a, b, f'{label}[{index}]')
    elif isinstance(expected, (float, int)) and not isinstance(expected, bool):
        require(type(actual) in (float, int) and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8), label + ': geometry changed')
    else:
        require(actual == expected, label + ': changed')


def scale_rows(matrix, scales):
    return [[value * scale for value in row] for row, scale in zip(matrix, scales)]


def resized_camera(old, new):
    old_size, new_size = [old.get('width'), old.get('height')], [new.get('width'), new.get('height')]
    require(all(type(v) is int and 0 < v <= 16384 for v in old_size + new_size), 'Invalid camera dimensions')
    sx, sy = [new_size[i] / old_size[i] for i in range(2)]
    require(math.isclose(sx, sy, rel_tol=1e-12) and sx != 1, 'Only a proportional resolution change is supported')
    for key in ('T_cv_from_site', 'cameraPositionWorldM', 'lensModel', 'groundCoverageM', 'classGroundPlaneWorldZM'):
        require(key in old and key in new, f'Missing {key}; cannot establish unchanged geometry')
        close(new[key], old[key], key)
    for key in ('K', 'projectionMatrix3x4'):
        close(new[key], scale_rows(old[key], [sx, sy, 1]), key)
    for key in ('imageToGroundHomography',):
        close(new[key], [[row[0] / sx, row[1] / sy, row[2]] for row in old[key]], key)
    require(new['classImageToGroundHomographies'].keys() == old['classImageToGroundHomographies'].keys(),
            'Class calibration set changed')
    for name, matrix in old['classImageToGroundHomographies'].items():
        close(new['classImageToGroundHomographies'][name],
              [[row[0] / sx, row[1] / sy, row[2]] for row in matrix], 'class homography ' + name)
    close(new['validGroundPolygon'], [[x * sx, y * sy] for x, y in old['validGroundPolygon']], 'validGroundPolygon')
    return sx, sy


def prepare(site, rules, mobility, export, registration, directory: Path):
    """Return candidate JSON/bytes only. No input is mutated."""
    site, rules, mobility, export = map(deepcopy, (site, rules, mobility, export))
    require(site.get('id') == 'isaac-intersection-a' and site.get('mode') == 'live', 'Expected live Isaac site')
    require(export.get('schemaVersion') == 'city.isaac-camera-export.v1'
            and export.get('cameraOrder') == list(CAMERAS), 'Expected exact two-camera static export')
    order = [registration[name]['id'] for name in CAMERAS]
    require(len(set(order)) == 2 and [s['id'] for s in site['sources']] == order,
            'Save the full ordered two-camera site before pausing sources')
    close(export['map']['bounds'], site['map']['bounds'], 'map bounds')
    for key in ('roads', 'buildings'):
        close(export['map'].get(key, []), site['map'].get(key, []), 'map ' + key)
    close(export['groundWorldZM'], site['groundWorldZM'], 'road plane')
    revision = export.get('calibrationRevision')
    require(isinstance(revision, str) and revision, 'Missing new calibration revision')
    profile = json.loads((directory / 'active.json').read_text())
    require(profile.get('schemaVersion') == 'city.mv3dt-demo.v1' and profile.get('siteId') == site['id']
            and profile.get('cameraOrder') == order, 'Demo profile identity differs')
    files = {}
    for relative, expected in profile['fileHashes'].items():
        require(relative.startswith(PREFIX) and '..' not in Path(relative).parts, 'Invalid pinned config path')
        name = relative[len(PREFIX):]
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(directory.resolve())
                and path.stat().st_size <= 1024 * 1024, 'Invalid pinned config file')
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected, 'Pinned demo config changed: ' + name)
        files[name] = data
    require('package.json' in files and profile['trackerConfig'] in profile['fileHashes'], 'Incomplete pinned demo profile')
    package = json.loads(files['package.json'])
    require([c['sourceId'] for c in package['cameras']] == order, 'Package camera order differs')
    close(package['nativeProjectionPlaneWorldZM'], export['groundWorldZM'], 'native road plane')
    close(package['navigationWorldZM'], export['navigationWorldZM'], 'native person plane')
    manifest = json.loads((directory / 'manifest.json').read_text())
    tracker_size = manifest.get('trackerInputResolution')
    require(tracker_size == [640, 384], 'Current worker requires 640x384 tracker calibration')
    tracker = yaml.safe_load(files[profile['trackerConfig'][len(PREFIX):]])
    paths = tracker['ObjectModelProjection']['cameraModelFilepath']
    require(len(paths) == 2, 'Tracker must have two ordered camera YAML paths')
    previous_revisions = {}
    scales = []
    for index, name in enumerate(CAMERAS):
        old, new = site['sources'][index], export['cameras'][name]
        require(old.get('calibrationRevision') == profile['cameraCalibrations'].get(old['id'])
                == package['cameras'][index].get('calibrationRevision'), 'Saved calibration identities disagree')
        require(old['calibrationRevision'] != revision, 'New resolution must have a new static export revision')
        previous_revisions[old['id']] = old['calibrationRevision']
        sx, sy = resized_camera(old, new)
        resized_camera(package['cameras'][index], new)
        scales.append([sx, sy])
        source = {**old, **new, 'calibrationRevision': revision, 'browserClockVerified': False}
        source.pop('processedPreview', None)
        site['sources'][index] = source
        camera = {**package['cameras'][index], **new, 'calibrationRevision': revision}
        # These remain simulator-derived algebraic landmarks, never a new
        # independent image/clock qualification for the resized source.
        for landmark in camera.get('landmarks', []):
            landmark['imagePx'] = [landmark['imagePx'][0] * sx, landmark['imagePx'][1] * sy]
            if 'errorPx' in landmark:
                landmark['errorPx'] *= max(sx, sy)
        camera['landmarkQualification'] = 'Resolution-scaled prior simulator algebraic landmarks; no independent new image measurement.'
        package['cameras'][index] = camera
        yaml_path = paths[index]
        require(yaml_path.startswith('/state/' + PREFIX), 'Tracker camera path escaped approved demo directory')
        yaml_name = yaml_path[len('/state/' + PREFIX):]
        require(yaml_name in files, 'Tracker camera YAML is not pinned')
        camera_yaml = yaml.safe_load(files[yaml_name])
        projected = scale_rows(new['projectionMatrix3x4'], [tracker_size[0] / new['width'], tracker_size[1] / new['height'], 1])
        close(camera_yaml['projectionMatrix_3x4_w2p'], [v for row in projected for v in row], 'tracker projection')
        # A proportional source resize leaves tracker-space projection equal.
        # Preserve the byte-exact YAML and static modelInfo when that is true.
    require(len({tuple(s) for s in scales}) == 1, 'Both cameras must use the same resize ratio')
    require(len({(s['width'], s['height']) for s in site['sources']}) == 1, 'Both cameras must have equal dimensions')
    identifiers = [r['id'] for r in rules['rules']]
    require(len(set(identifiers)) == len(identifiers), 'Duplicate rule IDs')
    for rule in rules['rules']:
        require(rule['sourceId'] in previous_revisions and rule['geometry']['space'] in ('image-normalized', 'site-metres'),
                'Unrecognized source or rule geometry')
        require(rule.get('calibrationRevision') in (None, previous_revisions[rule['sourceId']]), 'Rule already has a stale calibration binding')
        rule['calibrationRevision'] = revision
    config = mobility.get('config', mobility)
    for category, references in (('movements', ('entryRuleId', 'exitRuleId')), ('crossings', ('waitingRuleId', 'crossingRuleId')),
                                 ('queues', ('zoneRuleId',)), ('curbs', ('zoneRuleId',))):
        for row in config.get(category, []):
            require(all(row[key] in identifiers for key in references), 'A saved mobility measurement references a missing rule')
    package['calibrationRevision'] = revision
    profile['cameraCalibrations'] = {source_id: revision for source_id in order}
    files['package.json'] = (json.dumps(package, indent=2) + '\n').encode()
    profile['fileHashes'] = {PREFIX + name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    manifest['parentInputSha256'] = manifest.get('inputSha256')
    manifest['inputSha256'] = hashlib.sha256(files['package.json']).hexdigest()
    manifest['calibrationRevision'] = revision
    manifest.update(enabled=False, runtimeQualified=False, transportClockQualified=False, diagnosticOnly=True)
    old_evidence = {key: manifest.pop(key) for key in ('maximumSourceSkewMs', 'maximumReprojectionErrorPx', 'timingEvidenceSha256') if key in manifest}
    manifest['previousMeasurementEvidence'] = old_evidence
    summary = {'schemaVersion': 'city.isaac-resolution-migration.v1', 'candidateOnly': True, 'runtimeChanged': False,
        'previousCalibrationRevisions': previous_revisions, 'newCalibrationRevision': revision,
        'newResolution': [site['sources'][0]['width'], site['sources'][0]['height']], 'scale': scales[0],
        'cameraOrder': order, 'rulesPreserved': len(identifiers),
        'mobilityCounts': {key: len(config.get(key, [])) for key in ('movements', 'queues', 'crossings', 'curbs')},
        'trackerProjectionUnchanged': True, 'trackerInputResolution': tracker_size,
        'trackerAndTopicsPreserved': True, 'productionQualified': False,
        'applyNote': 'Root must pause both sources, refresh current site/rule expectedRevision immediately before PUT, apply site then all rules, retain mobility config, install reviewed demo files, render/recreate gateway allowlist, and resume in camera order. Source history resets; no new timing/accuracy qualification.'}
    manifest['resolutionMigration'] = summary
    site.pop('expectedRevision', None)
    rules.pop('expectedRevision', None)
    return {'site': site, 'rules': rules, 'mobility': config, 'export': export, 'profile': profile,
            'files': files, 'manifest': manifest, 'summary': summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('site', 'rules', 'mobility', 'camera-package', 'registration', 'demo-directory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = prepare(*(json.loads(path.read_text()) for path in (args.site, args.rules, args.mobility, args.camera_package, args.registration)), args.demo_directory)
    require(not args.output.exists(), 'Output must be a new review directory; no overwrite allowed')
    args.output.mkdir(parents=True)
    for name in ('site', 'rules', 'mobility', 'summary'):
        (args.output / (name + '.json')).write_text(json.dumps(result[name], indent=2) + '\n')
    demo = args.output / 'mv3dt-demo'
    demo.mkdir()
    for name, data in result['files'].items():
        target = demo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for name, value in (('active.json', result['profile']), ('manifest.json', result['manifest']), ('current-static-export.json', result['export'])):
        (demo / name).write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
