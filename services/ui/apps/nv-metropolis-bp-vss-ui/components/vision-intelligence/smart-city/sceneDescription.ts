// SPDX-License-Identifier: MIT
export interface SceneDescriptionFrame {
  siteId: string; epoch: string; sourceId: string; sessionId: string;
  sourceTimeNs: string; imageBase64: string;
}
export interface SceneDescription extends Omit<SceneDescriptionFrame, 'imageBase64'> {
  observedAt: string; completedAt: string; text: string; model: string; inferenceMs: number;
}
