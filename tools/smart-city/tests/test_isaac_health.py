# SPDX-License-Identifier: Apache-2.0
"""CPU-only stream/receipt controls; no Kit, RTSP or service calls."""
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('isaac_health_demo_dependency', TOOLS / 'isaac_demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
spec = importlib.util.spec_from_file_location('isaac_health_under_test', TOOLS / 'isaac_health.py')
m = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'isaac_demo': demo}):
    spec.loader.exec_module(m)


@pytest.fixture(autouse=True)
def selected_stage(monkeypatch):
    monkeypatch.setattr(m, 'selected_scene_stage', lambda: str(m.CITY / 'stages/smart_city_pilot.usda'))


def sample(backend='native', count=60):
    cameras = demo.CAMERA_IDS
    native = {name: {'attached': True, 'server': True, 'failed': False, 'pushed': count,
        'frames': 100000, 'first_error': None, 'swizzle_error': None} for name in cameras}
    stream = {'backend': backend, 'attached': True, 'n_cameras': 2, 'generation': 4,
        'urls': [{'cam': name} for name in cameras], 'streams': native,
        'stats': {'push_errors': 0, 'streams': {name: {'frame_id': count, 'encoderAlive': True, 'error': None} for name in cameras}}}
    state = {'loaded': True, 'playing': True, 'streaming': True, 'streamBusy': False,
        'stage': str(m.CITY / 'stages/smart_city_pilot.usda'), 'simTime': 1, 'streams': stream}
    actual = {'backend': backend, 'streamRenderProductCount': 2,
        'frameCounts': {name: count for name in cameras}, 'nativeStreams': deepcopy(native),
        'pendingFrames': None if backend == 'native' else {name: 0 for name in cameras},
        'maximumQueuedFramesPerCamera': None if backend == 'native' else 1}
    return state, actual


def test_health_requires_selected_scene_instead_of_original_pilot(monkeypatch):
    selected = str(m.CITY / 'stages/neighborhood/pedestrian-pocket-v3/smart_city_expo_pedestrian.usda')
    monkeypatch.setattr(m, 'selected_scene_stage', lambda: selected)
    state, actual = sample()
    with pytest.raises(RuntimeError, match='lifecycle mismatch'):
        m.delivery_sample(state, actual, 'native')
    state['stage'] = selected
    assert m.delivery_sample(state, actual, 'native')['backend'] == 'native'


def test_native_progress_uses_actual_handoffs_without_claiming_software_queue_bound():
    state, actual = sample()
    # Main-thread runtime and bridge samples can differ because they are sequential.
    actual['frameCounts']['cam_SW'] = 65
    result = m.delivery_sample(state, actual, 'native')
    assert result['frameCounts']['cam_SW'] == 65
    assert result['counterBasis'] == 'native-server-handoffs'
    assert result['maximumQueuedFramesPerCamera'] is None
    assert result['queueBoundStatus'] == 'unavailable-native-api'


@pytest.mark.parametrize('case', ['backend', 'products', 'missing-count', 'boolean-count', 'queue-claim',
    'server-dead', 'writer-detached', 'swizzle-failure', 'writer-error', 'extra-camera'])
def test_native_runtime_mismatch_or_failure_is_rejected(case):
    state, actual = sample()
    if case == 'backend': actual['backend'] = 'software'
    elif case == 'products': actual['streamRenderProductCount'] = 3
    elif case == 'missing-count': actual['frameCounts'].pop('cam_SW')
    elif case == 'boolean-count': actual['frameCounts']['cam_SW'] = True
    elif case == 'queue-claim': actual['maximumQueuedFramesPerCamera'] = 1
    elif case == 'server-dead': actual['nativeStreams']['cam_SW']['server'] = False
    elif case == 'writer-detached': actual['nativeStreams']['cam_SW']['attached'] = False
    elif case == 'swizzle-failure': actual['nativeStreams']['cam_SW']['swizzle_error'] = 'colors invalid'
    elif case == 'writer-error': actual['nativeStreams']['cam_SW'] = {'error': 'stats failed'}
    else: state['streams']['streams']['cam_SE'] = deepcopy(state['streams']['streams']['cam_SW'])
    with pytest.raises(RuntimeError):
        m.delivery_sample(state, actual, 'native')


def test_software_retains_real_one_frame_queue_guard():
    state, actual = sample('software')
    assert m.delivery_sample(state, actual, 'software')['maximumQueuedFramesPerCamera'] == 1
    actual['pendingFrames']['cam_SW'] = 2
    with pytest.raises(RuntimeError, match='one-frame'):
        m.delivery_sample(state, actual, 'software')


@pytest.mark.parametrize('failure', [None, 'generation', 'counter', 'no-progress', 'one-slow-sample'])
def test_monitor_native_receipt_and_progress_guards_are_backend_aware(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(m, 'CITY', tmp_path)
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/vss_runtime_policy.json').write_text(json.dumps({'isaacAvailableMemoryStopGiB': None}))
    out = tmp_path / 'receipt'
    monkeypatch.setattr(sys, 'argv', ['isaac_health.py', '--output', str(out), '--seconds', '60'])
    clock = [0.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda value: clock.__setitem__(0, clock[0] + value))
    monkeypatch.setattr(m.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(m, 'configured_backend', lambda: 'native')
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    monkeypatch.setattr(m, 'json_request', lambda *_: {'recordingStatus': 'on', 'questionReady': True})
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda *_: SimpleNamespace(free=64 * 1024**3))
    def current():
        count = 60 if failure == 'no-progress' else 60 + int(clock[0] * 10)
        state, actual = sample(count=count)
        state['simTime'] = 1 + clock[0]
        if clock[0] >= 5 and failure == 'generation': state['streams']['generation'] += 1
        if clock[0] >= 5 and failure == 'counter': actual['frameCounts']['cam_SW'] = 1
        return state, actual
    monkeypatch.setattr(m, 'bridge', lambda: current()[0])
    def script(*_args, **_kwargs):
        if failure == 'one-slow-sample': clock[0] += 60
        return {'result': current()[1]}
    monkeypatch.setattr(m, 'script', script)
    with pytest.raises(SystemExit) as exit_info:
        m.main()
    result = json.loads((out / 'receipt.json').read_text())
    assert result['passed'] is (failure is None)
    assert exit_info.value.code == (0 if failure is None else 1)
    assert result['criteria']['maximumQueuedFramesPerCamera'] is None
    assert result['criteria']['queueBoundStatus'] == 'unavailable-native-api'
    rows = [json.loads(line) for line in (out / 'samples.ndjson').read_text().splitlines()]
    assert all('encoderAlive' not in row['streams']['cam_SW'] for row in rows)
    if failure is None:
        assert result['samples'] == 12 and result['minimumRollingFps'] == {'cam_SW': 10., 'cam_NE': 10.}
    elif failure == 'generation': assert 'generation changed' in result['failure']
    elif failure == 'counter': assert 'went backward' in result['failure']
    elif failure == 'one-slow-sample': assert 'Insufficient camera samples' in result['failure']
    else: assert '5 FPS minimum' in result['failure']
