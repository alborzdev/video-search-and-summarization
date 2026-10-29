import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location('stable_ids', Path(__file__).parents[1] / 'prepare_mv3dt_stable_ids.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(root, *, update=None):
    prefix = m.PREFIX + 'original/'
    state = root / '.spark/city/state'
    directory = state / prefix
    directory.mkdir(parents=True)
    tracker = {'BaseConfig': {'checkClassMatch': 1, 'useBatchNumForFrameId': 1},
               'MultiViewAssociator': {'multiViewAssociatorType': 1,
                    'enableLatePeerReAssoc': 1, 'enableIDCorrection': 1,
                    'enableSeeThrough': 0, 'minPeerTrackletMatchScore': .5},
               'ReID': {'reidType': 0}, 'PoseEstimator': {'poseEstimatorType': 0},
               'ObjectModelProjection': {'objectModelType': 0, 'cameraModelFilepath':
                    ['/state/' + prefix + f'camera-{i}.yml' for i in range(2)]},
               'Communicator': {'communicatorType': 2,
                    'pubSubInfoConfigPath': '/state/' + prefix + 'pub-sub.yml',
                    'mqttProtoAdaptorConfigPath': '/state/' + prefix + 'mqtt.ini'}}
    if update:
        update(tracker)
    values = {'tracker-mv3dt.experimental.yml': yaml.safe_dump(tracker).encode(),
              'package.json': m.calibration.encoded({'siteId': 'isaac-intersection-a',
                    'calibrationRevision': 'cal-v1',
                    'cameras': [{'sourceId': 'sw'}, {'sourceId': 'ne'}]}),
              'manifest.json': m.calibration.encoded({'runtimeQualified': False, 'inputSha256': 'source'}),
              'pub-sub.yml': b'pubBrokerTopicStr: ["127.0.0.1:1883;/sw", "127.0.0.1:1883;/ne"]\n',
              'mqtt.ini': b'[message-broker]\nset-threaded=0\n',
              'camera-0.yml': b'camera: sw\n', 'camera-1.yml': b'camera: ne\n'}
    for name, value in values.items():
        (directory / name).write_bytes(value)
    (directory / 'current-static-export.json').write_bytes(m.calibration.encoded({'calibrationRevision': 'cal-v1'}))
    profile = {'schemaVersion': 'city.mv3dt-demo.v1', 'enabled': True,
               'siteId': 'isaac-intersection-a', 'cameraOrder': ['sw', 'ne'],
               'cameraCalibrations': {'sw': 'cal-v1', 'ne': 'cal-v1'},
               'imageId': 'sha256:' + 'a' * 64,
               'trackerConfig': prefix + 'tracker-mv3dt.experimental.yml',
               'fileHashes': {prefix + k: hashlib.sha256(v).hexdigest() for k, v in values.items()}}
    active = state / m.PREFIX / 'active.json'
    active.write_bytes(m.calibration.encoded(profile))
    return state, directory, active, tracker


def test_clone_changes_only_flags_paths_and_manifest(tmp_path):
    state, directory, active, original = fixture(tmp_path)
    before = {p: p.read_bytes() for p in state.rglob('*') if p.is_file()}
    r = m.prepare(tmp_path, 'trial-stable')
    assert all(p.read_bytes() == value for p, value in before.items())
    assert r['rollback'] == active.read_bytes()
    for name in m.FILES - {'tracker-mv3dt.experimental.yml', 'manifest.json'}:
        assert r['files'][name] == (directory / name).read_bytes()
    tracker = yaml.safe_load(r['files']['tracker-mv3dt.experimental.yml'])
    for key in ('enableLatePeerReAssoc', 'enableIDCorrection'):
        assert tracker['MultiViewAssociator'][key] == 0
    assert tracker['MultiViewAssociator']['minPeerTrackletMatchScore'] == .5
    assert tracker['ReID'] == original['ReID']
    assert tracker['PoseEstimator'] == original['PoseEstimator']
    assert r['profile']['imageId'] == 'sha256:' + 'a' * 64
    assert r['profile']['cameraCalibrations'] == {'sw': 'cal-v1', 'ne': 'cal-v1'}
    assert r['profile']['identityPolicyVariant']['name'] == m.VARIANT


def test_review_actual_loader_and_rollback(tmp_path):
    root = tmp_path / 'root'
    _, _, active, _ = fixture(root)
    r = m.prepare(root, 'trial-stable')
    output = tmp_path / 'review'
    m.write_review(output, r)
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['runtimeLoaderValidationPassed'] is True
    assert receipt['runtimeChanged'] is False
    assert len(receipt['candidateFileHashes']) == 7
    assert (output / 'rollback-active.json').read_bytes() == active.read_bytes()
    for name, expected in r['profile']['fileHashes'].items():
        assert m.calibration.sha((output / name).read_bytes()) == expected
    with pytest.raises(ValueError, match='new review'):
        m.write_review(output, r)


@pytest.mark.parametrize('name', ['original', '../escape', 'a/b', '.', 'x' * 101])
def test_reject_existing_or_escaping_snapshot(tmp_path, name):
    fixture(tmp_path)
    with pytest.raises(ValueError):
        m.prepare(tmp_path, name)


def test_reject_changed_pin(tmp_path):
    _, directory, _, _ = fixture(tmp_path)
    (directory / 'camera-0.yml').write_text('changed\n')
    with pytest.raises(ValueError, match='config changed'):
        m.prepare(tmp_path, 'trial')


@pytest.mark.parametrize('update', [
    lambda t: t['MultiViewAssociator'].update(enableIDCorrection=0),
    lambda t: t['MultiViewAssociator'].update(enableLatePeerReAssoc=True),
    lambda t: t['MultiViewAssociator'].update(enableSeeThrough=1),
    lambda t: t['ObjectModelProjection']['cameraModelFilepath'].reverse(),
    lambda t: t['Communicator'].update(mqttProtoAdaptorConfigPath='/state/other.ini'),
])
def test_reject_wrong_baseline_or_references(tmp_path, update):
    fixture(tmp_path, update=update)
    with pytest.raises(ValueError):
        m.prepare(tmp_path, 'trial')


def test_reject_export_calibration_change(tmp_path):
    _, directory, _, _ = fixture(tmp_path)
    (directory / 'current-static-export.json').write_text('{"calibrationRevision":"wrong"}')
    with pytest.raises(ValueError, match='calibration differs'):
        m.prepare(tmp_path, 'trial')
