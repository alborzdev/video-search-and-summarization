"""Offline HTTP/clock controls: these never call a model or live service."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime,timezone
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import qualify_questions as trial

SID='291399aa-a062-43b6-badc-48c34bc08237'


def options(output=None,**kwargs):
    values={'allow_real_ask':True,'site_id':'cpu-control','source_id':SID,'root':Path('/unused'),
        'device':'spark','output_dir':output,'vss_origin':'http://127.0.0.1:7777',
        'gateway_origin':'http://127.0.0.1:9184','allow_vss_alias':[],'between_calls_seconds':60.,'timeout_seconds':55.}
    return argparse.Namespace(**{**values,**kwargs})


class FakeClock:
    def __init__(self):self.seconds=0.
    def monotonic(self):return self.seconds
    def time(self):return 1792647000+self.seconds
    def sleep(self,seconds):self.seconds+=seconds


def memory(*args):
    return {'availableGiB':25,'guardAvailableGiB':24,'savedReserveGiB':20,'guardFloorGiB':20,'guardAgeSeconds':1}


class FakeAPI:
    def __init__(self,clock):self.clock=clock;self.posts=[];self.windows=[];self.exports=[];self.fetched=[]
    def request(self,url,payload=None,**kwargs):
        self.assert_bounded(url,kwargs)
        if '/city/snapshot' in url:
            return {'siteId':'cpu-control','mode':'live','rulesRevision':21,'sources':[
                {'id':SID,'vssSensorId':SID,'name':'Traffic','status':'live','timestampBasis':'source-rtcp',
                 'sessionId':'stable','lastSourceTimeNs':str(int(self.clock.time()*1e9))}]}
        if '/city/health' in url:
            return {'siteId':'cpu-control','status':'ok','nativeAnalyticsStatus':{'status':'active','requestedRevision':21,'appliedRevision':21}}
        if '/workload-admission?' in url:return {'workload':'current_visual_question','decision':'allow'}
        if url.endswith('/analyst'):
            self.posts.append((self.clock.seconds,payload));at=datetime.fromisoformat(payload['askedAt']).timestamp()
            stamp=lambda value:datetime.fromtimestamp(value,timezone.utc).isoformat()
            window={'startTime':stamp(at-5),'endTime':stamp(at)};self.windows.append(window)
            self.clock.seconds+=2
            return {'answer':'PRIVATE GENERATED TEXT','grounded':True,'evidenceTools':['video_understanding_iso'],'observedWindow':window}
        if '/evidence?' in url:
            query=parse_qs(urlsplit(url).query);window={key:query[key][0] for key in ['startTime','endTime']}
            if query['sensorId']!=[SID]:raise AssertionError('wrong requested identity')
            self.exports.append(window);index=self.windows.index(window)+1
            return {'startTime':window['startTime'],'videoUrl':f'/vst/storage/temp_files/clip-{index}.mp4'}
        raise AssertionError('unexpected HTTP call')
    def assert_bounded(self,url,kwargs):
        limit=1024*1024 if '/city/snapshot' in url else 65536
        if kwargs['timeout']>55 or kwargs['cap']>limit:raise AssertionError('unbounded HTTP options')
    def fetch(self,url,args):
        self.fetched.append(url);self.clock.seconds+=1
        return {'bytes':128,'sha256':hashlib.sha256(url.encode()).hexdigest(),'fetchSeconds':1}


class SerialTrialControls(unittest.TestCase):
    def test_native_question_preflight_requires_explicit_basis_and_exact_proof(self):
        clock=FakeClock();api=FakeAPI(clock)
        def request(url,*args,**kwargs):
            value=api.request(url,*args,**kwargs)
            if '/city/snapshot' in url:
                source=value['sources'][0]
                source.update(timestampBasis='source-native-sei',sourceClockMode='source-native-sei',rawSourcePtsNs='1234',browserClockVerified=False)
                source['sourceClockEvidence']={'schemaVersion':'city.source-native-sei.v1','method':'isaac-native-sei-wall-capture',
                    'correlation':'exact-au-pts','captureTimeNs':source['lastSourceTimeNs'],'auPtsNs':'1234','frameCounter':'42'}
            if '/city/health' in url:value['nativeAnalyticsStatus']['sourceClockMode']='source-native-sei'
            return value
        with patch.object(trial,'json_request',side_effect=request),patch.object(trial.soak,'host_memory',side_effect=memory):
            _,receipt=trial.preflight(options(expected_source_clock_basis='source-native-sei'))
            self.assertEqual(receipt['timestampBasis'],'source-native-sei')
            with self.assertRaisesRegex(trial.TrialFailure,'source-clock-missing'):trial.preflight(options())
        for fault in ('pts','ack'):
            def invalid(url,*args,**kwargs):
                value=request(url,*args,**kwargs)
                if fault=='pts' and '/city/snapshot' in url:value['sources'][0]['sourceClockEvidence']['auPtsNs']='1235'
                if fault=='ack' and '/city/health' in url:value['nativeAnalyticsStatus'].pop('sourceClockMode')
                return value
            with patch.object(trial,'json_request',side_effect=invalid),patch.object(trial.soak,'host_memory',side_effect=memory):
                with self.assertRaisesRegex(trial.TrialFailure,'native-sei-clock-proof-or-ack-missing'):
                    trial.preflight(options(expected_source_clock_basis='source-native-sei'))

    def test_three_serial_unique_windows_and_one_evidence_only_repeat(self):
        clock=FakeClock();api=FakeAPI(clock)
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'private'
            with patch.object(trial,'json_request',side_effect=api.request),patch.object(trial,'fetch_clip',side_effect=api.fetch), \
                 patch.object(trial.soak,'host_memory',side_effect=memory),patch.object(trial,'time',clock),redirect_stdout(io.StringIO()):
                self.assertEqual(trial.run(options(out)),0)
            receipt=json.loads((out/'receipt.json').read_text())
            self.assertEqual(receipt['actualAskCount'],3);self.assertEqual(len(api.posts),3)
            self.assertEqual(len(api.exports),4);self.assertEqual(api.exports[0],api.exports[-1])
            self.assertEqual(len({tuple(w.values()) for w in api.windows}),3)
            self.assertGreaterEqual(api.posts[1][0]-api.posts[0][0],63)
            self.assertTrue(all(row['sources'][0]['sensorId']==SID and row['lookbackSeconds']==5 for _,row in api.posts))
            self.assertTrue(receipt['cachedRepeat']['sameMediaUri']);self.assertTrue(receipt['cachedRepeat']['sameByteHash'])
            self.assertNotIn('PRIVATE GENERATED TEXT',(out/'receipt.json').read_text())
            self.assertEqual(out.stat().st_mode&0o777,0o700)
            self.assertEqual((out/'receipt.json').stat().st_mode&0o777,0o600)

    def test_failure_aborts_without_retry_or_second_question(self):
        clock=FakeClock();api=FakeAPI(clock)
        def request(url,payload=None,**kwargs):
            value=api.request(url,payload,**kwargs)
            if url.endswith('/analyst'):value['answer']=''
            return value
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'private'
            with patch.object(trial,'json_request',side_effect=request),patch.object(trial.soak,'host_memory',side_effect=memory), \
                 patch.object(trial,'time',clock),redirect_stdout(io.StringIO()):
                self.assertEqual(trial.run(options(out)),1)
            self.assertEqual(len(api.posts),1);self.assertEqual(api.exports,[])
            self.assertIn('missing-answer',json.loads((out/'receipt.json').read_text())['failure'])

    def test_readiness_rejects_wrong_source_missing_clock_and_denied_admission(self):
        for case in ['source','clock','admission','memory','native-revision']:
            clock=FakeClock();api=FakeAPI(clock)
            def request(url,payload=None,**kwargs):
                value=api.request(url,payload,**kwargs)
                if '/snapshot' in url:
                    if case=='source':value['sources'][0]['id']='other-source'
                    if case=='clock':value['sources'][0].pop('lastSourceTimeNs')
                if case=='admission' and '/workload-admission' in url:value['decision']='queue'
                if case=='native-revision' and '/health' in url:value['nativeAnalyticsStatus']['requestedRevision']=None
                return value
            with self.subTest(case=case),patch.object(trial,'json_request',side_effect=request), \
                 patch.object(trial.soak,'host_memory',return_value={**memory(),'availableGiB':19} if case=='memory' else memory()):
                with self.assertRaises(trial.TrialFailure):trial.preflight(options())
            self.assertEqual(api.posts,[])

    def test_stalled_or_changed_clock_epoch_prevents_new_question(self):
        clock=FakeClock();api=FakeAPI(clock)
        with patch.object(trial,'json_request',side_effect=api.request),patch.object(trial.soak,'host_memory',side_effect=memory):
            _,previous=trial.preflight(options())
            with self.assertRaisesRegex(trial.TrialFailure,'clock-not-advancing'):trial.preflight(options(),previous)
            clock.seconds+=60
            with self.assertRaisesRegex(trial.TrialFailure,'epoch-changed'):
                trial.preflight(options(),{**previous,'sessionId':'a-different-epoch'})
        self.assertEqual(api.posts,[])

    def test_new_window_reusing_identical_media_uri_aborts_without_third_ask(self):
        clock=FakeClock();api=FakeAPI(clock)
        def request(url,payload=None,**kwargs):
            value=api.request(url,payload,**kwargs)
            if '/evidence?' in url:value['videoUrl']='/vst/storage/temp_files/always-same.mp4'
            return value
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)/'private'
            with patch.object(trial,'json_request',side_effect=request),patch.object(trial,'fetch_clip',side_effect=api.fetch), \
                 patch.object(trial.soak,'host_memory',side_effect=memory),patch.object(trial,'time',clock),redirect_stdout(io.StringIO()):
                self.assertEqual(trial.run(options(out)),1)
            self.assertEqual(len(api.posts),2)
            self.assertEqual(json.loads((out/'receipt.json').read_text())['failure'],'different-window-reused-evidence-uri')

    def test_invalid_window_time_and_missing_answer_evidence_fail(self):
        window={'startTime':'2026-10-22T05:29:14Z','endTime':'2026-10-22T05:29:19Z'}
        wall=trial.timestamp(window['endTime']);base={'answer':'text','grounded':True,'evidenceTools':['tool'],'observedWindow':window}
        for patch_value in [{'answer':''},{'grounded':False},{'evidenceTools':[]},
                            {'observedWindow':{**window,'startTime':'invalid'}},
                            {'observedWindow':{**window,'endTime':'2026-10-22T05:29:30Z'}}]:
            with self.subTest(patch_value=patch_value),self.assertRaises(trial.TrialFailure):
                trial.validate_answer({**base,**patch_value},wall)
        with self.assertRaisesRegex(trial.TrialFailure,'not-new'):trial.validate_answer(base,wall,window)

    def test_cli_requires_opt_in_exact_uuid_and_safe_timing(self):
        base=['trial','--site-id','cpu-control','--source-id',SID,'--allow-real-ask']
        for argv in [base[:-1],base+['--between-calls-seconds','59'],base+['--timeout-seconds','56'],
                     base+['--source-id','not-a-uuid']]:
            with self.subTest(argv=argv),patch.object(sys,'argv',argv),redirect_stdout(io.StringIO()),patch('sys.stderr',new=io.StringIO()):
                with self.assertRaises(SystemExit):trial.arguments()
        with patch.object(sys,'argv',base):self.assertEqual(trial.arguments().vss_origin,'http://127.0.0.1:7777')


class MediaSafetyControls(unittest.TestCase):
    def test_only_exact_routes_same_origin_or_explicit_local_alias(self):
        args=options();good='/vst/storage/temp_files/clip.mp4';key='/api/vision/evidence-media?key='+'a'*64
        self.assertEqual(trial.safe_media_url(key,args.vss_origin),args.vss_origin+key)
        for value in ['http://evil.invalid'+good,'http://172.17.0.1:7777'+good,'//evil.invalid'+good,
                      '/vst/storage/temp_files/../secret.mp4','/vst/storage/temp_files/%2e%2e/secret.mp4',
                      '/vst/storage/temp_files/clip.mp4?token=private','/api/vision/evidence-media?key=bad',
                      'http://user:private@127.0.0.1:7777'+good,'http://172.17.0.1:30888'+good]:
            with self.subTest(value=value),self.assertRaises(trial.TrialFailure):trial.safe_media_url(value,args.vss_origin)
        self.assertEqual(trial.safe_media_url('http://172.17.0.1:7777'+good,args.vss_origin,['172.17.0.1']),args.vss_origin+good)

    def test_clip_limit_checks_header_and_stream_without_decoding(self):
        args=options();url=args.vss_origin+'/vst/storage/temp_files/clip.mp4'
        class Response(io.BytesIO):
            def __init__(self,body,length=None):
                super().__init__(body);self.headers=Message();self.headers['Content-Type']='video/mp4'
                if length is not None:self.headers['Content-Length']=str(length)
            def getcode(self):return 200
            def geturl(self):return url
        valid=b'\x00\x00\x00\x18ftypisom'+b'x'*32
        for body,length in [(valid,trial.MAX_CLIP_BYTES+1),(valid+b'x'*60,None)]:
            response=Response(body,length)
            with self.subTest(length=length),patch.object(trial,'MAX_CLIP_BYTES',64), \
                 patch.object(trial.urllib.request,'build_opener') as opener:
                opener.return_value.open.return_value=response
                with self.assertRaisesRegex(trial.TrialFailure,'size-limit'):trial.fetch_clip(url,args)
        with patch.object(trial.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=Response(valid,len(valid))
            result=trial.fetch_clip(url,args)
        self.assertEqual(result['sha256'],hashlib.sha256(valid).hexdigest());self.assertEqual(result['bytes'],len(valid))

    def test_redirect_is_rejected_instead_of_opening_its_target(self):
        args=options();url=args.vss_origin+'/vst/storage/temp_files/clip.mp4'
        self.assertIsNone(trial.NoRedirect().redirect_request(None,None,302,'redirect',{},'http://external.invalid/clip.mp4'))
        with patch.object(trial.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError(url,302,'redirect',{},None)
            with self.assertRaisesRegex(trial.TrialFailure,'http-status-302'):trial.fetch_clip(url,args)
            self.assertEqual(opener.return_value.open.call_count,1)


if __name__=='__main__':unittest.main()
