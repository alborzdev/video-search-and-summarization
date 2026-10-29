# SPDX-License-Identifier: Apache-2.0
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_tracking_quality as m

spec = importlib.util.spec_from_file_location('quality_native_fixture', Path(__file__).with_name('test_prepare_mv3dt_native.py'))
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def fixture(root, monkeypatch):
    _, _, active, _ = parent.fixture(root)
    onnx = root/'.spark/city/models'/m.ONNX
    onnx.parent.mkdir(parents=True);onnx.write_bytes(b'fixture-onnx')
    monkeypatch.setattr(m, 'ONNX_SHA', hashlib.sha256(onnx.read_bytes()).hexdigest())
    trial = root/'completed-trial';trial.mkdir()
    engine = trial/'bodypose.onnx_b1_gpu0_fp16.engine';engine.write_bytes(b'fixture-engine')
    (trial/'bodypose.onnx').write_bytes(onnx.read_bytes())
    (trial/'receipt.json').write_text(json.dumps(dict(result='complete')))
    (trial/'tracker.yml').write_text(yaml.safe_dump(dict(PoseEstimator=dict(operateOnClassIds=[0], poseInferenceInterval=-1))))
    return active, engine


@pytest.mark.parametrize('confidence', [.5, .75, .925])
def test_pins_assets_and_preserves_raw_classes_and_one_native_stage(tmp_path, monkeypatch, confidence):
    active, engine = fixture(tmp_path, monkeypatch)
    before = active.read_bytes()
    result = m.prepare(tmp_path, 'quality', 'sha256:'+'b'*64, engine, confidence)
    assert active.read_bytes() == before
    assert result['profile']['trackingClassPolicy'] == 'car-truck-family-v1'
    assert result['profile']['trackingArchitecture'] == 'mv3dt-native-v1'
    assert 'localTrackerConfig' not in result['profile']
    assert result['profile']['auxiliaryModelAssets'][m.ENGINE]['sha256'] == hashlib.sha256(engine.read_bytes()).hexdigest()
    for name in ('tracker-mv3dt.experimental.yml','tracker-single-0.yml','tracker-single-1.yml'):
        tracker = yaml.safe_load(result['files'][name])
        assert tracker['BaseConfig']['checkClassMatch'] == 1
        assert tracker['PoseEstimator']['operateOnClassIds'] == [0]
        assert tracker['PoseEstimator']['modelEngineFile'] == '/models/'+m.ENGINE
        assert tracker['ObjectModelProjection']['minPoseConfidence'] == confidence
    m.native.write_review(tmp_path/'review', result)
    assert json.loads((tmp_path/'review/receipt.json').read_text())['runtimeLoaderValidationPassed']


@pytest.mark.parametrize('change', ['unfinished','wrong-onnx','all-classes','wrong-interval'])
def test_rejects_incomplete_or_incompatible_pose_trials(tmp_path, monkeypatch, change):
    active, engine = fixture(tmp_path, monkeypatch)
    before = active.read_bytes()
    if change == 'unfinished':
        (engine.parent/'receipt.json').write_text(json.dumps(dict(result='failed')))
    if change == 'wrong-onnx':
        (engine.parent/'bodypose.onnx').write_bytes(b'changed')
    if change in ('all-classes','wrong-interval'):
        pose = dict(operateOnClassIds=[] if change=='all-classes' else [0], poseInferenceInterval=0 if change=='wrong-interval' else -1)
        (engine.parent/'tracker.yml').write_text(yaml.safe_dump(dict(PoseEstimator=pose)))
    with pytest.raises(ValueError, match='completed person-only trial'):
        m.prepare(tmp_path,'quality','sha256:'+'b'*64,engine,.75)
    assert active.read_bytes() == before
    assert not (tmp_path/'.spark/city/models'/m.ENGINE).exists()
