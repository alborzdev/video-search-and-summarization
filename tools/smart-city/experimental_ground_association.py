# SPDX-License-Identifier: Apache-2.0
"""Conservative, timestamped ground-plane association for two fixed cameras.

Only measured, observed person tracks enter this method. Ambiguous neighbors,
poor timing, clipped boxes and inconsistent tracklets stay camera-local.
No simulator actor labels or trajectories are accepted by this module.
"""
from __future__ import annotations
from collections import deque
from copy import deepcopy
import math
import statistics
import uuid

METHOD = 'calibrated-ground-v1'
MAX_SKEW_NS = 50_000_000
MIN_SAMPLES = 5
MIN_SPAN_NS = 350_000_000
MAX_MEDIAN_DISTANCE_M = .8
MAX_DISTANCE_M = 1.2
MIN_NEIGHBOR_MARGIN_M = .4
MAX_OFFSET_CHANGE_M = .5
LIVE_AGE_NS = 500_000_000


class GroundAssociator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.histories = {}
        self.node_groups = {}
        self.groups = {}
        self.source_epochs = {}

    @staticmethod
    def eligible(track, now):
        point = track.get('positionM')
        confidence = track.get('confidence')
        if (track.get('class') != 'person' or not track.get('observedThisFrame') or track.get('stale')
                or track.get('timestampBasis') != 'source-rtcp' or point is None
                or confidence is None or confidence < .55
                or not all(math.isfinite(value) for value in point)):
            return False
        if not 0 <= now - int(track['sourceTimeNs']) <= LIVE_AGE_NS:
            return False
        x, y, width, height = track['bboxPx']
        image = track.get('imageSize')
        if image and (x < 1 or y < 1 or x + width > image[0] - 1 or y + height > image[1] - 1):
            return False
        return True

    def pair_score(self, first, second):
        a = self.histories.get(first['id'], ())
        b = self.histories.get(second['id'], ())
        matches = []
        used = set()
        for timestamp, point in reversed(a):
            if not b:
                break
            other_time, other_point = min(b, key=lambda value: abs(value[0] - timestamp))
            if abs(other_time - timestamp) > MAX_SKEW_NS or other_time in used:
                continue
            used.add(other_time)
            matches.append((timestamp, [point[i] - other_point[i] for i in range(2)]))
            if len(matches) == MIN_SAMPLES:
                break
        if len(matches) < MIN_SAMPLES or matches[0][0] - matches[-1][0] < MIN_SPAN_NS:
            return None
        distances = [math.hypot(*offset) for _, offset in matches]
        change = math.dist(matches[0][1], matches[-1][1])
        return {'cost': statistics.median(distances), 'maximum': max(distances), 'offsetChange': change,
                'sampleCount': len(matches), 'spanNs': matches[0][0] - matches[-1][0]}

    def update(self, tracks, source_id, source_epoch, timestamp):
        previous_epoch = self.source_epochs.get(source_id)
        if previous_epoch is not None and previous_epoch != source_epoch:
            self.reset()
        self.source_epochs[source_id] = source_epoch
        now = int(timestamp)
        eligible = [track for track in tracks if self.eligible(track, now)]
        for track in eligible:
            if track['sourceId'] != source_id:
                continue
            history = self.histories.setdefault(track['id'], deque(maxlen=24))
            at = int(track['sourceTimeNs'])
            if not history or history[-1][0] < at:
                history.append((at, list(track['positionM'])))
        for identity, history in list(self.histories.items()):
            if not history or now - history[-1][0] > 30_000_000_000:
                self.histories.pop(identity, None)
                group = self.node_groups.pop(identity, None)
                if group in self.groups:
                    self.groups[group].discard(identity)
                    if not self.groups[group]:
                        self.groups.pop(group)
        sources = sorted({track['sourceId'] for track in eligible})
        confirmed = set()
        active_by_id = {track['id']: track for track in eligible}
        if len(sources) == 2:
            a = [track for track in eligible if track['sourceId'] == sources[0]]
            b = [track for track in eligible if track['sourceId'] == sources[1]]
            scores = {(left['id'], right['id']): score for left in a for right in b
                      if abs(int(left['sourceTimeNs']) - int(right['sourceTimeNs'])) <= MAX_SKEW_NS
                      and (score := self.pair_score(left, right)) is not None}
            for left in a:
                ranked = sorted(((scores[(left['id'], right['id'])]['cost'], right) for right in b
                                 if (left['id'], right['id']) in scores), key=lambda item: item[0])
                if not ranked:
                    continue
                cost, right = ranked[0]
                reverse = sorted(((score['cost'], identity) for (identity, other), score in scores.items()
                                  if other == right['id']), key=lambda item: item[0])
                if reverse[0][1] != left['id']:
                    continue
                if ((len(ranked) > 1 and ranked[1][0] - cost < MIN_NEIGHBOR_MARGIN_M)
                        or (len(reverse) > 1 and reverse[1][0] - cost < MIN_NEIGHBOR_MARGIN_M)):
                    continue
                score = scores[(left['id'], right['id'])]
                if cost > MAX_MEDIAN_DISTANCE_M or score['maximum'] > MAX_DISTANCE_M or score['offsetChange'] > MAX_OFFSET_CHANGE_M:
                    continue
                identities = {left['id'], right['id']}
                old_groups = {self.node_groups[identity] for identity in identities if identity in self.node_groups}
                members = set(identities)
                for group in old_groups:
                    members.update(self.groups.get(group, ()))
                live_members = [active_by_id[identity] for identity in members if identity in active_by_id]
                if len({track['sourceId'] for track in live_members}) != len(live_members):
                    continue # Never combine two active objects from one camera.
                if old_groups:
                    group = min(old_groups)
                else:
                    self.sequence += 1
                    group = f'ground:{self.epoch}:{self.sequence:08d}'
                for old in old_groups - {group}:
                    self.groups.pop(old, None)
                self.groups[group] = members
                for identity in members:
                    self.node_groups[identity] = group
                confirmed.update(identities)
        # One still-visible member can carry its established identity while the
        # other view is occluded. Two ambiguous visible members are not merged.
        group_live = {}
        for track in eligible:
            group = self.node_groups.get(track['id'])
            if group:
                group_live.setdefault(group, []).append(track['id'])
        assignments = {}
        for group, members in group_live.items():
            if len(members) == 1 or all(identity in confirmed for identity in members):
                for identity in members:
                    assignments[identity] = group
        return assignments


def map_tracks(tracks):
    """Combine only explicitly confirmed groups, retaining per-camera evidence."""
    groups = {}
    result = []
    for track in tracks:
        if track.get('associationMethod') == METHOD and track.get('globalTrackId'):
            groups.setdefault(track['globalTrackId'], []).append(track)
        else:
            result.append(track)
    for global_id, members in groups.items():
        observed = [track for track in members if track.get('observedThisFrame') and not track.get('stale') and track.get('positionM') is not None]
        if not observed:
            result.extend(members)
            continue
        representative = max(observed, key=lambda track: (track.get('confidence') or 0, int(track['sourceTimeNs'])))
        output = deepcopy(representative)
        weights = [(track.get('confidence') or .01) ** 2 for track in observed]
        output['positionM'] = [sum(track['positionM'][i] * weight for track, weight in zip(observed, weights)) / sum(weights) for i in range(2)]
        output['memberTrackIds'] = [track['id'] for track in members]
        output['evidenceSourceIds'] = sorted({track['sourceId'] for track in observed})
        output['globalTrackId'] = global_id
        result.append(output)
    return result
