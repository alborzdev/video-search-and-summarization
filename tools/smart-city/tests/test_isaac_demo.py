# SPDX-License-Identifier: Apache-2.0
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('isaac_demo_under_test', Path(__file__).parents[1] / 'isaac_demo.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def native_stream():
    return {'backend': 'native', 'attached': True, 'n_cameras': 2, 'generation': 1,
        'urls': [{'cam': name, 'mount': '/' + name, 'port': 18560 + i} for i, name in enumerate(m.CAMERA_IDS)],
        'cameras': [{'id': name, 'prim_path': '/World/SmartCity/Cameras/' + name} for name in m.CAMERA_IDS],
        'streams': {name: {'attached': True, 'server': True, 'failed': False, 'pushed': 30,
            'frames': 90, 'first_error': None, 'swizzle_error': None} for name in m.CAMERA_IDS}}


def live_state():
    return {'loaded': True, 'streaming': True, 'playing': True, 'playbackReady': True, 'streamBusy': False,
        'stage': str(m.CITY / 'stages/smart_city_pilot.usda'), 'streams': native_stream()}


def preparation_receipt(*, verified=False, updates_enabled=True):
    extensions = ['isaacsim.robot_setup.virtual_gantry.ui', 'isaacsim.robot_setup.virtual_gantry']
    return {'schemaVersion': 'city.vss-viewport.v1', 'resolutionScale': .5,
        'updatesEnabled': updates_enabled, 'streamRenderProductCount': 0, 'ready': verified,
        'gantry': {'primCount': 0, 'requestedDisabled': extensions, 'requestedAtUpdate': 10,
            'verifiedAtUpdate': 11 if verified else 10, 'verifiedAfterUpdate': verified,
            'extensionsEnabled': dict.fromkeys(extensions, not verified)}}


@pytest.fixture(autouse=True)
def isolated_backend(monkeypatch):
    monkeypatch.setattr(m, 'configured_backend', lambda: 'native')
    monkeypatch.setattr(m, 'expected_tracking_architecture', lambda: None)
    monkeypatch.setattr(m, 'expected_source_clock_mode', lambda: 'source-rtcp')


def test_recorder_recovery_is_source_scoped_and_requires_verified_footage(monkeypatch):
    calls = []
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    def request(url, payload=None, token=None, **kwargs):
        calls.append((url, payload))
        if url.endswith('/a/status'): return {'recordingStatus': 'off'}
        if url.endswith('/b/status'): return {'recordingStatus': 'alwaysOn'}
        if 'lookbackSeconds=' in url: return {'questionReady': True}
        return {'recordingStatus': 'on'}
    monkeypatch.setattr(m, 'json_request', request)
    monkeypatch.setattr(m, 'wait_for', lambda check, *_: check() or (_ for _ in ()).throw(RuntimeError('not ready')))
    m.ensure_recordings()
    assert [payload for _, payload in calls if payload] == [
        {'streamId': 'a', 'action': 'stop', 'lookbackSeconds': 5},
        {'streamId': 'a', 'action': 'start', 'lookbackSeconds': 5}]
    assert sum('lookbackSeconds=' in url for url, _ in calls) == 2


def recording_runtime(monkeypatch, *, initial='off', late_off=False, ready_after=0, always_off=False):
    clock, calls, starts = [0.], [], {'a': 0, 'b': 0}
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    def request(url, payload=None, token=None, *, timeout=20):
        calls.append((clock[0], url, deepcopy(payload), timeout))
        assert 0 < timeout <= min(20, 60 - clock[0])
        if '/record/' in url:
            return {'recordingStatus': initial if url.endswith('/a/status') else 'on'}
        if payload:
            assert payload['lookbackSeconds'] == 5
            if payload['action'] == 'start': starts[payload['streamId']] += 1
            return {'recordingStatus': 'on' if payload['action'] == 'start' else 'off'}
        assert 'lookbackSeconds=5' in url
        if 'streamId=b&' in url:
            return {'recordingStatus': 'on', 'questionReady': True}
        off = always_off or (late_off and starts['a'] == 1)
        return {'recordingStatus': 'off' if off else 'on', 'questionReady': not off and clock[0] >= ready_after}
    monkeypatch.setattr(m, 'json_request', request)
    return clock, calls, starts


def test_recorder_late_off_recovers_once_after_settle_grace(monkeypatch):
    clock, calls, starts = recording_runtime(monkeypatch, late_off=True, ready_after=5)
    m.ensure_recordings()
    assert starts == {'a': 2, 'b': 0} and clock[0] == 5
    controls = [(at, payload['action']) for at, _, payload, _ in calls if payload]
    assert controls == [(0, 'stop'), (0, 'start'), (2, 'stop'), (2, 'start')]


def test_recorder_on_but_window_filling_never_restarts(monkeypatch):
    clock, calls, starts = recording_runtime(monkeypatch, ready_after=7)
    m.ensure_recordings()
    assert starts == {'a': 1, 'b': 0} and clock[0] == 7
    assert [payload['action'] for _, _, payload, _ in calls if payload] == ['stop', 'start']


def test_recorder_exhausted_retry_keeps_exact_five_second_guard_and_times_out(monkeypatch):
    clock, _, starts = recording_runtime(monkeypatch, always_off=True)
    with pytest.raises(RuntimeError, match='Timed out: Waiting for verified five-second recordings'):
        m.ensure_recordings()
    assert starts == {'a': 2, 'b': 0} and clock[0] == 60


def test_initially_on_recorders_are_read_only_while_windows_fill(monkeypatch):
    clock, calls, starts = recording_runtime(monkeypatch, initial='on', ready_after=3)
    m.ensure_recordings()
    assert starts == {'a': 0, 'b': 0} and clock[0] == 3
    assert not any(payload for _, _, payload, _ in calls)


def test_recording_initial_controls_share_total_sixty_second_budget(monkeypatch):
    clock, calls, starts = recording_runtime(monkeypatch)
    original = m.json_request
    def slow_request(url, payload=None, token=None, *, timeout=20):
        result = original(url, payload, token, timeout=timeout)
        clock[0] += min(15, timeout)
        return result
    monkeypatch.setattr(m, 'json_request', slow_request)
    with pytest.raises(RuntimeError, match='Timed out: Waiting for verified five-second recordings'):
        m.ensure_recordings()
    assert clock[0] == 60 and starts == {'a': 1, 'b': 0}
    assert len(calls) == 4


def test_fully_live_pipeline_requires_every_enabled_rule_at_current_revision(monkeypatch):
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    health = {'siteId': 'isaac-intersection-a', 'mode': 'live',
        'sources': [{'id': x, 'status': 'live'} for x in ('a', 'b')],
        'processedPreview': {'sources': [{'id': x, 'available': True} for x in ('a', 'b')]},
        'nativeAnalyticsStatus': {'operationalStatus': 'fresh', 'status': 'active', 'requestedRevision': 3, 'appliedRevision': 3, 'primitives': [{'ruleId': str(i), 'primitiveStatus': 'compiled'} for i in range(12)]}}
    rules = {'revision': 3, 'status': 'active', 'authority': 'city-behavior-analytics', 'rules': [{'id': str(i), 'enabled': True} for i in range(12)]}
    monkeypatch.setattr(m, 'json_request', lambda url: rules if url.endswith('/rules') else health)
    assert m.ready() == health
    health['nativeAnalyticsStatus']['primitives'].pop()
    assert m.ready() is False


@pytest.mark.parametrize('fault', [None, 'proof', 'counter', 'extra', 'basis', 'mode', 'browser', 'ack'])
def test_native_clock_readiness_requires_exact_public_proof_and_native_ack(monkeypatch, fault):
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    monkeypatch.setattr(m, 'expected_source_clock_mode', lambda: 'source-native-sei')
    health = {'siteId': 'isaac-intersection-a', 'mode': 'live', 'sources': [{'id': x, 'status': 'live'} for x in ('a', 'b')],
        'processedPreview': {'sources': [{'id': x, 'available': True} for x in ('a', 'b')]},
        'nativeAnalyticsStatus': {'operationalStatus': 'fresh', 'status': 'active', 'requestedRevision': 3, 'appliedRevision': 3,
            'sourceClockMode': 'source-native-sei', 'primitives': [{'ruleId': 'one', 'primitiveStatus': 'compiled'}]}}
    selected = [{'id': x, 'status': 'live', 'timestampBasis': 'source-native-sei', 'sourceClockMode': 'source-native-sei',
        'lastSourceTimeNs': '1792770000123456789', 'rawSourcePtsNs': '1234', 'browserClockVerified': False,
        'sourceClockEvidence': {'schemaVersion': 'city.source-native-sei.v1', 'method': 'isaac-native-sei-wall-capture',
            'correlation': 'exact-au-pts', 'captureTimeNs': '1792770000123456789', 'auPtsNs': '1234', 'frameCounter': '42'}} for x in ('a', 'b')]
    source = selected[0]
    if fault == 'proof': source['sourceClockEvidence']['auPtsNs'] = '1235'
    if fault == 'counter': source['sourceClockEvidence']['frameCounter'] = str(2**64)
    if fault == 'extra': source['sourceClockEvidence']['offsetNs'] = 597000000
    if fault == 'basis': source['timestampBasis'] = 'source-rtcp'
    if fault == 'mode': source['sourceClockMode'] = 'source-rtcp'
    if fault == 'browser': source['browserClockVerified'] = True
    if fault == 'ack': health['nativeAnalyticsStatus'].pop('sourceClockMode')
    rules = {'revision': 3, 'status': 'active', 'authority': 'city-behavior-analytics', 'rules': [{'id': 'one'}]}
    snapshot = {'siteId': health['siteId'], 'mode': 'live', 'sources': selected}
    monkeypatch.setattr(m, 'json_request', lambda url: rules if url.endswith('/rules') else snapshot if url.endswith('/snapshot') else health)
    assert m.ready() == (health if fault is None else False)


@pytest.mark.parametrize('running,available,starts', [(True, 21, False), (False, 25, True), (False, 23, True), (False, 19, False)])
def test_video_recovery_reuses_owned_container_and_respects_reserve(monkeypatch, running, available, starts):
    calls = []
    def command(*args):
        calls.append(args)
        data = {'Running': running} if args[:2] == ('docker', 'inspect') else {'availableGiB': available, 'reserveGiB': 20}
        return SimpleNamespace(stdout=json.dumps(data))
    monkeypatch.setattr(m, 'command', command)
    monkeypatch.setattr(m, 'json_request', lambda *_: [])
    monkeypatch.setattr(m, 'wait_for', lambda check, *_: check())
    if not running and available < 20:
        with pytest.raises(RuntimeError, match='reserve'): m.ensure_video_service()
    else:
        m.ensure_video_service()
    assert (('docker', 'start', 'vss-vios-streamprocessing') in calls) is starts


def test_start_waits_for_restarting_gateway_before_live_readiness(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    monkeypatch.setattr(m.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(m, 'bridge', live_state)
    monkeypatch.setattr(m, 'validate_saved_calibration', lambda *_: None)
    monkeypatch.setattr(m, 'wait_for_controller', lambda *_: pytest.fail('A fully ready demo must not require cold controller admission'))
    monkeypatch.setattr(m, 'analysis', lambda *_: pytest.fail('A ready pipeline must not be paused/restarted'))
    monkeypatch.setattr(m, 'command', lambda *_: pytest.fail('Gateway waiting must not start/recreate services'))
    checked = []
    monkeypatch.setattr(m, 'ensure_recordings', lambda: checked.append('footage'))
    calls = []
    health = {'status': 'ok', 'service': 'vss-city-analytics', 'siteId': 'isaac-intersection-a', 'mode': 'live',
        'sources': [{'id': x, 'status': 'live'} for x in ('a', 'b')],
        'processedPreview': {'sources': [{'id': x, 'available': True} for x in ('a', 'b')]},
        'nativeAnalyticsStatus': {'operationalStatus': 'fresh', 'status': 'active', 'requestedRevision': 3, 'appliedRevision': 3, 'primitives': [{'ruleId': str(i), 'primitiveStatus': 'compiled'} for i in range(12)]}}
    def request(url, *_args, **_kwargs):
        calls.append(url)
        if url.endswith('/rules'): return {'revision': 3, 'status': 'active', 'authority': 'city-behavior-analytics', 'rules': [{'id': str(i), 'enabled': True} for i in range(12)]}
        if url.endswith('/site'): return {'id': 'isaac-intersection-a'}
        if url.endswith('/detections'): return {'state': 'running'}
        assert url == m.GATEWAY + 'health'
        if len(calls) <= 2:
            raise ConnectionRefusedError('Gateway is restarting')
        return health
    monkeypatch.setattr(m, 'json_request', request)
    m.start()
    assert len(calls) == 7
    assert checked == ['footage']
    assert clock[0] == 2


def test_gateway_timeout_has_no_simulator_or_source_side_effects(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    monkeypatch.setattr(m, 'json_request', lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionRefusedError()))
    monkeypatch.setattr(m.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('No simulator command before gateway readiness'))
    monkeypatch.setattr(m, 'analysis', lambda *_: pytest.fail('No source mutation before gateway readiness'))
    with pytest.raises(RuntimeError, match='Timed out: Waiting for the Smart City analytics service'):
        m.start()
    assert clock[0] == 60


def test_status_reports_unavailable_gateway_without_hiding_simulator_state(monkeypatch, capsys):
    monkeypatch.setattr(m.sys, 'argv', ['isaac_demo.py', 'status'])
    monkeypatch.setattr(m, 'bridge', lambda: {'running': True, 'streaming': True})
    monkeypatch.setattr(m, 'ready', lambda: (_ for _ in ()).throw(ConnectionRefusedError('private upstream detail')))
    m.main()
    result = json.loads(capsys.readouterr().out)
    assert result['isaac'] == {'running': True, 'streaming': True}
    assert result['vssReady'] is False
    assert 'unavailable' in result['vssError']
    assert 'ConnectionRefusedError' in result['vssError']
    assert 'private upstream detail' not in result['vssError']


def test_status_keeps_normal_ready_shape(monkeypatch, capsys):
    monkeypatch.setattr(m.sys, 'argv', ['isaac_demo.py', 'status'])
    state = live_state()
    monkeypatch.setattr(m, 'bridge', lambda: state)
    monkeypatch.setattr(m, 'ready', lambda: {'status': 'ok'})
    m.main()
    assert json.loads(capsys.readouterr().out) == {'isaac': state, 'vssReady': True}


def analysis_response(action='resume', **updates):
    return {'action': action, 'sensorId': 'source-a', 'name': 'SW', 'analysisProfileId': 'smart-city',
        'detectionEnabled': True, 'state': 'active' if action == 'resume' else 'paused',
        'analysisActive': action == 'resume', 'steps': {'detection': True, 'embedding': True}, **updates}


@pytest.mark.parametrize('action', ['resume', 'pause'])
def test_analysis_requires_confirmed_state_from_canonical_agent(monkeypatch, action):
    response = analysis_response(action)
    calls = []
    def command(*args):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(response))
    monkeypatch.setattr(m, 'command', command)
    assert m.analysis({'id': 'source-a', 'name': 'SW'}, action) == response
    assert len(calls) == 1
    assert 'source-analysis' in calls[0]


@pytest.mark.parametrize('mode', ['on-demand', 'disabled'])
def test_resume_accepts_explicit_independent_indexing_policy_without_starting_embeddings(monkeypatch, mode):
    response = analysis_response(indexingPolicy=mode, indexingRequired=False,
        steps={'detection': True, 'embedding': False, 'embedding_resource': False, 'caption_resource': True})
    calls = []
    def command(*args):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(response))
    monkeypatch.setattr(m, 'command', command)
    assert m.analysis({'id': 'source-a', 'name': 'SW'}, 'resume') == response
    assert len(calls) == 1
    assert 'source-analysis' in calls[0]


@pytest.mark.parametrize('updates', [
    {}, {'indexingRequired': False}, {'indexingPolicy': 'on-demand'},
    {'indexingPolicy': 'continuous', 'indexingRequired': False},
    {'indexingPolicy': 'on-demand', 'indexingRequired': True},
    {'indexingPolicy': 'on-demand', 'indexingRequired': 0},
    {'indexingPolicy': 'on-demand', 'indexingRequired': 'false'},
    {'indexingPolicy': 'on-demand', 'indexingRequired': False, 'steps': {'detection': True}},
])
def test_resume_never_infers_indexing_independence_from_missing_or_inconsistent_fields(monkeypatch, updates):
    response = analysis_response(**{'steps': {'detection': True, 'embedding': False}, **updates})
    monkeypatch.setattr(m, 'command', lambda *_: SimpleNamespace(stdout=json.dumps(response)))
    monkeypatch.setattr(m, 'analysis_failure_detail', lambda *_: None)
    with pytest.raises(RuntimeError, match='Analysis resume failed'):
        m.analysis({'id': 'source-a', 'name': 'SW'}, 'resume')


def test_pause_still_requires_embedding_stop_receipt_with_on_demand_policy(monkeypatch):
    response = analysis_response('pause', indexingPolicy='on-demand', indexingRequired=False,
        steps={'detection': True, 'embedding': False})
    monkeypatch.setattr(m, 'command', lambda *_: SimpleNamespace(stdout=json.dumps(response)))
    with pytest.raises(RuntimeError, match='Analysis pause failed'):
        m.analysis({'id': 'source-a', 'name': 'SW'}, 'pause')


@pytest.mark.parametrize('updates', [
    {'sensorId': 'another-source'}, {'analysisProfileId': 'semantic-search'}, {'name': 'different'},
    {'action': 'pause'}, {'detectionEnabled': False}, {'analysisActive': False}, {'state': 'partial'},
    {'steps': {'detection': False, 'embedding': True}}, {'steps': {'embedding': True}},
    {'steps': {'detection': 'true', 'embedding': True}}, {'steps': {}},
])
def test_resume_rejects_partial_wrong_identity_or_missing_detector_without_retry(monkeypatch, updates):
    calls = []
    def command(*args):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(analysis_response(**updates)))
    monkeypatch.setattr(m, 'command', command)
    monkeypatch.setattr(m, 'analysis_failure_detail', lambda *_: 'Registered source CPU decode probe failed')
    with pytest.raises(RuntimeError):
        m.analysis({'id': 'source-a', 'name': 'SW'}, 'resume')
    assert len(calls) == 1  # No log-driven retries or service changes in the launcher.


@pytest.mark.parametrize('state,steps', [
    ('partial', {'detection': False, 'embedding': True}), ('paused', {'embedding': True}),
    ('paused', {'detection': True}),
])
def test_pause_partial_or_missing_detector_confirmation_is_rejected(monkeypatch, state, steps):
    response = analysis_response('pause', state=state, steps=steps)
    monkeypatch.setattr(m, 'command', lambda *_: SimpleNamespace(stdout=json.dumps(response)))
    with pytest.raises(RuntimeError, match='Analysis pause failed'):
        m.analysis({'id': 'source-a', 'name': 'SW'}, 'pause')


def test_resume_error_surfaces_only_fresh_source_scoped_sanitized_admission_detail(monkeypatch):
    calls = []
    response = analysis_response(state='partial', analysisActive=False,
        steps={'detection': False, 'embedding': True, 'embedding_resource': True})
    monkeypatch.setattr(m, 'command', lambda *_: SimpleNamespace(stdout=json.dumps(response)))
    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[:3] == ['docker', 'logs', '--since']
        assert args[3].endswith('+00:00')
        assert kwargs['timeout'] == 5
        return SimpleNamespace(returncode=0, stdout='', stderr='\n'.join([
            'Could not restore detection for another-source: RTVI-CV returned 422: {"detail":"unrelated"}',
            'Could not restore detection for source-a: RTVI-CV returned 422: {"detail":"Registered source CPU decode probe failed"}',
        ]))
    monkeypatch.setattr(m.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='HTTP 422: Registered source CPU decode probe failed'):
        m.analysis({'id': 'source-a', 'name': 'SW'}, 'resume')
    assert len(calls) == 1


def test_diagnostic_never_discloses_unexpected_details_or_accepts_other_source(monkeypatch):
    def run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout='', stderr='\n'.join([
            'Could not restore detection for other-source: RTVI-CV returned 422: {"detail":"Registered source CPU decode probe failed"}',
            'Could not restore detection for source-a: RTVI-CV returned 409: {"detail":"private rtsp://password@host"}',
        ]))
    monkeypatch.setattr(m.subprocess, 'run', run)
    detail = m.analysis_failure_detail('source-a', '2026-10-23T16:01:00Z')
    assert 'HTTP 409' in detail
    assert 'private' not in detail and 'password' not in detail and 'decode' not in detail
    assert m.analysis_failure_detail('absent-source', '2026-10-23T16:01:00Z') is None


def controller_health(entries=None, **updates):
    entries = [] if entries is None else entries
    return {'ready': True, 'stream-info': {'stream-info': entries},
        'capacity': {'maxSources': 2, 'registeredSources': len(entries), 'availableSources': 2 - len(entries)},
        **updates}


def test_wait_for_controller_requires_actual_identity_and_consistent_inventory(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def request(url, **kwargs):
        calls.append(url)
        assert kwargs['timeout'] == 5
        if len(calls) <= 2:
            raise ConnectionRefusedError()
        if url.endswith('/health'):
            return controller_health([{'camera_id': 'a', 'camera_name': 'SW', 'status': 'registered-stopped'}])
        assert url == m.CONTROLLER + '/openapi.json'
        return {'info': {'title': 'Local VSS Smart City source controller'}}
    monkeypatch.setattr(m, 'json_request', request)
    monkeypatch.setattr(m, 'command', lambda *_: pytest.fail('Readiness must not start services'))
    monkeypatch.setattr(m, 'analysis', lambda *_: pytest.fail('Readiness must not change sources'))
    m.wait_for_controller([{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    assert clock[0] == 2
    assert len(calls) == 4


@pytest.mark.parametrize('health,title', [
    (controller_health(ready=False), 'Local VSS Smart City source controller'),
    (controller_health(), 'Different service'),
    ({'ready': True}, 'Local VSS Smart City source controller'),
    (controller_health(capacity={'maxSources': 2, 'registeredSources': True, 'availableSources': 1}), 'Local VSS Smart City source controller'),
    (controller_health(capacity={'maxSources': 4, 'registeredSources': 0, 'availableSources': 4}), 'Local VSS Smart City source controller'),
    (controller_health([{'camera_id': 'unrelated', 'camera_name': 'SW', 'status': 'running'}]), 'Local VSS Smart City source controller'),
    (controller_health([{'camera_id': 'a', 'camera_name': 'wrong-name', 'status': 'running'}]), 'Local VSS Smart City source controller'),
    (controller_health([{'camera_id': 'a', 'camera_name': 'SW', 'status': 'running'}] * 2), 'Local VSS Smart City source controller'),
])
def test_controller_unready_or_wrong_inventory_never_accepts_generic_http_success(monkeypatch, health, title):
    clock = [0.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(m, 'json_request', lambda url, **_: health if url.endswith('/health') else {'info': {'title': title}})
    with pytest.raises(RuntimeError, match='Timed out: Waiting for the Smart City source controller'):
        m.wait_for_controller([{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    assert clock[0] == 60


def test_start_controller_timeout_precedes_all_source_and_simulator_mutations(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    monkeypatch.setattr(m, 'wait_for_gateway', lambda: None)
    monkeypatch.setattr(m, 'validate_saved_calibration', lambda *_: None)
    calls = []
    def run(args, **_):
        calls.append(args)
        assert args == ['systemctl', '--user', 'is-active', '--quiet', m.WORKSPACE_SERVICE]
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(m.subprocess, 'run', run)
    def request(url, **_):
        if url == m.GATEWAY + 'site':
            return {'id': 'isaac-intersection-a'}
        assert url == m.CONTROLLER + '/api/v1/health'
        raise ConnectionRefusedError()
    monkeypatch.setattr(m, 'json_request', request)
    monkeypatch.setattr(m, 'analysis', lambda *_: pytest.fail('No initial or rollback source pause before controller readiness'))
    monkeypatch.setattr(m, 'command', lambda *_: pytest.fail('No service mutations before controller readiness'))
    with pytest.raises(RuntimeError, match='Timed out: Waiting for the Smart City source controller'):
        m.start()
    assert len(calls) == 1 and clock[0] == 60


def test_start_tolerates_active_isaac_unit_before_bridge_is_serving(monkeypatch):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    monkeypatch.setattr(m, 'wait_for_gateway', lambda: None)
    monkeypatch.setattr(m, 'validate_saved_calibration', lambda *_: None)
    monkeypatch.setattr(m, 'json_request', lambda *_: {'id': 'isaac-intersection-a', 'state': 'running'})
    monkeypatch.setattr(m.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    def bridge():
        calls.append('bridge')
        if len(calls) < 3:
            raise ConnectionRefusedError('Isaac unit is still booting')
        return live_state()
    monkeypatch.setattr(m, 'bridge', bridge)
    monkeypatch.setattr(m, 'ready', lambda: True)
    monkeypatch.setattr(m, 'ensure_recordings', lambda: calls.append('footage'))
    monkeypatch.setattr(m, 'wait_for_controller', lambda *_: pytest.fail('Already-ready path needs no cold admission'))
    monkeypatch.setattr(m, 'analysis', lambda *_: pytest.fail('Booting ready unit must not change sources'))
    monkeypatch.setattr(m, 'command', lambda *_: pytest.fail('Booting ready unit must not restart services'))
    m.start()
    assert calls == ['bridge', 'bridge', 'bridge', 'footage'] and clock[0] == 2


@pytest.mark.parametrize('failed_sources', [{'a'}, {'a', 'b'}])
def test_stop_attempts_both_owned_sources_and_isaac_despite_partial_cleanup(monkeypatch, failed_sources, capsys):
    calls = []
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    def analysis(source, action):
        calls.append((source['id'], action))
        if source['id'] in failed_sources:
            raise RuntimeError('Agent returned partial')
    monkeypatch.setattr(m, 'analysis', analysis)
    monkeypatch.setattr(m, 'command', lambda *args: calls.append(args))
    with pytest.raises(RuntimeError, match='Stop completed only partially'):
        m.stop()
    assert calls == [('a', 'pause'), ('b', 'pause'), ('systemctl', '--user', 'stop', m.WORKSPACE_SERVICE)]
    assert 'sources are paused' not in capsys.readouterr().out


def test_stop_reports_failed_service_stop_without_claiming_full_success(monkeypatch, capsys):
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a', 'name': 'SW'}, {'id': 'b', 'name': 'NE'}])
    monkeypatch.setattr(m, 'analysis', lambda *_: None)
    monkeypatch.setattr(m, 'command', lambda *_: (_ for _ in ()).throw(m.subprocess.CalledProcessError(1, ['systemctl'])))
    with pytest.raises(RuntimeError, match='Isaac service stop unconfirmed'):
        m.stop()
    assert 'sources are paused' not in capsys.readouterr().out


def mixed_rule_pipeline(monkeypatch):
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    rules = {'revision': 7, 'status': 'active', 'authority': 'city-behavior-analytics',
        'rules': [{'id': 'image-line', 'enabled': True, 'geometry': {'space': 'image-normalized'}},
            {'id': 'world-queue', 'enabled': True, 'geometry': {'space': 'site-metres'}},
            {'id': 'disabled', 'enabled': False, 'geometry': {'space': 'site-metres'}}]}
    health = {'siteId': 'isaac-intersection-a', 'mode': 'live',
        'sources': [{'id': x, 'status': 'live'} for x in ('a', 'b')],
        'processedPreview': {'sources': [{'id': x, 'available': True} for x in ('a', 'b')]},
        'nativeAnalyticsStatus': {'status': 'active', 'operationalStatus': 'fresh',
            'requestedRevision': 7, 'appliedRevision': 7,
            'primitives': [{'ruleId': 'image-line', 'primitiveStatus': 'compiled'},
                {'ruleId': 'world-queue', 'primitiveStatus': 'backend-only', 'reason': 'World geometry is evaluated by the backend'}]}}
    monkeypatch.setattr(m, 'json_request', lambda url: rules if url.endswith('/rules') else health)
    return health, rules


def test_ready_accepts_explicit_backend_only_world_rules_without_claiming_native_compile(monkeypatch):
    health, _ = mixed_rule_pipeline(monkeypatch)
    assert m.ready() == health
    health['association'] = {'mapFusion': {'enabled': True, 'available': True, 'qualified': False}}
    assert m.ready() == health  # Experimental map association does not alter rule authority.


def test_staged_ready_requires_current_architecture_shared_epoch_and_fresh_source_sessions(monkeypatch):
    health, rules = mixed_rule_pipeline(monkeypatch)
    snapshot = {'siteId': health['siteId'], 'mode': 'live', 'sources': deepcopy(health['sources'])}
    calls = []
    def request(url):
        calls.append(url)
        return snapshot if url.endswith('/snapshot') else rules if url.endswith('/rules') else health
    monkeypatch.setattr(m, 'json_request', request)
    monkeypatch.setattr(m, 'expected_tracking_architecture', lambda: 'nvdcf-local-then-mv3dt-v1')
    assert all(set(source) == {'id', 'status'} for source in health['sources'])
    assert m.ready() is False
    for source in snapshot['sources']:
        source.update(trackingArchitecture='nvdcf-local-then-mv3dt-v1', trackingMode='mv3dt-demo',
            fusionEpoch='fresh-fusion-epoch', sourceSessionId='new-' + source['id'])
    calls.clear()
    assert m.ready(excluded_source_sessions={'a': 'old-a', 'b': 'old-b'}) == health
    assert calls.count(m.GATEWAY + 'snapshot') == 1
    assert m.ready(excluded_source_sessions={'a': 'new-a', 'b': 'old-b'}) is False
    assert m.ready(excluded_source_sessions={'a': 'old-a'}) is False
    snapshot['sources'][1]['fusionEpoch'] = 'prior-epoch'
    assert m.ready() is False
    snapshot['sources'][1]['fusionEpoch'] = 'fresh-fusion-epoch'
    snapshot['sources'][1]['trackingArchitecture'] = None
    assert m.ready() is False


@pytest.mark.parametrize('case', ['site', 'mode', 'missing', 'duplicate', 'order', 'stale'])
def test_staged_ready_rejects_mismatched_current_snapshot_source_dto(monkeypatch, case):
    health, rules = mixed_rule_pipeline(monkeypatch)
    snapshot = {'siteId': health['siteId'], 'mode': 'live', 'sources': [
        {'id': sid, 'status': 'live', 'trackingArchitecture': 'nvdcf-local-then-mv3dt-v1',
         'trackingMode': 'mv3dt-demo', 'fusionEpoch': 'fresh', 'sourceSessionId': 'new-' + sid}
        for sid in ('a', 'b')]}
    if case == 'site': snapshot['siteId'] = 'other'
    elif case == 'mode': snapshot['mode'] = 'recorded-inference'
    elif case == 'missing': snapshot['sources'].pop()
    elif case == 'duplicate': snapshot['sources'][1] = deepcopy(snapshot['sources'][0])
    elif case == 'order': snapshot['sources'].reverse()
    else: snapshot['sources'][1]['status'] = 'stale'
    monkeypatch.setattr(m, 'json_request', lambda url:
        snapshot if url.endswith('/snapshot') else rules if url.endswith('/rules') else health)
    monkeypatch.setattr(m, 'expected_tracking_architecture', lambda: 'nvdcf-local-then-mv3dt-v1')
    assert m.ready() is False


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'unsupported', 'world-compiled', 'image-backend',
    'no-reason', 'backend-inactive', 'wrong-authority', 'old-request', 'old-ack', 'stale', 'missing-preview'])
def test_ready_rejects_unaccounted_rules_or_stale_pipeline(monkeypatch, case):
    health, rules = mixed_rule_pipeline(monkeypatch)
    native = health['nativeAnalyticsStatus']
    if case == 'missing': native['primitives'].pop()
    elif case == 'duplicate': native['primitives'].append(deepcopy(native['primitives'][0]))
    elif case == 'unsupported': native['primitives'][1]['primitiveStatus'] = 'unsupported'
    elif case == 'world-compiled': native['primitives'][1]['primitiveStatus'] = 'compiled'
    elif case == 'image-backend': native['primitives'][0].update(primitiveStatus='backend-only', reason='wrong space')
    elif case == 'no-reason': native['primitives'][1].pop('reason')
    elif case == 'backend-inactive': rules['status'] = 'pending'
    elif case == 'wrong-authority': rules['authority'] = 'native-only'
    elif case == 'old-request': native['requestedRevision'] = 6
    elif case == 'old-ack': native['appliedRevision'] = 6
    elif case == 'stale': native['operationalStatus'] = 'stale'
    else: health['processedPreview']['sources'].pop()
    assert m.ready() is False


def test_native_writer_readiness_uses_pushed_not_write_calls_or_software_fields():
    stream = native_stream()
    assert m.stream_progress(stream, expected_backend='native', minimum_frames=30)['frameCounts'] == {'cam_SW': 30, 'cam_NE': 30}
    stream['streams']['cam_SW']['pushed'] = 0
    with pytest.raises(RuntimeError, match='not produced'):
        m.stream_progress(stream, minimum_frames=30)


@pytest.mark.parametrize('field,value', [('server', False), ('attached', False), ('failed', True),
    ('first_error', 'encode failed'), ('swizzle_error', 'invalid colors'), ('error', 'stats failed'), ('pushed', True)])
def test_native_writer_failure_never_passes_readiness(field, value):
    stream = native_stream()
    stream['streams']['cam_NE'][field] = value
    with pytest.raises(RuntimeError):
        m.stream_progress(stream)


def test_status_does_not_claim_native_ready_for_other_attached_backend(monkeypatch, capsys):
    monkeypatch.setattr(m.sys, 'argv', ['isaac_demo.py', 'status'])
    state = live_state()
    state['streams']['backend'] = 'software'
    monkeypatch.setattr(m, 'bridge', lambda: state)
    monkeypatch.setattr(m, 'ready', lambda: {'status': 'ok'})
    m.main()
    assert json.loads(capsys.readouterr().out)['vssReady'] is False


@pytest.mark.parametrize('viewport_verified', [True, False])
def test_backend_cutover_reuses_calibration_rules_map_and_saved_registrations(monkeypatch, viewport_verified):
    sources = [{'id': 'saved-sw', 'name': 'SW'}, {'id': 'saved-ne', 'name': 'NE'}]
    site = {'id': 'isaac-intersection-a', 'revision': 42, 'sources': sources,
        'map': {'imageUrl': '/saved-map.png'}, 'fusion': {'profile': 'saved-mv3dt'}}
    before = deepcopy(site)
    state = live_state()
    state['streams']['backend'] = 'software'
    selected_backend = ['software']
    calls, validations = [], []
    monkeypatch.setattr(m, 'sources', lambda: sources)
    monkeypatch.setattr(m, 'wait_for_gateway', lambda: None)
    monkeypatch.setattr(m, 'wait_for_controller', lambda *_: None)
    monkeypatch.setattr(m.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(m, 'bridge', lambda: state)
    monkeypatch.setattr(m, 'json_request', lambda url: site)
    monkeypatch.setattr(m, 'validate_saved_calibration', lambda *args: validations.append(args))
    monkeypatch.setattr(m, 'ready', lambda: {'sources': sources, 'globalFusionEnabled': False})
    monkeypatch.setattr(m, 'wait_for', lambda check, *_: check())
    monkeypatch.setattr(m, 'analysis', lambda source, action: calls.append((source['id'], action)))
    monkeypatch.setattr(m, 'ensure_video_service', lambda: None)
    monkeypatch.setattr(m, 'ensure_recordings', lambda: calls.append('recordings'))
    monkeypatch.setattr(m, 'command', lambda *args: calls.append(tuple(str(arg) for arg in args)))
    def script(path, **defines):
        calls.append((path, defines))
        if path == 'scripts/tools/prepare_vss_viewport.py':
            assert state['loaded'] is True and state['streaming'] is False
            return {'result': preparation_receipt(verified=defines.get('ACTION') == 'verify', updates_enabled=viewport_verified)}
        assert path == 'scripts/tools/pilot_ext_driver.py'  # Never export/replace saved geometry on codec change.
        if defines['BTN'] == 'stop_stream': state['streaming'] = False
        elif defines['BTN'].startswith('rtsp:'):
            assert state['streaming'] is False
            selected_backend[0] = defines['BTN'].split(':', 1)[1]
        elif defines['BTN'] == 'start_stream':
            streams = native_stream()
            streams['backend'] = selected_backend[0]
            state.update(streaming=True, streams=streams)
    monkeypatch.setattr(m, 'script', script)
    if not viewport_verified:
        with pytest.raises(RuntimeError, match='viewport preparation was not confirmed'):
            m.start()
        assert not any(isinstance(call, tuple) and len(call) == 2 and call[1] == 'resume' for call in calls)
        assert not any(isinstance(call, tuple) and len(call) == 2 and isinstance(call[1], dict)
            and call[1].get('BTN') == 'start_stream' for call in calls)
        assert site == before
        return
    m.start()
    assert ('saved-sw', 'pause') in calls and ('saved-ne', 'pause') in calls
    assert calls[-3:] == [('saved-sw', 'resume'), ('saved-ne', 'resume'), 'recordings']
    assert site == before and len(validations) == 2
    assert selected_backend == ['native']
    prepare_index = calls.index(('scripts/tools/prepare_vss_viewport.py', {}))
    start_index = calls.index(('scripts/tools/pilot_ext_driver.py', {'ACTION': 'click', 'BTN': 'start_stream'}))
    verified_index = calls.index(('scripts/tools/prepare_vss_viewport.py', {'ACTION': 'verify', 'REQUESTED_AT_UPDATE': 10}))
    assert prepare_index < verified_index < start_index
    assert not any('isaac_site.py' in str(call) or 'isaac_mobility.py' in str(call) for call in calls)


@pytest.fixture
def saved_geometry(monkeypatch, tmp_path):
    monkeypatch.setattr(m, 'CITY', tmp_path)
    monkeypatch.setattr(m, 'ROOT', tmp_path / 'vss')
    (tmp_path / 'config').mkdir()
    (tmp_path / 'logs/vss-integration').mkdir(parents=True)
    profile = {'cameraIds': list(m.CAMERA_IDS), 'resolution': [1280, 720]}
    package = {'schemaVersion': 'city.isaac-camera-export.v1', 'cameraOrder': list(m.CAMERA_IDS),
        'stage': str(tmp_path / 'stages/smart_city_pilot.usda'), 'calibrationRevision': 'saved-rev',
        'cameras': {name: {'width': 1280, 'height': 720} for name in m.CAMERA_IDS}}
    (tmp_path / 'config/vss_camera_profile.json').write_text(json.dumps(profile))
    (tmp_path / 'logs/vss-integration/camera-map-export.json').write_text(json.dumps(package))
    registrations = [{'id': 'a'}, {'id': 'b'}]
    site = {'sources': [{'id': source['id'], 'width': 1280, 'height': 720, 'calibrationRevision': 'saved-rev'} for source in registrations]}
    return tmp_path, profile, package, registrations, site


def test_preserved_package_checks_resolution_stage_and_camera_prim_identity(saved_geometry):
    _, _, _, registrations, site = saved_geometry
    state = live_state()
    m.validate_saved_calibration(site, registrations, state)
    state['streams']['cameras'][1]['prim_path'] = '/World/OtherCamera'
    with pytest.raises(RuntimeError, match='camera prims'):
        m.validate_saved_calibration(site, registrations, state)


@pytest.mark.parametrize('change', ['profile-resolution', 'package-stage', 'package-revision', 'site-revision', 'site-resolution'])
def test_saved_geometry_mismatch_fails_before_reusing_calibration(saved_geometry, change):
    root, profile, package, registrations, site = saved_geometry
    if change == 'profile-resolution': profile['resolution'] = [1920, 1080]
    elif change == 'package-stage': package['stage'] = '/other/stage.usda'
    elif change == 'package-revision': package['calibrationRevision'] = None
    elif change == 'site-revision': site['sources'][0]['calibrationRevision'] = 'other'
    else: site['sources'][0]['width'] = 1920
    (root / 'config/vss_camera_profile.json').write_text(json.dumps(profile))
    (root / 'logs/vss-integration/camera-map-export.json').write_text(json.dumps(package))
    with pytest.raises(RuntimeError, match='calibration|resolution'):
        m.validate_saved_calibration(site, registrations)


def test_paused_source_reuses_only_matching_controller_calibration_archive(saved_geometry):
    root, _, _, registrations, site = saved_geometry
    archive = root / 'vss/.spark/city/controller-calibrations.json'
    archive.parent.mkdir(parents=True)
    archive.write_text(json.dumps({row['id']: row for row in site['sources']}))
    site['sources'] = []  # Normal post-pause site shape, not missing static geometry.
    m.validate_saved_calibration(site, registrations)
    archive.write_text(json.dumps({'a': {'width': 1280, 'height': 720, 'calibrationRevision': 'saved-rev'}}))
    with pytest.raises(RuntimeError, match='saved camera calibration'):
        m.validate_saved_calibration(site, registrations)


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'unrelated'])
def test_missing_or_wrong_source_identity_cannot_silently_reuse_geometry(saved_geometry, case):
    _, _, _, registrations, site = saved_geometry
    if case == 'missing': site['sources'].pop()
    elif case == 'duplicate': site['sources'][1] = deepcopy(site['sources'][0])
    else: site['sources'][1]['id'] = 'other-camera'
    with pytest.raises(RuntimeError, match='camera identities|saved camera calibration'):
        m.validate_saved_calibration(site, registrations)


def test_preparation_waits_for_normal_update_and_both_extension_readbacks(monkeypatch):
    clock, calls = [0.], []
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def script(path, **defines):
        calls.append((path, defines))
        if not defines:
            return {'result': preparation_receipt()}
        assert defines == {'ACTION': 'verify', 'REQUESTED_AT_UPDATE': 10}
        return {'result': preparation_receipt(verified=clock[0] >= 1)}
    monkeypatch.setattr(m, 'script', script)
    assert m.prepare_pre_stream()['ready'] is True
    assert len(calls) == 3 and clock[0] == 1


@pytest.mark.parametrize('invalid', ['same-update', 'ui-enabled', 'runtime-enabled', 'missing-readback', 'new-gantry'])
def test_preparation_never_accepts_early_or_incomplete_shutdown(monkeypatch, invalid):
    clock = [0.]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    receipt = preparation_receipt(verified=True)
    if invalid == 'same-update': receipt['gantry']['verifiedAtUpdate'] = 10
    elif invalid == 'ui-enabled': receipt['gantry']['extensionsEnabled']['isaacsim.robot_setup.virtual_gantry.ui'] = True
    elif invalid == 'runtime-enabled': receipt['gantry']['extensionsEnabled']['isaacsim.robot_setup.virtual_gantry'] = True
    elif invalid == 'missing-readback': receipt['gantry'].pop('extensionsEnabled')
    else: receipt['gantry']['primCount'] = 1
    monkeypatch.setattr(m, 'script', lambda path, **defines: {'result': receipt if defines else preparation_receipt()})
    with pytest.raises(RuntimeError, match='Timed out: Waiting for unused gantry'):
        m.prepare_pre_stream()
    assert clock[0] == 30


def test_fresh_frames_cannot_mask_an_exited_detector_during_warm_start(monkeypatch):
    monkeypatch.setattr(m, 'sources', lambda: [{'id': 'a'}, {'id': 'b'}])
    monkeypatch.setattr(m, 'wait_for_gateway', lambda: None)
    monkeypatch.setattr(m.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(m, 'bridge', live_state)
    monkeypatch.setattr(m, 'validate_saved_calibration', lambda *_: None)
    monkeypatch.setattr(m, 'json_request', lambda *_: {'id': 'isaac-intersection-a', 'state': 'stopped'})
    monkeypatch.setattr(m, 'ready', lambda: True)
    monkeypatch.setattr(m, 'ensure_recordings', lambda: pytest.fail('A dead detector cannot claim ready'))
    def cold(*_):
        raise RuntimeError('cold recovery reached')
    monkeypatch.setattr(m, 'wait_for_controller', cold)
    with pytest.raises(RuntimeError, match='cold recovery reached'):
        m.start()


def test_failed_city_load_reports_its_reason_without_waiting_another_deadline(monkeypatch):
    monkeypatch.setattr(m, 'bridge', lambda: {'loaded': False, 'loading': False, 'error': 'Pedestrian preparation failed'})
    with pytest.raises(m.CityLoadFailed, match='Pedestrian preparation failed'):
        m.wait_for(m.loaded_city, 'loading city', 210)

@pytest.mark.parametrize('stopped', [True, False])
def test_optional_embedding_pause_needs_independent_host_stop_proof(monkeypatch, stopped):
    response = analysis_response('pause', state='partial', indexingPolicy='on-demand', indexingRequired=False,
        steps={'detection': True, 'embedding': False})
    monkeypatch.setattr(m, 'command', lambda *_: SimpleNamespace(stdout=json.dumps(response)))
    monkeypatch.setattr(m, 'embedding_service_stopped', lambda: stopped)
    if stopped:
        assert m.analysis({'id':'source-a','name':'SW'}, 'pause') == response
    else:
        with pytest.raises(RuntimeError, match='Analysis pause failed'):
            m.analysis({'id':'source-a','name':'SW'}, 'pause')
