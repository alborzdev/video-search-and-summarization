"""CPU-only isolated probe preparation and immutable-input contracts."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

TOOLS = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('city_mv3dt_probe', TOOLS / 'mv3dt_probe.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def profile(tmp_path):
    state = tmp_path / '.spark/city/state'
    source = state / 'native/mv3dt'
    source.mkdir(parents=True)
    package = {'cameras': [{'sourceId': 'sw', 'width': 1280, 'height': 720}, {'sourceId': 'ne', 'width': 1280, 'height': 720}],
        'classGeometry': [{'class': name, 'shape': 'cylinder', 'heightM': 1.9 + i, 'radiusM': .26 + i} for i, name in enumerate(m.CLASSES)]}
    for name, value in [('package.json', package), ('manifest.json', {'enabled': False}), ('promotion-gates.json', {'falseMerges': 0})]:
        (source / name).write_text(json.dumps(value))
    (source / 'mqtt.ini').write_text('[message-broker]\nset-threaded=0\n')
    (source / 'pub-sub.yml').write_text(yaml.safe_dump({'pubBrokerTopicStr': ['127.0.0.1:18883;a', '127.0.0.1:18883;b'], 'subPeerBrokerTopicStrs': [['127.0.0.1:18883;b'], ['127.0.0.1:18883;a']]}))
    tracker = {'BaseConfig': {'checkClassMatch': 1}, 'ObjectModelProjection': {'objectModelType': 0, 'cameraModelFilepath': ['/state/native/mv3dt/camera-0.yml', '/state/native/mv3dt/camera-1.yml']},
        'MultiViewAssociator': {'enableSeeThrough': 1, 'enableMsgSync': 0, 'minPeerTrackletMatchScore': .5},
        'Communicator': {'communicatorType': 2, 'pubSubInfoConfigPath': 'old', 'mqttProtoAdaptorConfigPath': 'old'}}
    (source / 'tracker-mv3dt.experimental.yml').write_text(yaml.safe_dump(tracker))
    for i in range(2):
        (source / f'camera-{i}.yml').write_text(yaml.safe_dump({'projectionMatrix_3x4_w2p': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0],
            'modelInfo': [{'classID': j, 'height': 1.9 + j, 'radius': .26 + j} for j in range(len(m.CLASSES))]}))
    return state, source


@pytest.mark.parametrize('candidate', m.CANDIDATES)
def test_candidate_preserves_baseline_and_snapshots_inputs(profile, candidate):
    state, source = profile
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    run = source / ('probe-' + candidate)
    receipt = m.prepare_candidate(source, run, candidate, state)
    assert all((source / key).read_bytes() == value for key, value in before.items())
    assert receipt['runtimeQualified'] is False and receipt['globalOutputEnabled'] is False
    assert (run / 'promotion-gates.json').read_bytes() == before['promotion-gates.json']
    tracker = yaml.safe_load((run / 'tracker-mv3dt.experimental.yml').read_text())
    assert tracker['ObjectModelProjection']['cameraModelFilepath'][0].endswith(f'probe-{candidate}/camera-0.yml')
    assert (run / 'camera-0.yml').read_bytes() == before['camera-0.yml']
    assert receipt['staticClassModels'][0] == {'classID': 0, 'height': 1.9, 'radius': .26}
    if candidate == 'sv3dt-only':
        assert 'MultiViewAssociator' not in tracker and 'Communicator' not in tracker
        assert receipt['identityScope'] == 'camera-local-control'
    else:
        assert tracker['MultiViewAssociator']['enableSeeThrough'] == (0 if candidate == 'mv3dt-no-see-through' else 1)
        assert tracker['MultiViewAssociator']['minPeerTrackletMatchScore'] == .5
        topology = yaml.safe_load((run / 'pub-sub.yml').read_text())
        assert topology['pubBrokerTopicStr'][0] == topology['subPeerBrokerTopicStrs'][1][0]
        assert '/probe/' in topology['pubBrokerTopicStr'][0]
    with pytest.raises(FileExistsError):
        m.prepare_candidate(source, run, candidate, state)


def test_preparation_never_calls_docker_or_gpu_guard(profile, monkeypatch, capsys):
    state, source = profile
    monkeypatch.setattr(m, 'ROOT', state.parents[2])
    monkeypatch.setattr(sys, 'argv', ['probe', '--prepare-only', '--candidate', 'sv3dt-only'])
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Runtime action from CPU-only preparation')
    monkeypatch.setattr(m.subprocess, 'run', forbidden)
    monkeypatch.setattr(m.subprocess, 'check_output', forbidden)
    monkeypatch.setattr(m.manage, 'ensure_headroom', forbidden)
    m.main()
    assert json.loads(capsys.readouterr().out)['preparedOnly']


def test_recorded_input_mount_is_present_and_read_only(tmp_path):
    volumes = m.volume_args(tmp_path)
    assert str(tmp_path / '.spark/city/media') + ':/media:ro' in volumes
    assert str(tmp_path / '.spark/city/models') + ':/models:ro' in volumes


def test_bad_candidate_or_mismatched_camera_resolution_rejected(profile):
    state, source = profile
    with pytest.raises(ValueError, match='Unknown'):
        m.prepare_candidate(source, source / 'bad', 'unbounded-sweep', state)
    package = json.loads((source / 'package.json').read_text())
    package['cameras'][1]['height'] = 1080
    (source / 'package.json').write_text(json.dumps(package))
    with pytest.raises(ValueError, match='equal-resolution'):
        m.prepare_candidate(source, source / 'bad', 'baseline', state)
    assert not (source / 'bad').exists()


@pytest.mark.parametrize('mutation', ['camera-height', 'missing-class', 'nonfinite-radius'])
def test_static_geometry_drift_rejected_before_preparation(profile, mutation):
    state, source = profile
    if mutation == 'camera-height':
        path = source / 'camera-1.yml'
        camera = yaml.safe_load(path.read_text())
        camera['modelInfo'][0]['height'] += .1
        path.write_text(yaml.safe_dump(camera))
    else:
        path = source / 'package.json'
        package = json.loads(path.read_text())
        if mutation == 'missing-class':
            package['classGeometry'].pop()
        else:
            package['classGeometry'][0]['radiusM'] = float('nan')
        path.write_text(json.dumps(package))
    with pytest.raises(ValueError, match='static|Static'):
        m.prepare_candidate(source, source / 'bad', 'sv3dt-only', state)
    assert not (source / 'bad').exists()


def test_replay_provenance_preserves_order_and_pins_original_file_bytes(tmp_path):
    media = tmp_path / '.spark/city/media/paired'
    media.mkdir(parents=True)
    (media / 'first.mkv').write_bytes(b'first-original-file')
    (media / 'second.mkv').write_bytes(b'second-original-file')
    receipt = media / 'verification.json'
    receipt.write_text('{"alignmentQualified":false}')
    value = m.replay_provenance(tmp_path, ['sw=file:///media/paired/first.mkv', 'ne=file:///media/paired/second.mkv'], str(receipt))
    assert value['replayInputs'] == [
        {'sourceId': 'sw', 'containerUri': 'file:///media/paired/first.mkv', 'fileSha256': m.digest(media / 'first.mkv')},
        {'sourceId': 'ne', 'containerUri': 'file:///media/paired/second.mkv', 'fileSha256': m.digest(media / 'second.mkv')}]
    assert value['recordedClockVerificationSha256'] == m.digest(receipt)
    assert 'No clock is rewritten' in value['recordedClockVerificationNote']


def test_replay_provenance_rejects_escape_and_false_mixed_clock_claim(tmp_path):
    media = tmp_path / '.spark/city/media'
    media.mkdir(parents=True)
    outside = tmp_path / 'outside.mkv'
    outside.write_bytes(b'outside')
    (media / 'escape.mkv').symlink_to(outside)
    for uri in ('file:///media/escape.mkv', 'file:///media/%2e%2e/outside.mkv', 'file://host/media/x.mkv', 'file:///media/x.mkv?offset=1'):
        with pytest.raises(ValueError):
            m.replay_provenance(tmp_path, ['sw=' + uri])
    with pytest.raises(ValueError, match='two recorded'):
        m.replay_provenance(tmp_path, ['sw=rtsp://localhost/camera'], str(outside))


def test_replay_provenance_rejects_file_change_during_hashing(tmp_path, monkeypatch):
    media = tmp_path / '.spark/city/media'
    media.mkdir(parents=True)
    path = media / 'changing.mkv'
    path.write_bytes(b'before')
    def change(_path):
        path.write_bytes(b'after-and-longer')
        return 'not-an-immutable-hash'
    monkeypatch.setattr(m, 'digest', change)
    with pytest.raises(ValueError, match='changed while hashing'):
        m.replay_provenance(tmp_path, ['sw=file:///media/changing.mkv'])
