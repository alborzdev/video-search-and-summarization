# SPDX-License-Identifier: Apache-2.0
"""Small camera-owned readouts for the three trade-show stories.

Time is accumulated only between fresh, consecutive source observations.
Scenario placement, actor identity and the host wall clock never supply counts.
"""
from copy import deepcopy

RULES = {
    'expo-crossing-occupancy': 'crossing-occupancy',
    'expo-approach-queue': 'queue-blockage',
    'expo-junction-blockage': 'queue-blockage',
    'expo-emergency-blockage': 'emergency-access',
}


class ShowcaseAnalytics:
    def __init__(self):
        self.rows = {}

    def observe(self, engine, source_id, ns):
        scope = engine.scope_json()
        if scope.get('kind') != 'scenario' or engine.analytics_suppressed:
            return
        source = engine.sources[source_id]
        for rule in engine.rules:
            if (rule.sourceId != source_id or not rule.enabled
                    or RULES.get(rule.id) != scope.get('scenarioId')):
                continue
            metric = engine.metrics.get(rule.id)
            if metric is None:
                continue
            identity = (scope['epoch'], source['sessionId'], rule.revision)
            row = self.rows.get(rule.id)
            interrupted = row is not None and row['_identity'] != identity
            if row is None or row['_identity'] != identity:
                row = self.rows[rule.id] = {'_identity': identity, '_lastNs': None, '_occupied': False,
                    'ruleId': rule.id, 'name': rule.name, 'sourceId': source_id,
                    'sessionId': source['sessionId'], 'count': 0, 'peakCount': 0,
                    'occupiedSeconds': 0., 'continuousSeconds': 0., 'hasGaps': interrupted,
                    'savedEventIds': [], 'status': 'waiting'}
            reliable = metric.get('status') != 'unknown'
            count = metric.get('count', 0)
            events = [event for event in engine.events.values() if event['ruleId'] == rule.id
                and event['sessionId'] == source['sessionId']
                and event.get('analyticsScope', {}).get('epoch') == scope['epoch']]
            # Stopped-in-zone counts must be confirmed stopped tracks, not all
            # vehicles merely passing through the polygon.
            if rule.kind == 'stopped-in-zone':
                count = len({track for event in events if event['state'] == 'active'
                             for track in event['trackIds']})
            occupied = reliable and count > 0
            gap = ns - row['_lastNs'] if row['_lastNs'] is not None else None
            contiguous = gap is not None and 0 < gap <= rule.conditions.maximumObservationGapMs * 1_000_000
            if occupied and row['_occupied'] and contiguous:
                row['occupiedSeconds'] += gap / 1e9
                row['continuousSeconds'] += gap / 1e9
            elif not occupied or not row['_occupied'] or not contiguous:
                row['continuousSeconds'] = 0.
            if (not reliable and (row['_occupied'] or row['occupiedSeconds'] > 0)
                    or gap is not None and not contiguous):
                row['hasGaps'] = True
            row.update(_lastNs=ns, _occupied=occupied, count=count,
                peakCount=max(row['peakCount'], count), asOfSourceTimeNs=str(ns),
                status='unknown' if not reliable else 'occupied' if occupied else 'clear')
            # _event writes synchronously to CityStore before publishing an ID.
            row['savedEventIds'] = list(dict.fromkeys([*row['savedEventIds'], *[event['id'] for event in events]]))[-16:]

    def snapshot(self, engine):
        result = []
        for value in self.rows.values():
            row = deepcopy({key: item for key, item in value.items() if not key.startswith('_')})
            source = engine.sources.get(row['sourceId'])
            if not source or engine.clock() - source['received'] > engine.freshness:
                row.update(status='waiting', count=None)
            result.append(row)
        return result
