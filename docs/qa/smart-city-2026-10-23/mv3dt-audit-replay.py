#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Saved-data diagnostic replay only; never changes runtime or original comparison gates.

Requires the pinned private captures retained on this development host.
Isolated-match and time-offset summaries are diagnostics, never sample exclusions.
"""
import sys, json, math, bisect, hashlib, collections
from pathlib import Path
sys.path.insert(0,'/home/sparkdev/vss/tools/smart-city')
from evaluate_mv3dt_probe import assignment,percentile,evaluate
from isaac_site import project
ROOT=Path('/home/sparkdev/vss')
RUNS=[('road-plane','mv3dt','probe-20261023T043825Z','1792730163503929787'),('person-plane','mv3dt-person-plane','probe-20261023T044318Z','1792730597793823324')]
def summary(vals):return {'count':len(vals),'median':percentile(vals,.5),'p95':percentile(vals,.95),'maximum':max(vals) if vals else None}
def short(s):return s.split('/')[3]
def audit(name,folder,rid,gtid):
 p=ROOT/'.spark/city/state/native'/folder;run=p/rid;gp=Path('/home/sparkdev/isaac_city_sim/logs/vss-integration')/f'evaluation-ground-truth-{gtid}.ndjson'
 out=evaluate(run,gp,p/'package.json');saved=json.loads((run/'engineering-comparison-final.json').read_text())
 package=json.loads((p/'package.json').read_text());cams={c['sourceId']:c for c in package['cameras']}
 gt=[json.loads(l) for l in gp.read_text().splitlines()][1:];times=[int(g['captureUnixNs']) for g in gt]
 rows=[json.loads(l) for l in (run/'observations.ndjson').read_text().splitlines()];valid=[r for r in rows if r['timestampBasis']=='source-rtcp'];start=min(int(r['sourceTimeNs']) for r in valid)
 scored=[];matches=[];counts=collections.Counter();idlabels=collections.defaultdict(collections.Counter);isolated_idlabels=collections.defaultdict(collections.Counter)
 gt_skews=[];foot_h_error=[];foot_bbox_ground_error=[];native_foot_label_error=[]
 for r in valid:
  t=int(r['sourceTimeNs'])
  if t-start<1e10:continue
  ix=bisect.bisect_left(times,t);ix=min([i for i in (ix-1,ix) if 0<=i<len(times)],key=lambda i:abs(times[i]-t));sk=times[ix]-t
  if abs(sk)>250e6:continue
  gt_skews.append(sk/1e6);c=cams[r['sourceId']];labels=[]
  for nm,w in gt[ix]['peopleWorldM'].items():
   q=[sum(a*b for a,b in zip(line,[w[0],w[1],w[2]-package.get('groundWorldZM',-.2),1])) for line in c['projectionMatrix3x4']]
   if q[2]<=0:continue
   pixel=[q[0]/q[2],q[1]/q[2]]
   if 0<=pixel[0]<=c['width'] and 0<=pixel[1]<=c['height']:labels.append((short(nm),w[:2],pixel))
  objects=[o for o in r['objects'] if o['class']=='person' and o['observedThisFrame'] and o.get('native3D') and o['native3D'].get('visibility') is not None and o['native3D']['visibility']>=.25]
  costs=[]
  for o in objects:
   x,y,w,h=o['bboxPx'];costs.append([math.hypot((px[0]-x-w/2)/max(w,10),(px[1]-y-h)/max(h,20)) for nm,pos,px in labels])
   foot_h_error.append(math.dist(project(c['imageToGroundHomography'],o['native3D']['imageFootPx']),o['native3D']['worldPositionM']))
   foot_bbox_ground_error.append(math.dist(project(c['imageToGroundHomography'],[x+w/2,y+h]),o['native3D']['worldPositionM']))
  ids=[o['localTrackId'] for o in objects];counts['sameFrameDuplicateIdRows']+=len(ids)!=len(set(ids))
  rr={'t':t,'source':r['sourceId'],'matches':{}}
  for oi,li in assignment(costs):
   o=objects[oi];nm,pos,px=labels[li];x,y,w,h=o['bboxPx'];tid=o['localTrackId'];gate_roots=sum(v<1 for v in costs[oi]);gate_objects=sum(cs[li]<1 for cs in costs);isolated=gate_roots==1 and gate_objects==1
   counts['ambiguousMultipleRoots']+=gate_roots>1;counts['ambiguousMultipleObjects']+=gate_objects>1;counts['assignmentNotNearest']+=costs[oi][li]>min(costs[oi])+1e-12;counts['isolatedByOriginalImageGate']+=isolated
   native_foot_label_error.append(math.dist(o['native3D']['imageFootPx'],px))
   m={'source':r['sourceId'],'t':t,'id':tid,'actor':nm,'isolated':isolated,'cost':costs[oi][li],'error':math.dist(o['native3D']['worldPositionM'],pos),'baselineError':math.dist(project(c['imageToGroundHomography'],[x+w/2,y+h]),pos),'pos':o['native3D']['worldPositionM'],'gt':pos,'roots':gate_roots,'objects':gate_objects}
   matches.append(m);rr['matches'][nm]=m;idlabels[tid][nm]+=1
   if isolated:isolated_idlabels[tid][nm]+=1
  scored.append(rr)
 bysource={s:[r for r in scored if r['source']==s] for s in cams};a,b=bysource.values();bt=[r['t'] for r in b];used=collections.Counter();conflicts=[];same=[];opp=collections.Counter()
 for r in a:
  ix=bisect.bisect_left(bt,r['t']);i=min([i for i in (ix-1,ix) if 0<=i<len(b)],key=lambda i:abs(bt[i]-r['t']))
  if abs(bt[i]-r['t'])>50e6:continue
  used[i]+=1;other=b[i]
  for nm in r['matches'].keys()&other['matches'].keys():
   m,n=r['matches'][nm],other['matches'][nm];opp['all']+=1;opp['same']+=m['id']==n['id']
   if m['isolated'] and n['isolated']:opp['isolated']+=1;opp['isolatedSame']+=m['id']==n['id']
  for m in r['matches'].values():
   for n in other['matches'].values():
    if m['id']==n['id']:
     same.append(math.dist(m['pos'],n['pos']))
     if m['actor']!=n['actor']:conflicts.append({'id':m['id'],'actors':[m['actor'],n['actor']],'timeNs':str(r['t']),'isolatedBoth':m['isolated'] and n['isolated'],'groundTruthSeparationM':math.dist(m['gt'],n['gt']),'nativeSeparationM':math.dist(m['pos'],n['pos'])})
 per_actor={};switches=collections.Counter();previous={}
 for m in matches:
  key=(m['source'],m['actor']);old=previous.get(key)
  if old and m['t']-old['t']<=500e6 and old['id']!=m['id']:switches['all']+=1;switches['isolatedBoth']+=old['isolated'] and m['isolated']
  previous[key]=m
 for actor in sorted({m['actor'] for m in matches}):
  mm=[m for m in matches if m['actor']==actor];per_actor[actor]={'matches':len(mm),'uniqueSdkIds':len({m['id'] for m in mm}),'isolatedUniqueSdkIds':len({m['id'] for m in mm if m['isolated']}),'positionM':summary([m['error'] for m in mm]),'isolatedPositionM':summary([m['error'] for m in mm if m['isolated']])}
 invocation=json.loads((run/'invocation.json').read_text());config_names=['package.json','camera-0.yml','camera-1.yml','tracker-mv3dt.experimental.yml','promotion-gates.json','pub-sub.yml'];config_match={k:hashlib.sha256((p/k).read_bytes()).hexdigest()==invocation['inputHashes'][k] for k in config_names}
 timing_sensitivity = {}
 for offset in (-250, -100, -50, 0, 50, 100, 250):
  ne=[];be=[]
  for m in matches:
   tt=m['t']+offset*1000000;ix=bisect.bisect_left(times,tt);ix=min([i for i in (ix-1,ix) if 0<=i<len(times)],key=lambda i:abs(times[i]-tt))
   if abs(times[ix]-tt)>250e6:continue
   w=next(w[:2] for nm,w in gt[ix]['peopleWorldM'].items() if short(nm)==m['actor'])
   ne.append(math.dist(m['pos'],w))
  timing_sensitivity[str(offset)] = summary(ne)
 command=invocation['command']; source_order=[command[i+1].split('=',1)[0] for i,v in enumerate(command[:-1]) if v=='--source']
 result={'schemaVersion':'city.mv3dt.offline-audit.v1','run':str(run.relative_to(ROOT)),'savedMetricsReproducedExactly':out['metrics']==saved['metrics'],'savedChecksReproducedExactly':all(out['checks'][k]==v for k,v in saved['checks'].items()),'inputIntegrity':out['inputIntegrity'],'passedOriginalGates':out['passed'],'originalChecks':out['checks'],'originalMetrics':out['metrics'],'groundTruthSha256':out['groundTruthSha256'],'observationsSha256':out['observationsSha256'],'configHashesMatchInvocation':config_match,'cameraOrderMatchesInvocation':list(cams)==source_order,'timingSensitivityFixedOriginalActorLabelsNativeM':timing_sensitivity,'sourceClock':{'strictlyMonotonicBySource':all(all(int(b['sourceTimeNs'])>int(a['sourceTimeNs']) for a,b in zip(rr,rr[1:])) for rr in [[r for r in valid if r['sourceId']==s] for s in cams]),'scoredSourceSessions':{s:len({r['sourceSessionId'] for r in valid if r['sourceId']==s and int(r['sourceTimeNs'])-start>=1e10}) for s in cams},'fusionEpochs':len({r['fusionEpoch'] for r in valid}),'sourceToNearestGtOffsetMs':summary(gt_skews),'pairedSecondViewReuseCount':sum(v-1 for v in used.values())},'imageAssignmentDiagnostics':dict(counts),'identityDiagnostics':{'idLabelCounts':dict(idlabels),'idsWithMultipleIsolatedLabels':{i:dict(v) for i,v in isolated_idlabels.items() if len(v)>1},'crossView':dict(opp),'simultaneousConflictingIdPairs':len(conflicts),'simultaneousConflictingIdPairsIsolatedBoth':sum(c['isolatedBoth'] for c in conflicts),'isolatedConflictTruthSeparationM':summary([c['groundTruthSeparationM'] for c in conflicts if c['isolatedBoth']]),'isolatedConflictNativeSeparationM':summary([c['nativeSeparationM'] for c in conflicts if c['isolatedBoth']]),'conflictsById':dict(collections.Counter(c['id'] for c in conflicts)),'firstIsolatedConflicts':[c for c in conflicts if c['isolatedBoth']][:8],'sameIdNativeCrossViewSeparationM':summary(same),'observedIdChangesWithin500Ms':dict(switches),'people':per_actor},'positionDiagnostics':{'nativeImageFootHomographyVsNativeWorldM':summary(foot_h_error),'nativeWorldVsBboxBottomGroundM':summary(foot_bbox_ground_error),'nativeFootVsMatchedGtPixelPx':summary(native_foot_label_error),'isolatedMatchesNativeM':summary([m['error'] for m in matches if m['isolated']]),'isolatedMatchesBboxGroundM':summary([m['baselineError'] for m in matches if m['isolated']])},'limits':['Diagnostic subsets do not remove samples from saved promotion gates.','Isolated means one-to-one under the original image-space distance gate, not independently verified visibility or correct identity.','Unique SDK IDs per actor and short-gap changes include tracker ID corrections, label error and fragmentation; not HOTA/IDF1.','GT capture time versus source RTCP is nearest-neighbor matching, not recorded frame-ID evidence.']}
 dest=ROOT/'docs/qa/smart-city-2026-10-23'/f'mv3dt-{name}-offline-audit.json';dest.write_text(json.dumps(result,indent=2)+'\n')
 print(name,json.dumps({k:result[k] for k in ['savedMetricsReproducedExactly','savedChecksReproducedExactly','sourceClock','imageAssignmentDiagnostics','positionDiagnostics']}));print('identity',json.dumps({k:v for k,v in result['identityDiagnostics'].items() if k not in ['idLabelCounts','people']}))
for args in RUNS:audit(*args)
