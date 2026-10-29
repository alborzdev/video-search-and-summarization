# SPDX-License-Identifier: Apache-2.0
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

spec = importlib.util.spec_from_file_location('isaac_resolution', Path(__file__).parents[1] / 'isaac_resolution.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(tmp_path, size=(960, 540)):
    camera = {'width': 1280, 'height': 720, 'calibrationRevision': 'old',
        'K': [[640, 0, 640], [0, 640, 360], [0, 0, 1]],
        'projectionMatrix3x4': [[640, 0, 640, 0], [0, 640, 360, 0], [0, 0, 1, 1]],
        'T_cv_from_site': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        'imageToGroundHomography': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        'classImageToGroundHomographies': {'person': [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        'validGroundPolygon': [[0, 0], [1280, 0], [1280, 720], [0, 720]],
        'groundCoverageM': [[0, 0], [10, 0], [10, 10]], 'cameraPositionWorldM': [0, 0, 5],
        'lensModel': 'pinhole-rectified', 'classGroundPlaneWorldZM': {'person': .1}}
    source_ids = ['sw', 'ne']
    registration = {name: {'id': source_id} for name, source_id in zip(m.CAMERAS, source_ids)}
    site = {'id': 'isaac-intersection-a', 'mode': 'live', 'revision': 42, 'groundWorldZM': 0,
        'sources': [{**copy.deepcopy(camera), 'id': source_id, 'customOperatorField': 'preserve'} for source_id in source_ids],
        'map': {'bounds': [0, 0, 10, 10], 'roads': [], 'buildings': [], 'imageUrl': '/map.png'}}
    rules = {'revision': 25, 'rules': [{'id': f'rule-{i}', 'sourceId': source_ids[i % 2], 'calibrationRevision': 'old',
        'enabled': i != 5, 'geometry': {'space': 'image-normalized' if i < 6 else 'site-metres',
        'points': [[.1, .2], [.3, .2], [.3, .4]]}, 'conditions': {'minimumDurationMs': 1777}, 'revision': 25} for i in range(14)]}
    mobility = {'config': {'revision': 3, 'movements': [{'entryRuleId': 'rule-0', 'exitRuleId': 'rule-2'}],
        'queues': [{'zoneRuleId': 'rule-6', 'stopLine': [[1, 2], [3, 2]], 'upstreamPoint': [1, 5]}],
        'crossings': [{'waitingRuleId': 'rule-7', 'crossingRuleId': 'rule-9'}], 'curbs': [{'zoneRuleId': 'rule-10'}]}}
    package = {'siteId': site['id'], 'cameras': [{**copy.deepcopy(camera), 'sourceId': source_id,
        'landmarks': [{'worldM': [1, 2, 3], 'imagePx': [200, 400], 'errorPx': .2}]} for source_id in source_ids],
        'nativeProjectionPlaneWorldZM': 0, 'navigationWorldZM': .1, 'classGeometry': [{'saved': 'keep'}]}
    sx, sy = size[0] / 1280, size[1] / 720
    new = copy.deepcopy(camera)
    new.update(width=size[0], height=size[1])
    new.pop('calibrationRevision')
    for key in ('K', 'projectionMatrix3x4'):
        new[key] = m.scale_rows(new[key], [sx, sy, 1])
    new['imageToGroundHomography'] = [[r[0] / sx, r[1] / sy, r[2]] for r in new['imageToGroundHomography']]
    new['classImageToGroundHomographies']['person'] = copy.deepcopy(new['imageToGroundHomography'])
    new['validGroundPolygon'] = [[x * sx, y * sy] for x, y in new['validGroundPolygon']]
    export = {'schemaVersion': 'city.isaac-camera-export.v1', 'calibrationRevision': 'new',
        'cameraOrder': list(m.CAMERAS), 'cameras': {name: copy.deepcopy(new) for name in m.CAMERAS},
        'map': copy.deepcopy(site['map']), 'groundWorldZM': 0, 'navigationWorldZM': .1}
    tmp_path.mkdir(exist_ok=True)
    files = {'package.json': json.dumps(package).encode(),
        'tracker.yml': yaml.safe_dump({'ObjectModelProjection': {'cameraModelFilepath': ['/state/native/mv3dt-demo/' + f'camera-{i}.yml' for i in range(2)]},
            'MultiViewAssociator': {'enableSeeThrough': 0}}).encode(),
        'pub-sub.yml': b'pubBrokerTopicStr: ["127.0.0.1:1883;saved-topic"]\n'}
    for i in range(2):
        files[f'camera-{i}.yml'] = yaml.safe_dump({'projectionMatrix_3x4_w2p': [v for row in m.scale_rows(camera['projectionMatrix3x4'], [.5, 384 / 720, 1]) for v in row], 'modelInfo': [{'height': 2, 'radius': .3}]}).encode()
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    profile = {'schemaVersion': 'city.mv3dt-demo.v1', 'siteId': site['id'], 'cameraOrder': source_ids,
        'cameraCalibrations': dict.fromkeys(source_ids, 'old'), 'enabled': True, 'imageId': 'sha256:' + 'a' * 64,
        'trackerConfig': m.PREFIX + 'tracker.yml', 'fileHashes': {m.PREFIX + name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    (tmp_path / 'active.json').write_text(json.dumps(profile))
    (tmp_path / 'manifest.json').write_text(json.dumps({'trackerInputResolution': [640, 384],
        'transportClockQualified': True, 'runtimeQualified': True, 'maximumSourceSkewMs': 0}))
    return site, rules, mobility, export, registration, tmp_path


@pytest.mark.parametrize('size', [(960, 540), (640, 360)])
def test_resize_preserves_all_rules_mobility_topics_and_input(tmp_path, size):
    args = fixture(tmp_path, size)
    before = copy.deepcopy(args[:5])
    files_before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = m.prepare(*args)
    assert args[:5] == before
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == files_before
    assert result['mobility'] == before[2]['config']
    assert len(result['rules']['rules']) == 14
    for old, new in zip(before[1]['rules'], result['rules']['rules']):
        assert new == {**old, 'calibrationRevision': 'new'}
    for name in ('camera-0.yml', 'camera-1.yml', 'tracker.yml', 'pub-sub.yml'):
        assert result['files'][name] == files_before[name]
    assert result['site']['sources'][0]['customOperatorField'] == 'preserve'
    assert result['site']['map']['imageUrl'] == '/map.png'
    assert result['manifest']['runtimeQualified'] is False
    assert result['manifest']['transportClockQualified'] is False
    assert result['manifest']['previousMeasurementEvidence']['maximumSourceSkewMs'] == 0
    for relative, sha in result['profile']['fileHashes'].items():
        assert sha == hashlib.sha256(result['files'][relative[len(m.PREFIX):]]).hexdigest()


@pytest.mark.parametrize('mutation', ['pose', 'lens', 'person-plane', 'person-h', 'crop', 'source-order', 'rule-source', 'missing-rule', 'clock-pin'])
def test_rejects_unsafe_or_unrelated_changes(tmp_path, mutation):
    args = fixture(tmp_path)
    site, rules, mobility, export, registration, directory = args
    camera = export['cameras']['cam_SW']
    if mutation == 'pose': camera['T_cv_from_site'][0][3] += 1
    elif mutation == 'lens': camera['lensModel'] = 'unrectified'
    elif mutation == 'person-plane': camera['classGroundPlaneWorldZM']['person'] += .1
    elif mutation == 'person-h': camera['classImageToGroundHomographies']['person'][0][2] += 1
    elif mutation == 'crop': camera['K'][0][2] += 1
    elif mutation == 'source-order': site['sources'].reverse()
    elif mutation == 'rule-source': rules['rules'][0]['sourceId'] = 'other'
    elif mutation == 'missing-rule': mobility['config']['curbs'][0]['zoneRuleId'] = 'missing'
    elif mutation == 'clock-pin': (directory / 'pub-sub.yml').write_text('changed')
    with pytest.raises(ValueError):
        m.prepare(*args)


def test_rejects_wrong_tracker_projection_even_when_rehashed(tmp_path):
    args = fixture(tmp_path)
    path = tmp_path / 'camera-0.yml'
    value = yaml.safe_load(path.read_text())
    value['projectionMatrix_3x4_w2p'][0] += 20
    path.write_text(yaml.safe_dump(value))
    profile = json.loads((tmp_path / 'active.json').read_text())
    profile['fileHashes'][m.PREFIX + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path / 'active.json').write_text(json.dumps(profile))
    with pytest.raises(ValueError, match='tracker projection'):
        m.prepare(*args)


def test_nonproportional_resize_rejected(tmp_path):
    with pytest.raises(ValueError, match='proportional'):
        m.prepare(*fixture(tmp_path, (960, 500)))
