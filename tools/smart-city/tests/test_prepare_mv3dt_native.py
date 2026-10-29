# SPDX-License-Identifier: Apache-2.0
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_mv3dt_native as m

spec = importlib.util.spec_from_file_location('native_parent_fixture', Path(__file__).with_name('test_prepare_mv3dt_stable_ids.py'))
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def fixture(root):
    def update(t):
        t['StateEstimator'] = {'stateEstimatorType': 3}
        t['VisualTracker'] = {'visualTrackerType': 2, 'vpiBackend4DcfTracker': 1}
        t['TrajectoryManagement'] = {'useUniqueID': 0}
        t['TargetManagement'] = {'outputVisibility': 1}
    state, directory, active, tracker = parent.fixture(root, update=update)
    topics = dict(pubBrokerTopicStr=['127.0.0.1:1883;/sw', '127.0.0.1:1883;/ne'],
        subPeerBrokerTopicStrs=[['127.0.0.1:1883;/ne'], ['127.0.0.1:1883;/sw']])
    (directory / 'pub-sub.yml').write_text(yaml.safe_dump(topics))
    for i in range(2):
        (directory / f'camera-{i}.yml').write_text(yaml.safe_dump(dict(modelInfo=[
            dict(classID=cls, height=1., radius=.5) for cls in range(6)])))
    profile = json.loads(active.read_bytes())
    profile['fileHashes'] = {p: hashlib.sha256((state / p).read_bytes()).hexdigest() for p in profile['fileHashes']}
    active.write_text(json.dumps(profile))
    return state, directory, active, tracker


def test_native_bundle_removes_extra_tracker_and_orders_each_single_camera(tmp_path):
    state, directory, active, _ = fixture(tmp_path)
    before = {p: p.read_bytes() for p in state.rglob('*') if p.is_file()}
    result = m.prepare(tmp_path, 'single-native', 'sha256:' + 'b' * 64)
    assert all(p.read_bytes() == value for p, value in before.items())
    profile = result['profile']
    assert profile['trackingArchitecture'] == 'mv3dt-native-v1'
    assert 'localTrackerConfig' not in profile
    assert yaml.safe_load(result['files']['tracker-mv3dt.experimental.yml'])['MultiViewAssociator']['enableMsgSync'] == 0
    assert not any('nvdcf-local' in p for p in profile['fileHashes'])
    for i, source in enumerate(profile['cameraOrder']):
        single = yaml.safe_load(result['files'][f'tracker-single-{i}.yml'])
        assert single['ObjectModelProjection']['cameraModelFilepath'] == [f'/state/{result["prefix"]}camera-{i}.yml']
        assert single['MultiViewAssociator']['enableMsgSync'] == 0
        assert single['ObjectModelProjection']['outputVisibility'] == 1
        assert single['TargetManagement']['outputVisibility'] == 1
        assert source in profile['singleCameraTrackerConfigs']
        assert yaml.safe_load(result['files'][f'pub-sub-single-{i}.yml'])['pubBrokerTopicStr'] == [
            yaml.safe_load((directory / 'pub-sub.yml').read_bytes())['pubBrokerTopicStr'][i]]
    m.write_review(tmp_path / 'review', result)
    assert (tmp_path / 'review/rollback-active.json').read_bytes() == active.read_bytes()
    receipt = json.loads((tmp_path / 'review/receipt.json').read_text())
    assert receipt['runtimeLoaderValidationPassed']
    assert receipt['generatorSha256'] == m.calibration.sha(Path(m.__file__).read_bytes())


def test_two_wheeler_gets_provisional_pinned_prior_in_both_cameras(tmp_path):
    _, _, active, _ = fixture(tmp_path)
    old = active.read_bytes()
    result = m.prepare(tmp_path, 'trafficcam', 'sha256:' + 'b' * 64, two_wheeler=True)
    assert active.read_bytes() == old
    for i in range(2):
        camera = yaml.safe_load(result['files'][f'camera-{i}.yml'])
        assert next(m for m in camera['modelInfo'] if m['classID'] == 6) == {
            'classID': 6, 'height': 1.0, 'radius': 0.5}
        path = result['prefix'] + f'camera-{i}.yml'
        assert result['profile']['fileHashes'][path] == m.calibration.sha(result['files'][f'camera-{i}.yml'])
    assert 'two-wheeler' in result['profile']['identityPolicyVariant']['classes']
    assert 'not calibrated' in result['profile']['identityPolicyVariant']['twoWheeler3dPrior']


def test_existing_two_wheeler_prior_survives_next_profile_preparation(tmp_path):
    state, directory, active, _ = fixture(tmp_path)
    for i in range(2):
        path = directory / f'camera-{i}.yml'
        camera = yaml.safe_load(path.read_text())
        camera['modelInfo'].append(dict(classID=6, height=1.5, radius=.3))
        path.write_text(yaml.safe_dump(camera))
    profile = json.loads(active.read_bytes())
    profile['fileHashes'] = {p: hashlib.sha256((state / p).read_bytes()).hexdigest() for p in profile['fileHashes']}
    active.write_text(json.dumps(profile))
    result = m.prepare(tmp_path, 'next', 'sha256:' + 'b' * 64, two_wheeler=True)
    for i in range(2):
        models = yaml.safe_load(result['files'][f'camera-{i}.yml'])['modelInfo']
        assert [model for model in models if model['classID'] == 6] == [dict(classID=6, height=1.5, radius=.3)]
    assert 'two-wheeler' in result['profile']['identityPolicyVariant']['classes']


@pytest.mark.parametrize('change', ['calibration-drift', 'missing-class', 'wrong-peer', 'wrong-estimator', 'pva'])
def test_native_preparation_refuses_invalid_parent_evidence(tmp_path, change):
    state, directory, active, tracker = fixture(tmp_path)
    if change == 'calibration-drift':
        (directory / 'camera-0.yml').write_text('changed')
    else:
        if change == 'missing-class': (directory / 'camera-0.yml').write_text('modelInfo: []')
        if change == 'wrong-peer': (directory / 'pub-sub.yml').write_text('pubBrokerTopicStr: [a,b]\nsubPeerBrokerTopicStrs: [[a],[b]]')
        if change == 'wrong-estimator': tracker['StateEstimator']['stateEstimatorType'] = 1
        if change == 'pva': tracker['VisualTracker']['vpiBackend4DcfTracker'] = 2
        if change in ('wrong-estimator', 'pva'):
            (directory / 'tracker-mv3dt.experimental.yml').write_text(yaml.safe_dump(tracker))
        value = json.loads(active.read_bytes())
        value['fileHashes'] = {p: hashlib.sha256((state / p).read_bytes()).hexdigest() for p in value['fileHashes']}
        active.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        m.prepare(tmp_path, 'native', 'sha256:' + 'b' * 64)
