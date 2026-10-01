// SPDX-License-Identifier: MIT
import { consolidateIncidents, incidentDurationLabel, incidentTitle, incidentVerdictLabel, isOperatorIncidentCandidate, isOperatorRelevantIncident } from '../incidentModel';

describe('incident model', () => {
  it('merges every separated candidate contained by a longer event and preserves audit records', () => {
    const info = { alertRuleId: 'fcbf13a2-c4e9-4e3f-b13d-942e0b9d3fd3', verdict: 'confirmed', triggerPhrase: 'forklift visible' };
    const sensorId = '3688c328-7e71-493c-a1c7-011ad2fb3893';
    const records = [
      { Id: 'whole', timestamp: '2026-10-01T18:54:49Z', end: '2026-10-01T18:57:23Z', sensorId, info },
      { Id: 'one', timestamp: '2026-10-01T18:55:13Z', end: '2026-10-01T18:55:36Z', sensorId, info },
      { Id: 'two', timestamp: '2026-10-01T18:55:43Z', end: '2026-10-01T18:56:06Z', sensorId, info },
      { Id: 'three', timestamp: '2026-10-01T18:56:13Z', end: '2026-10-01T18:56:36Z', sensorId, info },
      { Id: 'outside', timestamp: '2026-10-01T18:58:00Z', end: '2026-10-01T18:58:23Z', sensorId, info },
      { Id: 'other-source', timestamp: '2026-10-01T18:55:13Z', end: '2026-10-01T18:55:36Z', sensorId: 'another-camera', info },
    ];
    for (const order of [records, [...records].reverse()]) {
      const result = consolidateIncidents(order);
      expect(result).toHaveLength(3);
      const merged = result.find((incident) => incident.candidateIds.includes('whole'))!;
      expect(merged.candidateCount).toBe(4);
      expect(new Set(merged.candidateIds)).toEqual(new Set(['whole', 'one', 'two', 'three']));
      expect(merged.candidateVerdicts).toEqual(['confirmed', 'confirmed', 'confirmed', 'confirmed']);
      expect(merged.timestamp).toBe('2026-10-01T18:54:49.000Z');
      expect(merged.end).toBe('2026-10-01T18:57:23.000Z');
    }
  });
  it('includes detector matches from authored rules as pending review without claiming visual verification', () => {
    const incident = {
      Id: 'area-match', category: 'Restricted Area Violation',
      sensorId: 'warehouse', objectIds: ['17'], timestamp: '2026-10-01T17:59:48Z',
      info: { alertRuleId: 'warehouse-aisle-rule' },
    };
    expect(isOperatorIncidentCandidate(incident)).toBe(true);
    expect(isOperatorRelevantIncident(incident)).toBe(true);
    expect(incidentVerdictLabel(incident)).toBe('Pending review');
    expect(incidentTitle(incident)).toBe('Restricted Area Violation');
    expect(isOperatorIncidentCandidate({ ...incident, info: {} })).toBe(false);
  });
  it('consolidates overlapping candidates while retaining their audit state', () => {
    const consolidated = consolidateIncidents([
      {
        Id: 'confirmed',
        timestamp: '2025-01-01T00:01:33.733Z',
        end: '2025-01-01T00:01:35.766Z',
        sensorId: 'warehouse',
        objectIds: ['22', '23'],
        info: { verdict: 'confirmed', reasoning: 'A person in white attire is visible.' },
      },
      {
        Id: 'rejected',
        timestamp: '2025-01-01T00:01:33.633Z',
        end: '2025-01-01T00:01:35.666Z',
        sensorId: 'warehouse',
        objectIds: ['21', '22'],
        info: { verdict: 'rejected', reasoning: 'No person is visible.' },
      },
    ]);

    expect(consolidated).toHaveLength(1);
    expect(consolidated[0]).toEqual(expect.objectContaining({
      candidateCount: 2,
      candidateIds: ['confirmed', 'rejected'],
      candidateVerdicts: ['confirmed', 'rejected'],
      objectIds: ['22', '23', '21'],
      timestamp: '2025-01-01T00:01:33.633Z',
      end: '2025-01-01T00:01:35.766Z',
    }));
    expect(consolidated[0].info?.reasoning).toBe('A person in white attire is visible.');
  });

  it('uses operator language and real duration instead of claiming track counts are people', () => {
    const incident = consolidateIncidents([{
      Id: 'confirmed', timestamp: '2025-01-01T00:00:00Z', end: '2025-01-01T00:00:03.2Z',
      sensorId: 'warehouse', objectIds: ['1', '2', '3'],
      info: { verdict: 'confirmed', reasoning: 'A person carrying a broom is visible in the monitored area.' },
    }])[0];
    expect(incidentTitle(incident)).toBe('Person observed in monitored area');
    expect(incidentVerdictLabel(incident)).toBe('Confirmed');
    expect(incidentDurationLabel(incident)).toBe('3 sec');
    expect(incidentTitle(incident)).not.toContain('3');
  });

  it('keeps empty backend candidates and dismissed records out of operator metrics', () => {
    const emptyConfirmed = {
      Id: 'empty', timestamp: '2025-01-01T00:00:00Z', sensorId: 'camera-id',
      info: { verdict: 'confirmed', verificationResponseStatus: 'success' },
    };
    const dismissedWithEvidence = {
      Id: 'dismissed', timestamp: '2025-01-01T00:01:00Z', sensorId: 'camera-id',
      info: { verdict: 'rejected', reasoning: 'No person is visible in the selected interval.' },
    };
    const confirmedWithEvidence = {
      Id: 'confirmed', timestamp: '2025-01-01T00:02:00Z', sensorId: 'camera-id',
      info: { verdict: 'confirmed', reasoning: 'A person is visible.' },
    };

    expect(isOperatorIncidentCandidate(emptyConfirmed)).toBe(false);
    expect(isOperatorRelevantIncident(emptyConfirmed)).toBe(false);
    expect(incidentTitle(emptyConfirmed)).toBe('Analytics processing record');
    expect(incidentVerdictLabel(emptyConfirmed)).toBe('Processed');
    expect(isOperatorIncidentCandidate(dismissedWithEvidence)).toBe(true);
    expect(isOperatorRelevantIncident(dismissedWithEvidence)).toBe(false);
    expect(isOperatorRelevantIncident(confirmedWithEvidence)).toBe(true);
  });
});
