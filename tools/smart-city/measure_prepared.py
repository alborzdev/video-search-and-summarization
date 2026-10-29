#!/usr/bin/env python3
"""Bounded read-only prepared-scenario observer. Start before clicking Prepare.

Scene receipts and image analytics are saved separately. This does not start a
scenario, change settings, weaken evidence guards, or feed native positions to AI.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import time
import urllib.request


def get(url):
    with urllib.request.urlopen(url, timeout=4) as response:
        return json.load(response)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=150)
    args = p.parse_args()
    if not 5 <= args.seconds <= 300: p.error('Bounded observation must be 5–300 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('prepared_preview_check', Path(__file__).with_name('soak.py'))
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    start = time.monotonic(); initial = get('http://127.0.0.1:9190/api/v1/demo')['scenario'].get('runId')
    run_id = None; summary = {'startedAtNs': str(time.time_ns()), 'sceneControl': {}, 'phases': [],
        'exactPreviews': 0, 'errors': [], 'sourceSessions': {}, 'sourceClockMonotonic': True,
        'cameraObservedMotion': None, 'preparationAnalyticsSuppressed': True,
        'sceneControlAndCameraEvidenceAreSeparate': True}
    previous_ns = {}; phases = set(); first_play = None; anchors = {}; next_image = 0
    with (args.output/'trace.ndjson').open('w') as trace:
        while time.monotonic()-start < args.seconds:
            began = time.monotonic()
            sample = {'elapsedWallSeconds': began-start, 'wallTimeNs': str(time.time_ns())}
            try:
                control = get('http://127.0.0.1:9190/api/v1/demo'); scene = control['scenario']; sample['sceneControl'] = control
                snapshot = get('http://127.0.0.1:9184/api/v1/city/snapshot'); sample['cameraAnalytics'] = snapshot
                sample['mobility'] = get('http://127.0.0.1:9184/api/v1/city/mobility?windowMinutes=1')
                boundary = get('http://127.0.0.1:9184/api/v1/city/scenario-boundary'); sample['analyticsBoundary'] = boundary
                if scene.get('runId') and scene['runId'] != initial and run_id is None:
                    run_id = scene['runId']; summary.update(runId=run_id, scenarioId=scene.get('scenarioId'), firstRunObservedSeconds=began-start)
                if run_id and scene.get('runId') == run_id:
                    phase = (scene.get('state'), scene.get('phase'), scene.get('timings', {}).get('hostPhase'))
                    if phase not in phases:
                        phases.add(phase); summary['phases'].append({'state':phase[0], 'phase':phase[1], 'hostPhase':phase[2], 'elapsedWallSeconds':began-start})
                        print(json.dumps(summary['phases'][-1]), flush=True)
                    summary['sceneControl'] = {k:scene.get(k) for k in ('state','reason','restored','normalFlowVerified','timings','preparation')}
                    if scene.get('state') == 'running' and first_play is None:
                        first_play = began; summary['runningFirstObservedSeconds'] = began-start
                    if scene.get('state') in ('preparing','ready') and (snapshot.get('tracks') or snapshot.get('metrics')):
                        summary['preparationAnalyticsSuppressed'] = False
                for source in snapshot.get('sources', []):
                    sid=source['id']; ns=int(source.get('lastSourceTimeNs') or 0)
                    if sid in previous_ns and ns < previous_ns[sid]: summary['sourceClockMonotonic'] = False
                    previous_ns[sid] = ns
                    sessions=summary['sourceSessions'].setdefault(sid,[])
                    if source.get('sourceSessionId') not in sessions: sessions.append(source.get('sourceSessionId'))
                    if began >= next_image:
                        body = check.preview_request('http://127.0.0.1:7782', sid)
                        if body:
                            identity=check.parse_preview_envelope(body,sid,'isaac-intersection-a')
                            sample.setdefault('exactPreviewProofs',[]).append(identity); summary['exactPreviews']+=1
                            length=struct.unpack('>I',body[:4])[0];dto=json.loads(body[4:4+length]);jpg=body[4+length:]
                            stem=f'{int((began-start)*1000):06d}-{sid[:8]}'
                            (args.output/(stem+'.jpg')).write_bytes(jpg)
                            (args.output/(stem+'.json')).write_text(json.dumps(dto)+'\n')
                if began >= next_image: next_image = began+2
                # Host-decorated scene timing is separate. This independent image-path
                # observation requires fresh camera tracking and visible anchor
                # movement over >=0.5s; it is not a crossing/count qualification.
                if first_play and snapshot.get('analyticsScope',{}).get('kind')=='scenario':
                    want='person' if summary.get('scenarioId')=='pedestrian-service' else 'car'
                    for track in snapshot.get('tracks',[]):
                        if track.get('class') != want or track.get('predictionOnly'):continue
                        box=track.get('bboxPx'); key=(track.get('sourceId'),track.get('localTrackId'))
                        if not box:continue
                        point=(box[0]+box[2]/2,box[1]+box[3]);old=anchors.setdefault(key,(began,point))
                        shift=((point[0]-old[1][0])**2+(point[1]-old[1][1])**2)**.5
                        if summary['cameraObservedMotion'] is None and began-old[0]>=.5 and shift>=5:
                            summary['cameraObservedMotion']={'secondsAfterRunningFirstObserved':began-first_play,
                                'sourceId':key[0], 'localTrackId':key[1], 'anchorDisplacementPx':shift,
                                'basis':'two image-derived track anchors at least 0.5s apart; not a count or physical motion accuracy score'}
                trace.write(json.dumps(sample,separators=(',',':'))+'\n'); trace.flush()
                if (run_id and scene.get('runId')==run_id and scene.get('state') in ('completed','failed','cancelled')
                        and scene.get('restored') and scene.get('normalFlowVerified') and boundary.get('state')=='normal'):
                    summary['automaticNormalRestorationObserved']=True;break
                if run_id and scene.get('state')=='recovery-failed': break
            except Exception as exc:
                error={'elapsedWallSeconds':time.monotonic()-start,'error':str(exc)[:300]};summary['errors'].append(error)
                trace.write(json.dumps(error)+'\n');trace.flush();print(json.dumps(error),flush=True)
            time.sleep(max(0,.5-(time.monotonic()-began)))
    summary['observedWallSeconds']=time.monotonic()-start
    if run_id:
        # Host boundary IDs and native run IDs are intentionally separate.
        # Retain the archived camera result even after normal traffic resumes.
        try:
            host_run = scene.get('analyticsBoundary', {}).get('runId')
            scopes = get('http://127.0.0.1:9184/api/v1/city/analytics-scopes')
            archive = [row for row in scopes.get('prior', []) if host_run and row.get('runId') == host_run]
            (args.output/'scope-archive.json').write_text(json.dumps(archive, indent=2)+'\n')
            summary['analyticsRunId'] = host_run
            summary['archivedScopeCount'] = len(archive)
        except Exception as exc:
            summary['errors'].append({'stage':'archive', 'error':str(exc)[:300]})
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
