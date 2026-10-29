#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evaluate the unconnected map prototype on fixed recorded world-pose evidence."""
from __future__ import annotations
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from evaluate_vehicle_ground_truth import interpolate, sample_time, match, OFFSETS_MS, VEHICLE_CLASSES, evaluate
from prototype_vehicle_map_association import (VehicleMapAssociator, objects, MAX_SKEW_NS, MAX_DISTANCE_M,
                                              MIN_MARGIN_M, CONFIRMATIONS, LEASE_TTL_NS)


def run(samples, rows, calibrations):
    # Reuse the independent evaluator's epoch/session/calibration/clock checks.
    baseline=evaluate(samples,rows,calibrations)
    ids=baseline['sourceOrder']
    grouped={source:[row for row in rows if row['sourceId']==source and row['timestampBasis']=='source-rtcp'] for source in ids}
    aa,bb=[grouped[source] for source in ids];bt=[int(row['sourceTimeNs']) for row in bb]
    low,high=max(int(aa[0]['sourceTimeNs']),bt[0]),min(int(aa[-1]['sourceTimeNs']),bt[-1])
    frames=[]
    for row in aa:
        timestamp=int(row['sourceTimeNs'])
        if not low<=timestamp<=high:continue
        index=bisect_left(bt,timestamp)
        index=min((i for i in (index-1,index) if 0<=i<len(bt)),key=lambda i:abs(bt[i]-timestamp))
        if abs(bt[index]-timestamp)<=MAX_SKEW_NS:frames.append((row,bb[index]))
    if len(frames)!=baseline['framePairsWithin50Ms']:raise AssertionError('Baseline frame selection differs.')
    prototype=VehicleMapAssociator(ids,rows[0]['fusionEpoch'],{source:calibrations[source]['calibrationRevision'] for source in ids})
    times=[sample_time(sample) for sample in samples];cache={};counts=defaultdict(Counter)
    def assignments(row,offset):
        key=(row['sourceId'],row['sourceFrameId'],offset)
        if key in cache:return cache[key]
        actors,error=interpolate(samples,times,int(row['sourceTimeNs'])+offset*1_000_000)
        mapped={};failures={}
        for identity,obj in objects(row,calibrations[row['sourceId']]['calibrationRevision']).items():
            assigned,reason=match(obj['native3D']['worldPositionM'],obj['class'],actors) if actors is not None else (None,error)
            if assigned:mapped[identity]=assigned
            else:failures[identity]=reason
        collisions=Counter(value['arrivalId'] for value in mapped.values())
        for identity in list(mapped):
            if collisions[mapped[identity]['arrivalId']]>1:
                del mapped[identity];failures[identity]='multiple-observations-for-one-GT-actor'
        cache[key]=(mapped,failures);return mapped,failures
    def score(rowa,rowb,item,offset):
        a,ea=assignments(rowa,offset);b,eb=assignments(rowb,offset);ia,ib=item['targetIds'];ga,gb=a.get(ia),b.get(ib)
        if ga and gb:return ('same-actor' if ga['arrivalId']==gb['arrivalId'] else 'different-actor',ga['arrivalId'],gb['arrivalId'])
        return ('one-or-both-unmatched',ga['arrivalId'] if ga else None,gb['arrivalId'] if gb else None)
    raw_candidates=Counter();confirmed=Counter();sdk_equal=Counter();leases=defaultdict(set);confirmed_scores=defaultdict(Counter)
    raw_scores=defaultdict(Counter);robust=defaultdict(Counter);examples=defaultdict(list);gtcoverage=defaultdict(Counter)
    all_associations=[]
    for ar,br in frames:
        update=prototype.update(ar,br)
        candidate_pairs={tuple(item['targetIds']) for item in update['candidates']}
        confirmed_pairs={tuple(item['targetIds']) for item in update['associations']}
        for item in update['candidates']:
            name=item['class'];raw_candidates[name]+=1
            for offset in OFFSETS_MS:raw_scores[(offset,name)][score(ar,br,item,offset)[0]]+=1
        for item in update['associations']:
            name=item['class'];confirmed[name]+=1;leases[name].add(item['mapAssociationId'])
            sdk_equal[name]+=item['targetIds'][0]==item['targetIds'][1]
            outcomes=[score(ar,br,item,offset) for offset in OFFSETS_MS]
            for offset,value in zip(OFFSETS_MS,outcomes):confirmed_scores[(offset,name)][value[0]]+=1
            stable=('same-actor-all-offsets' if outcomes[0][0]=='same-actor' else 'different-actor-all-offsets') if len(set(outcomes))==1 and outcomes[0][0]!='one-or-both-unmatched' else ('unmatched-all-offsets' if all(v[0]=='one-or-both-unmatched' for v in outcomes) else 'timing-sensitive-or-partly-unmatched')
            robust[name][stable]+=1
            record={**item,'sourceFrameIds':[ar['sourceFrameId'],br['sourceFrameId']],
                    'gtSensitivity':{str(offset):value for offset,value in zip(OFFSETS_MS,outcomes)}}
            all_associations.append(record)
            if len(examples[(name,stable)])<3:examples[(name,stable)].append(record)
        ga,_=assignments(ar,0);gb,_=assignments(br,0)
        byactor_a={value['arrivalId']:identity for identity,value in ga.items()};byactor_b={value['arrivalId']:identity for identity,value in gb.items()}
        ao,bo=objects(ar,calibrations[ar['sourceId']]['calibrationRevision']),objects(br,calibrations[br['sourceId']]['calibrationRevision'])
        for actor in byactor_a.keys()&byactor_b.keys():
            ia,ib=byactor_a[actor],byactor_b[actor];name=ao[ia]['class']
            if name!=bo[ib]['class']:continue
            record=gtcoverage[name];record['eligible-actor-pairs']+=1;record['native-same-sdk-id']+=ia==ib
            record['geometry-before-confirmation']+=(ia,ib) in candidate_pairs
            record['geometry-confirmed']+=(ia,ib) in confirmed_pairs
    result={'parameters':{'maximumClockSkewMs':MAX_SKEW_NS/1e6,'maximumDistanceM':MAX_DISTANCE_M,
                         'minimumRunnerUpMarginEachDirectionM':MIN_MARGIN_M,'mutualNearest':True,'confirmations':CONFIRMATIONS,
                         'leaseTtlMs':LEASE_TTL_NS/1e6,'displayOnCurrentValidPairOnly':True,'velocityHeadingGate':False},
            'framePairsWithin50Ms':len(frames),'groundTruthMatchGates':{'maximumDistanceM':2,'minimumMarginM':1,'maximumBracketMs':500,'offsetsMs':list(OFFSETS_MS)},
            'limitations':'Geometry-based GT correspondences, not independently annotated image IDs. Unmeasured render/exposure delay. GT is evaluation-only; prototype has no GT input or live VSS connection.',
            'byClass':{},'associations':all_associations}
    for name in VEHICLE_CLASSES:
        result['byClass'][name]={'rawCandidatePairObservations':raw_candidates[name],'confirmedPairObservations':confirmed[name],
            'uniqueMapLeases':len(leases[name]),'confirmedSameNativeSdkId':sdk_equal[name],
            'confirmedDifferentNativeSdkIds':confirmed[name]-sdk_equal[name],
            'rawGTByOffsetMs':{str(offset):dict(raw_scores[(offset,name)]) for offset in OFFSETS_MS},
            'confirmedGTByOffsetMs':{str(offset):dict(confirmed_scores[(offset,name)]) for offset in OFFSETS_MS},
            'robustGTAllOffsets':dict(robust[name]),'nominalGtCoverage':dict(gtcoverage[name]),
            'examples':{key:list(value) for (cls,key),value in examples.items() if cls==name}}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--calibrations',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    manifest=json.loads((args.capture/'manifest.json').read_text())
    if manifest['result']!='complete':raise ValueError('Capture is not complete.')
    for name,limit in [('ground-truth.ndjson',8*1024*1024),('observations.ndjson',32*1024*1024)]:
        if (args.capture/name).stat().st_size>limit:raise ValueError('Capture exceeds byte bound.')
    samples=[json.loads(line) for line in (args.capture/'ground-truth.ndjson').read_text().splitlines()]
    rows=[json.loads(line) for line in (args.capture/'observations.ndjson').read_text().splitlines()]
    calibrations=json.loads(args.calibrations.read_text());result=run(samples,rows,calibrations)
    result.update(schemaVersion='city.vehicle-geometry-prototype-evaluation.v1',capture=str(args.capture),
        sourceHashes={str(Path(__file__).name):hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      'prototype_vehicle_map_association.py':hashlib.sha256(Path(__file__).with_name('prototype_vehicle_map_association.py').read_bytes()).hexdigest()},
        observationSha256=hashlib.sha256((args.capture/'observations.ndjson').read_bytes()).hexdigest(),
        groundTruthSha256=hashlib.sha256((args.capture/'ground-truth.ndjson').read_bytes()).hexdigest(),
        calibrationsSha256=hashlib.sha256(args.calibrations.read_bytes()).hexdigest())
    with args.output.open('x') as output:output.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='associations'},indent=2))


if __name__=='__main__':main()
