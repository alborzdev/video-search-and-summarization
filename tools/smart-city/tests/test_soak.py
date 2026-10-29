"""Offline CPU failure controls; no live monitor, Docker or model is started."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import soak


def options(**values):
    defaults={'site_id':'cpu-control','source_id':['camera-one','camera-two'],'warmup_seconds':10,
        'stale_seconds':5,'clock_window_seconds':20,'minimum_clock_ratio':.9,'maximum_clock_ratio':1.1,
        'trust_source_rtcp_utc':False,'maximum_source_age_seconds':5,'maximum_duplicate_fraction':.05,
        'vss_origin':'http://localhost:7777','agent_origin':'http://localhost:8100','ask_timeout_seconds':55}
    return argparse.Namespace(**{**defaults,**values})


def sample(seconds,clock_rate=1.,offset=0):
    ns=int((1700000000+offset+seconds*clock_rate)*1e9)
    source=lambda sid:{'id':sid,'name':sid,'status':'live','lastSourceTimeNs':str(ns),
                       'timestampBasis':'source-rtcp','sessionId':'stable-session'}
    counter=lambda fps:{'frames':int(seconds*fps),'uniquePts':int(seconds*fps),'duplicatePts':0,
        'backwardPts':0,'clockRollbacks':0,'sequenceGaps':0,'sessionChanges':0}
    return {'monotonicSeconds':1000+seconds,'wallSeconds':1700000000+seconds,
        'memory':{'availableGiB':25.,'guardAvailableGiB':24.,'savedReserveGiB':20.,'guardFloorGiB':20.,'guardAgeSeconds':1.},
        'containers':{'native':{'id':'stable-container','running':True,'status':'running','restartCount':0,
            'oomKilled':False,'health':None,'memoryEvents':{'oom':0,'oom_kill':0},'memoryMax':'17179869184'}},
        'snapshot':{'siteId':'cpu-control','mode':'live','rulesRevision':21,
            'sources':[source('camera-one'),source('camera-two')],'tracks':[]},
        'health':{'siteId':'cpu-control','status':'ok','nativeAnalyticsStatus':{
            'status':'active','requestedRevision':21,'appliedRevision':21,'counterEpoch':'epoch21'}},
        'nativeAck':{'revision':'21','status':'active','counterEpoch':'epoch21'},
        'frames':{'camera-one':counter(30),'camera-two':counter(10)}}


class ClockAndResourceControls(unittest.TestCase):
    def native_sample(self, seconds):
        value=sample(seconds)
        for source in value['snapshot']['sources']:
            source.update(timestampBasis='source-native-sei',sourceClockMode='source-native-sei',browserClockVerified=False,rawSourcePtsNs=str(int(seconds*1e9)))
            source['sourceClockEvidence']={'schemaVersion':'city.source-native-sei.v1','method':'isaac-native-sei-wall-capture',
                'correlation':'exact-au-pts','captureTimeNs':source['lastSourceTimeNs'],'auPtsNs':source['rawSourcePtsNs'],'frameCounter':str(int(seconds*30))}
        value['health']['nativeAnalyticsStatus']['sourceClockMode']='source-native-sei'
        value['nativeAck']['sourceClockMode']='source-native-sei'
        return value

    def test_native_monitor_requires_explicit_basis_and_proof_without_relabelling_rtcp(self):
        native=soak.Checks(options(expected_source_clock_basis='source-native-sei',trust_native_sei_wall_utc=True))
        native.evaluate(self.native_sample(0));result=native.evaluate(self.native_sample(20))
        self.assertEqual(result['sources']['camera-one']['basis'],'source-native-sei')
        self.assertEqual(result['sources']['camera-one']['trustedSourceAgeSeconds'],0)
        generic=soak.Checks(options());generic.evaluate(self.native_sample(0))
        with self.assertRaisesRegex(soak.SoakFailure,'expected-source-clock-basis-required'):
            generic.evaluate(self.native_sample(20))
        native=soak.Checks(options(expected_source_clock_basis='source-native-sei'))
        native.evaluate(sample(0))
        with self.assertRaisesRegex(soak.SoakFailure,'expected-source-clock-basis-required'):native.evaluate(sample(20))

    def test_native_monitor_rejects_missing_ambiguous_or_nonmatching_proof_and_ack(self):
        for fault in ('capture','pts','counter','extra','browser','ack'):
            with self.subTest(fault=fault):
                checks=soak.Checks(options(expected_source_clock_basis='source-native-sei'))
                checks.evaluate(self.native_sample(0));value=self.native_sample(20);source=value['snapshot']['sources'][0]
                if fault=='capture':source['sourceClockEvidence']['captureTimeNs']='1'
                if fault=='pts':source['sourceClockEvidence']['auPtsNs']='1'
                if fault=='counter':source['sourceClockEvidence']['frameCounter']=str(2**64)
                if fault=='extra':source['sourceClockEvidence']['offsetNs']=597000000
                if fault=='browser':source['browserClockVerified']=True
                if fault=='ack':value['nativeAck'].pop('sourceClockMode')
                with self.assertRaisesRegex(soak.SoakFailure,'native-sei-clock-proof-or-ack-missing'):checks.evaluate(value)

    def test_thirty_healthy_virtual_iterations(self):
        checks=soak.Checks(options())
        for index in range(30):result=checks.evaluate(sample(index*5))
        self.assertEqual(set(result['sources']),{'camera-one','camera-two'})
        self.assertTrue(result['nativeActive'])
        self.assertTrue(all(abs(v-1)<1e-6 for v in checks.clock_ratios.values()))

    def test_stalled_clock_rejected_even_with_live_receipt_status(self):
        checks=soak.Checks(options());checks.evaluate(sample(0))
        with self.assertRaisesRegex(soak.SoakFailure,'clock-stalled'):
            checks.evaluate(sample(15,clock_rate=0))

    def test_slow_advancing_clock_rejected(self):
        checks=soak.Checks(options())
        for second in (0,5,10,15):checks.evaluate(sample(second,clock_rate=.8))
        with self.assertRaisesRegex(soak.SoakFailure,'clock-rate-outside'):
            checks.evaluate(sample(20,clock_rate=.8))

    def test_duplicate_pts_rejected_despite_advancing_source_clock(self):
        checks=soak.Checks(options());checks.evaluate(sample(0))
        bad=sample(15);bad['frames']['camera-two']['duplicatePts']=120
        with self.assertRaisesRegex(soak.SoakFailure,'duplicate-native-pts'):
            checks.evaluate(bad)

    def test_startup_duplicate_peak_is_separate_from_gate_evaluated_peak(self):
        checks=soak.Checks(options());checks.evaluate(sample(0))
        startup=sample(5);startup['frames']['camera-two']['duplicatePts']=3
        checks.evaluate(startup)
        self.assertAlmostEqual(checks.max_duplicate['camera-two'],.06)
        self.assertNotIn('camera-two',checks.max_duplicate_post_warmup)
        warmed=sample(10);warmed['frames']['camera-two']['duplicatePts']=3
        checks.evaluate(warmed)
        self.assertAlmostEqual(checks.max_duplicate['camera-two'],.06)
        self.assertAlmostEqual(checks.max_duplicate_post_warmup['camera-two'],.03)

    def test_absolute_age_only_checked_with_explicit_clock_trust(self):
        checks=soak.Checks(options());checks.evaluate(sample(0,offset=-90));checks.evaluate(sample(15,offset=-90))
        trusted=soak.Checks(options(trust_source_rtcp_utc=True));trusted.evaluate(sample(0,offset=-90))
        with self.assertRaisesRegex(soak.SoakFailure,'utc-age-outside'):
            trusted.evaluate(sample(15,offset=-90))

    def test_low_reserve_and_stale_guard_fail(self):
        for key,value,message in [('availableGiB',19.99,'below-reserve'),('guardAgeSeconds',20,'telemetry-stale')]:
            data=sample(0);data['memory'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(soak.SoakFailure,message):
                soak.Checks(options()).evaluate(data)

    def test_cgroup_oom_and_container_recreation_fail(self):
        for field,value,message in [('memoryEvents',{'oom':1,'oom_kill':1},'cgroup-oom-event'),('id','new-container','restarted-or-recreated')]:
            checks=soak.Checks(options());checks.evaluate(sample(0));bad=sample(5)
            bad['containers']['native'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(soak.SoakFailure,message):checks.evaluate(bad)

    def test_starting_health_is_allowed_only_before_warmup(self):
        checks=soak.Checks(options())
        for second in (0,9.999):
            data=sample(second);data['containers']['native']['health']='starting'
            checks.evaluate(data)
        data=sample(10);data['containers']['native']['health']='starting'
        with self.assertRaisesRegex(soak.SoakFailure,'container-not-healthy:native'):
            checks.evaluate(data)

    def test_healthy_or_no_healthcheck_and_startup_transition_are_valid(self):
        for health in (None,'healthy'):
            checks=soak.Checks(options())
            for second in (0,10,20):
                data=sample(second);data['containers']['native']['health']=health
                checks.evaluate(data)
        checks=soak.Checks(options())
        for second,health in ((0,'starting'),(9,'healthy'),(10,'healthy')):
            data=sample(second);data['containers']['native']['health']=health
            checks.evaluate(data)

    def test_nonrunning_status_fails_even_with_running_true_during_grace(self):
        for status in ('paused','created','restarting','removing','exited','dead','unknown',None):
            for second in (0,10):
                with self.subTest(status=status,second=second):
                    checks=soak.Checks(options());checks.evaluate(sample(0))
                    data=sample(second);data['containers']['native'].update(running=True,status=status,health='healthy')
                    with self.assertRaisesRegex(soak.SoakFailure,'container-not-healthy:native'):
                        checks.evaluate(data)

    def test_unhealthy_or_unknown_health_fails_without_startup_waiver(self):
        for health in ('unhealthy','unknown','',False,1,[],{}):
            for second in (0,10):
                with self.subTest(health=health,second=second):
                    checks=soak.Checks(options());checks.evaluate(sample(0))
                    data=sample(second);data['containers']['native']['health']=health
                    with self.assertRaisesRegex(soak.SoakFailure,'container-not-healthy:native'):
                        checks.evaluate(data)

    def test_stale_native_ack_and_negative_uncertainty_fail(self):
        checks=soak.Checks(options());checks.evaluate(sample(0));bad=sample(15);bad['nativeAck']['revision']='20'
        with self.assertRaisesRegex(soak.SoakFailure,'ack-not-current'):checks.evaluate(bad)
        bad=sample(0);bad['snapshot']['tracks']=[{'positionUncertaintyM':-.1}]
        with self.assertRaisesRegex(soak.SoakFailure,'negative-or-invalid'):soak.Checks(options()).evaluate(bad)


class IncrementalFrames(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'frames.ndjson';self.path.write_bytes(b'')
    def tearDown(self):self.temp.cleanup()
    def row(self,seq=0,pts=100,uncertainty=None):
        return {'siteId':'cpu-control','sourceId':'camera-one','sourceSessionId':'run-one',
            'sequence':str(seq),'rawSourcePtsNs':str(pts),'sourceTimeNs':str(1700000000000000000+pts),
            'timestampBasis':'source-rtcp','objects':[{'positionUncertaintyM':uncertainty}]}
    def test_partial_lines_duplicates_and_truncation(self):
        tail=soak.FrameTail(self.path,['camera-one','camera-two'],'cpu-control')
        try:
            encoded=json.dumps(self.row()).encode()
            with self.path.open('ab') as file:file.write(encoded[:30])
            self.assertEqual(tail.read()['camera-one']['frames'],0)
            with self.path.open('ab') as file:file.write(encoded[30:]+b'\n'+json.dumps(self.row(1)).encode()+b'\n')
            values=tail.read()['camera-one'];self.assertEqual(values['frames'],2);self.assertEqual(values['duplicatePts'],1)
            self.path.write_bytes(b'')
            with self.assertRaisesRegex(soak.SoakFailure,'truncated'):tail.read()
        finally:tail.close()
    def test_start_at_end_ignores_old_inflight_record(self):
        self.path.write_bytes(b'{"oldPartial":')
        tail=soak.FrameTail(self.path,['camera-one','camera-two'],'cpu-control')
        try:
            with self.path.open('ab') as file:file.write(b'true}\n'+json.dumps(self.row()).encode()+b'\n')
            self.assertEqual(tail.read()['camera-one']['frames'],1)
        finally:tail.close()
    def test_negative_and_nonfinite_uncertainty_are_not_counted_as_healthy(self):
        for value in (-.1,float('nan')):
            tail=soak.FrameTail(self.path,['camera-one','camera-two'],'cpu-control')
            try:
                with self.assertRaisesRegex(soak.SoakFailure,'negative-or-invalid'):tail.ingest(self.row(uncertainty=value))
            finally:tail.close()


class RotatingFrames(IncrementalFrames):
    def write_row(self,sequence):
        with self.path.open('ab') as handle:handle.write(json.dumps(self.row(sequence,sequence+100)).encode()+b'\n')

    def manifest(self,generation):
        files=[]
        for index in range(min(generation,3)):
            path=Path(str(self.path)+('' if index==0 else '.'+str(index)))
            stat=path.stat()
            files.append({'name':path.name,'generation':str(generation-index),'device':str(stat.st_dev),'inode':str(stat.st_ino)})
        document={'schemaVersion':'city.observations.rotation.v1','generation':str(generation),'maxBytes':1024*1024,'retainedFiles':2,'files':files}
        Path(str(self.path)+'.manifest.json').write_text(json.dumps(document))

    def rotate(self,generation,commit=True):
        Path(str(self.path)+'.2').unlink(missing_ok=True)
        previous=Path(str(self.path)+'.1')
        if previous.exists():previous.rename(str(self.path)+'.2')
        self.path.rename(previous);self.path.write_bytes(b'')
        if commit:self.manifest(generation)

    def test_drains_two_sealed_generations_and_current_without_losing_frames(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            self.write_row(0);self.rotate(2);self.write_row(1);self.rotate(3);self.write_row(2)
            counts=tail.read()['camera-one']
            self.assertEqual(counts['frames'],3);self.assertEqual(counts['sequenceGaps'],0)
            self.assertEqual(tail.rotations,2)
            self.write_row(3);self.assertEqual(tail.read()['camera-one']['frames'],4)
        finally:tail.close()

    def test_final_old_record_arrives_between_eof_and_manifest_read(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            original=tail._rotation_manifest;changed=False
            def racing_manifest():
                nonlocal changed
                if not changed:
                    changed=True;self.write_row(0);self.rotate(2);self.write_row(1)
                return original()
            with patch.object(tail,'_rotation_manifest',side_effect=racing_manifest):
                counts=tail.read()['camera-one']
            self.assertEqual(counts['frames'],2)
            self.assertEqual(counts['sequenceGaps'],0)
            self.assertEqual(tail.rotations,1)
        finally:tail.close()

    def test_rename_before_manifest_commit_waits_then_resumes_exactly(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            self.write_row(0);self.rotate(2,commit=False)
            self.assertEqual(tail.read()['camera-one']['frames'],1)
            self.manifest(2);self.write_row(1)
            self.assertEqual(tail.read()['camera-one']['frames'],2)
            self.assertEqual(tail.counts['camera-one']['sequenceGaps'],0)
        finally:tail.close()

    def test_permanent_rename_mismatch_and_missed_retention_fail(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            self.rotate(2,commit=False)
            with patch.object(soak.time,'monotonic',side_effect=[10,13]):
                tail.read()
                with self.assertRaisesRegex(soak.SoakFailure,'rotation-incomplete'):tail.read()
            self.manifest(2);self.rotate(3);self.rotate(4)
            with self.assertRaisesRegex(soak.SoakFailure,'retention-exceeded'):tail.read()
        finally:tail.close()

    def test_partial_sealed_line_and_sequence_gaps_are_not_hidden_by_rotation(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            self.path.write_bytes(b'{"partial":');self.rotate(2)
            with self.assertRaisesRegex(soak.SoakFailure,'partial-line'):tail.read()
        finally:tail.close()

    def test_sequence_gap_across_rotation_remains_a_failure_counter(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            self.write_row(0);tail.read();self.rotate(2);self.write_row(3)
            self.assertEqual(tail.read()['camera-one']['sequenceGaps'],1)
        finally:tail.close()

    def test_manifest_cannot_redirect_reader_outside_log_family(self):
        self.manifest(1)
        path=Path(str(self.path)+'.manifest.json');document=json.loads(path.read_text())
        document['files'][0]['name']='../unrelated';path.write_text(json.dumps(document))
        with self.assertRaisesRegex(soak.SoakFailure,'invalid-manifest'):
            soak.FrameTail(self.path,['camera-one'],'cpu-control')

    def test_changed_inode_in_committed_manifest_is_rejected(self):
        self.manifest(1);tail=soak.FrameTail(self.path,['camera-one'],'cpu-control')
        try:
            path=Path(str(self.path)+'.manifest.json');document=json.loads(path.read_text())
            document['files'][0]['inode']='123';path.write_text(json.dumps(document))
            with self.assertRaisesRegex(soak.SoakFailure,'identity-changed'):tail.read()
        finally:tail.close()


class CLIAndProvenanceControls(unittest.TestCase):
    def test_default_vss_origin_uses_ui_front_door(self):
        argv=['soak.py','--site-id','cpu-control','--source-id','camera-one',
              '--source-id','camera-two','--observations','/tmp/not-opened.ndjson']
        with patch.object(sys,'argv',argv):args=soak.arguments()
        self.assertEqual(args.vss_origin,'http://127.0.0.1:7777')

    def test_source_hash_is_pinned_when_module_loads(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'tools'/'smart-city'/'soak.py';path.parent.mkdir(parents=True)
            source=Path(soak.__file__).read_bytes();path.write_bytes(source)
            spec=importlib.util.spec_from_file_location('soak_provenance_control',path)
            loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
            expected=hashlib.sha256(source).hexdigest()
            self.assertEqual(loaded.MONITOR_SOURCE_SHA256,expected)
            path.write_bytes(source+b'\n# changed after monitoring started\n')
            self.assertEqual(loaded.MONITOR_SOURCE_SHA256,expected)
            self.assertNotEqual(loaded.MONITOR_SOURCE_SHA256,soak.file_sha(path))


class OptInActions(unittest.TestCase):
    def test_live_ask_uses_real_identity_and_receipt_omits_answer_text(self):
        source={'id':'camera-one','name':'City north','vssSensorId':'actual-vios-id'}
        payload=soak.ask_payload(source,1,1700000000)
        self.assertEqual(payload['sources'][0]['kind'],'live')
        self.assertEqual(payload['sources'][0]['sensorId'],'actual-vios-id')
        self.assertNotIn('currentTimeSeconds',payload['sources'][0]['playback'])
        with patch.object(soak,'json_request',return_value={'answer':'private test response','grounded':True,
            'observedWindow':{'startTime':'start','endTime':'end'},'evidenceTools':['actual-tool']}):
            receipt=soak.ask_once(options(),source,1)
        self.assertTrue(receipt['grounded']);self.assertNotIn('private test response',json.dumps(receipt))

    def test_pause_calls_only_specified_sources_and_attempts_second_after_failure(self):
        calls=[]
        def request(url,payload=None,**kwargs):
            if payload is None:return [{'sensorId':sid,'name':sid} for sid in ['camera-one','camera-two','unrelated-camera']]
            calls.append((url,payload))
            if 'camera-one' in url:raise soak.SoakFailure('http-status-503')
            return {'state':'paused'}
        with patch.object(soak,'json_request',side_effect=request):result=soak.pause_sources(options())
        self.assertEqual(len(calls),2);self.assertTrue(all(body['action']=='pause' for _,body in calls))
        self.assertFalse(any('unrelated-camera' in url for url,_ in calls))
        self.assertFalse(result[0]['requestCompleted']);self.assertTrue(result[1]['requestCompleted'])


if __name__=='__main__':unittest.main()
