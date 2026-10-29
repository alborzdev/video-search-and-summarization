"""Fast CPU cancellation controls: no sockets, containers, models, or real waits."""
import argparse
import json
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import soak


@pytest.fixture
def observer(monkeypatch, tmp_path):
    clock = [0.0]
    marker = tmp_path / 'cancel'
    args = argparse.Namespace(root=tmp_path, device='spark', output_dir=tmp_path/'run',
        site_id='cpu-site', source_id=['a','b'], observations=tmp_path/'unused.ndjson',
        native_ack=tmp_path/'ack.json', duration_seconds=1800, ask_every_seconds=None,
        ask_timeout_seconds=55, sample_every_seconds=5, warmup_seconds=15,
        require_processed_preview=False, gateway_origin='http://unused', container=[],
        pause_on_failure=True, cancel_file=marker, clock_window_seconds=30,
        minimum_clock_ratio=.9, maximum_clock_ratio=1.1, maximum_duplicate_fraction=.05,
        trust_source_rtcp_utc=False, maximum_source_age_seconds=5)
    args.native_ack.write_text('{}')
    handlers = {}
    monkeypatch.setattr(soak.signal, 'signal', lambda sig, fn: handlers.__setitem__(sig, fn))
    monkeypatch.setattr(soak.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(soak.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    monkeypatch.setattr(soak, 'host_memory', lambda *_: {})
    monkeypatch.setattr(soak, 'json_request', lambda *_args, **_kwargs: {
        'siteId':'cpu-site', 'mode':'live', 'rulesRevision':1, 'nativeAnalyticsStatus':{},
        'sources':[{'id':sid, 'name':sid} for sid in ['a','b']]})
    monkeypatch.setattr(soak, 'container_state', lambda *_: pytest.fail('No real container requests'))
    monkeypatch.setattr(soak, 'ask_once', lambda *_: pytest.fail('No real model requests'))
    pauses = []
    monkeypatch.setattr(soak, 'pause_sources', lambda *_: pauses.append(True) or [])
    class Tail:
        counts = {'a':{'frames':20}, 'b':{'frames':20}}
        rotations = 0
        def __init__(self, *_): pass
        def read(self): return self.counts
        def close(self): pass
    monkeypatch.setattr(soak, 'FrameTail', Tail)
    class Checks:
        min_available=25
        max_age={};max_duplicate={};max_duplicate_post_warmup={};clock_ratios={'a':1,'b':1};previews=None
        def __init__(self, *_): pass
        def evaluate(self, sample):
            marker.touch()
            return {'nativeActive':True}
    monkeypatch.setattr(soak, 'Checks', Checks)
    return SimpleNamespace(args=args, marker=marker, clock=clock, pauses=pauses, handlers=handlers, Checks=Checks,
        receipt=lambda: json.loads((args.output_dir/'receipt.json').read_text()))


def test_existing_marker_cancels_before_any_observation_and_never_pauses(observer, monkeypatch):
    observer.marker.touch()
    monkeypatch.setattr(soak, 'FrameTail', lambda *_: pytest.fail('No frame reader after early cancellation'))
    assert soak.run(observer.args) == 1
    receipt=observer.receipt()
    assert receipt['passed'] is False and receipt['cancelled'] is True
    assert receipt['sampleCount'] == 0 and receipt['pauseReceipts'] == []
    assert receipt['cancellation']['pendingAskMayFinish'] is False
    assert observer.pauses == []


def test_marker_created_during_sample_preserves_sample_then_cancels_without_new_ask(observer):
    assert soak.run(observer.args) == 1
    receipt=observer.receipt()
    assert receipt['sampleCount'] == 1 and receipt['cancelled'] is True
    assert receipt['failure'] == 'monitor-cancelled-by-request'
    assert receipt['scheduledAskCount'] == 0 and observer.pauses == []
    progress=json.loads((observer.args.output_dir/'progress.json').read_text())
    assert progress['status'] == 'cancelled' and progress['passed'] is False


def test_real_failure_observed_in_same_sample_keeps_failure_pause_behavior(observer, monkeypatch):
    def fail(_self, _sample):
        observer.marker.touch()
        raise soak.SoakFailure('source-clock-stalled:a')
    monkeypatch.setattr(observer.Checks, 'evaluate', fail)
    assert soak.run(observer.args) == 1
    receipt=observer.receipt()
    assert receipt['cancelled'] is False and receipt['failure'] == 'source-clock-stalled:a'
    assert observer.pauses == [True]


def test_signal_interruption_retains_default_failure_pause_path(observer, monkeypatch):
    observer.args.cancel_file=None
    def interrupt(_self, _sample):
        observer.handlers[signal.SIGTERM]()
        return {'nativeActive':True}
    monkeypatch.setattr(observer.Checks, 'evaluate', interrupt)
    assert soak.run(observer.args) == 1
    assert observer.receipt()['failure'] == 'monitor-interrupted'
    assert observer.receipt()['cancelled'] is False and observer.pauses == [True]


def test_existing_inflight_ask_is_disclosed_and_not_claimed_cancelled(observer, monkeypatch):
    observer.args.ask_every_seconds=900
    monkeypatch.setattr(observer.Checks, 'evaluate', lambda *_: {'nativeActive':True})
    monkeypatch.setattr(soak.time, 'sleep', lambda _seconds: observer.clock.__setitem__(0, observer.clock[0]+900))
    calls=[]
    class Future:
        def done(self): return False
        def cancel(self): calls.append('cancel-attempt'); return False
    class Executor:
        def __init__(self, **_): pass
        def submit(self, *_):
            observer.marker.touch()
            calls.append('submitted')
            return Future()
        def shutdown(self, **kwargs):
            assert kwargs == {'wait':False, 'cancel_futures':True}
    monkeypatch.setattr(soak, 'ThreadPoolExecutor', Executor)
    assert soak.run(observer.args) == 1
    receipt=observer.receipt()
    assert receipt['cancelled'] is True and receipt['scheduledAskCount'] == 1
    assert receipt['cancellation']['askPendingAtCancellation'] is True
    assert receipt['cancellation']['pendingAskMayFinish'] is True
    assert calls == ['submitted','cancel-attempt'] and observer.pauses == []


def test_partial_pause_transport_success_is_not_confirmed_paused(monkeypatch):
    def request(url, payload=None, **_):
        if payload is None:
            return [{'sensorId':sid,'name':sid} for sid in ['a','b']]
        sid=url.rsplit('/',2)[-2]
        return {'sensorId':sid,'action':'pause','state':'partial' if sid=='a' else 'paused',
                'analysisActive':False,'steps':{'detection':sid!='a','embedding':True}}
    monkeypatch.setattr(soak,'json_request',request)
    receipts=soak.pause_sources(argparse.Namespace(source_id=['a','b'],vss_origin='http://unused',agent_origin='http://unused'))
    assert all(row['requestCompleted'] for row in receipts)
    assert [row['pauseConfirmed'] for row in receipts] == [False,True]


def test_cancel_file_is_optional_and_explicit_on_cli(monkeypatch, tmp_path):
    args=['soak.py','--site-id','cpu-site','--source-id','a','--source-id','b','--observations',str(tmp_path/'frames')]
    monkeypatch.setattr(sys,'argv',args)
    assert soak.arguments().cancel_file is None
    monkeypatch.setattr(sys,'argv',args+['--cancel-file',str(tmp_path/'cancel')])
    assert soak.arguments().cancel_file == tmp_path/'cancel'
