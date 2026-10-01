// SPDX-License-Identifier: MIT
import type { VisionAnalystRequest } from '../analyst';
import { rankCrossSources, summarizeCrossSourceEvidence } from '../crossSourceAnalysis';

const request: VisionAnalystRequest = {
  askedAt: '2026-08-13T12:00:00Z',
  conversationId: 'conversation-1',
  query: 'Which cameras need attention?',
  scope: 'all-sources',
  sources: [
    { kind: 'replay', name: 'sample-sim-traffic', sensorId: 'traffic', streamId: 'traffic' },
    { kind: 'replay', name: 'warehouse-camera', sensorId: 'warehouse', streamId: 'warehouse' },
  ],
};

const evidence = {
  incidents: [{
    Id: 'incident-1', sensorId: 'warehouse-camera', timestamp: '2025-01-01T00:01:00Z',
    info: { verdict: 'confirmed', reasoning: 'A person is visible.' },
  }],
  intelligenceByStreamId: {
    traffic: { evidenceEvents: 0, semanticSegments: 27, trackedObservations: 0 },
    warehouse: { evidenceEvents: 6, semanticSegments: 48, trackedObservations: 3724 },
  },
};

describe('cross-source analysis', () => {
  it('ranks real live coverage first, then sources with stronger indexed evidence', () => {
    expect(rankCrossSources(request.sources, evidence)[0].streamId).toBe('warehouse');
    expect(rankCrossSources(
      [{ ...request.sources[0], kind: 'live' }, request.sources[1]],
      evidence
    )[0].streamId).toBe('traffic');
  });

  it('answers cross-camera status questions from deterministic local evidence', () => {
    expect(summarizeCrossSourceEvidence(request, evidence, '2026-08-13T12:00:01Z')).toEqual(expect.objectContaining({
      answer: expect.stringContaining('Warehouse Camera currently has the strongest local evidence signal'),
      evidenceTools: ['video_analytics', 'source_intelligence'],
      generatedAt: '2026-08-13T12:00:01Z',
      grounded: true,
      scope: 'all-sources',
      sourceNames: ['warehouse-camera'],
    }));
  });

  it('counts overlapping detector and VLM records as one operator incident', () => {
    const duplicatedEvidence = {
      ...evidence,
      incidents: [
        evidence.incidents[0],
        {
          ...evidence.incidents[0],
          Id: 'incident-1-verification',
          timestamp: '2025-01-01T00:01:00.200Z',
          end: '2025-01-01T00:01:01Z',
        },
      ],
    };
    expect(summarizeCrossSourceEvidence(request, duplicatedEvidence).answer).toContain('1 confirmed incident');
    expect(summarizeCrossSourceEvidence(request, duplicatedEvidence).answer).not.toContain('2 confirmed incidents');
  });

  it('does not turn indexed activity counts into operator alerts', () => {
    const activityOnly = { ...evidence, incidents: [] };
    const answer = summarizeCrossSourceEvidence(request, activityOnly).answer;
    expect(answer).toContain('No operator-ready incident currently requires attention');
    expect(answer).toContain('indexed activity counts, not alerts');
    expect(answer).not.toContain('confirmed incident');
  });

  it('does not treat an incomplete event feed as proof that no incident requires attention', () => {
    const answer = summarizeCrossSourceEvidence(request, { ...evidence, incidents: [], incidentCoverage: 'partial' }).answer;
    expect(answer).toContain('Event coverage is incomplete');
    expect(answer).not.toContain('No operator-ready incident');
  });

  it('distinguishes a direct visual rule match from a confirmed incident', () => {
    const answer = summarizeCrossSourceEvidence(request, { ...evidence, incidents: [{
      ...evidence.incidents[0], info: { verdict: 'confirmed', alertRuleId: 'rule', alertCategory: 'semantic', triggerPhrase: 'yes' },
    }] }).answer;
    expect(answer).toContain('1 visual rule match');
    expect(answer).not.toContain('1 confirmed incident');
  });

  it('counts a long visual rule match and its separated contained windows once', () => {
    const info = { verdict: 'confirmed', alertRuleId: 'rule', alertCategory: 'Browser check forklift visible', triggerPhrase: 'forklift visible' };
    const incidents = [
      { Id: 'whole', sensorId: 'warehouse-camera', timestamp: '2026-10-01T18:54:49Z', end: '2026-10-01T18:57:23Z', info },
      { Id: 'one', sensorId: 'warehouse-camera', timestamp: '2026-10-01T18:55:13Z', end: '2026-10-01T18:55:36Z', info },
      { Id: 'two', sensorId: 'warehouse-camera', timestamp: '2026-10-01T18:55:43Z', end: '2026-10-01T18:56:06Z', info },
      { Id: 'three', sensorId: 'warehouse-camera', timestamp: '2026-10-01T18:56:13Z', end: '2026-10-01T18:56:36Z', info },
    ];
    const answer = summarizeCrossSourceEvidence(request, { ...evidence, incidents }).answer;
    expect(answer).toContain('1 visual rule match');
    expect(answer).not.toContain('4 visual rule matches');
  });

  it('excludes internal analytics records that have no operator evidence', () => {
    const internalOnly = {
      incidents: [{
        Id: 'internal-confirmation',
        sensorId: 'warehouse-camera',
        timestamp: '2026-08-13T12:00:00Z',
        info: { verdict: 'confirmed' },
      }],
      intelligenceByStreamId: {
        traffic: { evidenceEvents: 0, semanticSegments: 0, trackedObservations: 0 },
        warehouse: { evidenceEvents: 0, semanticSegments: 0, trackedObservations: 0 },
      },
    };
    expect(summarizeCrossSourceEvidence(request, internalOnly).answer).toContain(
      'No operator events or tracked observations'
    );
  });
});
