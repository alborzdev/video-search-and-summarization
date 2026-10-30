#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observe two active Smart City sources; never start a detector or GPU worker.

Optional real UI Ask requests require --ask-every-seconds. Optional failure
pause uses only the two specified sources' canonical Agent analysis controls.
An explicit --cancel-file marker stops observation without pausing those sources.
"""
from __future__ import annotations
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import struct
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
ID=re.compile(r'^[A-Za-z0-9._:-]{1,160}$')
# Pin the source at import, before monitoring or optional request workers start.
# A later edit must not change the provenance of an already executing monitor.
MONITOR_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PREVIEW_JSON_MAX=512*1024
PREVIEW_JPEG_MAX=2*1024*1024
PREVIEW_ENVELOPE_MAX=4+PREVIEW_JSON_MAX+PREVIEW_JPEG_MAX
PREVIEW_INTERVAL_SECONDS=5
PREVIEW_TIMEOUT_SECONDS=3
PREVIEW_STALE_SECONDS=5


class SoakFailure(RuntimeError):pass


class SoakCancelled(SoakFailure):pass


def native_sei_source_clock(source):
    """Strict public DTO proof; this validates AU handoff provenance, not exposure."""
    if not isinstance(source,dict):return False
    proof=source.get('sourceClockEvidence')
    if (source.get('timestampBasis')!='source-native-sei' or source.get('sourceClockMode')!='source-native-sei'
            or source.get('browserClockVerified') is not False or not isinstance(proof,dict)
            or set(proof)!={'schemaVersion','method','correlation','captureTimeNs','auPtsNs','frameCounter'}
            or proof.get('schemaVersion')!='city.source-native-sei.v1'
            or proof.get('method')!='isaac-native-sei-wall-capture' or proof.get('correlation')!='exact-au-pts'):
        return False
    for key in ('captureTimeNs','auPtsNs','frameCounter'):
        value=proof.get(key)
        if (not isinstance(value,str) or not value.isascii() or not value.isdigit() or len(value)>20
                or int(value)>(2**64-1 if key=='frameCounter' else 2**63-1)):
            return False
    return (int(proof['captureTimeNs'])>0 and proof['captureTimeNs']==source.get('lastSourceTimeNs')
        and proof['auPtsNs']==source.get('rawSourcePtsNs'))


def check_cancellation(args):
    path=getattr(args,'cancel_file',None)
    if path is not None and path.is_file():raise SoakCancelled('monitor-cancelled-by-request')


def utc():return datetime.now(timezone.utc).isoformat()


def file_sha(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def atomic_json(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=f'.{path.name}.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as handle:
            json.dump(payload,handle,allow_nan=False,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)


def origin(value):
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError('Use an HTTP origin without credentials, query or fragment')
    if parsed.path not in ('','/'):
        raise argparse.ArgumentTypeError('Use an origin without an API path')
    return value.rstrip('/')


def json_request(url,payload=None,timeout=8,cap=1024*1024):
    request=urllib.request.Request(url,data=None if payload is None else json.dumps(payload).encode(),
        method='GET' if payload is None else 'POST',headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            body=response.read(cap+1)
            if len(body)>cap:raise SoakFailure('http-response-body-limit')
            return json.loads(body)
    except HTTPError as exc:raise SoakFailure(f'http-status-{exc.code}') from None
    except (URLError,TimeoutError,OSError):raise SoakFailure('http-unavailable-or-timeout') from None
    except ValueError:raise SoakFailure('http-invalid-json') from None



def preview_request(vss_origin,source_id):
    """Same-origin bounded binary GET; http.client deliberately never redirects."""
    parsed=urlsplit(origin(vss_origin));connection=None;deadline=time.monotonic()+PREVIEW_TIMEOUT_SECONDS
    try:
        factory=http.client.HTTPSConnection if parsed.scheme=='https' else http.client.HTTPConnection
        connection=factory(parsed.hostname,parsed.port,timeout=PREVIEW_TIMEOUT_SECONDS)
        connection.request('GET','/api/vision/city/preview/'+quote(source_id,safe=''),
                           headers={'Accept':'application/vnd.connecttech.city-frame'})
        if connection.sock:connection.sock.settimeout(max(.001,deadline-time.monotonic()))
        response=connection.getresponse()
        if response.status==204:return None
        if response.status!=200:raise SoakFailure(f'preview-http-status-{response.status}')
        if response.getheader('Content-Type','').split(';',1)[0].strip()!='application/vnd.connecttech.city-frame':
            raise SoakFailure('preview-http-content-type')
        declared=response.getheader('Content-Length')
        if declared is not None and (not re.fullmatch(r'[0-9]{1,10}',declared) or int(declared)>PREVIEW_ENVELOPE_MAX):
            raise SoakFailure('preview-http-body-limit')
        chunks=[];size=0
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise SoakFailure('preview-http-deadline')
            if connection.sock:connection.sock.settimeout(remaining)
            chunk=response.read1(min(65536,PREVIEW_ENVELOPE_MAX-size+1))
            if not chunk:break
            size+=len(chunk)
            if size>PREVIEW_ENVELOPE_MAX:raise SoakFailure('preview-http-body-limit')
            chunks.append(chunk)
        if declared is not None and size!=int(declared):raise SoakFailure('preview-http-truncated')
        return b''.join(chunks)
    except (OSError,TimeoutError,http.client.HTTPException):raise SoakFailure('preview-http-unavailable-or-timeout') from None
    finally:
        if connection is not None:connection.close()


def preview_integer(value,name,maximum=9223372036854775807):
    if isinstance(value,bool) or not isinstance(value,(str,int)) or not re.fullmatch(r'[0-9]{1,30}',str(value)) or int(value)>maximum:
        raise SoakFailure('preview-invalid-'+name)
    return int(value)


def preview_jpeg_dimensions(jpeg):
    if not 4<=len(jpeg)<=PREVIEW_JPEG_MAX or jpeg[:2]!=b'\xff\xd8' or jpeg[-2:]!=b'\xff\xd9':
        raise SoakFailure('preview-jpeg-markers-or-size')
    offset=2
    while offset+4<=len(jpeg):
        if jpeg[offset]!=255:raise SoakFailure('preview-jpeg-marker')
        while offset<len(jpeg) and jpeg[offset]==255:offset+=1
        if offset>=len(jpeg):break
        marker=jpeg[offset];offset+=1
        if marker in (0xd8,0xd9,0xda):break
        if marker==1 or 0xd0<=marker<=0xd7:continue
        if offset+2>len(jpeg):break
        length=int.from_bytes(jpeg[offset:offset+2],'big')
        if length<2 or offset+length>len(jpeg):raise SoakFailure('preview-jpeg-segment')
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
            if length<8:raise SoakFailure('preview-jpeg-sof')
            height,width=struct.unpack('>HH',jpeg[offset+3:offset+7])
            if min(width,height)<1 or max(width,height)>16384:raise SoakFailure('preview-jpeg-dimensions')
            return width,height
        offset+=length
    raise SoakFailure('preview-jpeg-dimensions-unavailable')


def parse_preview_envelope(body,source_id,site_id):
    """Independent wire validation; return only safe identity, geometry and hashes."""
    if not 8<=len(body)<=PREVIEW_ENVELOPE_MAX:raise SoakFailure('preview-envelope-size')
    length=struct.unpack('>I',body[:4])[0]
    if not 0<length<=PREVIEW_JSON_MAX or length+4>=len(body):raise SoakFailure('preview-envelope-prefix')
    try:
        def invalid_constant(_):raise ValueError('nonfinite')
        dto=json.loads(body[4:4+length].decode('utf-8'),parse_constant=invalid_constant)
        snapshot=dto['snapshot'];sources=snapshot['sources'];image=dto['image'];proof=dto['provenance']
        if not isinstance(sources,list) or len(sources)!=1:raise SoakFailure('preview-matched-source-count')
        source=sources[0]
        if dto.get('schemaVersion')!='city.preview.v1' or dto.get('sourceId')!=source_id or source.get('id')!=source_id:
            raise SoakFailure('preview-source-or-schema-mismatch')
        if snapshot.get('siteId')!=site_id or snapshot.get('mode')!='live':raise SoakFailure('preview-site-or-mode-mismatch')
        for key in ('sessionId','sourceSessionId','modelRevision'):
            value=dto.get(key)
            if not isinstance(value,str) or not 1<=len(value)<=512 or source.get(key)!=value:
                raise SoakFailure('preview-matched-'+key)
        sequence=preview_integer(dto['sequence'],'sequence',10**30-1)
        ns=preview_integer(dto['sourceTimeNs'],'source-time')
        if preview_integer(source['sequence'],'matched-sequence',10**30-1)!=sequence or str(source['lastSourceTimeNs'])!=str(dto['sourceTimeNs']):
            raise SoakFailure('preview-matched-clock-or-sequence')
        if str(snapshot.get('sourceTimeNs'))!=str(dto['sourceTimeNs']) or dto.get('timestampBasis')!=source.get('timestampBasis') or not source.get('timestampBasis'):
            raise SoakFailure('preview-matched-clock-basis')
        if source.get('timestampBasis')=='source-native-sei' and (
                not native_sei_source_clock(source) or dto.get('sourceClockEvidence')!=source.get('sourceClockEvidence')):
            raise SoakFailure('preview-native-sei-proof-mismatch')
        if proof.get('kind')!='native-post-inference-exact-frame' or proof.get('correlation')!='source-session-sequence-time' or proof.get('clockAlignment')!='source-frame-exact' or proof.get('browserClockVerified') is not False:
            raise SoakFailure('preview-provenance-mismatch')
        dimensions=[image[key] for key in ('width','height','jpegWidth','jpegHeight')]
        if any(type(v) is not int or not 1<=v<=16384 for v in dimensions) or image.get('mimeType')!='image/jpeg':
            raise SoakFailure('preview-image-geometry')
        width,height,jpeg_width,jpeg_height=dimensions
        if source.get('width')!=width or source.get('height')!=height or jpeg_width>width or jpeg_height>height or abs(jpeg_width*height-jpeg_height*width)>max(width,height):
            raise SoakFailure('preview-matched-image-geometry')
        if any(not isinstance(snapshot.get(key),list) for key in ('tracks','zones','events','rules','metrics')):
            raise SoakFailure('preview-matched-snapshot-schema')
        valid_uncertainty(snapshot['tracks'])
        for track in snapshot['tracks']:
            box=track.get('bboxPx')
            if track.get('sourceId')!=source_id or track.get('sessionId')!=dto['sessionId'] or not isinstance(box,list) or len(box)!=4 or not all(finite(v) for v in box):
                raise SoakFailure('preview-matched-track-identity')
        jpeg=body[4+length:]
        if preview_jpeg_dimensions(jpeg)!=(jpeg_width,jpeg_height):raise SoakFailure('preview-jpeg-sof-geometry-mismatch')
        return {'available':True,'sourceId':source_id,'sessionId':dto['sessionId'],'sourceSessionId':dto['sourceSessionId'],
            'sequence':str(sequence),'sourceTimeNs':str(ns),'timestampBasis':dto['timestampBasis'],'modelRevision':dto['modelRevision'],'width':width,'height':height,
            'jpegWidth':jpeg_width,'jpegHeight':jpeg_height,'envelopeBytes':len(body),'jpegBytes':len(jpeg),
            'envelopeSha256':hashlib.sha256(body).hexdigest(),'jpegSha256':hashlib.sha256(jpeg).hexdigest()}
    except (KeyError,TypeError,ValueError,AttributeError,UnicodeError):raise SoakFailure('preview-envelope-json-or-schema') from None


class ProcessedPreviewChecks:
    def __init__(self,source_ids):
        self.source_ids=set(source_ids);self.accepted=None;self.accepted_at=None
        self.sources={};self.epoch_resets=0;self.successful_fetches={sid:0 for sid in source_ids}

    def evaluate(self,sample,warm):
        now=sample['monotonicSeconds'];health=sample['health'].get('processedPreview',{})
        native=health.get('nativeDelivery',{});configured={s['id']:s for s in sample['snapshot'].get('sources',[])}
        ready=health.get('sources',[]);delivery=native.get('sources',[])
        if not isinstance(ready,list) or not isinstance(delivery,list):raise SoakFailure('preview-health-schema')
        if any(not isinstance(row,dict) for row in ready+delivery):raise SoakFailure('preview-health-schema')
        ready_ids=[s.get('id') for s in ready];delivery_ids=[s.get('sourceId') for s in delivery]
        healthy=(health.get('enabled') is True and len(ready_ids)==len(self.source_ids) and set(ready_ids)==self.source_ids
            and all(s.get('available') is True and s.get('status')=='ready' for s in ready)
            and native.get('enabled') is True and native.get('status')=='fresh' and native.get('failed') is False
            and finite(native.get('deliveryAgeSeconds')) and 0<=native['deliveryAgeSeconds']<=PREVIEW_STALE_SECONDS
            and len(delivery_ids)==len(self.source_ids) and set(delivery_ids)==self.source_ids)
        if not healthy:
            if warm:raise SoakFailure('processed-preview-or-native-delivery-not-ready')
            return {'ready':False,'sources':{},'epochResetsDuringWarmup':self.epoch_resets}
        accepted=preview_integer(health.get('acceptedFrames'),'accepted-counter')
        if self.accepted is not None and accepted<self.accepted:
            self.epoch_resets+=1
            if warm:raise SoakFailure('preview-accepted-counter-epoch-reset')
            self.accepted_at=now
        if self.accepted is None or accepted>self.accepted:self.accepted_at=now
        self.accepted=accepted
        if warm and (accepted==0 or now-self.accepted_at>=PREVIEW_STALE_SECONDS):raise SoakFailure('preview-accepted-counter-stalled')
        rows={s['sourceId']:s for s in delivery};result={}
        for sid in self.source_ids:
            row=rows[sid];published=preview_integer(row.get('published'),'published-counter')
            current=configured[sid];record=sample.get('previews',{}).get(sid,{})
            if record.get('available') is not True:
                if warm:raise SoakFailure('preview-binary-unavailable:'+sid)
                continue
            if any(record.get(key)!=current.get(key) for key in ('sessionId','sourceSessionId','modelRevision','width','height')):
                raise SoakFailure('preview-binary-current-source-context-mismatch:'+sid)
            identity=(record['sessionId'],record['sourceSessionId'],record['modelRevision'])
            state=self.sources.get(sid)
            if state is None:
                state={'epoch':identity,'sequence':int(record['sequence']),'ns':int(record['sourceTimeNs']),
                    'published':published,'publishedAt':now,'identityAt':now,'fetchAt':None}
                self.sources[sid]=state
            if identity!=state['epoch'] or published<state['published']:
                self.epoch_resets+=1
                if warm:raise SoakFailure('preview-source-or-counter-epoch-reset:'+sid)
                state.update(epoch=identity,sequence=int(record['sequence']),ns=int(record['sourceTimeNs']),published=published,
                             publishedAt=now,identityAt=now,fetchAt=None)
            seq=int(record['sequence']);ns=int(record['sourceTimeNs'])
            if seq<state['sequence'] or ns<state['ns']:raise SoakFailure('preview-binary-identity-backwards:'+sid)
            if seq==state['sequence'] and ns!=state['ns']:raise SoakFailure('preview-binary-conflicting-identity:'+sid)
            if seq>state['sequence']:state['identityAt']=now
            if published>state['published']:state['publishedAt']=now
            if record.get('fetchedAtMonotonic')!=state['fetchAt']:
                self.successful_fetches[sid]+=1;state['fetchAt']=record.get('fetchedAtMonotonic')
            if warm and (published==0 or now-state['publishedAt']>=PREVIEW_STALE_SECONDS):raise SoakFailure('preview-published-counter-stalled:'+sid)
            if warm and now-state['identityAt']>=PREVIEW_STALE_SECONDS:raise SoakFailure('preview-binary-identity-stalled:'+sid)
            state.update(sequence=seq,ns=ns,published=published)
            counters={key:row.get(key) for key in ('selected','encoded','published','rateDropped','sourceQueueOverruns',
                'identityMissing','identityEvicted','geometryMismatch','oversizeDropped','networkQueueDropped','postFailed','pendingDropped')}
            for key,value in counters.items():
                if value is not None:preview_integer(value,'native-'+key)
            result[sid]={**record,'nativeCounters':counters,'identityStalledForSeconds':now-state['identityAt'],
                'publishedStalledForSeconds':now-state['publishedAt'],'successfulFetches':self.successful_fetches[sid]}
        return {'ready':len(result)==len(self.source_ids),'acceptedFrames':accepted,'nativeDeliveryAgeSeconds':native['deliveryAgeSeconds'],
                'sources':result,'epochResetsDuringWarmup':self.epoch_resets}


def valid_uncertainty(objects):
    for item in objects:
        uncertainty=item.get('positionUncertaintyM')
        if uncertainty is not None and (not finite(uncertainty) or uncertainty<0):
            raise SoakFailure('negative-or-invalid-position-uncertainty')


class FrameTail:
    """Bounded incremental reader; adjacent distinct PTS are unique if monotonic."""
    def __init__(self,path,source_ids,site_id,start_at_end=True):
        self.path=Path(path);self.sources=set(source_ids);self.site=site_id
        self.handle=self.path.open('rb');self.stat=os.fstat(self.handle.fileno());self.pending=b''
        self.manifest_path=Path(str(self.path)+'.manifest.json')
        self.rotation_enabled=self.manifest_path.exists();self.generation=None;self.rotations=0;self.rotation_wait_since=None
        if self.rotation_enabled:
            try:
                manifest=self._rotation_manifest()
                self.generation=next((int(item['generation']) for item in manifest['files']
                    if (int(item['device']),int(item['inode']))==(self.stat.st_dev,self.stat.st_ino)),None)
                if self.generation is None:raise SoakFailure('observation-rotation-initial-identity')
            except BaseException:
                self.handle.close();raise
        self.discard_first=False
        if start_at_end:
            if self.stat.st_size:
                self.handle.seek(-1,os.SEEK_END);self.discard_first=self.handle.read(1)!=b'\n'
            self.handle.seek(0,os.SEEK_END)
        self.counts={sid:{'frames':0,'uniquePts':0,'duplicatePts':0,'backwardPts':0,
            'sequenceGaps':0,'sessionChanges':0,'clockRollbacks':0,'lastPts':None,
            'lastNs':None,'lastSequence':None,'session':None,'lastBasis':None} for sid in source_ids}

    def ingest(self,row):
        sid=row.get('sourceId')
        if sid not in self.sources or row.get('siteId')!=self.site:
            raise SoakFailure('observation-source-or-site-mismatch')
        count=self.counts[sid]
        try:
            pts=int(row['rawSourcePtsNs']);ns=int(row['sourceTimeNs']);sequence=int(row['sequence'])
            session=row['sourceSessionId'];basis=row['timestampBasis']
        except (KeyError,TypeError,ValueError):raise SoakFailure('observation-clock-schema') from None
        if min(pts,ns,sequence)<0 or not isinstance(session,str) or not session:
            raise SoakFailure('observation-clock-schema')
        valid_uncertainty(row.get('objects',[]))
        same=count['session']==session
        if count['session'] is not None and not same:count['sessionChanges']+=1
        if same:
            if pts==count['lastPts']:count['duplicatePts']+=1
            elif pts<count['lastPts']:count['backwardPts']+=1
            else:count['uniquePts']+=1
            if sequence!=count['lastSequence']+1:count['sequenceGaps']+=1
            if ns<count['lastNs']:count['clockRollbacks']+=1
        else:count['uniquePts']+=1
        count.update(frames=count['frames']+1,lastPts=pts,lastNs=ns,lastSequence=sequence,
                     session=session,lastBasis=basis)

    def _rotation_manifest(self):
        try:
            with self.manifest_path.open('rb') as handle:raw=handle.read(16385)
            if len(raw)>16384:raise ValueError('size')
            manifest=json.loads(raw)
            if manifest.get('schemaVersion')!='city.observations.rotation.v1':raise ValueError('schema')
            retained=manifest['retainedFiles'];maximum=manifest['maxBytes'];files=manifest['files']
            if type(retained) is not int or not 1<=retained<=8:raise ValueError('retention')
            if type(maximum) is not int or maximum<=0:raise ValueError('maximum')
            def decimal(value):
                if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,30}',value):raise ValueError('integer')
                return int(value)
            generation=decimal(manifest['generation'])
            if generation<1 or not isinstance(files,list) or len(files)!=min(generation,retained+1):raise ValueError('files')
            identities=set()
            for index,item in enumerate(files):
                expected=self.path.name+('' if index==0 else '.'+str(index))
                identity=(decimal(item['device']),decimal(item['inode']))
                if item['name']!=expected or decimal(item['generation'])!=generation-index or generation-index<1 or identity in identities:raise ValueError('identity')
                identities.add(identity)
            return manifest
        except (OSError,ValueError,KeyError,TypeError,AttributeError):
            raise SoakFailure('observation-rotation-invalid-manifest') from None

    def _rotation_busy(self):
        # A writer publishes the new manifest before the first new record. A
        # rename/manifest window may be observed, but cannot mask a lasting fault.
        now=time.monotonic()
        if self.rotation_wait_since is None:self.rotation_wait_since=now
        elif now-self.rotation_wait_since>2:raise SoakFailure('observation-rotation-incomplete')
        return False

    def _advance_rotation(self):
        manifest=self._rotation_manifest();current=int(manifest['generation'])
        if current<self.generation:raise SoakFailure('observation-rotation-generation-rollback')
        entries={int(item['generation']):item for item in manifest['files']}
        own=entries.get(self.generation)
        if own is None:raise SoakFailure('observation-rotation-retention-exceeded')
        if (int(own['device']),int(own['inode']))!=(self.stat.st_dev,self.stat.st_ino):
            raise SoakFailure('observation-rotation-identity-changed')
        if current==self.generation:
            try:observed=self.path.stat()
            except FileNotFoundError:return self._rotation_busy()
            if (observed.st_dev,observed.st_ino)!=(self.stat.st_dev,self.stat.st_ino):return self._rotation_busy()
            if observed.st_size>manifest['maxBytes']:raise SoakFailure('observation-rotation-file-over-limit')
            self.rotation_wait_since=None;return False
        # EOF was observed before reading the manifest. A final record may have
        # arrived on this inode just before the writer sealed it. Drain it first.
        sealed_size=os.fstat(self.handle.fileno()).st_size
        if sealed_size<self.handle.tell():raise SoakFailure('observation-file-replaced-or-truncated')
        if sealed_size>self.handle.tell():return True
        if self.pending or self.discard_first:raise SoakFailure('observation-rotation-partial-line')
        next_entry=entries.get(self.generation+1)
        if next_entry is None:raise SoakFailure('observation-rotation-generation-gap')
        try:
            handle=(self.path.parent/next_entry['name']).open('rb')
        except FileNotFoundError:return self._rotation_busy()
        observed=os.fstat(handle.fileno())
        if (observed.st_dev,observed.st_ino)!=(int(next_entry['device']),int(next_entry['inode'])):
            handle.close();return self._rotation_busy()
        if observed.st_size>manifest['maxBytes']:
            handle.close();raise SoakFailure('observation-rotation-file-over-limit')
        self.handle.close();self.handle=handle;self.stat=observed
        self.generation+=1;self.rotations+=1;self.rotation_wait_since=None
        return True

    def read(self,limit=16*1024*1024):
        if self.rotation_enabled:
            if os.fstat(self.handle.fileno()).st_size<self.handle.tell():
                raise SoakFailure('observation-file-replaced-or-truncated')
        else:
            current=self.path.stat()
            if (current.st_dev,current.st_ino)!=(self.stat.st_dev,self.stat.st_ino) or current.st_size<self.handle.tell():
                raise SoakFailure('observation-file-replaced-or-truncated')
        read=0
        while read<limit:
            block=self.handle.read(min(65536,limit-read))
            if not block:
                if self.rotation_enabled and self._advance_rotation():continue
                break
            read+=len(block);self.pending+=block
            lines=self.pending.split(b'\n');self.pending=lines.pop()
            if self.discard_first and lines:lines=lines[1:];self.discard_first=False
            if len(self.pending)>1024*1024:raise SoakFailure('observation-line-limit')
            for line in lines:
                if len(line)>1024*1024:raise SoakFailure('observation-line-limit')
                if line:
                    try:self.ingest(json.loads(line))
                    except (ValueError,TypeError):raise SoakFailure('observation-invalid-json') from None
        if read==limit:
            remaining=os.fstat(self.handle.fileno()).st_size>self.handle.tell()
            if not remaining and self.rotation_enabled and self._advance_rotation():
                remaining=os.fstat(self.handle.fileno()).st_size>0
            if remaining:raise SoakFailure('observation-reader-cannot-keep-up')
        return {sid:dict(values) for sid,values in self.counts.items()}

    def close(self):self.handle.close()


def host_memory(root,device,wall):
    settings=json.loads((root/f'.{device}/settings.json').read_text())
    guard_path=root/f'.{device}/guard-status.json';guard=json.loads(guard_path.read_text())
    fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    available=int(fields['MemAvailable'].strip().split()[0])/1024**2
    return {'availableGiB':available,'guardAvailableGiB':guard.get('available_gib'),
        'savedReserveGiB':settings.get('reserve_gib'),'guardFloorGiB':guard.get('floor_gib'),
        'guardAgeSeconds':wall-guard.get('time',0)}


def container_state(name,proc=Path('/proc'),cgroup=Path('/sys/fs/cgroup')):
    template='{"id":{{json .Id}},"state":{{json .State}},"restartCount":{{json .RestartCount}}}'
    result=subprocess.run(['docker','inspect','--format',template,name],capture_output=True,text=True,timeout=8)
    if result.returncode:raise SoakFailure(f'container-unavailable:{name}')
    raw=json.loads(result.stdout);state=raw['state'];pid=state['Pid']
    result={'id':raw['id'],'running':state['Running'],'status':state['Status'],
        'restartCount':raw['restartCount'],'oomKilled':state['OOMKilled'],
        'health':state.get('Health',{}).get('Status'),'memoryEvents':None}
    if pid>0:
        paths=(proc/str(pid)/'cgroup').read_text().splitlines()
        relative=next((line.split('::',1)[1] for line in paths if line.startswith('0::')),None)
        if relative is not None:
            directory=(cgroup/relative.lstrip('/')).resolve()
            if not directory.is_relative_to(cgroup.resolve()):raise SoakFailure('unsafe-cgroup-path')
            result['memoryEvents']={key:int(value) for key,value in
                (line.split() for line in (directory/'memory.events').read_text().splitlines())}
            result['memoryCurrentBytes']=int((directory/'memory.current').read_text())
            result['memoryMax']=(directory/'memory.max').read_text().strip()
    return result


class Checks:
    def __init__(self,args):
        self.args=args;self.started=None;self.sources={};self.containers={};self.frame_windows={}
        self.min_available=None;self.reserve_floor=None;self.max_age={};self.max_duplicate={};self.max_duplicate_post_warmup={};self.clock_ratios={}
        self.previews=ProcessedPreviewChecks(args.source_id) if getattr(args,'require_processed_preview',False) else None

    def evaluate(self,sample):
        now=sample['monotonicSeconds'];wall=sample['wallSeconds']
        if self.started is None:self.started=now
        warm=now-self.started>=self.args.warmup_seconds
        memory=sample['memory']
        for key in ('availableGiB','guardAvailableGiB','savedReserveGiB','guardFloorGiB','guardAgeSeconds'):
            if not finite(memory.get(key)):raise SoakFailure('invalid-memory-guard-telemetry')
        floor=memory['savedReserveGiB']
        if floor < 0:raise SoakFailure('invalid-memory-guard-telemetry')
        self.reserve_floor=floor
        if memory['guardFloorGiB']<floor:raise SoakFailure('memory-guard-floor-below-saved-reserve')
        if memory['guardAgeSeconds']>15 or memory['guardAgeSeconds']< -2:raise SoakFailure('memory-guard-telemetry-stale')
        available=min(memory['availableGiB'],memory['guardAvailableGiB'])
        self.min_available=available if self.min_available is None else min(self.min_available,available)
        if available<floor:raise SoakFailure('available-memory-below-reserve')
        for name,state in sample['containers'].items():
            container_health=state.get('health')
            if (not state['running'] or state.get('status')!='running' or state['oomKilled']
                    or container_health not in (None,'healthy','starting')
                    or (container_health=='starting' and warm)):
                raise SoakFailure(f'container-not-healthy:{name}')
            events=state.get('memoryEvents')
            if not isinstance(events,dict):raise SoakFailure(f'cgroup-oom-telemetry-unavailable:{name}')
            if not all(key in events for key in ('oom','oom_kill')):raise SoakFailure(f'cgroup-oom-counters-missing:{name}')
            previous=self.containers.setdefault(name,state)
            if state['id']!=previous['id'] or state['restartCount']!=previous['restartCount']:
                raise SoakFailure(f'container-restarted-or-recreated:{name}')
            if state.get('memoryMax')!=previous.get('memoryMax'):
                raise SoakFailure(f'container-memory-limit-changed:{name}')
            if any(events.get(key,0)>previous['memoryEvents'].get(key,0) for key in ('oom','oom_kill','oom_group_kill')):
                raise SoakFailure(f'cgroup-oom-event:{name}')
        snapshot=sample['snapshot'];health=sample['health']
        if snapshot.get('siteId')!=self.args.site_id or health.get('siteId')!=self.args.site_id or snapshot.get('mode')!='live':
            raise SoakFailure('gateway-site-or-live-mode-mismatch')
        if health.get('status')!='ok':raise SoakFailure('gateway-not-healthy')
        valid_uncertainty(snapshot.get('tracks',[]))
        native=health.get('nativeAnalyticsStatus',{})
        ack=sample['nativeAck']
        active=(native.get('status')=='active' and str(native.get('requestedRevision')).isdigit()
                and str(native.get('requestedRevision'))==str(native.get('appliedRevision'))
                and str(ack.get('revision'))==str(native.get('appliedRevision')) and ack.get('status')=='active'
                and str(snapshot.get('rulesRevision'))==str(native.get('appliedRevision')) and bool(ack.get('counterEpoch'))
                and ack.get('counterEpoch')==native.get('counterEpoch'))
        if warm and not active:raise SoakFailure('native-analytics-ack-not-current-and-active')
        by_id={source['id']:source for source in snapshot.get('sources',[])}
        metrics={}
        for sid in self.args.source_id:
            source=by_id.get(sid)
            if source is None:raise SoakFailure(f'configured-source-missing:{sid}')
            if warm and source.get('status')!='live':raise SoakFailure(f'gateway-source-stale:{sid}')
            try:ns=int(source['lastSourceTimeNs'])
            except (KeyError,TypeError,ValueError):
                if warm:raise SoakFailure(f'source-clock-missing:{sid}') from None
                continue
            session=source.get('sessionId');basis=source.get('timestampBasis')
            state=self.sources.setdefault(sid,{'session':session,'basis':basis,'history':deque(maxlen=256),
                                             'lastNs':ns,'lastAdvance':now})
            if session!=state['session'] or basis!=state['basis']:
                state.update(session=session,basis=basis,history=deque(maxlen=256),lastNs=ns,lastAdvance=now)
                if warm:raise SoakFailure(f'source-clock-epoch-changed:{sid}')
            if ns<state['lastNs']:raise SoakFailure(f'source-clock-backwards:{sid}')
            if ns>state['lastNs']:state['lastAdvance']=now
            state['lastNs']=ns;state['history'].append((now,ns))
            if warm and now-state['lastAdvance']>self.args.stale_seconds:raise SoakFailure(f'source-clock-stalled:{sid}')
            expected_basis=getattr(self.args,'expected_source_clock_basis','source-rtcp')
            if warm and basis!=expected_basis:raise SoakFailure(f'expected-source-clock-basis-required:{sid}')
            if warm and expected_basis=='source-native-sei' and (not native_sei_source_clock(source)
                    or native.get('sourceClockMode')!=expected_basis or ack.get('sourceClockMode')!=expected_basis):
                raise SoakFailure(f'native-sei-clock-proof-or-ack-missing:{sid}')
            history=state['history']
            while len(history)>1 and now-history[1][0]>=self.args.clock_window_seconds:history.popleft()
            elapsed=now-history[0][0];ratio=None
            if elapsed>=self.args.clock_window_seconds:
                ratio=(ns-history[0][1])/1e9/elapsed
                self.clock_ratios[sid]=ratio
                if not self.args.minimum_clock_ratio<=ratio<=self.args.maximum_clock_ratio:
                    raise SoakFailure(f'source-clock-rate-outside-bounds:{sid}')
            trust_utc=(self.args.trust_source_rtcp_utc and basis=='source-rtcp') or (
                getattr(self.args,'trust_native_sei_wall_utc',False) and basis=='source-native-sei' and native_sei_source_clock(source))
            age=wall-ns/1e9 if trust_utc else None
            if age is not None:
                self.max_age[sid]=max(age,self.max_age.get(sid,age))
                if warm and (age>self.args.maximum_source_age_seconds or age< -1):raise SoakFailure(f'trusted-source-utc-age-outside-bounds:{sid}')
            count=sample['frames'][sid]
            window=self.frame_windows.setdefault(sid,deque(maxlen=256));window.append((now,dict(count)))
            while len(window)>1 and now-window[1][0]>=self.args.clock_window_seconds:window.popleft()
            first=window[0][1];n=count['frames']-first['frames'];duplicates=count['duplicatePts']-first['duplicatePts']
            fraction=duplicates/max(1,n)
            self.max_duplicate[sid]=max(fraction,self.max_duplicate.get(sid,0))
            # Match the exact duplicate gate's eligibility, without resetting
            # its rolling window or excluding earlier frames from that window.
            if warm and n>=20:
                self.max_duplicate_post_warmup[sid]=max(fraction,self.max_duplicate_post_warmup.get(sid,0))
            if warm and count['frames']==0:raise SoakFailure(f'no-new-native-frames:{sid}')
            if warm and any(count[key]>0 for key in ('backwardPts','clockRollbacks','sequenceGaps')):
                raise SoakFailure(f'native-frame-clock-or-sequence-error:{sid}')
            if warm and n>=20 and fraction>self.args.maximum_duplicate_fraction:
                raise SoakFailure(f'duplicate-native-pts-fraction:{sid}')
            metrics[sid]={'status':source.get('status'),'basis':basis,'sourceTimeNs':str(ns),'sessionId':session,
                'clockToWallRatio':ratio,'trustedSourceAgeSeconds':age,'clockStalledForSeconds':now-state['lastAdvance'],
                'windowFrames':n,'windowDuplicateFraction':fraction,'frames':count['frames'],'uniquePts':count['uniquePts']}
        result={'sources':metrics,'minimumAvailableGiB':self.min_available,'nativeActive':active,
                'nativeRevision':native.get('appliedRevision'),'warmedUp':warm}
        if self.previews is not None:result['processedPreview']=self.previews.evaluate(sample,warm)
        return result


def ask_payload(source,number,wall):
    at=datetime.fromtimestamp(wall,timezone.utc).isoformat()
    return {'askedAt':at,'conversationId':f'city-soak-{int(wall)}-{number}',
        'query':'Briefly describe the visible people and vehicles in the inspected video. Do not infer events outside it.',
        'scope':'selected-source','lookbackSeconds':5,'sources':[{'kind':'live','name':source['name'],
            'sensorId':source['vssSensorId'] if source.get('vssSensorId') else source['id'],
            'streamId':source['vssSensorId'] if source.get('vssSensorId') else source['id'],
            'playback':{'capturedAt':at}}]}


def ask_once(args,source,number):
    started=time.monotonic();payload=ask_payload(source,number,time.time())
    response=json_request(args.vss_origin+'/api/vision/analyst',payload,timeout=args.ask_timeout_seconds,cap=65536)
    answer=response.get('answer');window=response.get('observedWindow');tools=response.get('evidenceTools')
    if not isinstance(answer,str) or not answer.strip() or response.get('grounded') is not True or not window or not tools:
        raise SoakFailure('real-ask-missing-answer-or-grounded-evidence')
    return {'at':utc(),'sourceId':source['id'],'wallSeconds':time.monotonic()-started,
        'answerSha256':hashlib.sha256(answer.encode()).hexdigest(),'answerCharacters':len(answer),
        'grounded':True,'observedWindow':{k:str(window.get(k,''))[:100] for k in ('startTime','endTime')},
        'evidenceToolCount':len(tools),'scope':'Real UI API call; semantic answer correctness is not automatically established.'}


def pause_sources(args):
    inventory=json_request(args.vss_origin+'/vst/api/v1/sensor/list')
    names={item.get('sensorId'):item.get('name') for item in inventory if isinstance(item,dict)}
    receipts=[]
    for sid in args.source_id:
        try:
            name=names.get(sid)
            if not isinstance(name,str) or not name:raise SoakFailure('pause-source-name-not-in-vios-inventory')
            response=json_request(args.agent_origin+'/api/v1/rtsp-streams/'+quote(sid,safe='')+'/analysis',
                                  {'action':'pause','name':name},timeout=30,cap=65536)
            steps=response.get('steps',{})
            confirmed=(response.get('sensorId')==sid and response.get('action')=='pause'
                and response.get('state')=='paused' and response.get('analysisActive') is False
                and isinstance(steps,dict) and steps.get('detection') is True and steps.get('embedding') is True
                and all(value is True for value in steps.values()))
            receipts.append({'sourceId':sid,'action':'pause','state':response.get('state'),
                             'requestCompleted':True,'pauseConfirmed':confirmed})
        except Exception as exc:
            receipts.append({'sourceId':sid,'action':'pause','requestCompleted':False,
                             'pauseConfirmed':False,'error':str(exc)[:100] if isinstance(exc,SoakFailure) else type(exc).__name__})
    return receipts


def run(args):
    output=args.output_dir
    if output is None:output=args.root/f'.{args.device}/city/runtime'/('soak-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(parents=True,exist_ok=False)
    checks=Checks(args);tail=None
    started=time.monotonic();started_wall=time.time();deadline=started+args.duration_seconds
    samples=0;failure=None;last_metrics=None;ask_results=[];future=None;ask_number=0
    cancelled=False;pending_ask_at_cancel=False;ask_cancel_accepted=None
    next_ask=started+args.ask_every_seconds if args.ask_every_seconds else math.inf
    next_report=started;next_preview=started;preview_records={};executor=ThreadPoolExecutor(max_workers=1) if args.ask_every_seconds else None
    interrupted=[False]
    def stop(*_):interrupted[0]=True
    previous={sig:signal.signal(sig,stop) for sig in (signal.SIGINT,signal.SIGTERM)}
    sample_path=output/'samples.ndjson';sample_path.touch();pause=[]
    try:
        check_cancellation(args)
        tail=FrameTail(args.observations,args.source_id,args.site_id)
        with sample_path.open('a') as durable:
            while time.monotonic()<deadline:
                if interrupted[0]:raise SoakFailure('monitor-interrupted')
                check_cancellation(args)
                now=time.monotonic();wall=time.time()
                sample={'at':utc(),'monotonicSeconds':now,'wallSeconds':wall,
                    'memory':host_memory(args.root,args.device,wall),'frames':tail.read(),
                    'snapshot':json_request(args.gateway_origin+'/api/v1/city/snapshot'),
                    'health':json_request(args.gateway_origin+'/api/v1/city/health'),
                    'nativeAck':json.loads(args.native_ack.read_text()),
                    'containers':{name:container_state(name) for name in args.container}}
                if args.require_processed_preview and now>=next_preview:
                    preview_records={}
                    for sid in args.source_id:
                        try:
                            binary=preview_request(args.vss_origin,sid)
                            record=parse_preview_envelope(binary,sid,args.site_id) if binary is not None else {'available':False,'status':'waiting'}
                        except SoakFailure as exc:
                            if now-started>=args.warmup_seconds:raise
                            record={'available':False,'status':str(exc)[:100]}
                        preview_records[sid]={**record,'fetchedAtMonotonic':time.monotonic()}
                    next_preview=now+PREVIEW_INTERVAL_SECONDS
                if args.require_processed_preview:sample['previews']=preview_records
                samples+=1
                # Persist the failing observation too, with no source URLs, full
                # frames, model text or Docker environment/credential fields.
                try:last_metrics=checks.evaluate(sample)
                finally:
                    compact={k:sample[k] for k in ('at','monotonicSeconds','wallSeconds','memory','frames','containers')}
                    compact['metrics']=last_metrics
                    if args.require_processed_preview:
                        preview_health=sample['health'].get('processedPreview',{});native_delivery=preview_health.get('nativeDelivery',{})
                        compact['processedPreview']={'binarySamples':sample.get('previews',{}),
                            'acceptedFrames':preview_health.get('acceptedFrames'),
                            'sources':[{key:row.get(key) for key in ('id','available','status')} for row in preview_health.get('sources',[])],
                            'nativeDelivery':{key:native_delivery.get(key) for key in ('status','enabled','failed','deliveryAgeSeconds')},
                            'nativeSources':[{key:row.get(key) for key in ('sourceId','selected','encoded','published','rateDropped',
                                'sourceQueueOverruns','identityMissing','identityEvicted','geometryMismatch','oversizeDropped',
                                'networkQueueDropped','postFailed','pendingDropped')} for row in native_delivery.get('sources',[])]}
                    compact['gateway']={'siteId':sample['snapshot'].get('siteId'),'mode':sample['snapshot'].get('mode'),
                        'rulesRevision':sample['snapshot'].get('rulesRevision'),
                        'sources':[{key:source.get(key) for key in ('id','status','lastSourceTimeNs','timestampBasis','sessionId')}
                                   for source in sample['snapshot'].get('sources',[]) if source.get('id') in args.source_id],
                        'native':{key:sample['health'].get('nativeAnalyticsStatus',{}).get(key)
                                  for key in ('status','requestedRevision','appliedRevision','counterEpoch')},
                        'ack':{key:sample['nativeAck'].get(key) for key in ('status','revision','counterEpoch')}}
                    durable.write(json.dumps(compact,allow_nan=False)+'\n');durable.flush();os.fsync(durable.fileno())
                if future is not None and future.done():
                    ask_results.append(future.result());future=None;atomic_json(output/'asks.json',ask_results)
                # Validate and preserve an in-flight observation first. A real
                # failure must still take its ordinary source-pause path.
                check_cancellation(args)
                if executor is not None and now>=next_ask and future is None and deadline-now>=args.ask_timeout_seconds+args.sample_every_seconds:
                    sid=args.source_id[ask_number%len(args.source_id)]
                    source=next(item for item in sample['snapshot']['sources'] if item['id']==sid)
                    ask_number+=1;future=executor.submit(ask_once,args,source,ask_number)
                    next_ask=now+args.ask_every_seconds
                progress={'schemaVersion':'city.soak-progress.v1','at':utc(),'siteId':args.site_id,
                    'sourceIds':args.source_id,'elapsedSeconds':now-started,'sampleCount':samples,
                    'metrics':last_metrics,'completedAsks':len(ask_results),'askPending':future is not None,'status':'running'}
                atomic_json(output/'progress.json',progress)
                if now>=next_report:print(json.dumps(progress,allow_nan=False),flush=True);next_report=now+30
                time.sleep(max(0,min(args.sample_every_seconds,deadline-time.monotonic(),30)))
            check_cancellation(args)
            if future is not None:
                # Never report a successful soak with an unaccounted model call.
                ask_results.append(future.result(timeout=args.ask_timeout_seconds));future=None
                atomic_json(output/'asks.json',ask_results)
            check_cancellation(args)
            if set(checks.clock_ratios)!=set(args.source_id) or not last_metrics or not last_metrics.get('nativeActive'):
                raise SoakFailure('qualification-window-incomplete')
            if checks.previews is not None and (not last_metrics.get('processedPreview',{}).get('ready') or any(v<2 for v in checks.previews.successful_fetches.values())):
                raise SoakFailure('processed-preview-qualification-window-incomplete')
            if any(count['frames']<20 for count in tail.counts.values()):raise SoakFailure('too-few-new-native-frames')
    except SoakCancelled as exc:
        failure=str(exc);cancelled=True
        pending_ask_at_cancel=future is not None and not future.done()
    except Exception as exc:
        failure=str(exc)[:240] if isinstance(exc,SoakFailure) else f'monitor-error:{type(exc).__name__}'
        if args.pause_on_failure:
            try:pause=pause_sources(args)
            except Exception as pause_error:pause=[{'action':'pause','requestCompleted':False,'error':type(pause_error).__name__}]
    finally:
        if tail is not None:tail.close()
        if future is not None:ask_cancel_accepted=future.cancel()
        if executor is not None:executor.shutdown(wait=False,cancel_futures=True)
        for sig,handler in previous.items():signal.signal(sig,handler)
    receipt={'schemaVersion':'city.soak-result.v1','siteId':args.site_id,'sourceIds':args.source_id,
        'startedAt':datetime.fromtimestamp(started_wall,timezone.utc).isoformat(),'finishedAt':utc(),
        'requestedSeconds':args.duration_seconds,'wallSeconds':time.monotonic()-started,'sampleCount':samples,
        'passed':failure is None,'failure':failure,'minimumAvailableGiB':checks.min_available,
        'cancelled':cancelled,
        'cancellation':{'requestedBy':'cancel-file','file':str(args.cancel_file),
            'askPendingAtCancellation':pending_ask_at_cancel,
            'pendingAskMayFinish':pending_ask_at_cancel and ask_cancel_accepted is not True} if cancelled else None,
        'frames':tail.counts if tail is not None else {},'observationRotations':tail.rotations if tail is not None else 0,'lastMetrics':last_metrics,'maximumTrustedSourceAgeSeconds':checks.max_age,
        'maximumDuplicateFractions':checks.max_duplicate,
        'maximumPostWarmupDuplicateFractions':checks.max_duplicate_post_warmup,
        'lastClockToWallRatios':checks.clock_ratios,
        'requireProcessedPreview':args.require_processed_preview,
        'askEnabled':bool(args.ask_every_seconds),'scheduledAskCount':ask_number,'asks':ask_results,'pauseOnFailure':args.pause_on_failure,'pauseReceipts':pause,
        'samplesFile':str(sample_path),'samplesSha256':file_sha(sample_path),
        'monitorSourceSha256':MONITOR_SOURCE_SHA256,
        'criteria':{'minimumReserveGiB':checks.reserve_floor,'warmupSeconds':args.warmup_seconds,
            'sampleEverySeconds':args.sample_every_seconds,
            'processedPreview':{'required':args.require_processed_preview,'fetchEverySeconds':PREVIEW_INTERVAL_SECONDS,
                'requestTimeoutSeconds':PREVIEW_TIMEOUT_SECONDS,'maximumEnvelopeBytes':PREVIEW_ENVELOPE_MAX,'staleSeconds':PREVIEW_STALE_SECONDS},
            'clockWindowSeconds':args.clock_window_seconds,'clockRatioBounds':[args.minimum_clock_ratio,args.maximum_clock_ratio],
            'maximumDuplicateFraction':args.maximum_duplicate_fraction,'trustSourceRtcpUtc':args.trust_source_rtcp_utc,
            'expectedSourceClockBasis':getattr(args,'expected_source_clock_basis','source-rtcp'),
            'trustNativeSeiWallUtc':getattr(args,'trust_native_sei_wall_utc',False),
            'maximumSourceAgeSeconds':args.maximum_source_age_seconds},
        'scope':'Concurrent pipeline stability and optional real UI Ask qualification; not engine latency, semantic event accuracy, browser-frame latency or final-city/MV3DT qualification.'}
    atomic_json(output/'receipt.json',receipt);atomic_json(output/'progress.json',
        {**receipt,'status':'cancelled' if cancelled else ('passed' if failure is None else 'failed')})
    print(json.dumps(receipt,allow_nan=False),flush=True)
    return 0 if failure is None else 1


def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--device',choices=['spark','thor'],default='spark')
    parser.add_argument('--site-id',required=True);parser.add_argument('--source-id',action='append',required=True)
    parser.add_argument('--observations',type=Path,required=True);parser.add_argument('--native-ack',type=Path)
    parser.add_argument('--output-dir',type=Path);parser.add_argument('--duration-seconds',type=float,default=300)
    parser.add_argument('--sample-every-seconds',type=float,default=5);parser.add_argument('--warmup-seconds',type=float,default=15)
    parser.add_argument('--stale-seconds',type=float,default=5);parser.add_argument('--clock-window-seconds',type=float,default=30)
    parser.add_argument('--minimum-clock-ratio',type=float,default=.9);parser.add_argument('--maximum-clock-ratio',type=float,default=1.1)
    parser.add_argument('--maximum-duplicate-fraction',type=float,default=.05)
    parser.add_argument('--trust-source-rtcp-utc',action='store_true');parser.add_argument('--maximum-source-age-seconds',type=float,default=5)
    parser.add_argument('--expected-source-clock-basis',choices=['source-rtcp','source-native-sei'],default='source-rtcp')
    parser.add_argument('--trust-native-sei-wall-utc',action='store_true',help='Explicitly check encoded-AU handoff UTC age; never a physical-exposure clock claim')
    parser.add_argument('--gateway-origin',type=origin,default='http://127.0.0.1:9184')
    parser.add_argument('--vss-origin',type=origin,default='http://127.0.0.1:7777')
    parser.add_argument('--agent-origin',type=origin,default='http://127.0.0.1:8100')
    parser.add_argument('--container',action='append',default=None)
    parser.add_argument('--ask-every-seconds',type=float);parser.add_argument('--ask-timeout-seconds',type=float,default=55)
    parser.add_argument('--pause-on-failure',action='store_true')
    parser.add_argument('--cancel-file',type=Path,help='Opt in: creating this marker file cancels observation without pausing sources; receipt remains non-pass')
    parser.add_argument('--require-processed-preview',action='store_true',help='Require advancing exact-frame JPEG previews through the UI front door')
    args=parser.parse_args();args.root=args.root.resolve()
    if (args.trust_native_sei_wall_utc and args.expected_source_clock_basis!='source-native-sei') or (args.trust_source_rtcp_utc and args.expected_source_clock_basis!='source-rtcp'):
        parser.error('Clock trust flag must match the explicit expected source clock basis')
    if len(args.source_id)!=2 or len(set(args.source_id))!=2 or any(not ID.fullmatch(sid) for sid in args.source_id):
        parser.error('Exactly two distinct explicit source IDs are required')
    if args.require_processed_preview and args.sample_every_seconds>5:
        parser.error('Processed-preview qualification requires a sample interval at most5 seconds')
    if not args.site_id or len(args.site_id)>200:parser.error('A bounded site ID is required')
    if not 1<=args.duration_seconds<=86400 or not .5<=args.sample_every_seconds<=30 or not 0<=args.warmup_seconds<=60:
        parser.error('Duration1..86400, sample interval0.5..30 and warmup0..60 seconds are required')
    if not 1<=args.stale_seconds<=30 or not 5<=args.clock_window_seconds<=60 or not finite(args.minimum_clock_ratio) or not finite(args.maximum_clock_ratio) or not 0<args.minimum_clock_ratio<1<args.maximum_clock_ratio:
        parser.error('Use bounded stale/window settings and clock ratio bounds spanning1')
    if not 0<=args.maximum_duplicate_fraction<1 or not 0<args.maximum_source_age_seconds<=60:
        parser.error('Invalid duplicate fraction or source age limit')
    if args.ask_every_seconds is not None and (not math.isfinite(args.ask_every_seconds) or args.ask_every_seconds<900):
        parser.error('Optional Ask interval must be at least900 seconds')
    if not 1<=args.ask_timeout_seconds<=55:parser.error('Ask timeout must be1..55 seconds')
    if args.native_ack is None:args.native_ack=args.root/f'.{args.device}/city/state/native/analytics-ack.json'
    required=['vss-city-detector','vss-city-analytics','vss-agent','vss-vios-streamprocessing','vss-rtvi-embed','vss-rtvi-vlm']
    if args.device=='spark':required.append('vss-spark-spark-llm-1')
    args.container=list(dict.fromkeys(required+(args.container or [])))
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name) for name in args.container):parser.error('Invalid container name')
    return args


if __name__=='__main__':raise SystemExit(run(arguments()))
