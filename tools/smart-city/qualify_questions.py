#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Opt-in three-question/evidence trial. Never start workers or change budgets."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
import urllib.request
import uuid

import soak

ROOT=Path(__file__).resolve().parents[2]
SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_CLIP_BYTES=20*1024*1024
MAX_SNAPSHOT_BYTES=1024*1024
KNOWN_LOCAL_ALIASES=('172.17.0.1','127.0.0.1','localhost','host.docker.internal')
json_request=soak.json_request


class TrialFailure(RuntimeError):pass


def timestamp(value):
    if not isinstance(value,str) or len(value)>100:raise TrialFailure('invalid-window-timestamp')
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.utcoffset() is None:raise ValueError()
        result=parsed.timestamp()
    except (ValueError,OverflowError):raise TrialFailure('invalid-window-timestamp') from None
    if not math.isfinite(result):raise TrialFailure('invalid-window-timestamp')
    return result


def safe_media_url(value,vss_origin,aliases=()):
    """Allow only the two UI media routes; aliases are explicit and fixed-list."""
    if not isinstance(value,str) or len(value)>2048 or any(c in value for c in ('\r','\n','\\')):
        raise TrialFailure('unsafe-evidence-url')
    if any(alias not in KNOWN_LOCAL_ALIASES for alias in aliases):raise TrialFailure('unsafe-vss-alias')
    try:
        origin=urlsplit(vss_origin);raw=urlsplit(value);parsed=urlsplit(urljoin(vss_origin+'/',value))
        if raw.netloc and not raw.scheme:raise ValueError()
        if parsed.username or parsed.password or parsed.fragment:raise ValueError()
        if parsed.scheme!=origin.scheme or parsed.port!=origin.port:raise ValueError()
        if parsed.hostname!=origin.hostname and parsed.hostname not in aliases:raise ValueError()
        path=parsed.path
        if '%' in path or '..' in path or '//' in path:raise ValueError()
        if path=='/api/vision/evidence-media':
            query=parse_qs(parsed.query,strict_parsing=True)
            if set(query)!={'key'} or len(query['key'])!=1 or not re.fullmatch('[a-f0-9]{64}',query['key'][0]):raise ValueError()
        elif re.fullmatch(r'/vst/storage/temp_files/[A-Za-z0-9_.-]{1,240}\.mp4',path):
            if parsed.query:raise ValueError()
        else:raise ValueError()
        return urlunsplit((origin.scheme,origin.netloc,path,parsed.query,''))
    except ValueError:raise TrialFailure('unsafe-evidence-url') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def fetch_clip(url,args):
    url=safe_media_url(url,args.vss_origin,args.allow_vss_alias)
    request=urllib.request.Request(url,headers={'Accept':'video/mp4'})
    opener=urllib.request.build_opener(NoRedirect())
    started=time.monotonic();digest=hashlib.sha256();count=0;prefix=b''
    try:
        with opener.open(request,timeout=args.timeout_seconds) as response:
            if response.getcode()!=200:raise TrialFailure('evidence-media-not-full-http-200')
            if response.geturl()!=url:raise TrialFailure('evidence-media-redirected')
            if response.headers.get_content_type() not in ('video/mp4','application/octet-stream'):
                raise TrialFailure('evidence-media-content-type')
            length=response.headers.get('Content-Length')
            if length is not None:
                try:declared=int(length)
                except ValueError:raise TrialFailure('evidence-media-content-length') from None
                if declared<0 or declared>MAX_CLIP_BYTES:raise TrialFailure('evidence-media-size-limit')
            while True:
                if time.monotonic()-started>args.timeout_seconds:raise TrialFailure('evidence-media-timeout')
                block=response.read(min(65536,MAX_CLIP_BYTES-count+1))
                if not block:break
                if len(prefix)<64:prefix=(prefix+block)[:64]
                count+=len(block)
                if count>MAX_CLIP_BYTES:raise TrialFailure('evidence-media-size-limit')
                digest.update(block)
            if length is not None and count!=declared:raise TrialFailure('evidence-media-truncated')
    except HTTPError as exc:raise TrialFailure(f'evidence-http-status-{exc.code}') from None
    except (URLError,TimeoutError,OSError):raise TrialFailure('evidence-media-unavailable-or-timeout') from None
    if count<12 or b'ftyp' not in prefix:raise TrialFailure('evidence-media-not-mp4')
    return {'bytes':count,'sha256':digest.hexdigest(),'fetchSeconds':time.monotonic()-started}


def preflight(args,previous=None):
    snapshot=json_request(args.gateway_origin+'/api/v1/city/snapshot',timeout=8,cap=MAX_SNAPSHOT_BYTES)
    health=json_request(args.gateway_origin+'/api/v1/city/health',timeout=8,cap=65536)
    if not isinstance(snapshot,dict) or not isinstance(health,dict):raise TrialFailure('readiness-schema')
    if snapshot.get('siteId')!=args.site_id or health.get('siteId')!=args.site_id or snapshot.get('mode')!='live':
        raise TrialFailure('active-site-mismatch')
    if health.get('status')!='ok':raise TrialFailure('gateway-not-ready')
    native=health.get('nativeAnalyticsStatus',{})
    if (native.get('status')!='active' or not str(native.get('requestedRevision')).isdigit()
        or str(native.get('requestedRevision'))!=str(native.get('appliedRevision'))
        or str(snapshot.get('rulesRevision'))!=str(native.get('appliedRevision'))):
        raise TrialFailure('native-analytics-not-active')
    sources=[s for s in snapshot.get('sources',[]) if isinstance(s,dict) and s.get('id')==args.source_id]
    if len(sources)!=1:raise TrialFailure('active-source-mismatch')
    source=sources[0]
    if source.get('vssSensorId',args.source_id)!=args.source_id or source.get('status')!='live':
        raise TrialFailure('active-source-mismatch')
    try:ns=int(source['lastSourceTimeNs'])
    except (KeyError,TypeError,ValueError):raise TrialFailure('source-clock-missing') from None
    expected_basis=getattr(args,'expected_source_clock_basis','source-rtcp')
    if ns<=0 or source.get('timestampBasis')!=expected_basis or not source.get('sessionId'):
        raise TrialFailure('source-clock-missing')
    if expected_basis=='source-native-sei' and (not soak.native_sei_source_clock(source)
            or native.get('sourceClockMode')!=expected_basis):
        raise TrialFailure('native-sei-clock-proof-or-ack-missing')
    if previous and (source['sessionId']!=previous['sessionId'] or ns<=int(previous['sourceTimeNs'])):
        raise TrialFailure('source-clock-not-advancing-or-epoch-changed')
    admission=json_request(args.vss_origin+'/api/vision/workload-admission?workload=current_visual_question',timeout=8,cap=65536)
    if not isinstance(admission,dict) or admission.get('workload')!='current_visual_question' or admission.get('decision')!='allow':
        raise TrialFailure('visual-question-not-admitted')
    memory=soak.host_memory(args.root,args.device,time.time())
    if not all(soak.finite(memory.get(k)) for k in ('availableGiB','guardAvailableGiB','savedReserveGiB','guardFloorGiB','guardAgeSeconds')):
        raise TrialFailure('memory-guard-invalid')
    floor=max(20,memory['savedReserveGiB'])
    if memory['guardFloorGiB']<floor or not -2<=memory['guardAgeSeconds']<=15 or min(memory['availableGiB'],memory['guardAvailableGiB'])<floor:
        raise TrialFailure('memory-reserve-or-guard-not-ready')
    if not isinstance(source.get('name'),str) or not source['name']:raise TrialFailure('source-name-missing')
    return source,{'sourceTimeNs':str(ns),'timestampBasis':expected_basis,'sessionId':source['sessionId'],
                   'nativeRevision':native.get('appliedRevision'),'minimumAvailableGiB':min(memory['availableGiB'],memory['guardAvailableGiB'])}


def validate_answer(response,asked_wall,previous_window=None):
    if not isinstance(response,dict):raise TrialFailure('ask-response-schema')
    answer=response.get('answer');tools=response.get('evidenceTools');window=response.get('observedWindow')
    if not isinstance(answer,str) or not answer.strip() or response.get('grounded') is not True:
        raise TrialFailure('ask-missing-answer-or-grounded-flag')
    if not isinstance(tools,list) or not 1<=len(tools)<=16 or any(not isinstance(t,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',t) for t in tools):
        raise TrialFailure('ask-missing-evidence-tools')
    if not isinstance(window,dict):raise TrialFailure('ask-missing-observed-window')
    start=timestamp(window.get('startTime'));end=timestamp(window.get('endTime'))
    if not 4.75<=end-start<=5.25 or not -1<=asked_wall-end<=15:
        raise TrialFailure('ask-invalid-five-second-window')
    if previous_window and start<=timestamp(previous_window['endTime']):raise TrialFailure('ask-window-not-new')
    return {'answerSha256':hashlib.sha256(answer.encode()).hexdigest(),'answerCharacters':len(answer),
        'groundedFlag':True,'evidenceTools':tools,'observedWindow':{k:window[k] for k in ('startTime','endTime')}}


def evidence(args,window):
    query=urlencode({'sensorId':args.source_id,**window})
    response=json_request(args.vss_origin+'/api/vision/evidence?'+query,timeout=args.timeout_seconds,cap=65536)
    if not isinstance(response,dict):raise TrialFailure('evidence-response-schema')
    timestamp(response.get('startTime'))
    media=safe_media_url(response.get('videoUrl'),args.vss_origin,args.allow_vss_alias)
    result=fetch_clip(media,args)
    return {'returnedStartTime':response['startTime'],'mediaPath':urlunsplit(('', '',urlsplit(media).path,urlsplit(media).query,'')),
            'mediaUriSha256':hashlib.sha256(media.encode()).hexdigest(),**result}


def wait_until(deadline):
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:return
        time.sleep(min(remaining,1))


def run(args):
    if not args.allow_real_ask:raise TrialFailure('explicit-allow-real-ask-required')
    output=args.output_dir or args.root/f'.{args.device}/city/runtime'/('questions-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(mode=0o700,parents=True,exist_ok=False);os.chmod(output,0o700)
    started=time.monotonic();calls=[];cached=None;failure=None;previous=None;completed=None
    receipt={'schemaVersion':'city.question-trial.v1','siteId':args.site_id,'sourceId':args.source_id,
        'startedAt':soak.utc(),'runnerSourceSha256':SOURCE_SHA256,'soakHelperSourceSha256':soak.MONITOR_SOURCE_SHA256,
        'actualAskCount':0,'calls':calls,
        'betweenCompletedCallsMinimumSeconds':args.between_calls_seconds,'timeoutSeconds':args.timeout_seconds,
        'clipByteLimit':MAX_CLIP_BYTES,'scope':'Three real UI questions plus evidence-byte delivery. Grounded flags and hashes do not prove semantic correctness, allocation reuse, model accuracy or internal export-cache behavior.'}
    try:
        for number in range(1,4):
            if completed is not None:wait_until(completed+args.between_calls_seconds)
            source,readiness=preflight(args,previous);previous=readiness
            asked_wall=time.time();ask_start=time.monotonic()
            item={'number':number,'askedAt':datetime.fromtimestamp(asked_wall,timezone.utc).isoformat(),
                  'readiness':readiness,'status':'started'};calls.append(item)
            receipt['actualAskCount']+=1;soak.atomic_json(output/'progress.json',receipt)
            payload=soak.ask_payload(source,number,asked_wall)
            payload['conversationId']=f'city-question-trial-{uuid.uuid4()}-{number}'
            response=json_request(args.vss_origin+'/api/vision/analyst',payload,timeout=args.timeout_seconds,cap=65536)
            item['askSeconds']=time.monotonic()-ask_start
            if item['askSeconds']>args.timeout_seconds:raise TrialFailure('ask-timeout-exceeded')
            item.update(validate_answer(response,asked_wall,calls[-2]['observedWindow'] if number>1 else None))
            clip=evidence(args,item['observedWindow'])
            if any(clip['mediaUriSha256']==c.get('evidence',{}).get('mediaUriSha256') for c in calls[:-1]):
                raise TrialFailure('different-window-reused-evidence-uri')
            item['evidence']=clip;item['status']='complete';completed=time.monotonic();item['completedAt']=soak.utc()
            item['secondsFromPreviousCompletionToAskStart']=None if number==1 else ask_start-calls[-2]['completedMonotonicSeconds']
            item['completedMonotonicSeconds']=completed
            soak.atomic_json(output/'progress.json',receipt)
            print(json.dumps({'number':number,'status':'complete','askSeconds':item['askSeconds'],'clipBytes':clip['bytes']}),flush=True)
        preflight(args,previous)
        repeat=evidence(args,calls[0]['observedWindow']);first=calls[0]['evidence']
        cached={'request':'repeat-first-observed-window-evidence-only','actualAdditionalAskCount':0,**repeat,
                'sameMediaUri':repeat['mediaUriSha256']==first['mediaUriSha256'],'sameByteHash':repeat['sha256']==first['sha256'],
                'scope':'Observed URI/byte equality only; no inference about VIOS internal cache implementation.'}
        if not cached['sameByteHash']:raise TrialFailure('repeated-evidence-byte-hash-changed')
    except (Exception,KeyboardInterrupt) as exc:
        failure=str(exc)[:180] if isinstance(exc,(TrialFailure,soak.SoakFailure)) else 'trial-interrupted' if isinstance(exc,KeyboardInterrupt) else f'trial-error:{type(exc).__name__}'
    receipt.update(finishedAt=soak.utc(),wallSeconds=time.monotonic()-started,passed=failure is None,failure=failure,cachedRepeat=cached)
    soak.atomic_json(output/'receipt.json',receipt);soak.atomic_json(output/'progress.json',receipt)
    print(json.dumps({'passed':receipt['passed'],'actualAskCount':receipt['actualAskCount'],'failure':failure,'receipt':str(output/'receipt.json')}),flush=True)
    return 0 if failure is None else 1


def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-real-ask',action='store_true');parser.add_argument('--source-id',required=True)
    parser.add_argument('--site-id',required=True);parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--device',choices=['spark','thor'],default='spark');parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--vss-origin',type=soak.origin,default='http://127.0.0.1:7777')
    parser.add_argument('--gateway-origin',type=soak.origin,default='http://127.0.0.1:9184')
    parser.add_argument('--expected-source-clock-basis',choices=['source-rtcp','source-native-sei'],default='source-rtcp')
    parser.add_argument('--allow-vss-alias',action='append',choices=KNOWN_LOCAL_ALIASES,default=[])
    parser.add_argument('--between-calls-seconds',type=float,default=60)
    parser.add_argument('--timeout-seconds',type=float,default=55)
    args=parser.parse_args()
    if not args.allow_real_ask:parser.error('Use --allow-real-ask to authorize exactly three actual model requests')
    try:
        if str(uuid.UUID(args.source_id))!=args.source_id:raise ValueError()
    except ValueError:parser.error('Use the exact canonical registered source UUID')
    if not args.site_id or len(args.site_id)>200:parser.error('A bounded exact site ID is required')
    if not math.isfinite(args.between_calls_seconds) or not 60<=args.between_calls_seconds<=900:
        parser.error('Wait at least60 and at most900 seconds after each completed call')
    if not math.isfinite(args.timeout_seconds) or not 1<=args.timeout_seconds<=55:parser.error('Timeout must be1..55 seconds')
    args.root=args.root.resolve()
    return args


if __name__=='__main__':raise SystemExit(run(arguments()))
