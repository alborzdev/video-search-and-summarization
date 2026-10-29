"""Offline processed-preview wire/progress controls. No sockets or GPU jobs."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import soak
from test_soak import options,sample


def frame(source='camera-one',sequence=0,ns=None):
    ns=1700000000000000000+sequence*100000000 if ns is None else ns
    item={'id':source,'width':1920,'height':1080,'sessionId':'stable-session','sourceSessionId':'native-session',
        'sequence':str(sequence),'lastSourceTimeNs':str(ns),'modelRevision':'model-engine-sha','timestampBasis':'source-rtcp'}
    return {'schemaVersion':'city.preview.v1','sourceId':source,'sessionId':'stable-session','sourceSessionId':'native-session',
        'sequence':str(sequence),'sourceTimeNs':str(ns),'modelRevision':'model-engine-sha','timestampBasis':'source-rtcp',
        'image':{'width':1920,'height':1080,'jpegWidth':960,'jpegHeight':540,'mimeType':'image/jpeg'},
        'provenance':{'kind':'native-post-inference-exact-frame','correlation':'source-session-sequence-time',
            'clockAlignment':'source-frame-exact','browserClockVerified':False},
        'snapshot':{'siteId':'cpu-control','mode':'live','sources':[item],'sourceTimeNs':str(ns),
            'tracks':[],'zones':[],'events':[],'rules':[],'metrics':[]}}


def jpeg(width=960,height=540):
    return b'\xff\xd8\xff\xc0'+struct.pack('>HBHHBBBB',11,8,height,width,1,1,0x11,0)+b'\xff\xd9'


def envelope(dto=None,image=None):
    encoded=json.dumps(frame() if dto is None else dto).encode()
    return struct.pack('>I',len(encoded))+encoded+(jpeg() if image is None else image)


def preview_sample(seconds,sequence=None,published=None,accepted=None):
    row=sample(seconds);sequence=int(seconds*10) if sequence is None else sequence
    published=sequence+1 if published is None else published
    accepted=sequence*2+2 if accepted is None else accepted
    for source in row['snapshot']['sources']:
        source.update(width=1920,height=1080,sourceSessionId='native-session',modelRevision='model-engine-sha')
    row['health']['processedPreview']={'enabled':True,'acceptedFrames':accepted,
        'sources':[{'id':sid,'available':True,'status':'ready'} for sid in options().source_id],
        'nativeDelivery':{'enabled':True,'failed':False,'status':'fresh','deliveryAgeSeconds':.25,
            'sources':[{'sourceId':sid,'published':published,'selected':published+12,'rateDropped':sequence*2,
                'networkQueueDropped':sequence,'postFailed':sequence} for sid in options().source_id]}}
    row['previews']={sid:{**soak.parse_preview_envelope(envelope(frame(sid,sequence)),sid,'cpu-control'),
        'fetchedAtMonotonic':1000+seconds} for sid in options().source_id}
    return row


class BinaryEnvelopeControls(unittest.TestCase):
    def test_exact_pair_keeps_only_identity_geometry_and_hashes(self):
        body=envelope();value=soak.parse_preview_envelope(body,'camera-one','cpu-control')
        self.assertEqual((value['jpegWidth'],value['jpegHeight']),(960,540))
        self.assertEqual(value['jpegBytes'],len(jpeg()));self.assertEqual(value['envelopeBytes'],len(body))
        self.assertEqual(len(value['jpegSha256']),64);self.assertNotIn('snapshot',value)
        self.assertNotIn('tracks',value);self.assertFalse(any(isinstance(v,bytes) for v in value.values()))

    def test_bad_prefix_json_and_size_are_rejected(self):
        cases=[b'bad',struct.pack('>I',soak.PREVIEW_JSON_MAX+1)+b'{}'+jpeg(),
            struct.pack('>I',3)+b'{x}'+jpeg(),b'x'*(soak.PREVIEW_ENVELOPE_MAX+1)]
        for body in cases:
            with self.subTest(length=len(body)),self.assertRaises(soak.SoakFailure):
                soak.parse_preview_envelope(body,'camera-one','cpu-control')

    def test_source_site_native_engine_session_model_time_and_sequence_mismatch_rejected(self):
        mutations=[('source',lambda d:d.update(sourceId='other')),
            ('site',lambda d:d['snapshot'].update(siteId='other')),
            ('native session',lambda d:d.update(sourceSessionId='other')),
            ('engine session',lambda d:d.update(sessionId='other')),
            ('model',lambda d:d.update(modelRevision='other')),
            ('time',lambda d:d.update(sourceTimeNs='1700000000000000001')),
            ('sequence',lambda d:d.update(sequence='1')),
            ('clock basis',lambda d:d.update(timestampBasis='arrival-pts-unsynchronized'))]
        for label,change in mutations:
            dto=frame();change(dto)
            with self.subTest(label=label),self.assertRaises(soak.SoakFailure):
                soak.parse_preview_envelope(envelope(dto),'camera-one','cpu-control')

    def test_provenance_never_accepts_physical_clock_claim(self):
        for key,value in [('kind','nearest-arrival'),('browserClockVerified',True),('clockAlignment','utc')]:
            dto=frame();dto['provenance'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(soak.SoakFailure,'provenance'):
                soak.parse_preview_envelope(envelope(dto),'camera-one','cpu-control')

    def test_original_jpeg_sof_aspect_and_markers_are_checked(self):
        cases=[]
        dto=frame();dto['image']['width']=1000;cases.append(envelope(dto))
        dto=frame();dto['image']['jpegWidth']=900;cases.append(envelope(dto))
        cases.extend([envelope(image=jpeg(800,450)),envelope(image=jpeg()[:-2]),envelope(image=b'x'*(soak.PREVIEW_JPEG_MAX+1))])
        for body in cases:
            with self.subTest(size=len(body)),self.assertRaises(soak.SoakFailure):
                soak.parse_preview_envelope(body,'camera-one','cpu-control')

    def test_wrong_track_session_and_negative_uncertainty_rejected(self):
        dto=frame();dto['snapshot']['tracks']=[{'sourceId':'camera-one','sessionId':'other','bboxPx':[1,2,3,4]}]
        with self.assertRaisesRegex(soak.SoakFailure,'track-identity'):
            soak.parse_preview_envelope(envelope(dto),'camera-one','cpu-control')
        dto['snapshot']['tracks'][0].update(sessionId='stable-session',positionUncertaintyM=-.1)
        with self.assertRaisesRegex(soak.SoakFailure,'negative-or-invalid'):
            soak.parse_preview_envelope(envelope(dto),'camera-one','cpu-control')


class PreviewProgressControls(unittest.TestCase):
    def test_healthy_advancement_with_display_drops_is_not_failure(self):
        checks=soak.Checks(options(require_processed_preview=True))
        for second in range(0,151,5):result=checks.evaluate(preview_sample(second))
        self.assertTrue(result['processedPreview']['ready'])
        self.assertEqual(result['processedPreview']['epochResetsDuringWarmup'],0)
        self.assertGreater(result['processedPreview']['sources']['camera-one']['nativeCounters']['postFailed'],0)
        self.assertEqual(result['processedPreview']['sources']['camera-two']['successfulFetches'],31)

    def test_default_mode_ignores_unavailable_preview(self):
        checks=soak.Checks(options())
        checks.evaluate(sample(0));result=checks.evaluate(sample(15))
        self.assertNotIn('processedPreview',result)

    def test_ready_source_and_native_freshness_failures(self):
        changes=[lambda p:p['sources'][1].update(id='other'),
            lambda p:p['sources'][0].update(available=False,status='stale'),
            lambda p:p['nativeDelivery'].update(failed=True),
            lambda p:p['nativeDelivery'].update(status='stale',deliveryAgeSeconds=6),
            lambda p:p['nativeDelivery']['sources'].pop()]
        for change in changes:
            checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0));bad=preview_sample(15)
            change(bad['health']['processedPreview'])
            with self.subTest(change=change),self.assertRaisesRegex(soak.SoakFailure,'not-ready'):checks.evaluate(bad)

    def test_accepted_and_per_source_published_stall_despite_ready_frames(self):
        for key in ('accepted','published'):
            checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0))
            frozen=2 if key=='accepted' else 1
            with self.subTest(key=key),self.assertRaisesRegex(soak.SoakFailure,key+'-counter-stalled'):
                checks.evaluate(preview_sample(15,**{key:frozen}))

    def test_binary_identity_stall_despite_counters_advancing(self):
        checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0))
        with self.assertRaisesRegex(soak.SoakFailure,'binary-identity-stalled'):
            checks.evaluate(preview_sample(15,sequence=0,published=150,accepted=300))

    def test_binary_epoch_model_and_counter_resets_are_explicit(self):
        for kind in ('counter','native-session','model'):
            checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0,sequence=50))
            bad=preview_sample(15)
            if kind=='counter':bad['health']['processedPreview']['nativeDelivery']['sources'][0]['published']=1
            else:
                field='sourceSessionId' if kind=='native-session' else 'modelRevision'
                bad['snapshot']['sources'][0][field]='new-epoch';bad['previews']['camera-one'][field]='new-epoch'
            with self.subTest(kind=kind),self.assertRaisesRegex(soak.SoakFailure,'epoch-reset'):checks.evaluate(bad)

    def test_reset_during_grace_is_counted_and_can_recover(self):
        checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0,sequence=50))
        reset=preview_sample(5)
        for source in reset['snapshot']['sources']:source['sourceSessionId']='new-native'
        for value in reset['previews'].values():value['sourceSessionId']='new-native'
        result=checks.evaluate(reset)
        self.assertGreater(result['processedPreview']['epochResetsDuringWarmup'],0)
        recovered=preview_sample(15)
        for source in recovered['snapshot']['sources']:source['sourceSessionId']='new-native'
        for value in recovered['previews'].values():value['sourceSessionId']='new-native'
        self.assertTrue(checks.evaluate(recovered)['processedPreview']['ready'])

    def test_increasing_sequence_with_duplicate_source_timestamp_is_distinct(self):
        checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0))
        row=preview_sample(15)
        for sid in options().source_id:
            row['previews'][sid]={**soak.parse_preview_envelope(envelope(frame(sid,150,1700000000000000000)),sid,'cpu-control'),
                'fetchedAtMonotonic':1015}
        self.assertTrue(checks.evaluate(row)['processedPreview']['ready'])

    def test_same_sequence_cannot_claim_another_timestamp(self):
        checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0))
        row=preview_sample(15,sequence=0,published=150,accepted=300)
        for sid in options().source_id:
            row['previews'][sid]={**soak.parse_preview_envelope(envelope(frame(sid,0,1700000000000000001)),sid,'cpu-control'),
                'fetchedAtMonotonic':1015}
        with self.assertRaisesRegex(soak.SoakFailure,'conflicting-identity'):checks.evaluate(row)

    def test_latest_binary_must_match_current_source_context(self):
        checks=soak.Checks(options(require_processed_preview=True));checks.evaluate(preview_sample(0));bad=preview_sample(15)
        bad['previews']['camera-two']['modelRevision']='old-model'
        with self.assertRaisesRegex(soak.SoakFailure,'current-source-context'):checks.evaluate(bad)


class BoundedHttpControls(unittest.TestCase):
    def response(self,body,status=200,headers=None):
        response=MagicMock();response.status=status
        values={'Content-Type':'application/vnd.connecttech.city-frame','Content-Length':str(len(body)),**(headers or {})}
        response.getheader.side_effect=lambda key,default=None:values.get(key,default)
        response.read1.side_effect=[body[:100],body[100:],b'']
        return response

    def test_get_is_exact_ui_origin_path_bounded_and_no_redirect_follow(self):
        body=envelope();connection=MagicMock();connection.getresponse.return_value=self.response(body)
        with patch.object(soak.http.client,'HTTPConnection',return_value=connection) as factory:
            self.assertEqual(soak.preview_request('http://localhost:7777','camera-one'),body)
        factory.assert_called_once_with('localhost',7777,timeout=3)
        self.assertEqual(connection.request.call_args.args[:2],('GET','/api/vision/city/preview/camera-one'))
        connection.close.assert_called_once()
        connection.getresponse.return_value=self.response(b'',status=302,headers={'Location':'http://elsewhere'})
        with patch.object(soak.http.client,'HTTPConnection',return_value=connection),self.assertRaisesRegex(soak.SoakFailure,'status-302'):
            soak.preview_request('http://localhost:7777','camera-one')

    def test_declared_and_streamed_oversize_timeout_and_waiting(self):
        for mode in ('declared','streamed','timeout','waiting'):
            connection=MagicMock();response=self.response(envelope())
            if mode=='declared':response=self.response(b'',headers={'Content-Length':str(soak.PREVIEW_ENVELOPE_MAX+1)})
            if mode=='streamed':
                response=self.response(b'',headers={'Content-Length':None});response.read1.side_effect=[b'x'*(soak.PREVIEW_ENVELOPE_MAX+1)]
            if mode=='timeout':response.read1.side_effect=TimeoutError()
            if mode=='waiting':response.status=204
            connection.getresponse.return_value=response
            with self.subTest(mode=mode),patch.object(soak.http.client,'HTTPConnection',return_value=connection):
                if mode=='waiting':self.assertIsNone(soak.preview_request('http://localhost:7777','camera-one'))
                else:
                    with self.assertRaises(soak.SoakFailure):soak.preview_request('http://localhost:7777','camera-one')
            connection.close.assert_called_once()

    def test_cli_opt_in_and_at_most_five_second_sampling(self):
        argv=['soak.py','--site-id','cpu-control','--source-id','camera-one','--source-id','camera-two','--observations','/tmp/unopened']
        with patch.object(sys,'argv',argv):self.assertFalse(soak.arguments().require_processed_preview)
        with patch.object(sys,'argv',argv+['--require-processed-preview']):self.assertTrue(soak.arguments().require_processed_preview)
        with patch.object(sys,'argv',argv+['--require-processed-preview','--sample-every-seconds','6']),patch('sys.stderr'):
            with self.assertRaises(SystemExit):soak.arguments()


if __name__=='__main__':unittest.main()
