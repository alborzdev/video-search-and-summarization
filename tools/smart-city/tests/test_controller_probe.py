"""CPU-only transport, readiness-retry and process-bound controls."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('city_probe_under_test', Path(__file__).parents[1] / 'controller.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def execute_probe(monkeypatch, outcomes, *, live=True):
    captures = []
    sleeps = []
    class Capture:
        def __init__(self, *_args):
            self.outcome = outcomes[len(captures)]
            self.released = False
            captures.append(self)
        def isOpened(self):
            return self.outcome != 'closed'
        def read(self):
            return (False, None) if self.outcome == 'no-frame' else (True, SimpleNamespace(shape=(720, 1280, 3)))
        def get(self, prop):
            return {1: 0 if self.outcome == 'bad-geometry' else (640 if self.outcome == 'mismatch' else 1280),
                    2: 720, 3: 10, 4: 100}[prop]
        def release(self):
            self.released = True
    cv = SimpleNamespace(VideoCapture=Capture, setNumThreads=lambda _: None, CAP_FFMPEG=1900,
        CAP_PROP_OPEN_TIMEOUT_MSEC=53, CAP_PROP_READ_TIMEOUT_MSEC=54, CAP_PROP_HW_ACCELERATION=50,
        VIDEO_ACCELERATION_NONE=0, CAP_PROP_FRAME_WIDTH=1, CAP_PROP_FRAME_HEIGHT=2,
        CAP_PROP_FPS=3, CAP_PROP_FRAME_COUNT=4)
    monkeypatch.setitem(sys.modules, 'cv2', cv)
    monkeypatch.setattr(sys, 'argv', ['probe', 'rtsp://registered/camera' if live else '/recording.mp4', 'live' if live else 'recorded'])
    monkeypatch.setattr(m.time, 'sleep', sleeps.append)
    # The child normally owns this variable; avoid changing the test runner's environment.
    monkeypatch.setenv('OPENCV_FFMPEG_CAPTURE_OPTIONS', '')
    return lambda: exec(m.OPENCV_PROBE, {}), captures, sleeps


@pytest.mark.parametrize('first', ['closed', 'no-frame'])
def test_live_retry_releases_first_capture_and_forces_tcp(monkeypatch, capsys, first):
    run, captures, sleeps = execute_probe(monkeypatch, [first, 'valid'])
    run()
    assert json.loads(capsys.readouterr().out) == {'width': 1280, 'height': 720}
    assert len(captures) == 2 and all(c.released for c in captures)
    assert sleeps == [2]
    assert m.os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'].endswith('|rtsp_transport;tcp')


def test_failed_live_retry_is_bounded_to_two_attempts(monkeypatch):
    run, captures, sleeps = execute_probe(monkeypatch, ['no-frame', 'no-frame'])
    with pytest.raises(ValueError, match='no decodable frame'):
        run()
    assert len(captures) == 2 and all(c.released for c in captures)
    assert sleeps == [2]


@pytest.mark.parametrize('failure', ['bad-geometry', 'mismatch'])
def test_invalid_calibration_geometry_is_never_retried(monkeypatch, failure):
    run, captures, sleeps = execute_probe(monkeypatch, [failure])
    with pytest.raises(ValueError):
        run()
    assert len(captures) == 1 and captures[0].released and sleeps == []


def test_recording_has_no_retry_or_tcp_option(monkeypatch, capsys):
    run, captures, sleeps = execute_probe(monkeypatch, ['valid'], live=False)
    run()
    assert json.loads(capsys.readouterr().out)['durationSeconds'] == 10
    assert m.os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] == 'protocol_whitelist;file,pipe'
    assert len(captures) == 1 and captures[0].released and sleeps == []
    run, captures, sleeps = execute_probe(monkeypatch, ['closed'], live=False)
    with pytest.raises(ValueError, match='did not open'):
        run()
    assert len(captures) == 1 and captures[0].released and sleeps == []


def test_entire_retry_child_keeps_existing_twenty_second_hard_bound(monkeypatch):
    calls = []
    monkeypatch.setattr(m.shutil, 'which', lambda _: None)
    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs['timeout'] == 20
        raise m.subprocess.TimeoutExpired(args, kwargs['timeout'])
    monkeypatch.setattr(m.subprocess, 'run', run)
    with pytest.raises(ValueError, match='bounded timeout'):
        m.HostRuntime(m.Settings()).probe('rtsp://registered/camera')
    assert len(calls) == 1  # Both capture attempts occur inside this one bounded child.


@pytest.mark.parametrize('live', [True, False])
def test_ffprobe_tcp_applies_only_to_live_inputs_before_url(monkeypatch, live):
    calls = []
    monkeypatch.setattr(m.shutil, 'which', lambda _: '/usr/bin/ffprobe')
    runtime = m.HostRuntime(m.Settings())
    def command(args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'streams': [{'width': 1280, 'height': 720}],
                                                              'format': {'duration': '10'}}))
    monkeypatch.setattr(runtime, 'command', command)
    uri = 'rtsp://registered/camera' if live else '/recording.mp4'
    assert runtime.probe(uri)['width'] == 1280
    args = calls[0]
    assert args[-1] == uri
    if live:
        assert args[args.index('-rtsp_transport') + 1] == 'tcp'
        assert args.index('-rtsp_transport') < len(args) - 1
    else:
        assert '-rtsp_transport' not in args
    assert args[args.index('-rw_timeout') + 1] == '5000000'


def test_controller_readiness_snapshots_process_during_concurrent_remove():
    class ConcurrentState:
        reads = 0
        runtime = SimpleNamespace(readiness=lambda margin: (margin == .5, 'checked'))
        @property
        def process(self):
            self.reads += 1
            return SimpleNamespace(poll=lambda: None) if self.reads == 1 else None
    state = ConcurrentState()
    assert m.CityController.readiness(state) == (True, 'checked')
    assert state.reads == 1


@pytest.mark.parametrize('kind', [None, 'recorded', 'healthy', 'failed'])
def test_explicit_scenario_recovery_only_restarts_failed_registered_live_worker(tmp_path, kind):
    calls = []
    runtime = SimpleNamespace(stop=lambda process: calls.append('stop'),
        start=lambda log, live: calls.append(('start', live)) or SimpleNamespace(poll=lambda: None))
    controller = m.CityController(m.Settings(root=tmp_path), runtime)
    controller.sources = {} if kind is None else {'one': {'kind': 'recorded' if kind == 'recorded' else 'live'}}
    controller.process = SimpleNamespace(poll=lambda: None if kind == 'healthy' else 1)
    controller._wait_cold_readiness = lambda: calls.append('guard')
    controller._configure = lambda: calls.append('configure')
    if kind in (None, 'recorded'):
        with pytest.raises(ValueError): controller.recover_analysis()
        assert calls == []
    else:
        assert controller.recover_analysis() is (kind == 'failed')
        assert calls == (['stop', 'guard', 'configure', ('start', True)] if kind == 'failed' else [])
