// SPDX-License-Identifier: MIT
import { consolidateIncidents, incidentDurationLabel, incidentTitle, incidentVerdictLabel, isOperatorIncidentCandidate, isOperatorRelevantIncident } from '../incidentModel';

describe('incident model', () => {
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
