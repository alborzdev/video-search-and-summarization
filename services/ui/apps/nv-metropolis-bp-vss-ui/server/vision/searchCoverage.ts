// SPDX-License-Identifier: MIT

import {
  fetchSourceIntelligence,
  type SourceIntelligenceResult,
} from "./sourceIntelligence";

const VST_STREAMS_URL =
  process.env.VST_STREAMS_URL ||
  "http://127.0.0.1:30888/vst/api/v1/live/streams";
const VST_STORAGE_URL = (
  process.env.VST_INTERNAL_API_URL || "http://127.0.0.1:30888/vst/api"
).replace(/\/$/, "");

export type IndexCoverageStatus = "indexed" | "not-indexed" | "unknown";
export type RecordingCoverageStatus = "expired" | "retained" | "unavailable";

export interface SearchCoverageSource {
  indexStatus: IndexCoverageStatus;
  lastSemanticAt: string | null;
  name: string;
  recordingStatus: RecordingCoverageStatus;
  remediation: string;
  semanticSegments: number | null;
  sensorId: string;
  timelineEnd: string | null;
  timelineStart: string | null;
}

export interface SearchCoverageSummary {
  configuredSources: number;
  expiredIndexedSources: number;
  indexedSources: number;
  retainedSources: number;
  unknownIndexSources: number;
  unavailableRecordingSources: number;
}

export interface SearchCoverageSnapshot {
  generatedAt: string;
  sources: SearchCoverageSource[];
  summary: SearchCoverageSummary;
}

interface ConfiguredSource {
  name: string;
  sensorId: string;
}

interface Timeline {
  endTime?: unknown;
  startTime?: unknown;
}

interface TimelineCoverage {
  status: RecordingCoverageStatus;
  timelineEnd: string | null;
  timelineStart: string | null;
}

function readableName(value: unknown, sensorId: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : sensorId;
}

/** Converts the VIOS live-stream catalog into one operator-facing row per source. */
export function configuredSourcesFromCatalog(value: unknown): ConfiguredSource[] {
  if (!Array.isArray(value)) return [];

  const sources = new Map<string, ConfiguredSource>();
  for (const sensor of value) {
    if (!sensor || typeof sensor !== "object" || Array.isArray(sensor)) continue;
    for (const [sensorId, streams] of Object.entries(sensor)) {
      if (
        !sensorId ||
        !Array.isArray(streams) ||
        !streams.length ||
        sources.has(sensorId)
      ) {
        continue;
      }
      const firstStream = streams.find(
        (stream) => stream && typeof stream === "object" && !Array.isArray(stream)
      ) as { name?: unknown } | undefined;
      sources.set(sensorId, {
        name: readableName(firstStream?.name, sensorId),
        sensorId,
      });
    }
  }
  return [...sources.values()].sort((left, right) =>
    left.name.localeCompare(right.name)
  );
}

async function configuredSources(): Promise<ConfiguredSource[]> {
  const response = await fetch(VST_STREAMS_URL, {
    cache: "no-store",
    signal: AbortSignal.timeout(4_000),
  });
  if (!response.ok) {
    throw new Error(`Video I/O returned ${response.status}.`);
  }
  return configuredSourcesFromCatalog(await response.json());
}

function validTimeline(value: Timeline): value is Timeline & {
  endTime: string;
  startTime: string;
} {
  return (
    typeof value.startTime === "string" &&
    typeof value.endTime === "string" &&
    Number.isFinite(Date.parse(value.startTime)) &&
    Number.isFinite(Date.parse(value.endTime)) &&
    Date.parse(value.endTime) > Date.parse(value.startTime)
  );
}

async function timelineCoverage(sensorId: string): Promise<TimelineCoverage> {
  try {
    const response = await fetch(
      `${VST_STORAGE_URL}/v1/storage/${encodeURIComponent(sensorId)}/timelines`,
      { cache: "no-store", signal: AbortSignal.timeout(4_000) }
    );
    if (response.status === 404) {
      return { status: "expired", timelineEnd: null, timelineStart: null };
    }
    if (!response.ok) {
      return { status: "unavailable", timelineEnd: null, timelineStart: null };
    }
    const raw = await response.json();
    const timelines = Array.isArray(raw)
      ? raw.filter((timeline): timeline is Timeline =>
          Boolean(timeline && typeof timeline === "object" && !Array.isArray(timeline))
        )
      : [];
    const valid = timelines.filter(validTimeline);
    if (!valid.length) {
      // VIOS returns null for a deleted source, and an empty array when there
      // is no retained window. Both are a known absence of playable media.
      return { status: "expired", timelineEnd: null, timelineStart: null };
    }
    return {
      status: "retained",
      timelineEnd: new Date(
        Math.max(...valid.map((timeline) => Date.parse(timeline.endTime)))
      ).toISOString(),
      timelineStart: new Date(
        Math.min(...valid.map((timeline) => Date.parse(timeline.startTime)))
      ).toISOString(),
    };
  } catch {
    return { status: "unavailable", timelineEnd: null, timelineStart: null };
  }
}

function indexStatus(
  intelligence: SourceIntelligenceResult | null
): IndexCoverageStatus {
  if (!intelligence || intelligence.semanticSegments === null) return "unknown";
  return intelligence.semanticSegments > 0 ? "indexed" : "not-indexed";
}

function remediation(
  indexing: IndexCoverageStatus,
  recording: RecordingCoverageStatus
): string {
  if (indexing === "unknown") {
    return "The local index could not be read. Check local search services, then refresh this view.";
  }
  if (indexing === "not-indexed" && recording === "retained") {
    return "A recording window is retained, but no semantic moments are indexed yet. Configure or resume the source analysis, then allow indexing to complete.";
  }
  if (indexing === "not-indexed") {
    return recording === "unavailable"
      ? "Neither index nor recording availability could be confirmed. Check Video I/O and source analysis before retrying."
      : "No semantic moments are indexed and no retained recording window was found. Reconnect or ingest the source, then configure analysis.";
  }
  if (recording === "retained") {
    return "Semantic search and a retained recording window are available for this source.";
  }
  if (recording === "expired") {
    return "Indexed moments remain searchable, but their recording is no longer retained for playback. Extend retention or re-ingest footage to restore playable evidence.";
  }
  return "Indexed moments are available, but Video I/O could not confirm whether the recording can be played. Check Video I/O, then refresh.";
}

async function mapWithConcurrency<T, R>(
  values: T[],
  mapper: (value: T) => Promise<R>,
  limit = 2
): Promise<R[]> {
  const result = new Array<R>(values.length);
  let next = 0;
  const worker = async () => {
    while (next < values.length) {
      const current = next;
      next += 1;
      result[current] = await mapper(values[current]);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, worker));
  return result;
}

/**
 * Reads only catalog, index, and retention facts. It never starts analysis,
 * builds history, or changes source/storage configuration.
 */
export async function readSearchCoverage(): Promise<SearchCoverageSnapshot> {
  const configured = await configuredSources();
  const sources = await mapWithConcurrency(configured, async (source) => {
    const [intelligence, timeline] = await Promise.all([
      fetchSourceIntelligence(source.sensorId, source.name).catch(() => null),
      timelineCoverage(source.sensorId),
    ]);
    const indexing = indexStatus(intelligence);
    return {
      indexStatus: indexing,
      lastSemanticAt: intelligence?.lastSemanticAt ?? null,
      name: source.name,
      recordingStatus: timeline.status,
      remediation: remediation(indexing, timeline.status),
      semanticSegments: intelligence?.semanticSegments ?? null,
      sensorId: source.sensorId,
      timelineEnd: timeline.timelineEnd,
      timelineStart: timeline.timelineStart,
    };
  });
  return {
    generatedAt: new Date().toISOString(),
    sources,
    summary: {
      configuredSources: sources.length,
      expiredIndexedSources: sources.filter(
        (source) =>
          source.indexStatus === "indexed" && source.recordingStatus === "expired"
      ).length,
      indexedSources: sources.filter((source) => source.indexStatus === "indexed")
        .length,
      retainedSources: sources.filter(
        (source) => source.recordingStatus === "retained"
      ).length,
      unknownIndexSources: sources.filter(
        (source) => source.indexStatus === "unknown"
      ).length,
      unavailableRecordingSources: sources.filter(
        (source) => source.recordingStatus === "unavailable"
      ).length,
    },
  };
}
