// SPDX-License-Identifier: MIT
import type { NextApiRequest, NextApiResponse } from 'next';

import {
  cleanAgentAnswer,
  type VisionAnalystRequest,
  type VisionAnalystResponse,
} from '../../../components/vision-intelligence/analyst';
import {
  isCrossSourceOverviewQuestion,
  rankCrossSources,
  summarizeCrossSourceEvidence,
  type CrossSourceEvidence,
  type CrossSourceIncident,
} from '../../../components/vision-intelligence/crossSourceAnalysis';
import { fetchAnalyticsIncidents } from './incidents';
import { fetchSourceIntelligence } from '../../../server/vision/sourceIntelligence';
import {
  CosmosReservationError,
  withCosmosReservation,
} from '../../../server/vision/cosmosReservation';
import {
  admitWorkload,
  WorkloadAdmissionError,
  workloadAdmissionFailure,
  type WorkloadAdmissionFailure,
} from '../../../server/vision/workloadAdmissionAdapter';

interface DirectInspectionResponse {
  answer?: string;
  error?: string;
  evidence_tool?: string;
  observed_range?: { end_seconds: number; start_seconds: number } | null;
}

class AnalystRequestError extends Error {
  constructor(message: string, readonly statusCode: number) {
    super(message);
  }
}

const ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;

function directInspectionEndpoint(): string {
  if (process.env.VISION_INSPECTION_API_URL) return process.env.VISION_INSPECTION_API_URL;
  return `http://127.0.0.1:${process.env.VSS_AGENT_PORT || '8100'}/api/v1/vision-inspection`;
}

function validateRequest(value: unknown): asserts value is VisionAnalystRequest {
  if (!value || typeof value !== 'object') {
    throw new AnalystRequestError('A valid Vision Analyst request is required.', 400);
  }
  const request = value as Partial<VisionAnalystRequest>;
  const queryLength = typeof request.query === 'string' ? request.query.trim().length : 0;
  if (queryLength < 1 || queryLength > 1_000) {
    throw new AnalystRequestError('Enter a question between 1 and 1,000 characters.', 400);
  }
  if (request.scope !== 'all-sources' && request.scope !== 'selected-source') {
    throw new AnalystRequestError('Choose a valid source scope.', 400);
  }
  if (!Array.isArray(request.sources) || request.sources.length < 1 || request.sources.length > 8) {
    throw new AnalystRequestError('Choose between 1 and 8 video sources.', 400);
  }
  if (request.scope === 'selected-source' && request.sources.length !== 1) {
    throw new AnalystRequestError('Selected-source questions require exactly one source.', 400);
  }
  if (typeof request.askedAt !== 'string' || !Number.isFinite(Date.parse(request.askedAt))) {
    throw new AnalystRequestError('The question timestamp is invalid.', 400);
  }
  if (typeof request.conversationId !== 'string' || !ID_PATTERN.test(request.conversationId)) {
    throw new AnalystRequestError('The Vision Analyst conversation is invalid.', 400);
  }

  const streamIds = new Set<string>();
  for (const source of request.sources) {
    if (!source || (source.kind !== 'live' && source.kind !== 'replay')) {
      throw new AnalystRequestError('A source has an invalid footage type.', 400);
    }
    if (typeof source.name !== 'string' || source.name.trim().length < 1 || source.name.length > 256) {
      throw new AnalystRequestError('A source name is invalid.', 400);
    }
    if (!ID_PATTERN.test(source.sensorId) || !ID_PATTERN.test(source.streamId)) {
      throw new AnalystRequestError('A source identifier is invalid.', 400);
    }
    if (streamIds.has(source.streamId)) {
      throw new AnalystRequestError('Duplicate sources are not allowed.', 400);
    }
    streamIds.add(source.streamId);
    if (source.playback) {
      if (!Number.isFinite(Date.parse(source.playback.capturedAt))) {
        throw new AnalystRequestError('The playback timestamp is invalid.', 400);
      }
      for (const seconds of [source.playback.currentTimeSeconds, source.playback.durationSeconds]) {
        if (seconds !== undefined && (!Number.isFinite(seconds) || seconds < 0)) {
          throw new AnalystRequestError('The playback position is invalid.', 400);
        }
      }
    }
  }
  if (new Set(request.sources.map((source) => source.kind)).size > 1) {
    throw new AnalystRequestError(
      'Ask across live or recorded sources separately so every result uses the correct evidence path.',
      422
    );
  }
}

function timeoutFor(request: VisionAnalystRequest): number {
  const defaultMs = request.scope === 'all-sources'
    ? 240_000
    : request.sources[0].kind === 'live' ? 150_000 : 180_000;
  const configured = Number(process.env.VISION_ANALYST_TIMEOUT_MS || defaultMs);
  return Number.isFinite(configured) ? Math.min(600_000, Math.max(30_000, configured)) : defaultMs;
}

async function inspectSelectedSource(
  request: VisionAnalystRequest,
  signal: AbortSignal
): Promise<VisionAnalystResponse> {
  const source = request.sources[0];
  const response = await fetch(directInspectionEndpoint(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      asked_at: request.askedAt,
      current_time_seconds: source.playback?.currentTimeSeconds,
      duration_seconds: source.playback?.durationSeconds,
      query: request.query.trim(),
      sensor_id: source.sensorId,
      source_kind: source.kind,
    }),
    signal,
  });
  let payload: DirectInspectionResponse;
  try {
    payload = JSON.parse(await response.text()) as DirectInspectionResponse;
  } catch {
    throw new AnalystRequestError('The local visual inspector returned an unreadable response.', 502);
  }
  if (!response.ok || !payload.answer || !payload.evidence_tool) {
    throw new AnalystRequestError(
      response.status === 503
        ? 'The local visual inspector is busy. Try again in a moment.'
        : payload.error || 'The selected video could not be inspected.',
      response.status === 503 ? 503 : 502
    );
  }
  const answer = cleanAgentAnswer(payload.answer);
  if (!answer) throw new AnalystRequestError('The local visual inspector returned no answer.', 502);
  return {
    answer,
    evidenceTools: [payload.evidence_tool],
    generatedAt: new Date().toISOString(),
    grounded: true,
    ...(payload.observed_range ? {
      observedRange: {
        endSeconds: payload.observed_range.end_seconds,
        startSeconds: payload.observed_range.start_seconds,
      },
    } : {}),
    query: request.query.trim(),
    scope: request.scope,
    sourceNames: [source.name],
  };
}

async function loadCrossSourceEvidence(request: VisionAnalystRequest): Promise<CrossSourceEvidence> {
  const [incidentResult, intelligenceEntries] = await Promise.all([
    fetchAnalyticsIncidents().catch(() => []),
    Promise.all(request.sources.map(async (source) => [
      source.streamId,
      await fetchSourceIntelligence(source.sensorId, source.name),
    ] as const)),
  ]);
  return {
    incidents: incidentResult as CrossSourceIncident[],
    intelligenceByStreamId: Object.fromEntries(
      intelligenceEntries
        .filter((entry): entry is readonly [string, NonNullable<typeof entry[1]>] => Boolean(entry[1]))
        .map(([streamId, intelligence]) => [streamId, {
          evidenceEvents: intelligence.evidenceEvents,
          semanticSegments: intelligence.semanticSegments,
          trackedObservations: intelligence.trackedObservations,
        }])
    ),
  };
}

async function inspectHighestRankedSource(
  request: VisionAnalystRequest,
  evidence: CrossSourceEvidence,
  signal: AbortSignal
): Promise<VisionAnalystResponse> {
  const selected = rankCrossSources(request.sources, evidence)[0];
  const result = await inspectSelectedSource({
    ...request,
    scope: 'selected-source',
    sources: [selected],
  }, signal);
  return { ...result, scope: 'all-sources' };
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<VisionAnalystResponse | { error: string } | WorkloadAdmissionFailure>
) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed.' });
  }
  try {
    validateRequest(req.body);
  } catch (error) {
    const requestError = error instanceof AnalystRequestError
      ? error
      : new AnalystRequestError('A valid Vision Analyst request is required.', 400);
    return res.status(requestError.statusCode).json({ error: requestError.message });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutFor(req.body));

  try {
    const isOverview = req.body.scope === 'all-sources' &&
      isCrossSourceOverviewQuestion(req.body.query);
    if (!isOverview) await admitWorkload('current_visual_question');

    if (req.body.scope === 'selected-source') {
      const result = await withCosmosReservation(() =>
        inspectSelectedSource(req.body, controller.signal)
      );
      res.setHeader('Cache-Control', 'no-store');
      return res.status(200).json(result);
    }

    const evidence = await loadCrossSourceEvidence(req.body);
    if (isOverview) {
      const result = summarizeCrossSourceEvidence(req.body, evidence);
      res.setHeader('Cache-Control', 'no-store');
      return res.status(200).json(result);
    }

    // Free-form visual questions still receive deterministic handling: rank
    // sources from real local evidence, then inspect exactly one source. This
    // avoids relying on a planner to complete multiple visual tool calls.
    const result = await withCosmosReservation(() =>
      inspectHighestRankedSource(req.body, evidence, controller.signal)
    );
    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json(result);
  } catch (error) {
    const message = controller.signal.aborted
      ? 'The local Vision Analyst took too long to answer. Try a shorter time range or a more specific question.'
      : error instanceof Error ? error.message : 'The local Vision Analyst is unavailable.';
    const statusCode = controller.signal.aborted
      ? 504
      : error instanceof WorkloadAdmissionError
        ? error.statusCode
      : error instanceof AnalystRequestError || error instanceof CosmosReservationError
        ? error.statusCode
        : 502;
    return res.status(statusCode).json(
      error instanceof WorkloadAdmissionError
        ? workloadAdmissionFailure(error)
        : { error: message }
    );
  } finally {
    clearTimeout(timeout);
  }
}
