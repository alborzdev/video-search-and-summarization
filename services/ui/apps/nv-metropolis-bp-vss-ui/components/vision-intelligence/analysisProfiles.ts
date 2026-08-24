// SPDX-License-Identifier: MIT

export const SEMANTIC_ANALYSIS_PROFILE_ID = 'semantic-search';

export interface SourceAnalysisProfile {
  description: string;
  detectionEnabled: boolean;
  id: string;
  maxSources: number;
  modelId: string | null;
  modelLabel: string;
  name: string;
  objectTypes: string[];
  ready: boolean;
  readyDetail: string;
  resourceTier: 'low' | 'medium' | 'high';
  ruleKinds: string[];
  sceneTypes: string[];
  shortName: string;
}

async function payloadOrError(response: Response) {
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(String(payload.error || payload.detail || 'Analysis profiles are unavailable.'));
  }
  return payload;
}

export async function loadAnalysisProfileCatalog(
  signal?: AbortSignal,
): Promise<SourceAnalysisProfile[]> {
  const payload = await payloadOrError(await fetch('/api/vision/analysis-profiles', {
    cache: 'no-store',
    signal,
  }));
  return Array.isArray(payload.profiles) ? payload.profiles as SourceAnalysisProfile[] : [];
}

export async function loadSourceAnalysisProfile(
  sourceId: string,
  signal?: AbortSignal,
): Promise<SourceAnalysisProfile> {
  const payload = await payloadOrError(await fetch(
    `/api/vision/analysis-profiles?sourceId=${encodeURIComponent(sourceId)}`,
    { cache: 'no-store', signal },
  ));
  if (!payload.profile || typeof payload.profile !== 'object') {
    throw new Error('This source did not report an analysis profile.');
  }
  return payload.profile as SourceAnalysisProfile;
}
