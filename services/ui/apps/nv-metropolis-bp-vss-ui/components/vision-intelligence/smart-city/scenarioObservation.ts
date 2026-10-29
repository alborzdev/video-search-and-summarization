// SPDX-License-Identifier: MIT
export const OBSERVATION_INTERVAL_MS = 3000;
export const OBSERVATION_RULES: Readonly<Record<string, string>> = {
  'crossing-occupancy': 'expo-crossing-occupancy',
  'queue-blockage': 'expo-junction-blockage',
  'emergency-access': 'expo-emergency-blockage',
};
export interface ScenarioObservationFrame {
  siteId: string; scenarioId: string; epoch: string; runId: string;
  sourceId: string; sessionId: string; sourceTimeNs: string; imageBase64: string;
}
export interface ScenarioObservation {
  scenarioId: string; epoch: string; runId: string; sourceId: string; sessionId: string;
  sourceTimeNs: string; observedAt: string; completedAt: string; text: string;
  model: string; inferenceMs: number;
  shared?: boolean;
}
