#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline geometry-based MV3DT comparison against separately recorded world poses.

No GT is supplied to inference/analytics. Strict, predeclared gates are not an
independent image/identity annotation: exposure/render delay is not measured.
"""
from __future__ import annotations
import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from audit_live_tail import anchor, eligible, stats

MAX_DISTANCE_M = 2.0
MIN_MARGIN_M = 1.0
MAX_GT_BRACKET_NS = 500_000_000
OFFSETS_MS = (-100, -50, 0, 50, 100)
VEHICLE_CLASSES = ('bicycle', 'car', 'truck', 'bus', 'motorcycle')


def ground_class(vehicle):
    # Fixed before inspecting results, based on the authored asset, not output
    # class scores. TrafficSim groups the pickup into its kinematic car family.
    return 'truck' if Path(vehicle['asset']).name == 'car_pickup.usdc' else vehicle['simulationClass']


def sample_time(sample):
    return (int(sample['sampleStartUnixNs']) + int(sample['sampleEndUnixNs'])) // 2


def normal(sample):
    return (sample.get('playing') is True and not sample.get('errors') and not sample['scenario']['active']
            and sample['scenario'].get('classicState') in (None, 'IDLE', 'CLEARED', 'ABORTED')
            and all(not obj.get('scenarioOwner') and not obj.get('scenarioHeld')
                    and obj['modelToActualWorldErrorM'] <= 1e-5 for obj in sample['vehicles']))


def interpolate(samples, times, timestamp):
    index = bisect_left(times, timestamp)
    if not 0 < index < len(samples):
        return None, 'unbracketed'
    a, b = samples[index-1], samples[index]
    dt = times[index] - times[index-1]
    if dt <= 0 or dt > MAX_GT_BRACKET_NS:
        return None, 'GT-gap'
    if not normal(a) or not normal(b):
        return None, 'staged-or-invalid-GT'
    epoch = lambda x: (x['stageId'], x['controllerGeneration'], x['trafficGeneration'])
    if epoch(a) != epoch(b):
        return None, 'GT-generation-change'
    aa = {obj['arrivalId']: obj for obj in a['vehicles']}
    bb = {obj['arrivalId']: obj for obj in b['vehicles']}
    fraction = (timestamp-times[index-1]) / dt
    actors = []
    for identity in aa.keys() & bb.keys():
        first, second = aa[identity], bb[identity]
        if (first['asset'], first['primPath']) != (second['asset'], second['primPath']):
            continue
        distance = math.dist(first['worldPositionM'], second['worldPositionM'])
        if distance / (dt/1e9) > 25:
            continue  # Reject discontinuity; do not interpolate teleport/respawn.
        actors.append({'arrivalId': identity, 'class': ground_class(first), 'asset': first['asset'],
                       'positionM': [x+(y-x)*fraction for x,y in zip(first['worldPositionM'], second['worldPositionM'])]})
    return actors, None


def match(point, class_name, actors):
    distances = sorted((math.dist(point, actor['positionM'][:2]), actor['arrivalId'], actor) for actor in actors)
    if not distances:
        return None, 'no-GT-actors'
    distance, _, actor = distances[0]
    if distance > MAX_DISTANCE_M:
        return None, 'beyond-2m'
    # Test the nearest actual actor's class; never skip a closer wrong-class actor
    # to make a more distant same-class association appear valid.
    if actor['class'] != class_name:
        return None, 'class-mismatch'
    margin = distances[1][0]-distance if len(distances) > 1 else math.inf
    if margin < MIN_MARGIN_M:
        return None, 'margin-below-1m'
    return {'arrivalId': actor['arrivalId'], 'distanceM': distance, 'runnerUpMarginM': None if math.isinf(margin) else margin,
            'positionM': actor['positionM'], 'asset': actor['asset']}, None


def frame_objects(row):
    objects = [obj for obj in row['objects'] if obj['class'] in VEHICLE_CLASSES and eligible(obj)]
    counts = Counter(obj['native3D']['targetId'] for obj in objects)
    return {obj['native3D']['targetId']: obj for obj in objects if counts[obj['native3D']['targetId']] == 1}


def evaluate(samples, rows, calibrations):
    times = [sample_time(sample) for sample in samples]
    if any(b <= a for a,b in zip(times,times[1:])):
        raise ValueError('GT sample wall clock is not strictly increasing.')
    epochs = {row.get('fusionEpoch') for row in rows}
    if len(epochs) != 1:
        raise ValueError('Observation capture crosses fusion epochs.')
    ids = sorted({row['sourceId'] for row in rows})
    if len(ids) != 2:
        raise ValueError('Expected exactly two cameras.')
    grouped = {source: [row for row in rows if row['sourceId']==source and row['timestampBasis']=='source-rtcp'] for source in ids}
    for source,records in grouped.items():
        if len({row['sourceSessionId'] for row in records}) != 1:
            raise ValueError('Observation source session changed.')
        if any(int(b['sourceTimeNs']) <= int(a['sourceTimeNs']) for a,b in zip(records,records[1:])):
            raise ValueError('Observation source time is not strictly increasing.')
        if any(obj['native3D']['calibrationRevision'] != calibrations[source]['calibrationRevision']
               for row in records for obj in frame_objects(row).values()):
            raise ValueError('Observation calibration differs from pinned calibration.')
    aa, bb = [grouped[source] for source in ids]
    bt = [int(row['sourceTimeNs']) for row in bb]
    low, high = max(int(aa[0]['sourceTimeNs']),bt[0]), min(int(aa[-1]['sourceTimeNs']),bt[-1])
    frames=[]
    for row in aa:
        timestamp=int(row['sourceTimeNs'])
        if not low <= timestamp <= high:
            continue
        index=bisect_left(bt,timestamp)
        index=min((x for x in (index-1,index) if 0<=x<len(bt)),key=lambda x:abs(bt[x]-timestamp))
        if abs(bt[index]-timestamp)<=50_000_000:
            frames.append((row,bb[index]))
    output={'sourceOrder':ids,'framePairsWithin50Ms':len(frames),'offsetsMs':{},'robustSharedPairResults':{}}
    pair_assignments=defaultdict(dict)
    for offset in OFFSETS_MS:
        results={kind:{name:{'sharedSdkPairCounts':Counter(),'trueActorPairSdkAgreement':Counter(),
                             'matchedObjectErrorsM':[],'unmatchedReasons':Counter(),'sharedSdkIds':set()}
                       for name in VEHICLE_CLASSES} for kind in ('rect','world')}
        for ar,br in frames:
            objects_a,objects_b=frame_objects(ar),frame_objects(br)
            truths=[]
            for row in (ar,br):
                actors,reason=interpolate(samples,times,int(row['sourceTimeNs'])+offset*1_000_000)
                truths.append((actors,reason))
            for kind in ('rect','world'):
                mappings=[]
                for row,objects,(actors,reason) in zip((ar,br),(objects_a,objects_b),truths):
                    mapped={}
                    for identity,obj in objects.items():
                        point=anchor(row,obj,calibrations,kind)
                        matched,failure=match(point,obj['class'],actors) if actors is not None else (None,reason)
                        if failure:results[kind][obj['class']]['unmatchedReasons'][failure]+=1
                        else:
                            mapped[identity]=matched
                            results[kind][obj['class']]['matchedObjectErrorsM'].append(matched['distanceM'])
                    # Multiple same-camera boxes assigned to one actor cannot
                    # choose a winner for the true-actor ID agreement measure.
                    collisions=Counter(value['arrivalId'] for value in mapped.values())
                    mappings.append((mapped,collisions))
                (ma,ca),(mb,cb)=mappings
                for identity in objects_a.keys() & objects_b.keys():
                    ao,bo=objects_a[identity],objects_b[identity]
                    if ao['class']!=bo['class']:continue
                    record=results[kind][ao['class']];record['sharedSdkIds'].add(identity)
                    record['sharedSdkPairCounts']['candidates']+=1
                    a,b=ma.get(identity),mb.get(identity)
                    outcome=('same-actor' if a['arrivalId']==b['arrivalId'] else 'different-actor') if a and b else 'one-or-both-unmatched'
                    record['sharedSdkPairCounts'][outcome]+=1
                    separation=math.dist(anchor(ar,ao,calibrations,kind),anchor(br,bo,calibrations,kind))
                    if separation<=1:
                        record['sharedSdkPairCounts']['within-1m']+=1
                        record['sharedSdkPairCounts']['within-1m-'+outcome]+=1
                    key=(kind,ao['class'],identity,ar['sourceId'],ar['sourceFrameId'],br['sourceFrameId'])
                    pair_assignments[key][offset]=(outcome,a['arrivalId'] if a else None,b['arrivalId'] if b else None)
                ga={v['arrivalId']:identity for identity,v in ma.items() if ca[v['arrivalId']]==1}
                gb={v['arrivalId']:identity for identity,v in mb.items() if cb[v['arrivalId']]==1}
                for actor in ga.keys() & gb.keys():
                    ia,ib=ga[actor],gb[actor];name=objects_a[ia]['class']
                    if objects_b[ib]['class']!=name:continue
                    record=results[kind][name]['trueActorPairSdkAgreement']
                    record['eligible-actor-pairs']+=1;record['same-sdk-id' if ia==ib else 'different-sdk-id']+=1
        for kind in results:
            for record in results[kind].values():
                record['matchedObjectErrorsM']=stats(record['matchedObjectErrorsM'])
                record['sharedSdkIds']=sorted(record['sharedSdkIds'])
        output['offsetsMs'][str(offset)]=results
    robust=defaultdict(Counter)
    for (kind,name,*_),items in pair_assignments.items():
        if len(items)!=len(OFFSETS_MS):raise ValueError('Missing predeclared sensitivity offset.')
        values=list(items.values())
        if len(set(values))==1 and values[0][0]=='same-actor':verdict='same-actor-all-offsets'
        elif len(set(values))==1 and values[0][0]=='different-actor':verdict='different-actor-all-offsets'
        elif all(value[0]=='one-or-both-unmatched' for value in values):verdict='unmatched-all-offsets'
        else:verdict='timing-sensitive-or-partly-unmatched'
        robust[(kind,name)][verdict]+=1
    output['robustSharedPairResults']={kind:{name:dict(robust[(kind,name)]) for name in VEHICLE_CLASSES} for kind in ('rect','world')}
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--calibrations',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads((args.capture/'manifest.json').read_text())
    if manifest['result']!='complete':raise ValueError('GT capture did not complete.')
    for name,limit in [('ground-truth.ndjson',8*1024*1024),('observations.ndjson',32*1024*1024)]:
        if (args.capture/name).stat().st_size>limit:raise ValueError('Capture exceeds byte bound.')
    samples=[json.loads(row) for row in (args.capture/'ground-truth.ndjson').read_text().splitlines()]
    rows=[json.loads(row) for row in (args.capture/'observations.ndjson').read_text().splitlines()]
    calibrations=json.loads(args.calibrations.read_text())
    result={'schemaVersion':'city.vehicle-ground-truth-evaluation.v1','limits':{
        'maximumDistanceM':MAX_DISTANCE_M,'minimumRunnerUpMarginM':MIN_MARGIN_M,'maximumGtBracketMs':MAX_GT_BRACKET_NS/1e6,
        'timeSensitivityOffsetsMs':list(OFFSETS_MS),'interpretation':'Geometry-based GT correspondences, not independent image identity accuracy. Handoff/render exposure delay is unmeasured. No GT enters analytics.',
        'classMapping':'Authored car_pickup.usdc -> truck; other authored simulation classes unchanged. Nearest actual actor must have the predicted class; do not skip a nearer wrong class.'},
        'capture':manifest,'files':{name:hashlib.sha256((args.capture/name).read_bytes()).hexdigest() for name in ('manifest.json','ground-truth.ndjson','observations.ndjson')},
        'calibrationsSha256':hashlib.sha256(args.calibrations.read_bytes()).hexdigest(),
        'groundTruth':{'snapshots':len(samples),'normalSnapshots':sum(normal(x) for x in samples),
            'readWallMs':stats([x['readWallMilliseconds'] for x in samples]),
            'intervalMs':stats([(sample_time(b)-sample_time(a))/1e6 for a,b in zip(samples,samples[1:])]),
            'maximumModelToActualWorldErrorM':max((v['modelToActualWorldErrorM'] for x in samples for v in x['vehicles']),default=None),
            'uniqueArrivalIdsByClass':{name:sorted({v['arrivalId'] for x in samples for v in x['vehicles'] if ground_class(v)==name}) for name in VEHICLE_CLASSES}},
        'evaluation':evaluate(samples,rows,calibrations)}
    with args.output.open('x') as output:output.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
