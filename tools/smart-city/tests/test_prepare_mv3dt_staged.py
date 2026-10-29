import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_mv3dt_staged as m

spec = importlib.util.spec_from_file_location('staged_parent_fixture', Path(__file__).with_name('test_prepare_mv3dt_stable_ids.py'))
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)


def fixture(root):
    state, directory, active, tracker = parent.fixture(root, update=lambda t:
        t['MultiViewAssociator'].update(enableLatePeerReAssoc=0, enableIDCorrection=0))
    local = root / 'ordinary-local.yml'
    local.write_text(yaml.safe_dump({'BaseConfig': {'checkClassMatch': 1},
        'StateEstimator': {'stateEstimatorType': 1}, 'VisualTracker': {'visualTrackerType': 2},
        'ReID': {'reidType': 0}, 'TrajectoryManagement': {'useUniqueID': 1, 'enableReAssoc': 0}}))
    return state, directory, active, tracker, local


def test_staged_preparation_separates_authorities_and_preserves_inputs(tmp_path):
    state, directory, active, original, local = fixture(tmp_path)
    before = {p: p.read_bytes() for p in state.rglob('*') if p.is_file()}
    r = m.prepare(tmp_path, 'staged', 'sha256:' + 'b' * 64, local)
    assert all(p.read_bytes() == value for p, value in before.items())
    assert r['rollback'] == active.read_bytes() and len(r['profile']['fileHashes']) == 8
    assert r['profile']['imageId'] == 'sha256:' + 'b' * 64
    assert r['profile']['trackingArchitecture'] == m.ARCHITECTURE
    assert r['files'][m.LOCAL_NAME] == local.read_bytes()
    second = yaml.safe_load(r['files']['tracker-mv3dt.experimental.yml'])
    assert second['MultiViewAssociator']['enableLatePeerReAssoc'] == 1
    assert second['MultiViewAssociator']['enableIDCorrection'] == 1
    assert second['ReID'] == original['ReID']
    for name in m.baseline.FILES - {'tracker-mv3dt.experimental.yml', 'manifest.json'}:
        assert r['files'][name] == (directory / name).read_bytes()
    assert r['receipt']['runtimeChanged'] is False


def test_review_validates_actual_runtime_loader_and_exact_rollback(tmp_path):
    root = tmp_path / 'root'
    _, _, active, _, local = fixture(root)
    r = m.prepare(root, 'staged', 'sha256:' + 'b' * 64, local)
    output = tmp_path / 'review'
    m.write_review(output, r)
    receipt = json.loads((output / 'receipt.json').read_text())
    assert receipt['runtimeLoaderValidationPassed'] is True
    assert len(receipt['candidateFileHashes']) == 8
    assert (output / 'rollback-active.json').read_bytes() == active.read_bytes()
    assert receipt['generatorSha256'] == m.calibration.sha(Path(m.__file__).read_bytes())


@pytest.mark.parametrize('section,key,value', [
    ('ReID', 'reidType', 2), ('StateEstimator', 'stateEstimatorType', 3),
    ('TrajectoryManagement', 'enableReAssoc', 1), ('TrajectoryManagement', 'useUniqueID', 0),
    ('MultiViewAssociator', 'multiViewAssociatorType', 1),
])
def test_local_shared_or_reid_config_rejected(tmp_path, section, key, value):
    _, _, _, _, local = fixture(tmp_path)
    config = yaml.safe_load(local.read_bytes())
    config.setdefault(section, {})[key] = value
    local.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        m.prepare(tmp_path, 'staged', 'sha256:' + 'b' * 64, local)


def test_changed_parent_pin_rejected_before_candidate(tmp_path):
    _, directory, _, _, local = fixture(tmp_path)
    (directory / 'camera-0.yml').write_text('changed\n')
    with pytest.raises(ValueError, match='config changed'):
        m.prepare(tmp_path, 'staged', 'sha256:' + 'b' * 64, local)
