#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CPU-only experimental map association; no native ID fusion or GT inputs.

This prototype is not wired into VSS. It groups only currently observed 3D
vehicle points satisfying fixed geometry/clock/uniqueness gates. Camera counts,
native IDs, boxes and event identities remain outside this display association.
"""
from __future__ import annotations
from collections import Counter
import math

CLASSES = frozenset(('bicycle', 'car', 'truck', 'bus', 'motorcycle'))
MAX_SKEW_NS = 50_000_000
MAX_DISTANCE_M = 1.0
MIN_MARGIN_M = .5
CONFIRMATIONS = 3
LEASE_TTL_NS = 500_000_000


def objects(row, calibration):
    if row.get('timestampBasis') != 'source-rtcp':
        return {}
    # Match the native worker's fail-closed cross-class ID ambiguity rule.
    counts=Counter(obj.get('localTrackId') for obj in row['objects'] if isinstance(obj.get('localTrackId'),str))
    valid=[]
    for obj in row['objects']:
        native=obj.get('native3D') or {}
        point=native.get('worldPositionM')
        target=native.get('targetId')
        visibility=native.get('visibility')
        if (obj.get('class') not in CLASSES or obj.get('observedThisFrame') is not True
                or native.get('state')!='observed' or native.get('method')!='nvidia-mv3dt-9.2'
                or native.get('calibrationRevision')!=calibration or target!=obj.get('localTrackId')
                or not isinstance(target,str) or not target or visibility is None or not .25<=visibility<=1
                or not isinstance(point,list) or len(point)!=2
                or not all(math.isfinite(x) and abs(x)<=100000 for x in point)):
            continue
        valid.append(obj)
    return {obj['native3D']['targetId']:obj for obj in valid if counts[obj['native3D']['targetId']]==1}


def unique_nearest(first, second):
    matches={}
    for identity,obj in first.items():
        distances=sorted((math.dist(obj['native3D']['worldPositionM'],peer['native3D']['worldPositionM']),target)
                         for target,peer in second.items() if obj['class']==peer['class'])
        if not distances or distances[0][0]>MAX_DISTANCE_M:
            continue
        margin=distances[1][0]-distances[0][0] if len(distances)>1 else math.inf
        if margin<MIN_MARGIN_M:
            continue
        matches[identity]=(distances[0][1],distances[0][0],margin)
    return matches


class VehicleMapAssociator:
    def __init__(self, source_order, fusion_epoch, calibrations):
        if len(source_order)!=2 or len(set(source_order))!=2 or not fusion_epoch:
            raise ValueError('Exactly two sources and a nonempty epoch are required.')
        self.sources=tuple(source_order)
        self.epoch=fusion_epoch
        self.calibrations=dict(calibrations)
        self.sessions=None
        self.leases={}
        self.sequence=0
        self.generation=0
        self.last_time=None

    def update(self, first, second):
        rows=(first,second)
        if tuple(row['sourceId'] for row in rows)!=self.sources:
            raise ValueError('Unexpected camera order.')
        if any(row.get('fusionEpoch')!=self.epoch for row in rows):
            self.leases.clear()
            raise ValueError('Shared fusion epoch changed; create a new associator.')
        timestamps=[int(row['sourceTimeNs']) for row in rows]
        now=max(timestamps)
        sessions=tuple(row['sourceSessionId'] for row in rows)
        if self.sessions is not None and sessions!=self.sessions:
            self.leases.clear();self.generation+=1
        self.sessions=sessions
        if self.last_time is not None and now<self.last_time:
            self.leases.clear();raise ValueError('Source frame clocks rewound.')
        self.last_time=now
        self.leases={key:lease for key,lease in self.leases.items() if now-lease['lastSeenNs']<=LEASE_TTL_NS}
        if abs(timestamps[0]-timestamps[1])>MAX_SKEW_NS or any(row.get('timestampBasis')!='source-rtcp' for row in rows):
            for lease in self.leases.values():lease['confirmations']=0
            return {'candidates':[],'associations':[]}
        aa,bb=[objects(row,self.calibrations[row['sourceId']]) for row in rows]
        observed_classes=[]
        for row in rows:
            by_id={}
            for obj in row['objects']:
                by_id.setdefault(obj.get('localTrackId'),set()).add(obj.get('class'))
            observed_classes.append(by_id)
        for key in list(self.leases):
            if any(target in by_id and by_id[target]!={key[0]}
                   for target,by_id in zip(key[1:],observed_classes)):
                del self.leases[key]
        forward,backward=unique_nearest(aa,bb),unique_nearest(bb,aa)
        candidates=[]
        for a,(b,distance,margin_a) in forward.items():
            if b not in backward or backward[b][0]!=a:
                continue
            candidates.append({'class':aa[a]['class'],'targetIds':[a,b],'distanceM':distance,
                               'runnerUpMarginsM':[None if math.isinf(x) else x for x in (margin_a,backward[b][2])]})
        current_keys={(candidate['class'],*candidate['targetIds']) for candidate in candidates}
        # Competing ownership retires the old lease. A missed current gate stops
        # display grouping immediately; retained identity alone never joins dots.
        for key in list(self.leases):
            if key not in current_keys:
                self.leases[key]['confirmations']=0
                if any(key[1]==other[1] or key[2]==other[2] for other in current_keys):
                    del self.leases[key]
        frames=tuple(row['sourceFrameId'] for row in rows)
        associations=[]
        for candidate in candidates:
            key=(candidate['class'],*candidate['targetIds'])
            lease=self.leases.get(key)
            if lease is None:
                self.sequence+=1
                lease={'id':f'geometry-demo:{self.epoch}:{self.generation}:{self.sequence}',
                       'confirmations':0,'lastFrames':None,'lastSeenNs':now}
                self.leases[key]=lease
            previous=lease['lastFrames']
            # Reusing one neighbor image is not independent confirmation in
            # both cameras. It may remain displayed only after an earlier lease.
            if previous is None or all(a!=b for a,b in zip(previous,frames)):
                lease['confirmations']+=1;lease['lastFrames']=frames
            lease['lastSeenNs']=now
            if lease['confirmations']>=CONFIRMATIONS:
                associations.append({**candidate,'mapAssociationId':lease['id'],
                    'method':'calibrated-geometry-demo','nativeIdFusion':False,
                    'sourceIds':list(self.sources),'sourceSessionIds':list(sessions),'sourceFrameIds':list(frames),
                    'sourceTimesNs':[str(value) for value in timestamps],'confirmations':lease['confirmations']})
        if len({value['targetIds'][0] for value in associations})!=len(associations) or len({value['targetIds'][1] for value in associations})!=len(associations):
            raise AssertionError('Association is not one-to-one.')
        return {'candidates':candidates,'associations':associations}
