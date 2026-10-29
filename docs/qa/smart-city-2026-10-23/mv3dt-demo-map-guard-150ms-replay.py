#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CPU-only map guard estimate from saved inference, held-out labels and static camera snapshot.
No runtime access, label changes, threshold tuning or operational actor-truth input.
"""
import sys,json,math,bisect,hashlib,collections
from pathlib import Path
ROOT=Path('/home/sparkdev/vss');sys.path.insert(0,str(ROOT/'tools/smart-city'));sys.path.insert(0,str(ROOT/'services/analytics/behavior-analytics'))
from evaluate_mv3dt_probe import assignment,percentile
from apps.city.geometry import project
run=ROOT/'.spark/city/state/native/mv3dt/probe-mv3dt-no-see-through-20261023T191702471164Z'
gp=Path('/home/sparkdev/isaac_city_sim/logs/vss-integration/evaluation-ground-truth-1792783015032122329.ndjson')
pkg=json.loads((run/'package.json').read_text());cams={c['sourceId']:c for c in pkg['cameras']}
# Reuse the exact public static site snapshot retained by the first read-only audit.
retained=json.loads((ROOT/'docs/qa/smart-city-2026-10-23/mv3dt-demo-map-guard-offline-estimate.json').read_text())['currentStaticSite']
site={'id':retained['siteId'],'revision':retained['siteRevision'],'map':{'bounds':retained['mapBounds']},'sources':retained['sources']}
current={s['id']:s for s in site['sources']};assert set(current)==set(cams)
static={'siteId':site['id'],'siteRevision':site['revision'],'mapBounds':site['map']['bounds'],'sources':[{k:s.get(k) for k in ['id','width','height','calibrationRevision','imageToGroundHomography','classImageToGroundHomographies','validGroundPolygon']} for s in site['sources']]}
gt=[json.loads(l) for l in gp.read_text().splitlines()][1:];times=[int(g['captureUnixNs']) for g in gt];rows=[json.loads(l) for l in (run/'observations.ndjson').read_text().splitlines()];valid=[r for r in rows if r['timestampBasis']=='source-rtcp'];start=min(int(r['sourceTimeNs']) for r in valid)
scored=[];counts=collections.Counter({'accepted:same-actor':0,'accepted:different-actor':0,'accepted:unmatched-label':0});examples=[]
for r in valid:
 t=int(r['sourceTimeNs'])
 if t-start<1e10:continue
 ix=bisect.bisect_left(times,t);ix=min([i for i in (ix-1,ix) if 0<=i<len(times)],key=lambda i:abs(times[i]-t));labels=[];c=cams[r['sourceId']]
 if abs(times[ix]-t)<=250e6:
  for nm,w in gt[ix]['peopleWorldM'].items():
   q=[sum(a*b for a,b in zip(line,[w[0],w[1],w[2]-pkg.get('groundWorldZM',-.2),1])) for line in c['projectionMatrix3x4']]
   if q[2]<=0:continue
   px=[q[0]/q[2],q[1]/q[2]]
   if 0<=px[0]<=c['width'] and 0<=px[1]<=c['height']:labels.append((nm.split('/')[3],w[:2],px))
 objects=[o for o in r['objects'] if o['class']=='person' and o['observedThisFrame'] and o.get('native3D') and o['native3D'].get('visibility') is not None and o['native3D']['visibility']>=.25]
 costs=[]
 for o in objects:
  x,y,w,h=o['bboxPx'];costs.append([math.hypot((px[0]-x-w/2)/max(w,10),(px[1]-y-h)/max(h,20)) for nm,pos,px in labels])
 selected={oi:li for oi,li in assignment(costs)};mapped=[]
 for oi,o in enumerate(objects):
  cfg=current[r['sourceId']];x,y,w,h=o['bboxPx'];pos,status=project([x+w/2,y+h],cfg['classImageToGroundHomographies']['person'],cfg.get('validGroundPolygon'),site['map']['bounds'])
  if not(0<=x+w/2<=cfg['width'] and 0<=y+h<=cfg['height']):pos=None
  li=selected.get(oi);label=labels[li][0] if li is not None else None
  isolated=li is not None and sum(v<1 for v in costs[oi])==1 and sum(cs[li]<1 for cs in costs)==1
  mapped.append({'id':o['localTrackId'],'position':pos,'label':label,'isolated':isolated,'projectionStatus':status,'visibility':o['native3D']['visibility']})
 scored.append({'time':t,'source':r['sourceId'],'objects':mapped})
a,b=[[r for r in scored if r['source']==s] for s in cams];bt=[r['time'] for r in b];distances=[];used=collections.Counter();same_actor_opps=0;guard_same=0;skews=[]
for r in a:
 ix=bisect.bisect_left(bt,r['time']);i=min([i for i in (ix-1,ix) if 0<=i<len(bt)],key=lambda i:abs(bt[i]-r['time']));other=b[i];skew=abs(other['time']-r['time'])/1e6;skews.append(skew);counts['candidateFramePairs']+=1
 if skew>150:counts['framePairsRejectedClock']+=1;continue
 counts['framePairsWithin150Ms']+=1;used[i]+=1
 for m in r['objects']:
  for n in other['objects']:
   if m['label'] is not None and m['label']==n['label']:same_actor_opps+=1
   if m['id']!=n['id']:continue
   counts['sharedSdkIdPersonPairs']+=1
   label_kind = 'unmatched-label' if m['label'] is None or n['label'] is None else ('same-actor' if m['label']==n['label'] else 'different-actor')
   counts['shared:'+label_kind]+=1
   if m['position'] is None or n['position'] is None:counts['pairsRejectedProjection']+=1;continue
   distance=math.dist(m['position'],n['position']);distances.append(distance)
   if distance>1:counts['pairsRejectedOver1m']+=1;counts['distance-rejected:'+label_kind]+=1;continue
   counts['acceptedDisplayPairs']+=1
   if m['label'] is None or n['label'] is None:kind='unmatched-label'
   elif m['label']==n['label']:kind='same-actor';guard_same+=1
   else:kind='different-actor'
   counts['accepted:'+kind]+=1
   if m['isolated'] and n['isolated']:counts['accepted-isolated:'+kind]+=1
   if kind!='same-actor' and len(examples)<15:examples.append({'sourceTimeNs':str(r['time']),'targetId':m['id'],'labels':[m['label'],n['label']],'bothIsolated':m['isolated'] and n['isolated'],'positionAgreementM':distance,'cameraSkewMs':skew})
result={'schemaVersion':'city.mv3dt.demo-map-guard-analysis.v1','displayPolicy':'User-authorized demo-only 150ms window; production 50ms qualification unchanged','qualificationCameraSkewMs':50,'sourceOnly':True,'runtimeChanged':False,'productionQualified':False,'run':str(run.relative_to(ROOT)),'thresholds':{'warmupSeconds':10,'maximumCameraSkewMs':150,'maximumHomographyPositionDifferenceM':1,'minimumNativeVisibility':.25,'imageAssignmentGate':1,'maximumGtSkewMs':250},'inputHashes':{'observations':hashlib.sha256((run/'observations.ndjson').read_bytes()).hexdigest(),'groundTruth':hashlib.sha256(gp.read_bytes()).hexdigest(),'runPackage':hashlib.sha256((run/'package.json').read_bytes()).hexdigest(),'currentStaticSite':hashlib.sha256(json.dumps(static,sort_keys=True).encode()).hexdigest()},'currentStaticSite':static,'counts':dict(counts),'sameActorPairedImageAssignmentOpportunities':same_actor_opps,'correctDisplayPairFractionOfLabelledOpportunities':guard_same/same_actor_opps if same_actor_opps else None,'nearestFrameSkewP95Ms':percentile(skews,.95),'secondCameraFrameReuseCount':sum(v-1 for v in used.values()),'sharedIdHomographyAgreementMedianM':percentile(distances,.5),'sharedIdHomographyAgreementP95M':percentile(distances,.95),'acceptedNonSameActorExamples':examples,'limits':['Existing image-space label assignments are unchanged; ambiguity and occlusion remain unverified.','No samples relabelled or thresholds tuned for a pass.','This offline guard estimate uses every detector frame, not the actual UI preview cadence.','The source run emitted diagnostic SDK IDs, not server-approved mv3dt-demo hints; this estimates the geometric/clock display guard only.','Full original production qualification gates remain failed.','Counts are frame-pair observations, not distinct people or unique mistakes.']}
out=ROOT/'docs/qa/smart-city-2026-10-23/mv3dt-demo-map-guard-150ms-offline-estimate.json';out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['counts','sameActorPairedImageAssignmentOpportunities','correctDisplayPairFractionOfLabelledOpportunities','nearestFrameSkewP95Ms','secondCameraFrameReuseCount','sharedIdHomographyAgreementMedianM','sharedIdHomographyAgreementP95M','acceptedNonSameActorExamples']},indent=2))
