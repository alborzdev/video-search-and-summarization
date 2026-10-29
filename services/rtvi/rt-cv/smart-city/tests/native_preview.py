#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Explicit bounded GPU qualification; private local consumers, no VSS mutation."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import math
from pathlib import Path
import subprocess
import threading
import time

MAX_JPEG=2*1024*1024
SOURCES={'traffic-cam-1':(1920,1080),'pedestrian-cam-2':(768,576)}


def identity(row):
    return (row['sourceId'],row['sourceSessionId'],str(row['sequence']),str(row['sourceTimeNs']),row['modelRevision'])


def jpeg_dimensions(body):
    """Independent SOF inspection; no GPU or JPEG pixel decoder is used."""
    if not 4<=len(body)<=MAX_JPEG or body[:2]!=b'\xff\xd8' or body[-2:]!=b'\xff\xd9':
        raise ValueError('invalid-jpeg-boundary-or-size')
    cursor=2
    while cursor<len(body)-2:
        if body[cursor]!=255:raise ValueError('invalid-jpeg-marker')
        while cursor<len(body) and body[cursor]==255:cursor+=1
        if cursor>=len(body):break
        marker=body[cursor];cursor+=1
        if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7:continue
        if marker==0xda:break
        if cursor+2>len(body):break
        size=int.from_bytes(body[cursor:cursor+2],'big')
        if size<2 or cursor+size>len(body):raise ValueError('invalid-jpeg-segment-size')
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
            if size<8:raise ValueError('short-jpeg-sof')
            height=int.from_bytes(body[cursor+3:cursor+5],'big');width=int.from_bytes(body[cursor+5:cursor+7],'big')
            if not width or not height:raise ValueError('zero-jpeg-geometry')
            return width,height
        cursor+=size
    raise ValueError('jpeg-sof-missing')


def available_gib():
    fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(fields['MemAvailable'].split()[0])/1024**2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-gpu',action='store_true')
    parser.add_argument('--worker',default='/opt/city/city-worker');parser.add_argument('--config-dir',default='/opt/city/configs')
    parser.add_argument('--model-revision',default='rfdetr-small-fp16')
    parser.add_argument('--state-dir',type=Path,default=Path('/state/native-preview-qualification'))
    parser.add_argument('--memory-reserve-gib',type=float,default=20)
    args=parser.parse_args()
    if not args.allow_gpu:parser.error('This test starts real native GPU inference; explicit --allow-gpu and parent GPU lease are required')
    if not math.isfinite(args.memory_reserve_gib) or args.memory_reserve_gib<20 or available_gib()<args.memory_reserve_gib:
        parser.error('Saved available-memory reserve must be at least20GiB and currently available')
    args.state_dir.mkdir(parents=True,exist_ok=False)
    rows=[];observations={};previews=[];errors=[];positive={};first_jpegs={};lock=threading.Condition()
    unavailable={'at':None};close_requested=threading.Event();server_ref={}

    class Consumer(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def respond(self,status,body):
            data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)));self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if self.path=='/api/v1/city/observations':
                    if not 1<=length<=1024*1024:raise ValueError('observation-size')
                    row=json.loads(self.rfile.read(length));key=identity(row)
                    if row['sourceId'] not in SOURCES or row.get('siteId')!='native-preview-control':raise ValueError('unexpected-observation-source')
                    with lock:
                        if key in observations:raise ValueError('duplicate-observation')
                        observations[key]=row;rows.append((time.monotonic(),row));lock.notify_all()
                    self.respond(200,{'accepted':True});return
                if self.path!='/api/v1/city/preview':self.respond(404,{'accepted':False});return
                if self.headers.get_content_type()!='image/jpeg' or not 1<=length<=MAX_JPEG:raise ValueError('jpeg-body-type-or-size')
                body=self.rfile.read(length);width,height=jpeg_dimensions(body)
                key=(self.headers['X-City-Source-Id'],self.headers['X-City-Session-Id'],self.headers['X-City-Sequence'],
                     self.headers['X-City-Source-Time-Ns'],self.headers['X-City-Model-Revision'])
                with lock:
                    lock.wait_for(lambda:key in observations,timeout=.25)
                    row=observations.get(key)
                    if row is None:self.respond(202,{'accepted':False,'reason':'metadata-pending'});return
                    expected=(row['image']['width'],row['image']['height'])
                    declared=(int(self.headers['X-City-Width']),int(self.headers['X-City-Height']))
                    if declared!=expected or (width,height)!=expected or expected!=SOURCES[row['sourceId']]:
                        raise ValueError('jpeg-and-exact-observation-geometry-mismatch')
                    receipt={'receivedMonotonicSeconds':time.monotonic(),'sourceId':key[0],'sourceSessionId':key[1],
                        'sequence':key[2],'sourceTimeNs':key[3],'modelRevision':key[4],'width':width,'height':height,
                        'jpegBytes':len(body),'jpegSha256':hashlib.sha256(body).hexdigest(),'positiveDetections':len(row['objects'])}
                    previews.append(receipt)
                    if row['sourceId'] not in first_jpegs:
                        name='first-'+row['sourceId'];(args.state_dir/(name+'.jpg')).write_bytes(body)
                        (args.state_dir/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n');first_jpegs[row['sourceId']]=receipt
                    if row['objects'] and row['sourceId'] not in positive:
                        name='positive-'+row['sourceId'];(args.state_dir/(name+'.jpg')).write_bytes(body)
                        (args.state_dir/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n');positive[row['sourceId']]=receipt
                    if len(rows)>=240 and len(previews)>=8 and positive and not close_requested.is_set():
                        close_requested.set()
                        def unavailable_phase():
                            server_ref['preview'].shutdown();server_ref['preview'].server_close()
                            unavailable['at']=time.monotonic()
                        threading.Thread(target=unavailable_phase,daemon=True).start()
                self.respond(201,{'accepted':True})
            except (KeyError,ValueError,TypeError,IndexError) as error:
                with lock:errors.append(type(error).__name__+':'+str(error)[:120])
                self.respond(422,{'accepted':False})

    observation_server=ThreadingHTTPServer(('127.0.0.1',0),Consumer)
    preview_server=ThreadingHTTPServer(('127.0.0.1',0),Consumer);server_ref['preview']=preview_server
    threads=[threading.Thread(target=server.serve_forever,daemon=True) for server in (observation_server,preview_server)]
    for thread in threads:thread.start()
    stats_path=args.state_dir/'preview-stats.json';output=args.state_dir/'observations.ndjson'
    command=[args.worker,'--source','traffic-cam-1=file:///media/traffic-sample.mp4',
        '--source','pedestrian-cam-2=file:///media/pedestrian-sample.mp4',
        '--site-id','native-preview-control','--config-dir',args.config_dir,'--model-revision',args.model_revision,
        '--output',str(output),'--post-url',f'http://127.0.0.1:{observation_server.server_port}/api/v1/city/observations',
        '--preview-url',f'http://127.0.0.1:{preview_server.server_port}/api/v1/city/preview',
        '--preview-fps','15','--preview-stats-file',str(stats_path),'--cpu-decode','--frames','480']
    started=time.monotonic();result=None;failure=None
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=90)
        (args.state_dir/'worker.log').write_text(result.stdout+result.stderr)
    except subprocess.TimeoutExpired as error:
        failure='worker-timeout';(args.state_dir/'worker.log').write_bytes((error.stdout or b'')+(error.stderr or b''))
    finally:
        observation_server.shutdown();observation_server.server_close()
        if not close_requested.is_set():preview_server.shutdown();preview_server.server_close()
        for thread in threads:thread.join(timeout=1)
    counters=json.loads(stats_path.read_text()) if stats_path.exists() else {}
    summary={}
    if result:
        summary=next((json.loads(line.split(': ',1)[1]) for line in result.stderr.splitlines() if line.startswith('City publisher summary: ')),{})
    source_counts={};metadata_ordered=True
    for sid in SOURCES:
        items=[row for _,row in rows if row['sourceId']==sid];source_counts[sid]=len(items)
        metadata_ordered&=[row['sequence'] for row in items]==[str(i) for i in range(len(items))]
    after_unavailable=sum(1 for at,_ in rows if unavailable['at'] is not None and at>unavailable['at'])
    checks={'workerExitZero':bool(result and result.returncode==0),'all480Observations':len(rows)==480,
        'losslessPublisherCounts':summary.get('enqueued')==summary.get('published')==480,
        'orderedMetadataPerSource':metadata_ordered,'bothSourcesObserved':all(n>=80 for n in source_counts.values()),
        'previewExactMatches':len(previews)>=8 and not errors,'bothOriginalGeometries':{p['sourceId'] for p in previews}==set(SOURCES),
        'positiveMatchedJpeg':bool(positive),'unavailablePhaseReached':unavailable['at'] is not None,
        'metadataContinuedAfterPreviewUnavailable':after_unavailable>=40,
        'previewFailureCountersVisible':sum(s.get('postFailed',0) for s in counters.get('sources',[]))>0,
        'boundedIdentityMaps':all(s.get('identitiesPending',999)<=32 for s in counters.get('sources',[])),
        'boundedSenderQueue':counters.get('pendingJpegs',999)<=2,'previewBranchNotFailed':counters.get('failed') is False}
    receipt={'schemaVersion':'city.preview-native-qualification.v1','passed':failure is None and all(checks.values()),
        'failure':failure,'checks':checks,'wallSecondsIncludingStartup':time.monotonic()-started,
        'workerExitCode':result.returncode if result else None,'workerSha256':hashlib.sha256(Path(args.worker).read_bytes()).hexdigest(),
        'modelRevision':args.model_revision,'sourceFrames':source_counts,'jpegExactMatches':len(previews),
        'firstJpegs':first_jpegs,'positiveJpegs':positive,
        'previewEndpointClosedMonotonicSeconds':unavailable['at'],'observationsAfterEndpointClose':after_unavailable,
        'publisher':summary,'nativePreview':counters,'errors':errors,'memoryAvailableGiBAfter':available_gib(),
        'scope':'Actual native inference + exact observation/JPEG identity and geometry, then refused preview connections with lossless ordered metadata. Positive means matched observation has objects; saved JPEGs need visual inspection. Not semantic detector accuracy, final-city/MV3DT, browser render latency or converter fault isolation.'}
    (args.state_dir/'received-observations.ndjson').write_text(''.join(json.dumps({'receivedMonotonicSeconds':at,**row})+'\n' for at,row in rows))
    (args.state_dir/'received-previews.ndjson').write_text(''.join(json.dumps(row)+'\n' for row in previews))
    (args.state_dir/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
