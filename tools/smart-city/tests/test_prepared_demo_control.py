"""Transaction tests: gate ordering, ownership, fresh tracking and automatic cleanup."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('prepared_demo_control', Path(__file__).parents[1] / 'demo_control.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Controlled(m.DemoControl):
    def __init__(self, path=None):
        self.now = 1000.
        super().__init__(clock=lambda: self.now, state_path=path)
        self.calls = []
        self.boundary = {'state': 'normal'}
        self.scene = {'state': 'idle', 'restored': True, 'normalFlowVerified': True, 'active': False,
                      'catalog': [{'id': 'queue-recovery', 'available': True}]}
        self.gate_failure = False
        self.native_prepare_failure = None
        self.native_cancel_failure = False

    def _bridge(self, operation='status', **kwargs):
        if operation != 'status':
            self.calls.append(('scene', operation))
        if operation == 'prepare':
            if self.native_prepare_failure == 'before':
                raise OSError('native response lost before dispatch')
            self.scene.update(state='preparing', runId='native:001', active=True, restored=False,
                              normalFlowVerified=False, scenarioId=kwargs['scenario_id'], boundaryToken=kwargs['boundary_id'])
            if self.native_prepare_failure == 'after':
                raise OSError('native response lost after dispatch')
        elif operation == 'play':
            self.scene.update(state='running')
        elif operation in {'cancel', 'retry'}:
            assert kwargs['run_id'] == self.scene['runId']
            assert kwargs['boundary_id'] == self.scene['boundaryToken']
            if self.native_cancel_failure:
                raise OSError('native cancel response lost')
            self.scene.update(state='cancelled', active=False, restored=True, normalFlowVerified=True)
        return {'schemaVersion': 'city.tradeshow-control.v1', 'available': True, 'playing': True,
                'scenario': copy.deepcopy(self.scene)}

    def _boundary(self, action=None):
        if action:
            self.calls.append(('boundary', action))
            if self.gate_failure:
                raise OSError('gateway unavailable')
            self.boundary = {'state': {'prepare': 'preparing', 'recover': 'preparing', 'settle': 'settling',
                                      'play': 'running', 'normal': 'normal'}[action], 'trackingEpoch': 'fresh',
                             'runId': self.transaction['boundaryId']}
        self.transaction['boundary'] = copy.deepcopy(self.boundary)
        return copy.deepcopy(self.boundary)

    def prepare(self):
        return self.request('prepare', scenario_id='queue-recovery', request_id='p' * 16)

    def ready(self):
        self.prepare()
        self.scene['state'] = 'ready'
        self.poll()
        self.boundary['state'] = 'ready'
        self.poll()


class PreparedControlTests(unittest.TestCase):
    def test_prepare_gates_before_native_jump(self):
        c = Controlled()
        result = c.prepare()
        self.assertEqual(c.calls, [('boundary', 'prepare'), ('scene', 'prepare')])
        self.assertEqual(result['scenario']['state'], 'preparing')
        self.assertFalse(result['scenario']['analyticsBoundary']['ready'])

    def test_failed_gate_never_moves_actors(self):
        c = Controlled(); c.gate_failure = True
        with self.assertRaises(OSError): c.prepare()
        self.assertNotIn(('scene', 'prepare'), c.calls)
        self.assertIsNotNone(c.transaction)

    def test_ready_requires_both_sources_after_reset_not_just_scene(self):
        c = Controlled(); c.prepare(); c.scene['state'] = 'ready'; c.poll()
        result = c.request()
        self.assertEqual(result['scenario']['state'], 'preparing')
        self.assertFalse(result['scenario']['analyticsBoundary']['ready'])
        with self.assertRaises(ValueError): c.request('play', run_id='native:001', request_id='x' * 16)
        c.boundary['state'] = 'ready'; c.poll()
        self.assertTrue(c.request()['scenario']['analyticsBoundary']['ready'])

    def test_preparation_exposes_owned_native_progress_then_camera_settling(self):
        c = Controlled(); c.prepare()
        c.scene['phase'] = 'validating-starts'
        self.assertEqual(c.request()['scenario']['phase'], 'validating-starts')
        c.scene.update(state='ready', phase='ready'); c.poll()
        result = c.request()['scenario']
        self.assertEqual(result['state'], 'preparing')
        self.assertEqual(result['phase'], 'settling')
        self.assertFalse(result['analyticsBoundary']['ready'])

    def test_play_opens_image_scope_before_motion(self):
        c = Controlled(); c.ready(); c.calls.clear()
        c.request('play', run_id='native:001', request_id='x' * 16)
        self.assertEqual(c.calls, [('boundary', 'play'), ('scene', 'play')])

    def test_duplicate_prepare_play_and_wrong_owner(self):
        c = Controlled(); c.ready()
        c.prepare()
        self.assertEqual(c.calls.count(('scene', 'prepare')), 1)
        with self.assertRaises(ValueError): c.request('prepare', scenario_id='queue-recovery', request_id='z' * 16)
        with self.assertRaises(ValueError): c.request('play', run_id='other:001', request_id='x' * 16)
        c.request('play', run_id='native:001', request_id='x' * 16)
        c.request('play', run_id='native:001', request_id='x' * 16)
        self.assertEqual(c.calls.count(('scene', 'play')), 1)
        with self.assertRaises(ValueError): c.request('cancel', run_id='native:001', request_id='x' * 16)

    def test_success_restores_normal_without_browser_poll(self):
        c = Controlled(); c.ready(); c.request('play', run_id='native:001', request_id='x' * 16)
        c.scene.update(state='completed', active=False, restored=True, normalFlowVerified=True)
        c.poll()
        self.assertEqual(c.transaction['phase'], 'closed')
        self.assertEqual(c.boundary['state'], 'normal')
        self.assertEqual(c.request()['scenario']['state'], 'completed')

    def test_cancel_gates_before_release_and_settles_before_normal(self):
        for phase in ('preparing', 'ready', 'running'):
            with self.subTest(phase=phase):
                c = Controlled(); c.prepare()
                if phase != 'preparing':
                    c.scene['state'] = 'ready'; c.poll(); c.boundary['state'] = 'ready'; c.poll()
                if phase == 'running': c.request('play', run_id='native:001', request_id='x' * 16)
                c.calls.clear()
                c.request('cancel', run_id='native:001', request_id='c' * 16)
                self.assertEqual(c.calls[:2], [('boundary', 'recover'), ('scene', 'cancel')])
                c.poll()
                self.assertEqual(c.transaction['phase'], 'cleanup-settling')
                self.assertEqual(c.request()['scenario']['state'], 'recovering')
                c.boundary['state'] = 'ready'; c.poll()
                self.assertEqual(c.transaction['phase'], 'closed')

    def test_ready_expires_and_native_failure_cleans_up(self):
        c = Controlled(); c.ready(); c.now += 181; c.poll()
        self.assertEqual(c.transaction['phase'], 'cleanup')
        c = Controlled(); c.prepare()
        c.scene.update(state='failed', active=False, restored=True, normalFlowVerified=True, reason='native-path-refused')
        c.poll(); c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.request()['scenario']['state'], 'failed')
        self.assertEqual(c.boundary['state'], 'normal')

    def test_settling_failure_and_recovery_failure_are_bounded(self):
        c = Controlled(); c.prepare(); c.scene['state'] = 'ready'; c.poll()
        c.boundary.update(state='failed', error='camera missing'); c.poll()
        self.assertEqual(c.transaction['phase'], 'cleanup')
        c.poll(); c.now += 26; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        self.assertTrue(c.request()['scenario']['restored'])
        with self.assertRaises(ValueError): c.request('prepare', scenario_id='queue-recovery', request_id='n' * 16)
        c.request('retry', run_id='native:001', request_id='r' * 16); c.poll()
        c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.transaction['phase'], 'closed')

    def test_capture_failure_gets_one_fresh_session_but_still_needs_settling(self):
        c = Controlled(); c.prepare(); c.scene['state'] = 'ready'; c.poll()
        renewals = []
        c.recover_analysis = lambda: renewals.append(True) or True
        c._json = lambda *a, **kw: {'nativeAnalyticsStatus': {'status': 'error',
            'sourceClockMode': 'source-native-sei', 'error': 'native-capture-clock-rejected: duplicate UUID'}}
        c.boundary.update(state='failed'); c.calls.clear(); c.poll()
        self.assertEqual(renewals,[True]); self.assertEqual(c.calls,[('boundary','recover'),('boundary','settle')])
        self.assertEqual(c.transaction['phase'],'settling')
        self.assertTrue(c.request()['scenario']['analyticsBoundary']['captureRenewalAttempted'])
        with self.assertRaises(ValueError): c.request('play',run_id='native:001',request_id='x'*16)
        c.boundary.update(state='ready'); c.poll()
        self.assertEqual(c.transaction['phase'],'ready')
        self.assertNotIn(('scene','play'),c.calls)

    def test_second_capture_failure_cancels_and_never_renews_again(self):
        c = Controlled(); c.prepare(); c.scene['state'] = 'ready'; c.poll(); calls = []
        c.recover_analysis = lambda: calls.append(True) or True
        c._json = lambda *a, **kw: {'nativeAnalyticsStatus': {'status':'error',
            'sourceClockMode':'source-native-sei','error':'native-capture-clock-rejected: stale'}}
        c.boundary.update(state='failed'); c.poll(); c.boundary.update(state='failed'); c.poll()
        self.assertEqual(calls,[True]); self.assertEqual(c.transaction['phase'],'cleanup')
        self.assertIn(('scene','cancel'),c.calls)
        c.poll(); c.boundary.update(state='failed'); c.poll()
        self.assertEqual(calls,[True]); self.assertEqual(c.transaction['phase'],'recovery-failed')

    def test_capture_clock_failure_during_play_stops_scene_before_camera_renewal(self):
        c=Controlled();c.ready();c.request('play',run_id='native:001',request_id='x'*16);c.calls.clear()
        renewed=[];c.recover_analysis=lambda:renewed.append(True) or True
        c._json=lambda *a,**kw:{'nativeAnalyticsStatus':{'status':'error','sourceClockMode':'source-native-sei','error':'native-capture-clock-rejected: duplicate'}}
        c.poll();self.assertEqual(c.calls[:2],[('boundary','recover'),('scene','cancel')]);self.assertEqual(renewed,[])
        self.assertEqual(c.transaction['reason'],'camera-capture-clock-rejected')
        c.poll();c.boundary.update(state='failed');c.poll();self.assertEqual(renewed,[True])
        self.assertEqual(c.transaction['phase'],'cleanup-settling')

    def test_other_faults_and_paused_sources_do_not_get_auto_resumed(self):
        for native in ({'status':'error','sourceClockMode':'source-rtcp','error':'native-capture-clock-rejected: x'},
                       {'status':'error','sourceClockMode':'source-native-sei','error':'other fault'}):
            c = Controlled(); c.prepare(); c.scene['state']='ready'; c.poll(); renewals=[]
            c.recover_analysis=lambda: renewals.append(True) or True
            c._json=lambda *a,**kw: {'nativeAnalyticsStatus':native}
            c.boundary.update(state='failed'); c.poll()
            self.assertEqual(renewals,[]); self.assertEqual(c.transaction['phase'],'cleanup')
        c=Controlled(); c.prepare(); c.scene['state']='ready'; c.poll()
        c._json=lambda *a,**kw: {'nativeAnalyticsStatus':{'status':'error','sourceClockMode':'source-native-sei','error':'native-capture-clock-rejected: x'}}
        def paused(): raise ValueError('Camera detections are paused')
        c.recover_analysis=paused; c.boundary.update(state='failed'); c.poll()
        self.assertTrue(c.transaction['captureRenewalAttempted'])
        self.assertNotIn(('scene','play'),c.calls)

    def test_persisted_transaction_keeps_owner_on_controller_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'state.json'
            c = Controlled(p); c.prepare()
            restored = Controlled(p)
            self.assertEqual(restored.transaction['nativeRunId'], 'native:001')
            self.assertEqual(restored.requests['p' * 16], ['prepare', 'queue-recovery', None])

    def test_failed_gate_has_host_identity_and_can_cancel_without_native_run(self):
        c = Controlled(); c.gate_failure = True
        c.scene['normalFlowVerified'] = False
        with self.assertRaises(OSError): c.prepare()
        result = c.request()['scenario']
        self.assertEqual(result['state'], 'preparing')
        self.assertTrue(result['runId'].startswith('host-'))
        self.assertEqual(result['scenarioId'], 'queue-recovery')
        c.gate_failure = False
        c.request('cancel', run_id=result['runId'], request_id='c' * 16)
        c.poll(); self.assertEqual(c.transaction['phase'], 'cleanup-settling')
        c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.request()['scenario']['state'], 'cancelled')
        self.assertFalse(c.request()['scenario']['normalFlowVerified'])
        self.assertTrue(c.request()['scenario']['nativePreparationNotStarted'])
        self.assertTrue(c.request()['scenario']['normalFlowUnchanged'])
        self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))

    def test_transient_gate_failure_retries_gate_before_one_native_prepare(self):
        c = Controlled(); c.gate_failure = True
        with self.assertRaises(OSError): c.prepare()
        c.prepare()  # Same request returns the transaction, never creates another.
        c.gate_failure = False; c.poll(); c.poll()
        self.assertEqual(c.calls.count(('scene', 'prepare')), 1)
        self.assertEqual(c.transaction['nativeRunId'], 'native:001')

    def test_lost_native_response_adopts_exact_token_without_reissuing_prepare(self):
        c = Controlled(); c.native_prepare_failure = 'after'
        with self.assertRaises(OSError): c.prepare()
        self.assertIsNone(c.transaction['nativeRunId'])
        self.assertTrue(c.transaction['nativePrepareIssued'])
        c.scene['state'] = 'ready'; c.poll()
        self.assertEqual(c.transaction['nativeRunId'], 'native:001')
        self.assertEqual(c.transaction['phase'], 'settling')
        self.assertEqual(c.calls.count(('scene', 'prepare')), 1)

    def test_unknown_unexecuted_native_command_waits_for_expiry_then_recovers_without_cancel(self):
        c = Controlled(); c.native_prepare_failure = 'before'
        with self.assertRaises(OSError): c.prepare()
        c.poll(); self.assertEqual(c.transaction['phase'], 'staging')
        self.assertNotIn(('boundary', 'settle'), c.calls)
        c.now += 5; c.poll()
        self.assertEqual(c.transaction['phase'], 'cleanup')
        c.poll(); c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.transaction['phase'], 'closed')
        self.assertEqual(c.request()['scenario']['state'], 'failed')
        self.assertNotIn(('scene', 'cancel'), c.calls)
        self.assertEqual(c.calls.count(('scene', 'prepare')), 1)

    def test_foreign_ready_run_is_neither_adopted_played_nor_cancelled(self):
        c = Controlled(); c.native_prepare_failure = 'before'
        with self.assertRaises(OSError): c.prepare()
        c.scene.update(state='ready', active=True, runId='foreign:007', scenarioId='queue-recovery', boundaryToken='foreign-token')
        c.poll()
        self.assertIsNone(c.transaction['nativeRunId'])
        self.assertEqual(c.transaction['phase'], 'staging')
        c.now += 46; c.poll(); c.now += 31; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        self.assertNotIn(('scene', 'cancel'), c.calls)
        self.assertNotIn(('boundary', 'settle'), c.calls)

    def test_cancel_unknown_prepare_adopts_late_owned_run_and_cancels_only_that_run(self):
        c = Controlled(); c.native_prepare_failure = 'before'
        with self.assertRaises(OSError): c.prepare()
        host_id = c.request()['scenario']['runId']
        c.request('cancel', run_id=host_id, request_id='c' * 16)
        self.assertNotIn(('scene', 'cancel'), c.calls)
        c.scene.update(state='preparing', active=True, restored=False, runId='native:009',
                       scenarioId='queue-recovery', boundaryToken=c.transaction['boundaryId'])
        c.poll()
        self.assertEqual(c.transaction['nativeRunId'], 'native:009')
        self.assertEqual(c.calls.count(('scene', 'cancel')), 1)

    def test_failed_gate_expires_and_retry_uses_host_identity_to_finish_recovery(self):
        c = Controlled(); c.gate_failure = True
        with self.assertRaises(OSError): c.prepare()
        c.now += 46; c.poll()
        self.assertEqual(c.transaction['phase'], 'cleanup')
        c.now += 31; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        host_id = c.request()['scenario']['runId']
        c.gate_failure = False
        c.request('retry', run_id=host_id, request_id='r' * 16)
        c.poll(); c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.transaction['phase'], 'closed')
        self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))

    def test_explicit_recovery_renews_analysis_once_only_after_run_identity_validation(self):
        c = Controlled(); c.ready()
        c.request('cancel', run_id='native:001', request_id='c' * 16)
        c.poll(); c.boundary['state'] = 'failed'; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        calls = []; c.recover_analysis = lambda: calls.append('recover')
        with self.assertRaises(ValueError): c.request('retry', run_id='other:001', request_id='r' * 16)
        self.assertEqual(calls, [])
        c.request('retry', run_id='native:001', request_id='r' * 16)
        c.request('retry', run_id='native:001', request_id='r' * 16)
        self.assertEqual(calls, ['recover'])

    def test_camera_failure_while_ready_releases_scene_without_waiting_for_play_or_expiry(self):
        c = Controlled(); c.ready(); c.calls.clear()
        c.boundary.update(state='failed', error='Camera tracking stopped')
        c.poll()
        self.assertEqual(c.transaction['phase'], 'cleanup')
        self.assertEqual(c.transaction['reason'], 'Camera tracking stopped')
        self.assertIn(('scene', 'cancel'), c.calls)
        self.assertTrue(c.scene['restored'])

    def test_paused_detection_refusal_keeps_recovery_retryable(self):
        c = Controlled(); c.ready()
        c.request('cancel', run_id='native:001', request_id='c' * 16)
        c.poll(); c.boundary['state'] = 'failed'; c.poll()
        def paused(): raise ValueError('Camera detections are paused')
        c.recover_analysis = paused
        with self.assertRaisesRegex(ValueError, 'paused'):
            c.request('retry', run_id='native:001', request_id='r' * 16)
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        self.assertNotIn('r' * 16, c.requests)

    def test_repeated_cancel_transport_failure_does_not_extend_cleanup_deadline(self):
        c = Controlled(); c.prepare(); c.native_cancel_failure = True
        with self.assertRaises(OSError): c.request('cancel', run_id='native:001', request_id='c' * 16)
        started = c.transaction['phaseStartedAt']
        c.now += 20; c.poll()
        self.assertEqual(c.transaction['phaseStartedAt'], started)
        c.now += 11; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')

    def test_native_restoration_alone_does_not_release_analytics_without_normal_motion(self):
        c = Controlled(); c.ready(); c.request('play', run_id='native:001', request_id='x' * 16)
        c.scene.update(state='completed', active=False, restored=True, normalFlowVerified=False)
        c.poll(); self.assertEqual(c.transaction['phase'], 'running')
        self.assertNotIn(('boundary', 'normal'), c.calls)
        c.scene['normalFlowVerified'] = True; c.poll()
        self.assertEqual(c.transaction['phase'], 'closed')

    def retired_cleanup(self, path=None):
        c = Controlled(path); c.ready()
        c.request('cancel', run_id='native:001', request_id='c' * 16)
        c.poll(); c.now += 26; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        c.scene = {'state': 'idle', 'active': False, 'restored': True, 'normalFlowVerified': False,
                   'runId': None, 'scenarioId': None, 'boundaryToken': None, 'catalog': c.scene['catalog']}
        c.calls.clear()
        return c

    def test_retired_controller_reuses_persisted_release_receipt_for_camera_recovery_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            before = self.retired_cleanup(path)
            receipt = copy.deepcopy(before.transaction['native'])
            c = Controlled(path); c.scene = before.scene
            c.request('retry', run_id='native:001', request_id='r' * 16)
            c.poll()
            self.assertEqual(c.transaction['phase'], 'cleanup-settling')
            self.assertEqual(c.transaction['native'], receipt)
            recovering = c.request()['scenario']
            self.assertEqual(recovering['state'], 'recovering')
            self.assertTrue(recovering['restored'])
            self.assertFalse(recovering['analyticsBoundary']['ready'])
            c.boundary['state'] = 'ready'; c.poll()
            self.assertEqual(c.transaction['phase'], 'closed')
            result = c.request()['scenario']
            self.assertEqual(result['runId'], 'native:001')
            self.assertEqual(result['state'], 'cancelled')
            self.assertTrue(result['normalFlowVerified'])
            self.assertTrue(result['nativeRestorationReceiptRetained'])
            self.assertFalse(c.scene['normalFlowVerified'])
            self.assertEqual(c.transaction['native'], receipt)
            self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))
            self.assertEqual(c.boundary['state'], 'normal')
            restarted = Controlled(path); restarted.scene = c.scene
            self.assertEqual(restarted.request()['scenario']['runId'], 'native:001')
            self.assertEqual(restarted.transaction['native'], receipt)

    def test_retired_controller_requires_complete_owned_terminal_receipt(self):
        for change in ({'state': 'ready'}, {'state': 'idle'}, {'active': True}, {'restored': False},
                       {'normalFlowVerified': False}, {'normalFlowVerified': None}, {'runId': 'other:001'},
                       {'boundaryToken': 'other-boundary'}, {'scenarioId': 'curb-obstruction'}):
            with self.subTest(change=change):
                c = self.retired_cleanup()
                c.transaction['native']['scenario'].update(change)
                c.request('retry', run_id='native:001', request_id='r' * 16); c.poll()
                self.assertEqual(c.transaction['phase'], 'recovery-failed')
                self.assertNotIn(('boundary', 'settle'), c.calls)
                self.assertNotIn(('boundary', 'normal'), c.calls)
                self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))

    def test_retired_controller_requires_exact_unowned_idle_status(self):
        for change in ({'state': 'ready'}, {'active': True}, {'active': None}, {'restored': False},
                       {'runId': 'native:001'}, {'runId': 'other:001'}, {'boundaryToken': 'other-boundary'},
                       {'scenarioId': 'queue-recovery'}):
            with self.subTest(change=change):
                c = self.retired_cleanup(); c.scene.update(change)
                c.request('retry', run_id='native:001', request_id='r' * 16); c.poll()
                self.assertEqual(c.transaction['phase'], 'recovery-failed')
                self.assertNotIn(('boundary', 'settle'), c.calls)
                self.assertNotIn(('boundary', 'normal'), c.calls)
                self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))

    def test_retired_controller_receipt_cannot_resume_staging_ready_or_running(self):
        for phase in ('gating', 'staging', 'settling', 'ready', 'running'):
            with self.subTest(phase=phase):
                c = self.retired_cleanup(); c.transaction['phase'] = phase
                c.poll()
                self.assertEqual(c.transaction['phase'], 'recovery-failed')
                self.assertNotIn(('boundary', 'settle'), c.calls)
                self.assertNotIn(('boundary', 'normal'), c.calls)
                self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))

    def test_new_owner_during_retired_camera_settlement_blocks_normal_without_cancel(self):
        c = self.retired_cleanup()
        c.request('retry', run_id='native:001', request_id='r' * 16); c.poll()
        self.assertEqual(c.transaction['phase'], 'cleanup-settling')
        c.scene.update(state='ready', active=True, restored=False, runId='other:001',
                       scenarioId='queue-recovery', boundaryToken='other-boundary')
        c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.transaction['phase'], 'recovery-failed')
        self.assertNotIn(('boundary', 'normal'), c.calls)
        self.assertFalse(any(kind == 'scene' for kind, _ in c.calls))

    def test_camera_recovery_retains_owned_actor_release_without_allowing_new_preparation(self):
        c = Controlled(); c.ready()
        c.request('cancel', run_id='native:001', request_id='c' * 16)
        c.poll(); c.now += 26; c.poll()
        result = c.request()['scenario']
        self.assertEqual(result['state'], 'recovery-failed')
        self.assertTrue(result['restored'])
        self.assertTrue(result['normalFlowVerified'])
        self.assertFalse(result['analyticsBoundary']['ready'])
        with self.assertRaises(ValueError): c.request('prepare', scenario_id='queue-recovery', request_id='n' * 16)

    def test_foreign_receipt_cannot_claim_this_runs_actor_release_in_recovery_status(self):
        c = self.retired_cleanup()
        c.scene.update(state='cancelled', restored=True, normalFlowVerified=True, runId='other:001',
                       scenarioId='queue-recovery', boundaryToken=c.transaction['boundaryId'])
        result = c.request()['scenario']
        self.assertEqual(result['state'], 'recovery-failed')
        self.assertFalse(result['restored'])
        self.assertNotIn('nativeRestorationReceiptRetained', result)

    def test_retired_receipt_keeps_replacement_catalog_for_next_preparation(self):
        c = self.retired_cleanup()
        current_catalog = c.scene['catalog'] + [{'id': 'pedestrian-service', 'available': True}]
        c.scene['catalog'] = current_catalog
        self.assertEqual(c.request()['scenario']['catalog'], current_catalog)
        c.request('retry', run_id='native:001', request_id='r' * 16); c.poll()
        c.boundary['state'] = 'ready'; c.poll()
        self.assertEqual(c.request()['scenario']['catalog'], current_catalog)
        self.assertEqual(len(c.transaction['native']['scenario']['catalog']), 1)
        result = c.request('prepare', scenario_id='pedestrian-service', request_id='n' * 16)
        self.assertEqual(result['scenario']['scenarioId'], 'pedestrian-service')
        self.assertEqual(result['scenario']['state'], 'preparing')
        self.assertEqual(c.calls.count(('scene', 'prepare')), 1)


if __name__ == '__main__': unittest.main()
