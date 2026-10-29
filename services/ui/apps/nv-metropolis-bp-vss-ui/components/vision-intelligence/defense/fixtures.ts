// SPDX-License-Identifier: MIT
import type { DefenseEvidence, DefenseMode, DefenseReport, DefenseScenario, DefenseSnapshot } from './types';

const still = (id: string, sourceId: string, sourceName: string, image: string, time: string, observation?: string): DefenseEvidence => ({
  id, sourceId, sourceName, kind: 'illustrative', imageUrl: '/defense-preview/' + image + '.png',
  timeLabel: time, mediaSeconds: null, clockVerified: false, observation,
});
export const PREVIEW: DefenseSnapshot = {
  provenance: 'illustrative',
  evidence: [
    still('gate', 'cam-01', 'Camera 01 · Storage gate', 'site', '14:32:08', 'A person crossed the marked storage boundary.'),
    still('pass', 'cam-d1', 'Camera D1 · First pass', 'drone-wide', '14:32:08', 'A possible loose object was selected for review.'),
    still('close', 'cam-d1', 'Camera D1 · Closer view', 'drone-close', '14:32:24', 'A closer illustrative image shows a loose object.'),
    still('rear', 'rear', 'Rear camera', 'vehicle-rear', 'Preview still', 'A person is visible behind the vehicle.'),
    still('left', 'left', 'Left side', 'vehicle-left', 'Preview still'),
    still('right', 'right', 'Right side', 'vehicle-right', 'Preview still'),
  ],
  findings: [
    { id: '014', title: 'Person entered storage zone', location: 'Storage zone B', evidenceIds: ['gate'], limitations: ['Identity and entry permission are not established.'] },
    { id: '03', title: 'Possible loose object', location: 'Service apron', evidenceIds: ['pass', 'close'], limitations: ['Removal has not been checked.', 'Capture coverage does not establish surface clearance.'] },
  ],
};
const EMPTY: DefenseSnapshot = { provenance: 'disconnected', evidence: [], findings: [] };
export function snapshotFor(mode: DefenseMode): DefenseSnapshot { return mode === 'preview' ? PREVIEW : EMPTY; }
export function evidenceFor(snapshot: DefenseSnapshot, id: string): DefenseEvidence | undefined { return snapshot.evidence.find(item => item.id === id); }
export function createPreviewReport(mode: DefenseMode, scenario: DefenseScenario, notes: string, now = new Date()): DefenseReport | null {
  if (mode !== 'preview') return null;
  const finding = PREVIEW.findings[scenario === 'drone' ? 1 : 0];
  const ids = scenario === 'vehicle' ? ['rear', 'left', 'right'] : finding.evidenceIds;
  const evidence = PREVIEW.evidence.filter(item => ids.includes(item.id));
  return {
    schemaVersion: 'defense.preview-report.v1', provenance: 'illustrative',
    title: scenario === 'vehicle' ? 'Vehicle surroundings review' : finding.title,
    scenario, createdAt: now.toISOString(), observations: evidence.flatMap(item => item.observation ? [item.observation] : []),
    limitations: ['Design preview only. No camera footage or AI result is attached.', ...(scenario === 'vehicle' ? ['Positions and coverage are schematic, not measured.'] : finding.limitations)],
    evidence, analystNotes: notes,
  };
}
