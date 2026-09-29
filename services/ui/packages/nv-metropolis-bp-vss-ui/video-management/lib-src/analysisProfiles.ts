// SPDX-License-Identifier: MIT

export const SEMANTIC_ANALYSIS_PROFILE_ID = 'semantic-search';
export const WAREHOUSE_ANALYSIS_PROFILE_ID = 'warehouse-safety';
export const TRAFFIC_ANALYSIS_PROFILE_ID = 'traffic-monitoring';

export interface AnalysisProfile {
  id: string;
  name: string;
  shortName: string;
  description: string;
  detectionEnabled: boolean;
  maxSources: number;
  modelId: string | null;
  modelLabel: string;
  objectTypes: string[];
  ready: boolean;
  readyDetail: string;
  resourceTier: 'low' | 'medium' | 'high';
  ruleKinds: string[];
  sceneTypes: string[];
}

export interface AnalysisProfileRecommendation {
  alternatives: string[];
  confidence: number;
  planner: 'nemotron' | 'local-fallback';
  profileId: string;
  reason: string;
}

function apiBase(agentApiUrl: string): string {
  return agentApiUrl.replace(/\/$/, '');
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const text = await response.text().catch(() => '');
  try {
    const payload = text ? JSON.parse(text) as { detail?: string; error?: string } : {};
    const detail = payload.detail || payload.error;
    return typeof detail === 'string' && detail.trim() ? detail : fallback;
  } catch {
    return fallback;
  }
}

export async function loadAnalysisProfiles(
  agentApiUrl: string,
  signal?: AbortSignal,
): Promise<AnalysisProfile[]> {
  const response = await fetch(`${apiBase(agentApiUrl)}/analysis-profiles`, {
    cache: 'no-store',
    signal,
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Analysis profiles are unavailable. Check System, then reopen this form to retry.'));
  }
  const payload = await response.json() as { profiles?: AnalysisProfile[] };
  if (!Array.isArray(payload.profiles) || !payload.profiles.length) {
    throw new Error('This VSS appliance did not advertise any analysis profiles.');
  }
  return payload.profiles;
}

export async function recommendAnalysisProfile(
  agentApiUrl: string,
  source: { intent: string; sourceKind: 'live' | 'recorded'; sourceName: string },
  signal?: AbortSignal,
): Promise<AnalysisProfileRecommendation> {
  const response = await fetch(`${apiBase(agentApiUrl)}/analysis-profiles/recommend`, {
    body: JSON.stringify(source),
    headers: { 'Content-Type': 'application/json' },
    method: 'POST',
    signal,
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Thor could not recommend an analysis profile.'));
  }
  return response.json() as Promise<AnalysisProfileRecommendation>;
}

/** Customer-facing task names; profile IDs and capability checks stay authoritative. */
export function analysisProfileTask(profile: AnalysisProfile): { name: string; description: string } {
  switch (profile.id) {
    case SEMANTIC_ANALYSIS_PROFILE_ID:
      return { name: 'Find activity and ask questions', description: 'Search video using everyday language, then ask AI about a selected moment.' };
    case WAREHOUSE_ANALYSIS_PROFILE_ID:
      return { name: 'Track warehouse activity', description: 'Detect supported workers, vehicles and pallets to support tracking and configured warehouse alert rules.' };
    case TRAFFIC_ANALYSIS_PROFILE_ID:
      return { name: 'Track road activity', description: 'Detect supported people, bicycles and vehicles to support tracking and configured traffic alert rules.' };
    default:
      return { name: profile.name, description: profile.description };
  }
}
