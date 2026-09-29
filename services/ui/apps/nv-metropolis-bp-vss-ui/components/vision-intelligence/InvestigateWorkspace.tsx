// SPDX-License-Identifier: MIT

import { readEvidenceAnalysis } from "./readEvidenceAnalysis";
import type { EvidenceVisualInspection } from "./evidenceAnalysis";

import { useDialogAccessibility } from "@aiqtoolkit-ui/common";

import {
  recordingIsRetained,
  type RecordingTimeline,
} from "../../utils/recordingAvailability";
import {
  EvidenceAnalysisPanel,
  type SelectedEvidenceItem,
} from "./EvidenceAnalysisPanel";
import {
  FindSimilarSelector,
  type VisualReference,
} from "./FindSimilarSelector";
import type {
  EvidenceAnalysisRequest,
  EvidenceAnalysisResponse,
} from "./evidenceAnalysis";
import { evidenceClipEndpoint } from "./evidenceClip";
import {
  consolidateIncidents,
  type AnalyticsIncident,
  incidentTitle,
  incidentVerdict,
  isDiagnosticIncident,
} from "./incidentModel";
import type { VisionStream } from "./types";
import { useVisionStreams } from "./useVisionStreams";
import { isLiveStream, proxyVstPictureUrl, streamDisplayName } from "./utils";
import {
  IconAdjustmentsHorizontal,
  IconArrowRight,
  IconBox,
  IconCamera,
  IconCheck,
  IconChevronDown,
  IconClock,
  IconPlayerPlay,
  IconSearch,
  IconSparkles,
  IconX,
} from "@tabler/icons-react";
import React, {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

interface CriticResult {
  result: "confirmed" | "rejected" | "unverified";
  criteria_met?: Record<string, boolean>;
}

export interface VisionSearchResult {
  critic_result?: CriticResult;
  description: string;
  end_time: string;
  grouped_intervals?: Array<{ end_time: string; start_time: string }>;
  incident_id?: string;
  incident_reasoning?: string;
  match_signals?: MatchSignal[];
  object_ids: string[];
  screenshot_url: string;
  sensor_id: string;
  similarity: number;
  source_type?: IndexedSearchSourceType;
  start_time: string;
  video_name: string;
}

type MatchSignal =
  | "detector"
  | "incident"
  | "incident_candidate"
  | "semantic"
  | "visual"
  | "vlm_rejected"
  | "vlm_verified";

interface InvestigationRequest {
  camera?: VisionStream;
  query: string;
}

interface InvestigateWorkspaceProps {
  isActive?: boolean;
  agentApiUrl?: string | null;
  initialRequest?: InvestigationRequest | null;
  mdxWebApiUrl?: string | null;
  searchByImageEnabled?: boolean;
  vstApiUrl?: string | null;
}

type SearchSourceType = "all" | "rtsp" | "video_file";
type IndexedSearchSourceType = Exclude<SearchSourceType, "all">;
type SearchTimeRange = "all" | "15m" | "1h" | "24h";
type ResultStatus = "usable" | CriticResult["result"] | "all";
type SortMode = "newest" | "relevance";
type MediaAvailability = "available" | "expired" | "unknown";
type DetectorFrameAvailability = "available" | "checking" | "unavailable";

const RESULTS_PAGE_SIZE = 6;
const PRIMARY_SEARCH_SIMILARITY = "0.25";
const ALL_SOURCE_SEARCH_SIMILARITY = "0.12";
// Scoping to one source must not hide candidates accepted by all-source discovery.
const DISCOVERY_SEARCH_SIMILARITY = ALL_SOURCE_SEARCH_SIMILARITY;
const ALL_SOURCE_SEARCH_TOP_K = 18;
const SCOPED_SEARCH_TOP_K = 12;
const SOURCE_REPRESENTATIVE_SCORE_RATIO = 0.5;
const TRACK_GROUP_GAP_MS = 30_000;
const ADJACENT_CHUNK_GAP_MS = 1_500;

function apiErrorDetail(payload: unknown): string | null {
  if (typeof payload === "string") return payload.trim() || null;
  if (Array.isArray(payload)) {
    const details = payload
      .map((item) => apiErrorDetail(item))
      .filter((item): item is string => Boolean(item));
    return details.length ? details.join(" ") : null;
  }
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  for (const key of ["message", "error", "detail", "msg"]) {
    const detail = apiErrorDetail(record[key]);
    if (detail) return detail;
  }
  return null;
}

function operatorSearchError(detail: string | null, visual = false): string {
  const cleaned = detail
    ?.replace(/^\s*\d{3}:\s*/i, "")
    .replace(/^\s*(?:visual object )?search error:\s*/i, "")
    .trim();
  if (
    cleaned &&
    /all connection attempts failed|connection (?:refused|failed)|service unavailable/i.test(
      cleaned
    )
  ) {
    return visual
      ? "Local visual search is temporarily unavailable because its embedding service is offline. Check System readiness, then retry."
      : "Local video search is temporarily unavailable because its embedding service is offline. Check System readiness, then retry.";
  }
  return (
    cleaned || (visual ? "Visual object search failed." : "Search failed.")
  );
}

async function searchResponseError(
  response: Response,
  visual = false
): Promise<string> {
  let detail: string | null = null;
  try {
    detail = apiErrorDetail(await response.json());
  } catch {
    // FastAPI normally returns JSON. Preserve a useful status fallback if an
    // upstream proxy instead returns an empty or non-JSON response.
  }
  if ([502, 503, 504].includes(response.status)) {
    return "Video search is temporarily unavailable. Check local services in System, then retry. Your indexed evidence has not been removed.";
  }
  return operatorSearchError(
    detail ||
      `${visual ? "Visual object search" : "Search"} returned ${
        response.status
      }.`,
    visual
  );
}

interface SearchCriteria {
  camera?: VisionStream;
  reviewStatus: ResultStatus;
  sourceType: SearchSourceType;
  timeRange: SearchTimeRange;
}

const TIME_RANGE_MS: Record<Exclude<SearchTimeRange, "all">, number> = {
  "15m": 15 * 60 * 1000,
  "1h": 60 * 60 * 1000,
  "24h": 24 * 60 * 60 * 1000,
};

function sourceTypeForCamera(camera?: VisionStream): SearchSourceType {
  if (!camera) return "all";
  return isLiveStream(camera) ? "rtsp" : "video_file";
}

function indexedSourceTypes(
  criteria: SearchCriteria
): IndexedSearchSourceType[] {
  if (criteria.camera) {
    return [isLiveStream(criteria.camera) ? "rtsp" : "video_file"];
  }
  return criteria.sourceType === "all"
    ? ["video_file", "rtsp"]
    : [criteria.sourceType];
}

function timestampsForRange(timeRange: SearchTimeRange): {
  timestampEnd: string | null;
  timestampStart: string | null;
} {
  if (timeRange === "all") {
    return { timestampEnd: null, timestampStart: null };
  }
  const endTime = Date.now();
  return {
    timestampEnd: new Date(endTime).toISOString(),
    timestampStart: new Date(endTime - TIME_RANGE_MS[timeRange]).toISOString(),
  };
}

export function earliestRetainedRecordingStart(
  payload: unknown,
  scopedSensorId?: string
): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const starts: number[] = [];
  for (const [sensorId, value] of Object.entries(payload)) {
    if (
      sensorId === "total" ||
      (scopedSensorId && sensorId !== scopedSensorId)
    ) {
      continue;
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const timelines = (value as { timelines?: unknown }).timelines;
    if (!Array.isArray(timelines)) continue;
    for (const timeline of timelines) {
      if (
        !timeline ||
        typeof timeline !== "object" ||
        Array.isArray(timeline)
      ) {
        continue;
      }
      const parsed = Date.parse(
        String((timeline as { startTime?: unknown }).startTime ?? "")
      );
      if (Number.isFinite(parsed)) starts.push(parsed);
    }
  }
  return starts.length ? new Date(Math.min(...starts)).toISOString() : null;
}

function resultReviewStatus(item: VisionSearchResult): CriticResult["result"] {
  return item.critic_result?.result ?? "unverified";
}

function resultMatchSignals(
  item: VisionSearchResult,
  isVisualSearch = false
): MatchSignal[] {
  if (item.match_signals?.length) return item.match_signals;
  const signals: MatchSignal[] = [];
  if (item.incident_id) signals.push("incident");
  if (isVisualSearch) signals.push("visual");
  else signals.push("semantic");
  if (item.object_ids.length) signals.push("detector");
  if (item.critic_result?.result === "confirmed") signals.push("vlm_verified");
  if (item.critic_result?.result === "rejected") signals.push("vlm_rejected");
  return [...new Set(signals)];
}

function signalLabel(signal: MatchSignal): string {
  if (signal === "semantic") return "Semantic Match";
  if (signal === "detector") return "Detector Match";
  if (signal === "visual") return "Visual Match";
  if (signal === "vlm_verified") return "VLM Verified";
  if (signal === "vlm_rejected") return "VLM Rejected";
  if (signal === "incident_candidate") return "Incident Candidate";
  return "Confirmed Incident";
}

function resultReviewLabel(
  item: VisionSearchResult,
  isVisualSearch = false
): string {
  return resultMatchSignals(item, isVisualSearch).map(signalLabel).join(" + ");
}

function matchExplanation(
  item: VisionSearchResult,
  isVisualSearch = false
): string {
  const signals = resultMatchSignals(item, isVisualSearch);
  if (signals.includes("incident") || signals.includes("incident_candidate")) {
    return item.incident_reasoning
      ? `A retained analytics incident matched this query. ${item.incident_reasoning}`
      : "A retained analytics incident matched this query and time range.";
  }
  if (signals.includes("visual")) {
    return "Cosmos Embed ranked this tracked object's visual embedding against the indexed object archive.";
  }
  if (signals.includes("detector") && signals.includes("vlm_verified")) {
    return "Cosmos semantic retrieval and detector metadata agreed; Cosmos VLM then verified the visible match.";
  }
  if (signals.includes("detector")) {
    return "Cosmos semantic retrieval was fused with locally indexed detector and tracker metadata.";
  }
  if (signals.includes("vlm_verified")) {
    return "Cosmos semantic retrieval found this interval and Cosmos VLM verified it against the query.";
  }
  if (signals.includes("vlm_rejected")) {
    return "The interval matched semantically, but the visual verifier did not confirm the query.";
  }
  return "Cosmos Embed ranked this video interval by semantic similarity to the query.";
}

function resultTitle(item: VisionSearchResult, query: string): string {
  const description = item.description.trim();
  if (/^VST live stream$/i.test(description)) return resultSourceName(item.video_name);
  if (description && !/^attribute match at\s/i.test(description)) {
    return description;
  }
  return (
    query
      .replace(/^\s*(?:find|show|search for|look for)\s+/i, "")
      .replace(/[?.!]+$/, "")
      .replace(/^./, (character) => character.toUpperCase()) ||
    "Relevant video moment"
  );
}

function formatClock(value: string): string {
  if (!value) return "Time unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year:
      date.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatDuration(start: string, end: string): string {
  const durationMilliseconds = Date.parse(end) - Date.parse(start);
  if (durationMilliseconds > 0 && durationMilliseconds < 1_000) return "<1 sec";
  const seconds = Math.max(0, Math.round(durationMilliseconds / 1000));
  if (!Number.isFinite(seconds)) return "—";
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function recordedClipOffset(item: VisionSearchResult): string | null {
  const match = item.video_name.match(/_(\d{8})_(\d{6})_[a-z0-9]+(?:\.mp4)?$/i);
  const start = match
    ? Date.UTC(
        Number(match[1].slice(0, 4)),
        Number(match[1].slice(4, 6)) - 1,
        Number(match[1].slice(6, 8)),
        Number(match[2].slice(0, 2)),
        Number(match[2].slice(2, 4)),
        Number(match[2].slice(4, 6))
      )
    : item.start_time.startsWith("2025-01-01T")
    ? Date.parse("2025-01-01T00:00:00.000Z")
    : Number.NaN;
  const offset = (Date.parse(item.start_time) - start) / 1_000;
  if (!Number.isFinite(offset) || offset < 0 || offset > 24 * 60 * 60)
    return null;
  const whole = Math.round(offset);
  return `${Math.floor(whole / 60)}:${(whole % 60)
    .toString()
    .padStart(2, "0")} into recording`;
}

function normalizeMediaUrl(value: string, apiBase?: string | null): string {
  if (!value || !apiBase) return value;
  try {
    const media = new URL(value, new URL(apiBase).origin);
    return `${new URL(apiBase).origin}${media.pathname}${media.search}`;
  } catch {
    return value;
  }
}

function resultSourceName(videoName: string): string {
  return streamDisplayName(resultIndexedSensorName(videoName));
}

function resultIndexedSensorName(videoName: string): string {
  return videoName.replace(/_\d{8}_\d{6}_[a-z0-9]+(?:\.mp4)?$/i, "");
}

function resultIdentity(item: VisionSearchResult): string {
  return `${item.sensor_id}:${item.start_time}:${item.end_time}`;
}

async function resolveMediaAvailability(
  items: VisionSearchResult[],
  vstApiUrl: string | null | undefined,
  signal: AbortSignal
): Promise<Record<string, MediaAvailability>> {
  if (!vstApiUrl) return {};

  const sensorIds = [...new Set(items.map((item) => item.sensor_id))];
  const timelineEntries = await Promise.all(
    sensorIds.map(async (sensorId) => {
      try {
        const response = await fetch(
          `${vstApiUrl.replace(/\/$/, "")}/v1/storage/${encodeURIComponent(
            sensorId
          )}/timelines`,
          { signal }
        );
        if (response.status === 404)
          return [sensorId, [] as RecordingTimeline[]] as const;
        if (!response.ok) return [sensorId, null] as const;
        const timelines = (await response.json()) as RecordingTimeline[] | null;
        // VST returns HTTP 200 with JSON null for a deleted source. Treat that
        // as positively expired media rather than an unknown transient state,
        // otherwise stale embeddings appear usable and fail only after an
        // operator selects them for evidence analysis.
        return [
          sensorId,
          Array.isArray(timelines)
            ? timelines
            : timelines === null
            ? ([] as RecordingTimeline[])
            : null,
        ] as const;
      } catch (error) {
        if (signal.aborted) throw error;
        return [sensorId, null] as const;
      }
    })
  );
  const timelinesBySensor = new Map(timelineEntries);

  return Object.fromEntries(
    items.map((item) => {
      const timelines = timelinesBySensor.get(item.sensor_id);
      const availability: MediaAvailability = timelines
        ? recordingIsRetained(item.start_time, item.end_time, timelines)
          ? "available"
          : "expired"
        : "unknown";
      return [resultIdentity(item), availability];
    })
  );
}

function mergeSearchResults(
  resultGroups: VisionSearchResult[][],
  limit: number
): VisionSearchResult[] {
  const unique = new Map<string, VisionSearchResult>();
  for (const item of resultGroups.flat()) {
    const identity = resultIdentity(item);
    const existing = unique.get(identity);
    if (!existing || item.similarity > existing.similarity) {
      unique.set(identity, item);
    }
  }
  return groupRelatedResults([...unique.values()])
    .sort((left, right) => right.similarity - left.similarity)
    .slice(0, limit);
}

function sharesTrackedObject(
  left: VisionSearchResult,
  right: VisionSearchResult
): boolean {
  if (!left.object_ids.length || !right.object_ids.length) return false;
  const leftIds = new Set(left.object_ids);
  return right.object_ids.some((objectId) => leftIds.has(objectId));
}

function groupRelatedResults(
  values: VisionSearchResult[]
): VisionSearchResult[] {
  const sorted = [...values].sort((left, right) => {
    const sourceOrder = left.sensor_id.localeCompare(right.sensor_id);
    return (
      sourceOrder || Date.parse(left.start_time) - Date.parse(right.start_time)
    );
  });
  const groups: VisionSearchResult[][] = [];
  for (const item of sorted) {
    const itemStart = Date.parse(item.start_time);
    const group = groups.find((candidate) => {
      const last = candidate[candidate.length - 1];
      if (last.sensor_id !== item.sensor_id) return false;
      const gap = itemStart - Date.parse(last.end_time);
      return (
        gap <= ADJACENT_CHUNK_GAP_MS ||
        (gap <= TRACK_GROUP_GAP_MS && sharesTrackedObject(last, item))
      );
    });
    if (group) group.push(item);
    else groups.push([item]);
  }
  return groups.map((group) => {
    const primary = [...group].sort(
      (left, right) => right.similarity - left.similarity
    )[0];
    if (group.length === 1) return primary;
    const starts = group.map((item) => Date.parse(item.start_time));
    const ends = group.map((item) => Date.parse(item.end_time));
    return {
      ...primary,
      end_time: new Date(Math.max(...ends)).toISOString(),
      grouped_intervals: group.map((item) => ({
        end_time: item.end_time,
        start_time: item.start_time,
      })),
      match_signals: [
        ...new Set(group.flatMap((item) => resultMatchSignals(item))),
      ],
      object_ids: [...new Set(group.flatMap((item) => item.object_ids))],
      start_time: new Date(Math.min(...starts)).toISOString(),
    };
  });
}

const QUERY_STOP_WORDS = new Set([
  "a",
  "about",
  "all",
  "an",
  "and",
  "at",
  "during",
  "find",
  "for",
  "from",
  "in",
  "last",
  "me",
  "of",
  "on",
  "show",
  "the",
  "this",
  "to",
  "video",
  "was",
  "were",
  "what",
  "where",
  "who",
  "with",
]);

function queryTerms(value: string): string[] {
  return [
    ...new Set(
      value
        .toLowerCase()
        .match(/[a-z0-9]+/g)
        ?.filter((term) => term.length > 2 && !QUERY_STOP_WORDS.has(term)) ?? []
    ),
  ];
}

function incidentSnapshotUrl(
  incident: AnalyticsIncident,
  vstApiUrl: string
): string | null {
  const raw = incident.info?.snapshotUrls;
  if (!raw) return null;
  try {
    const values = JSON.parse(raw) as string[];
    return values[0] ? normalizeMediaUrl(values[0], vstApiUrl) : null;
  } catch {
    return null;
  }
}

function incidentSearchResults(
  query: string,
  incidents: AnalyticsIncident[],
  streams: VisionStream[],
  criteria: SearchCriteria,
  vstApiUrl: string
): VisionSearchResult[] {
  const terms = queryTerms(query);
  if (!terms.length) return [];
  const startBoundary =
    criteria.timeRange === "all"
      ? null
      : Date.now() - TIME_RANGE_MS[criteria.timeRange];
  return consolidateIncidents(incidents)
    .filter(
      (incident) =>
        !isDiagnosticIncident(incident) &&
        incidentVerdict(incident) !== "rejected"
    )
    .flatMap((incident): VisionSearchResult[] => {
      const stream = streams.find(
        (candidate) =>
          candidate.streamId === incident.sensorId ||
          candidate.sensorId === incident.sensorId ||
          candidate.name === incident.sensorId
      );
      if (!stream) return [];
      const streamType: IndexedSearchSourceType = isLiveStream(stream)
        ? "rtsp"
        : "video_file";
      if (
        (criteria.camera && criteria.camera.streamId !== stream.streamId) ||
        (criteria.sourceType !== "all" && criteria.sourceType !== streamType)
      ) {
        return [];
      }
      const timestamp = Date.parse(incident.timestamp);
      if (
        !Number.isFinite(timestamp) ||
        (startBoundary !== null && timestamp < startBoundary)
      ) {
        return [];
      }
      const searchable = [
        incidentTitle(incident),
        incident.info?.alertCategory,
        incident.info?.description,
        incident.info?.reasoning,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      const matchedTerms = terms.filter((term) => searchable.includes(term));
      if (!matchedTerms.length) return [];
      const verdict = incidentVerdict(incident);
      const screenshot = incidentSnapshotUrl(incident, vstApiUrl);
      return [
        {
          critic_result: {
            result: verdict === "confirmed" ? "confirmed" : "unverified",
          },
          description: incidentTitle(incident),
          end_time:
            incident.end ??
            new Date(Date.parse(incident.timestamp) + 2_000).toISOString(),
          incident_id: incident.Id,
          incident_reasoning: incident.info?.reasoning,
          match_signals: [
            verdict === "confirmed" ? "incident" : "incident_candidate",
            ...(incident.objectIds?.length
              ? (["detector"] as MatchSignal[])
              : []),
            ...(verdict === "confirmed"
              ? (["vlm_verified"] as MatchSignal[])
              : []),
          ],
          object_ids: incident.objectIds ?? [],
          screenshot_url:
            screenshot ??
            `${vstApiUrl.replace(
              /\/$/,
              ""
            )}/v1/replay/stream/${encodeURIComponent(
              stream.streamId
            )}/picture?startTime=${encodeURIComponent(incident.timestamp)}`,
          sensor_id: stream.streamId,
          similarity:
            verdict === "confirmed"
              ? Math.min(1, 0.9 + matchedTerms.length / (terms.length * 10))
              : Math.min(
                  0.75,
                  0.45 + matchedTerms.length / (terms.length * 10)
                ),
          source_type: streamType,
          start_time: incident.timestamp,
          video_name: stream.name,
        },
      ];
    });
}

function rankByRelevance(
  items: VisionSearchResult[],
  diversifySources: boolean
): VisionSearchResult[] {
  const ranked = [...items].sort(
    (left, right) => right.similarity - left.similarity
  );
  if (!diversifySources || ranked.length < 2) return ranked;

  const representativeFloor = Math.max(
    Number(ALL_SOURCE_SEARCH_SIMILARITY),
    ranked[0].similarity * SOURCE_REPRESENTATIVE_SCORE_RATIO
  );
  const representedSources = new Set<string>();
  const representatives: VisionSearchResult[] = [];
  const remaining: VisionSearchResult[] = [];

  for (const item of ranked) {
    if (
      !representedSources.has(item.sensor_id) &&
      item.similarity >= representativeFloor
    ) {
      representedSources.add(item.sensor_id);
      representatives.push(item);
    } else {
      remaining.push(item);
    }
  }
  return [...representatives, ...remaining];
}

function EvidenceViewer({
  item,
  onAsk,
  mdxWebApiUrl,
  onClose,
  onFindSimilar,
  query,
  searchByImageEnabled,
  visualSearchResult,
  vstApiUrl,
}: {
  item: VisionSearchResult;
  onAsk: () => void;
  mdxWebApiUrl?: string | null;
  onClose: () => void;
  onFindSimilar: (reference: VisualReference) => Promise<string | null>;
  query: string;
  searchByImageEnabled: boolean;
  visualSearchResult: boolean;
  vstApiUrl?: string | null;
}) {
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoStartTime, setVideoStartTime] = useState(item.start_time);
  const [error, setError] = useState<string | null>(null);
  const [selectionTimestamp, setSelectionTimestamp] = useState<string | null>(
    null
  );
  const [detectorFrames, setDetectorFrames] =
    useState<DetectorFrameAvailability>("checking");

  const dialogRef = useDialogAccessibility<HTMLDivElement>({ isOpen: true, onClose });
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (!searchByImageEnabled || !mdxWebApiUrl) {
      setDetectorFrames("unavailable");
      return;
    }
    const controller = new AbortController();
    const check = async () => {
      setDetectorFrames("checking");
      const start = Date.parse(item.start_time);
      const end = Date.parse(item.end_time);
      if (!Number.isFinite(start) || !Number.isFinite(end)) {
        setDetectorFrames("unavailable");
        return;
      }
      const params = new URLSearchParams({
        fromTimestamp: new Date(start - 1_000).toISOString(),
        sensorId: resultIndexedSensorName(item.video_name),
        toTimestamp: new Date(end + 1_000).toISOString(),
      });
      try {
        const response = await fetch(
          `${mdxWebApiUrl}/frames?${params.toString()}`,
          { signal: controller.signal }
        );
        if (!response.ok) throw new Error("Detector metadata is unavailable.");
        const payload = (await response.json()) as { frames?: unknown };
        if (!controller.signal.aborted) {
          setDetectorFrames(
            Array.isArray(payload.frames) && payload.frames.length > 0
              ? "available"
              : "unavailable"
          );
        }
      } catch {
        if (!controller.signal.aborted) setDetectorFrames("unavailable");
      }
    };
    void check();
    return () => controller.abort();
  }, [
    item.end_time,
    item.start_time,
    item.video_name,
    mdxWebApiUrl,
    searchByImageEnabled,
  ]);

  useEffect(() => {
    if (!vstApiUrl) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        const exactStart = Date.parse(item.start_time);
        const exactEnd = Date.parse(item.end_time);
        const requestedStart =
          visualSearchResult && Number.isFinite(exactStart)
            ? new Date(exactStart - 2_000).toISOString()
            : item.start_time;
        const requestedEnd =
          visualSearchResult && Number.isFinite(exactEnd)
            ? new Date(exactEnd + 2_000).toISOString()
            : item.end_time;
        const response = await fetch(
          evidenceClipEndpoint(item.sensor_id, requestedStart, requestedEnd),
          { signal: controller.signal }
        );
        if (!response.ok) {
          const failure = (await response.json().catch(() => null)) as {
            error?: string;
          } | null;
          throw new Error(
            failure?.error || `Evidence clip returned ${response.status}.`
          );
        }
        const data = (await response.json()) as {
          startTime?: string;
          videoUrl?: string;
        };
        if (!data.videoUrl)
          throw new Error("Evidence clip URL was not returned.");
        setVideoUrl(normalizeMediaUrl(data.videoUrl, vstApiUrl));
        setVideoStartTime(data.startTime ?? item.start_time);
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Evidence clip is unavailable."
          );
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [
    item.end_time,
    item.sensor_id,
    item.start_time,
    visualSearchResult,
    vstApiUrl,
  ]);

  return (
    <div
      ref={dialogRef}
      className="vi-evidence-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Evidence viewer"
    >
      <div className="vi-evidence-viewer">
        <button
          className="vi-evidence-close"
          type="button"
          onClick={onClose}
          aria-label="Close evidence"
        >
          <IconX size={21} />
        </button>
        <div className="vi-evidence-media">
          {selectionTimestamp && vstApiUrl && mdxWebApiUrl ? (
            <FindSimilarSelector
              frameTimestamp={selectionTimestamp}
              mdxWebApiUrl={mdxWebApiUrl}
              onCancel={() => setSelectionTimestamp(null)}
              onSearch={onFindSimilar}
              preferredObjectType={query}
              sensorId={item.sensor_id}
              sensorName={resultIndexedSensorName(item.video_name)}
              vstApiUrl={vstApiUrl}
            />
          ) : videoUrl ? (
            <video
              src={videoUrl}
              poster={proxyVstPictureUrl(
                normalizeMediaUrl(item.screenshot_url, vstApiUrl)
              )}
              autoPlay
              controls
              playsInline
              ref={videoRef}
            />
          ) : (
            <img
              src={proxyVstPictureUrl(
                normalizeMediaUrl(item.screenshot_url, vstApiUrl)
              )}
              alt={resultTitle(item, query)}
            />
          )}
          {!videoUrl && !error && (
            <div className="vi-evidence-loading">
              <span className="vi-spinner" /> Preparing evidence clip
            </div>
          )}
          {error && (
            <div className="vi-evidence-loading vi-evidence-loading--error">
              {error}
            </div>
          )}
        </div>
        <aside className="vi-evidence-detail">
          <span className="vi-evidence-kicker">
            <IconSparkles size={18} /> Evidence
          </span>
          <h2>{resultTitle(item, query)}</h2>
          <div className="vi-evidence-facts">
            <div>
              <IconCamera size={17} />
              <span>Source</span>
              <strong>{resultSourceName(item.video_name)}</strong>
            </div>
            <div>
              <IconClock size={17} />
              <span>Observed</span>
              <strong>
                {recordedClipOffset(item) ?? formatClock(item.start_time)}
              </strong>
            </div>
            <div>
              <IconSearch size={17} />
              <span>Evidence type</span>
              <strong>{resultReviewLabel(item, visualSearchResult)}</strong>
            </div>
          </div>
          <p>
            {searchByImageEnabled && detectorFrames === "available"
              ? "Pause on an object, then choose Find similar object to search for another appearance. Only objects detected in that frame can be selected."
              : searchByImageEnabled && detectorFrames === "checking"
              ? "Checking whether object search is available for this clip. You can keep watching."
              : searchByImageEnabled
              ? "Watch the matching moment to check what happened. Search by object is unavailable for this clip; you can still search using words."
              : "Watch the matching moment to check what happened. The source and recording position identify the footage behind this result."}
          </p>
          <button type="button" className="vi-button vi-button--primary" onClick={onAsk}>
            <IconSparkles size={18} /> Ask about this clip
          </button>
          <div className="vi-match-explanation">
            <strong>Why this matched</strong>
            <span>{matchExplanation(item, visualSearchResult)}</span>
          </div>
          {item.critic_result && (
            <div
              className={`vi-critic vi-critic--${item.critic_result.result}`}
            >
              {item.critic_result.result === "confirmed" ? (
                <IconCheck size={16} />
              ) : null}
              Critic: {item.critic_result.result}
            </div>
          )}
          {searchByImageEnabled &&
            detectorFrames === "available" &&
            videoUrl &&
            vstApiUrl &&
            mdxWebApiUrl &&
            !selectionTimestamp && (
              <button
                className="vi-find-similar-action"
                type="button"
                onClick={() => {
                  const video = videoRef.current;
                  video?.pause();
                  const baseTime = Date.parse(videoStartTime);
                  const offset = Math.max(0, video?.currentTime ?? 0) * 1_000;
                  if (Number.isFinite(baseTime)) {
                    setSelectionTimestamp(
                      new Date(baseTime + Math.round(offset)).toISOString()
                    );
                  }
                }}
              >
                <IconBox size={17} /> Find similar object
              </button>
            )}
          {searchByImageEnabled &&
            videoUrl &&
            (!vstApiUrl || !mdxWebApiUrl) && (
              <p className="vi-find-similar-unavailable">
                Visual object search is unavailable because detector metadata is
                not configured for this deployment.
              </p>
            )}
        </aside>
      </div>
    </div>
  );
}

export function InvestigateWorkspace({
  isActive = true,
  agentApiUrl,
  initialRequest,
  mdxWebApiUrl,
  searchByImageEnabled = false,
  vstApiUrl,
}: InvestigateWorkspaceProps) {
  const [query, setQuery] = useState(initialRequest?.query ?? "");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState<VisionSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchMessages, setSearchMessages] = useState<string[]>([]);
  const [selectedEvidence, setSelectedEvidence] =
    useState<VisionSearchResult | null>(null);
  const evidenceRevision = useRef(0);
  const lastEvidenceQuestion = useRef<string | undefined>(undefined);
  const [evidenceSelection, setEvidenceSelection] = useState<string[]>([]);
  const [evidenceSnapshots, setEvidenceSnapshots] = useState<Record<string, {
    item: VisionSearchResult; query: string; visual: boolean;
  }>>({});
  const questionInputRef = useRef<HTMLInputElement>(null);
  const focusQuestionAfterViewer = useRef(false);
  useEffect(() => {
    if (selectedEvidence || !focusQuestionAfterViewer.current) return;
    // Run after the viewer's cleanup restores focus to its opener.
    focusQuestionAfterViewer.current = false;
    questionInputRef.current?.focus();
  }, [selectedEvidence]);
  const [evidenceAnalysis, setEvidenceAnalysis] =
    useState<EvidenceAnalysisResponse | null>(null);
  const [evidenceAnalysisError, setEvidenceAnalysisError] = useState<
    string | null
  >(null);
  const [evidenceAnalysisLoading, setEvidenceAnalysisLoading] = useState(false);
  const [inspectionProgress, setInspectionProgress] = useState<EvidenceVisualInspection[]>([]);
  const [visualReference, setVisualReference] =
    useState<VisualReference | null>(null);
  const [scopedCamera, setScopedCamera] = useState<VisionStream | undefined>(
    initialRequest?.camera
  );
  const [sourceType, setSourceType] = useState<SearchSourceType>(
    sourceTypeForCamera(initialRequest?.camera)
  );
  const [timeRange, setTimeRange] = useState<SearchTimeRange>("all");
  const [resultStatus, setResultStatus] = useState<ResultStatus>("usable");
  const [sortMode, setSortMode] = useState<SortMode>("relevance");
  const [mediaAvailability, setMediaAvailability] = useState<
    Record<string, MediaAvailability>
  >({});
  const [visibleCount, setVisibleCount] = useState(RESULTS_PAGE_SIZE);
  const [showSearchMethod, setShowSearchMethod] = useState(false);
  const activeRequest = useRef<AbortController | null>(null);
  const appliedInitialRequest = useRef<{
    agentApiUrl?: string | null;
    request: InvestigationRequest;
  } | null>(null);
  const { isLoading: sourcesLoading, streams: availableStreams } =
    useVisionStreams(vstApiUrl, isActive);

  // Preserve the inquiry across navigation, but release the viewer and its media.
  useEffect(() => {
    if (!isActive) setSelectedEvidence(null);
  }, [isActive]);

  const availableSearchSources = useMemo(() => {
    const unique = new Map<string, VisionStream>();
    for (const stream of [
      ...availableStreams,
      ...(scopedCamera ? [scopedCamera] : []),
    ]) {
      if (sourceType === "all" || sourceTypeForCamera(stream) === sourceType) {
        unique.set(stream.streamId, stream);
      }
    }
    return [...unique.values()].sort((left, right) =>
      streamDisplayName(left.name).localeCompare(streamDisplayName(right.name))
    );
  }, [availableStreams, scopedCamera, sourceType]);

  const search = useCallback(
    async (nextQuery: string, criteria: SearchCriteria) => {
      const normalizedQuery = nextQuery.trim();
      if (!normalizedQuery) return;

      setSubmittedQuery(normalizedQuery);
      setVisibleCount(RESULTS_PAGE_SIZE);
      setSelectedEvidence(null);
      evidenceRevision.current += 1;
      setEvidenceAnalysis(null);
    setInspectionProgress([]);
      setEvidenceAnalysisError(null);
      setVisualReference(null);
      setMediaAvailability({});
      setSearchMessages([]);
      if (!agentApiUrl) {
        setLoading(false);
        setResults([]);
        setError("Video evidence search is not configured on this deployment.");
        return;
      }

      activeRequest.current?.abort();
      const controller = new AbortController();
      activeRequest.current = controller;
      const { timestampEnd, timestampStart } = timestampsForRange(
        criteria.timeRange
      );
      setLoading(true);
      setError(null);
      setResults([]);
      try {
        let retainedLiveStart: string | null = null;
        if (
          criteria.timeRange === "all" &&
          criteria.reviewStatus === "usable" &&
          vstApiUrl
        ) {
          try {
            const retentionResponse = await fetch(
              `${vstApiUrl}/v1/storage/size?timelines=true`,
              { signal: controller.signal }
            );
            if (retentionResponse.ok) {
              retainedLiveStart = earliestRetainedRecordingStart(
                await retentionResponse.json(),
                criteria.camera && isLiveStream(criteria.camera)
                  ? criteria.camera.streamId
                  : undefined
              );
            }
          } catch (retentionError) {
            if (controller.signal.aborted) throw retentionError;
            // Availability is still checked per result below. A failed
            // retention probe must not make semantic search unavailable.
          }
        }
        const request = async (
          requestSourceType: IndexedSearchSourceType,
          minCosineSimilarity: string,
          topK: number
        ) => {
          const response = await fetch(`${agentApiUrl}/search/fusion`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: controller.signal,
            body: JSON.stringify({
              query: normalizedQuery,
              video_sources: criteria.camera ? [criteria.camera.name] : [],
              timestamp_start:
                requestSourceType === "rtsp" && retainedLiveStart
                  ? retainedLiveStart
                  : timestampStart,
              timestamp_end: timestampEnd,
              min_cosine_similarity: minCosineSimilarity,
              top_k: topK,
              // Direct semantic retrieval is the interactive search path on a
              // single Thor. Agent-mode query planning can add roughly a
              // minute of local LLM latency before Elasticsearch is queried,
              // while returning the same ranked Cosmos-Embed matches for the
              // natural-language searches this workspace accepts. Nemotron is
              // reserved for the higher-value evidence synthesis and follow-up
              // stages below, where its latency produces a visible result.
              agent_mode: false,
              // Keep archive discovery responsive on a single Thor. Explicit
              // evidence analysis below reuses retained Cosmos captions and
              // invokes fresh visual inspection only when capacity is free.
              use_critic: false,
              source_type: requestSourceType,
            }),
          });
          if (!response.ok) {
            throw new Error(await searchResponseError(response));
          }
          return (await response.json()) as {
            data?: VisionSearchResult[];
            search_messages?: string[];
          };
        };

        const requestTypes = indexedSourceTypes(criteria);
        const runSearch = async (minCosineSimilarity: string, topK: number) => {
          const attempts = await Promise.allSettled(
            requestTypes.map((requestSourceType) =>
              request(requestSourceType, minCosineSimilarity, topK)
            )
          );
          const successful = attempts.flatMap((attempt, index) => {
            if (attempt.status !== "fulfilled") return [];
            return [
              {
                data: (attempt.value.data ?? []).map((item) => ({
                  ...item,
                  source_type: requestTypes[index],
                })),
                messages: attempt.value.search_messages ?? [],
              },
            ];
          });
          if (!successful.length) {
            const failure = attempts.find(
              (attempt): attempt is PromiseRejectedResult =>
                attempt.status === "rejected"
            );
            throw failure?.reason ?? new Error("Search failed.");
          }
          return {
            data: mergeSearchResults(
              successful.map((value) => value.data),
              topK
            ),
            searchMessages: [
              ...new Set(successful.flatMap((value) => value.messages)),
            ],
          };
        };

        let payload = criteria.camera
          ? await runSearch(PRIMARY_SEARCH_SIMILARITY, SCOPED_SEARCH_TOP_K)
          : await runSearch(
              ALL_SOURCE_SEARCH_SIMILARITY,
              ALL_SOURCE_SEARCH_TOP_K
            );
        if (
          criteria.camera &&
          !payload.data?.length &&
          !controller.signal.aborted
        ) {
          payload = await runSearch(
            DISCOVERY_SEARCH_SIMILARITY,
            SCOPED_SEARCH_TOP_K
          );
        }
        let nextResults = payload.data ?? [];
        const nextMessages = [...payload.searchMessages];
        const incidentStreams = [
          ...availableStreams,
          ...(criteria.camera ? [criteria.camera] : []),
        ];
        if (vstApiUrl && incidentStreams.length) {
          try {
            const incidentResponse = await fetch("/api/vision/incidents", {
              signal: controller.signal,
            });
            if (incidentResponse.ok) {
              const incidentPayload = (await incidentResponse.json()) as {
                incidents?: AnalyticsIncident[];
              };
              const incidentMatches = incidentSearchResults(
                normalizedQuery,
                incidentPayload.incidents ?? [],
                incidentStreams,
                criteria,
                vstApiUrl
              );
              nextResults = mergeSearchResults(
                [incidentMatches, nextResults],
                criteria.camera ? SCOPED_SEARCH_TOP_K : ALL_SOURCE_SEARCH_TOP_K
              );
            } else {
              nextMessages.push(
                "Retained incidents were unavailable; video search results are still complete."
              );
            }
          } catch (incidentError) {
            if (controller.signal.aborted) throw incidentError;
            nextMessages.push(
              "Retained incidents were unavailable; video search results are still complete."
            );
          }
        }
        const nextAvailability = await resolveMediaAvailability(
          nextResults,
          vstApiUrl,
          controller.signal
        );
        if (!controller.signal.aborted) {
          setMediaAvailability(nextAvailability);
          setResults(nextResults);
          setSearchMessages([...new Set(nextMessages)]);
        }
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Search failed."
          );
        }
      } finally {
        if (activeRequest.current === controller) {
          activeRequest.current = null;
          setLoading(false);
        }
      }
    },
    [agentApiUrl, availableStreams, vstApiUrl]
  );

  const searchByReference = useCallback(
    async (reference: VisualReference): Promise<string | null> => {
      const nextQuery = `Visually similar ${reference.objectType.toLowerCase()}`;
      if (!agentApiUrl) {
        return "Visual object search is not configured on this deployment.";
      }

      activeRequest.current?.abort();
      const controller = new AbortController();
      activeRequest.current = controller;
      setLoading(true);
      setError(null);
      try {
        const requestTypes: IndexedSearchSourceType[] =
          sourceType === "all" ? ["video_file", "rtsp"] : [sourceType];
        const attempts = await Promise.allSettled(
          requestTypes.map(async (requestSourceType) => {
            const response = await fetch(`${agentApiUrl}/search/image`, {
              body: JSON.stringify({
                agent_mode: false,
                query: nextQuery,
                reference_object: {
                  object_id: reference.objectId,
                  sensor_id: reference.sensorId,
                  sensor_name: reference.sensorName,
                  timestamp: reference.timestamp,
                },
                source_type: requestSourceType,
                top_k: 24,
              }),
              headers: { "Content-Type": "application/json" },
              method: "POST",
              signal: controller.signal,
            });
            if (!response.ok) {
              throw new Error(await searchResponseError(response, true));
            }
            return (await response.json()) as {
              data?: VisionSearchResult[];
              search_messages?: string[];
            };
          })
        );
        const payloads = attempts
          .filter(
            (
              attempt
            ): attempt is PromiseFulfilledResult<{
              data?: VisionSearchResult[];
              search_messages?: string[];
            }> => attempt.status === "fulfilled"
          )
          .map((attempt) => attempt.value);
        if (!payloads.length) {
          const failure = attempts.find(
            (attempt): attempt is PromiseRejectedResult =>
              attempt.status === "rejected"
          );
          throw failure?.reason ?? new Error("Visual object search failed.");
        }
        if (!controller.signal.aborted) {
          const nextResults = mergeSearchResults(
            payloads.map((payload) =>
              (payload.data ?? []).map((item) => ({
                ...item,
                match_signals: [
                  "visual" as MatchSignal,
                  ...(item.object_ids.length
                    ? (["detector"] as MatchSignal[])
                    : []),
                ],
              }))
            ),
            24
          );
          if (!nextResults.length) {
            const detail = payloads
              .flatMap((payload) => payload.search_messages ?? [])
              .join(" ");
            if (/not found|no embedding/i.test(detail)) {
              return "This box was detected, but it is not in the visual-similarity index. Choose another object or scrub to a later moment.";
            }
            return (
              detail ||
              "No visual matches were found for this object. Choose another box or moment."
            );
          }
          setVisualReference(reference);
          setQuery(nextQuery);
          setSubmittedQuery(nextQuery);
          setVisibleCount(RESULTS_PAGE_SIZE);
          const nextAvailability = await resolveMediaAvailability(
            nextResults,
            vstApiUrl,
            controller.signal
          );
          setMediaAvailability(nextAvailability);
          setResults(nextResults);
          setSelectedEvidence(null);
          evidenceRevision.current += 1;
          setEvidenceAnalysis(null);
    setInspectionProgress([]);
          setEvidenceAnalysisError(null);
          return null;
        }
        return "Visual search was cancelled.";
      } catch (requestError) {
        if (!controller.signal.aborted) {
          return requestError instanceof Error
            ? requestError.message
            : "Visual object search failed.";
        }
        return "Visual search was cancelled.";
      } finally {
        if (activeRequest.current === controller) {
          activeRequest.current = null;
          setLoading(false);
        }
      }
    },
    [agentApiUrl, sourceType, vstApiUrl]
  );

  useEffect(() => {
    if (!initialRequest?.query) return;
    const previous = appliedInitialRequest.current;
    if (
      previous?.request === initialRequest &&
      previous.agentApiUrl === agentApiUrl
    )
      return;
    appliedInitialRequest.current = { agentApiUrl, request: initialRequest };

    const nextSourceType = sourceTypeForCamera(initialRequest.camera);
    setQuery(initialRequest.query);
    setScopedCamera(initialRequest.camera);
    setSourceType(nextSourceType);
    setTimeRange("all");
    void search(initialRequest.query, {
      camera: initialRequest.camera,
      reviewStatus: "usable",
      sourceType: nextSourceType,
      timeRange: "all",
    });
  }, [agentApiUrl, initialRequest, search]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const visibleResults = useMemo(() => {
    const filtered = results.filter((item) => {
      const status = resultReviewStatus(item);
      if (resultStatus === "all") return true;
      if (resultStatus === "usable") {
        return (
          status !== "rejected" &&
          mediaAvailability[resultIdentity(item)] !== "expired"
        );
      }
      return status === resultStatus;
    });
    if (sortMode === "relevance") {
      return rankByRelevance(filtered, !scopedCamera);
    }
    return [...filtered].sort((left, right) => {
      const leftTime = Date.parse(left.start_time);
      const rightTime = Date.parse(right.start_time);
      return (
        (Number.isFinite(rightTime) ? rightTime : 0) -
        (Number.isFinite(leftTime) ? leftTime : 0)
      );
    });
  }, [mediaAvailability, resultStatus, results, scopedCamera, sortMode]);
  const shownResults = visibleResults.slice(0, visibleCount);
  const visibleSourceCount = useMemo(
    () =>
      new Set(visibleResults.map((item) => resultSourceName(item.video_name)))
        .size,
    [visibleResults]
  );
  const selectedResults = useMemo(() => {
    return evidenceSelection
      .map((identity) => evidenceSnapshots[identity]?.item)
      .filter(
        (item): item is VisionSearchResult =>
          Boolean(item) &&
          mediaAvailability[resultIdentity(item!)] !== "expired"
      );
  }, [evidenceSelection, evidenceSnapshots, mediaAvailability]);
  const selectedEvidenceItems = useMemo<SelectedEvidenceItem[]>(
    () =>
      selectedResults.map((item) => ({
        clientId: resultIdentity(item),
        endTime: item.end_time,
        imageUrl: proxyVstPictureUrl(
          normalizeMediaUrl(item.screenshot_url, vstApiUrl)
        ),
        matchType: resultReviewLabel(item, evidenceSnapshots[resultIdentity(item)]?.visual ?? false),
        sensorId: item.sensor_id,
        sourceName: resultSourceName(item.video_name),
        startTime: item.start_time,
        startLabel: recordedClipOffset(item) ?? undefined,
        durationLabel: formatDuration(item.start_time, item.end_time),
        fromEarlierSearch: !results.some((result) => resultIdentity(result) === resultIdentity(item)),
        title: resultTitle(item, evidenceSnapshots[resultIdentity(item)]?.query ?? submittedQuery),
      })),
    [selectedResults, evidenceSnapshots, submittedQuery, vstApiUrl, results]
  );

  const analyzeSelectedEvidence = async (question?: string) => {
    if (!selectedResults.length || evidenceAnalysisLoading) return;
    const request: EvidenceAnalysisRequest = {
      query: submittedQuery,
      ...(question ? { question } : {}),
      evidence: selectedResults.map((item) => ({
        client_id: resultIdentity(item),
        end_time: item.end_time,
        match_type: resultReviewLabel(item, evidenceSnapshots[resultIdentity(item)]?.visual ?? false),
        search_description: item.description,
        sensor_id: item.sensor_id,
        source_name: resultSourceName(item.video_name),
        start_time: item.start_time,
      })),
    };
    lastEvidenceQuestion.current = question;
    const revision = ++evidenceRevision.current;
    setEvidenceAnalysis(null);
    setInspectionProgress([]);
    setEvidenceAnalysisLoading(true);
    setEvidenceAnalysisError(null);
    try {
      const response = await fetch("/api/vision/evidence-analysis", {
        body: JSON.stringify(request),
        headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
        method: "POST",
      });
      const payload = await readEvidenceAnalysis(response, (inspection) => {
        if (revision === evidenceRevision.current) {
          setInspectionProgress((current) => [...current, inspection]);
        }
      });
      if (revision === evidenceRevision.current) setEvidenceAnalysis(payload);
    } catch (analysisError) {
      if (revision !== evidenceRevision.current) return;
      setEvidenceAnalysisError(
        analysisError instanceof Error
          ? analysisError.message
          : "Selected evidence could not be analyzed."
      );
    } finally {
      setEvidenceAnalysisLoading(false);
    }
  };

  const addEvidence = (identity: string) => {
    if (evidenceSelection.includes(identity)) return;
    if (evidenceSelection.length >= 6) {
      setEvidenceAnalysisError("Choose up to six clips. Remove one before adding another.");
      return;
    }
    const item = results.find((result) => resultIdentity(result) === identity);
    if (!item) return;
    setEvidenceSnapshots((snapshots) => ({ ...snapshots,
      [identity]: { item, query: submittedQuery, visual: Boolean(visualReference) },
    }));
    setEvidenceSelection((selection) => [...selection, identity]);
    evidenceRevision.current += 1;
    setEvidenceAnalysis(null);
    setInspectionProgress([]);
    setEvidenceAnalysisError(null);
  };

  const removeEvidence = (identity: string) => {
    setEvidenceSnapshots((snapshots) => {
      const next = { ...snapshots };
      delete next[identity];
      return next;
    });
    setEvidenceSelection((selection) =>
      selection.filter((value) => value !== identity)
    );
    evidenceRevision.current += 1;
    setEvidenceAnalysis(null);
    setInspectionProgress([]);
    setEvidenceAnalysisError(null);
  };

  const clearEvidence = () => {
    setEvidenceSelection([]);
    setEvidenceSnapshots({});
    evidenceRevision.current += 1;
    setEvidenceAnalysis(null);
    setInspectionProgress([]);
    setEvidenceAnalysisError(null);
  };

  const openEvidence = (identity: string) => {
    const item = evidenceSnapshots[identity]?.item;
    if (item) setSelectedEvidence(item);
  };

  const currentCriteria = useCallback(
    (overrides: Partial<SearchCriteria> = {}): SearchCriteria => ({
      camera: scopedCamera,
      reviewStatus: resultStatus,
      sourceType,
      timeRange,
      ...overrides,
    }),
    [resultStatus, scopedCamera, sourceType, timeRange]
  );

  const rerunSubmittedSearch = (criteria: SearchCriteria) => {
    if (submittedQuery) void search(submittedQuery, criteria);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void search(query, currentCriteria());
  };

  return (
    <section className="vi-investigate">
      <form className="vi-investigate-query" onSubmit={submit}>
        <IconSparkles size={24} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Describe the moment you want to find…"
          aria-label="Search video evidence"
        />
        <button type="submit" aria-label="Search">
          <IconArrowRight size={22} />
        </button>
      </form>
      <div className="vi-investigate-filters">
        <label className="vi-investigate-filter">
          <IconCamera size={17} />
          <select
            aria-label="Search source"
            disabled={loading || sourcesLoading}
            value={scopedCamera?.streamId ?? "all"}
            onChange={(event) => {
              const nextCamera = availableSearchSources.find(
                (stream) => stream.streamId === event.target.value
              );
              setScopedCamera(nextCamera);
              rerunSubmittedSearch(currentCriteria({ camera: nextCamera }));
            }}
          >
            <option value="all">All sources</option>
            {availableSearchSources.map((stream) => (
              <option key={stream.streamId} value={stream.streamId}>
                {streamDisplayName(stream.name)}
              </option>
            ))}
          </select>
        </label>
        <details className="vi-search-refinements">
          <summary>Refine search{(timeRange !== "all" || sourceType !== "all" || resultStatus !== "usable") ? ` · ${[timeRange !== "all", sourceType !== "all", resultStatus !== "usable"].filter(Boolean).length} active` : ""}</summary>
          <div>
        <label className="vi-investigate-filter">
          <IconClock size={17} />
          <select
            aria-label="Time range"
            disabled={loading}
            value={timeRange}
            onChange={(event) => {
              const nextTimeRange = event.target.value as SearchTimeRange;
              setTimeRange(nextTimeRange);
              rerunSubmittedSearch(
                currentCriteria({ timeRange: nextTimeRange })
              );
            }}
          >
            <option value="all">All time</option>
            <option value="15m">Last 15 minutes</option>
            <option value="1h">Last hour</option>
            <option value="24h">Last 24 hours</option>
          </select>
        </label>
        <label className="vi-investigate-filter">
          <IconAdjustmentsHorizontal size={17} />
          <select
            aria-label="Footage type"
            disabled={loading}
            value={sourceType}
            onChange={(event) => {
              const nextSourceType = event.target.value as SearchSourceType;
              const nextCamera =
                scopedCamera &&
                (nextSourceType === "all" ||
                  sourceTypeForCamera(scopedCamera) === nextSourceType)
                  ? scopedCamera
                  : undefined;
              setSourceType(nextSourceType);
              setScopedCamera(nextCamera);
              rerunSubmittedSearch(
                currentCriteria({
                  camera: nextCamera,
                  sourceType: nextSourceType,
                })
              );
            }}
          >
            <option value="all">All footage</option>
            <option value="video_file">Recorded video</option>
            <option value="rtsp">Live archive</option>
          </select>
        </label>
        <label className="vi-investigate-filter">
          <IconCheck size={17} />
          <select
            aria-label="Review status"
            value={resultStatus}
            onChange={(event) => {
              const nextResultStatus = event.target.value as ResultStatus;
              setResultStatus(nextResultStatus);
              // "Usable" all-time RTSP searches are bounded to media that VST
              // still retains. Crossing that boundary needs one server refresh;
              // every other status change is an immediate local filter.
              if (
                vstApiUrl &&
                timeRange === "all" &&
                (resultStatus === "usable" || nextResultStatus === "usable")
              ) {
                rerunSubmittedSearch(
                  currentCriteria({ reviewStatus: nextResultStatus })
                );
              }
            }}
          >
            <option value="usable">Usable matches</option>
            <option value="confirmed">Confirmed only</option>
            <option value="unverified">Unverified only</option>
            <option value="rejected">Rejected only</option>
            <option value="all">All statuses</option>
          </select>
        </label>
          </div>
        </details>
      </div>

      {!submittedQuery && !loading && (
        <div className="vi-investigate-empty">
          <IconSearch size={28} />
          <h1>Find the moment that matters</h1>
          <p>
            Search in everyday language. Watch a matching clip, select it as evidence,
            then ask AI to explain what is visible—with a citation back to the footage.
          </p>
          <div>
            {[
              "People moving",
              "Vehicles at an intersection",
              "Forklift activity",
            ].map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => {
                  setQuery(suggestion);
                  void search(suggestion, currentCriteria());
                }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && (
        <div className="vi-investigate-loading">
          <span className="vi-spinner" /> Searching indexed video evidence…
        </div>
      )}
      {error && (
        <div className="vi-investigate-error">
          <strong>
            {visualReference
              ? "Visual search could not complete"
              : "Search could not complete"}
          </strong>
          <span>{error}</span>
          {visualReference && (
            <div className="vi-investigate-error-actions">
              <button
                type="button"
                onClick={() => void searchByReference(visualReference)}
              >
                Retry visual search
              </button>
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setVisualReference(null);
                  setSubmittedQuery("");
                  setQuery("");
                }}
              >
                Start a new search
              </button>
            </div>
          )}
        </div>
      )}

      {!loading && submittedQuery && !error && (
        <div className="vi-results-shell">
          {visualReference && (
            <div
              className="vi-visual-reference"
              aria-label="Visual search reference"
            >
              <IconBox size={18} />
              <div>
                <strong>
                  Similar to selected {visualReference.objectType.toLowerCase()}
                </strong>
                <span>
                  {streamDisplayName(visualReference.sensorName)} · tracked
                  object {visualReference.objectId} · exact indexed frame
                </span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setVisualReference(null);
                  setResults([]);
                  setSubmittedQuery("");
                  setQuery("");
                }}
              >
                Clear visual search
              </button>
            </div>
          )}
          {!visualReference && (
            <div className="vi-search-summary" aria-label="Search summary">
              <div>
                <IconSparkles size={22} />
                <div>
                  <strong>
                    {visibleResults.length} relevant{" "}
                    {visibleResults.length === 1 ? "clip" : "clips"} found
                    across {visibleSourceCount}{" "}
                    {visibleSourceCount === 1 ? "source" : "sources"}
                  </strong>
                  <span>
                    {visibleResults.length > 0
                      ? `Matches for “${submittedQuery}”. Play a clip to check it, then choose Ask about this clip to ask your own question.`
                      : `No playable matches for “${submittedQuery}” with the current filters. This does not establish that the activity never occurred.`}
                  </span>
                </div>
              </div>
              <button
                type="button"
                aria-expanded={showSearchMethod}
                onClick={() => setShowSearchMethod((current) => !current)}
              >
                How this was answered
                <IconChevronDown
                  className={showSearchMethod ? "is-open" : ""}
                  size={16}
                />
              </button>
            </div>
          )}
          {!visualReference && searchMessages.length > 0 && (
            <div className="vi-search-notices" aria-label="Search notices">
              {searchMessages.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          )}
          {!visualReference && showSearchMethod && (
            <div
              className="vi-search-intelligence"
              aria-label="Search pipeline"
            >
              <div>
                <IconSparkles size={17} />
                <strong>Fast local search</strong>
                <span>Cosmos semantic retrieval</span>
                <span>Local evidence ranking</span>
                {results.some((item) => item.object_ids.length > 0) && (
                  <span>Detector + track fusion</span>
                )}
                {results.some((item) => item.incident_id) && (
                  <span>Retained incidents</span>
                )}
              </div>
            </div>
          )}
          <div className="vi-results-heading">
            <div>
              <strong>
                {visibleResults.length}{" "}
                {visualReference
                  ? `visually similar object${visibleResults.length === 1 ? "" : "s"}`
                  : `matching clip${visibleResults.length === 1 ? "" : "s"}`}
              </strong>
              <span>
                {sortMode === "relevance"
                  ? "Ranked by relevance"
                  : "Newest evidence first"}
              </span>
            </div>
            <div className="vi-results-heading-actions" style={visibleResults.length < 2 ? { display: "none" } : undefined}>
              <button
                type="button"
                className={sortMode === "relevance" ? "is-active" : ""}
                aria-pressed={sortMode === "relevance"}
                onClick={() => setSortMode("relevance")}
              >
                Relevance
              </button>
              <button
                type="button"
                className={sortMode === "newest" ? "is-active" : ""}
                aria-pressed={sortMode === "newest"}
                onClick={() => setSortMode("newest")}
              >
                Newest first
              </button>

            </div>
          </div>
          {selectedResults.length > 0 && (
            <EvidenceAnalysisPanel
              key={evidenceRevision.current}
              questionInputRef={questionInputRef}
              analysis={evidenceAnalysis}
              error={evidenceAnalysisError}
              isAnalyzing={evidenceAnalysisLoading}
              items={selectedEvidenceItems}
              inspections={inspectionProgress}
              onAnalyze={() => void analyzeSelectedEvidence()}
              onRetry={() => void analyzeSelectedEvidence(lastEvidenceQuestion.current)}
              onAsk={(question) => void analyzeSelectedEvidence(question)}
              onClear={clearEvidence}
              onOpenEvidence={openEvidence}
              onRemove={removeEvidence}
            />
          )}
          {visibleResults.length ? (
            <div className={`vi-results-grid${visibleResults.length === 1 ? " vi-results-grid--single" : ""}`}>
              {shownResults.map((item, index) => {
                const identity = resultIdentity(item);
                const isSelected = evidenceSelection.includes(identity);
                const evidenceLabel = resultTitle(item, submittedQuery);
                const recordingExpired =
                  mediaAvailability[identity] === "expired";
                return (
                  <article
                    className={`vi-result-card${
                      isSelected ? " is-selected" : ""
                    }${recordingExpired ? " is-expired" : ""}`}
                    key={`${identity}-${index}`}
                  >
                    <button
                      className="vi-result-image"
                      type="button"
                      aria-label={
                        recordingExpired
                          ? `Preview unavailable for ${evidenceLabel}`
                          : `Play clip: ${evidenceLabel}`
                      }
                      disabled={recordingExpired}
                      onClick={() => setSelectedEvidence(item)}
                    >
                      {recordingExpired ? (
                        <div
                          className="vi-result-expired-frame"
                          aria-hidden="true"
                        >
                          <IconClock size={22} />
                          <small>Recording unavailable</small>
                        </div>
                      ) : (
                        <img
                          src={proxyVstPictureUrl(
                            normalizeMediaUrl(item.screenshot_url, vstApiUrl)
                          )}
                          alt={evidenceLabel}
                        />
                      )}
                      <span>
                        <IconPlayerPlay size={15} />{" "}
                        {formatDuration(item.start_time, item.end_time)}
                      </span>
                    </button>
                    <div className="vi-result-body">
                      <div className="vi-result-rank">{index + 1}</div>
                      <div className="vi-result-copy">
                        <h2>{resultTitle(item, submittedQuery)}</h2>
                        <p>{resultSourceName(item.video_name)}</p>
                        <time>
                          {recordedClipOffset(item) ??
                            formatClock(item.start_time)}{" "}
                          · {formatDuration(item.start_time, item.end_time)}{" "}
                          clip
                        </time>
                        <div className="vi-result-tags">
                          {resultMatchSignals(
                            item,
                            Boolean(visualReference)
                          ).map((signal) => (
                            <span className={`is-${signal}`} key={signal}>
                              {(signal === "vlm_verified" ||
                                signal === "incident") && (
                                <IconCheck size={13} />
                              )}
                              {signal === "vlm_rejected" && <IconX size={13} />}
                              {signalLabel(signal)}
                            </span>
                          ))}
                          <span>Indexed locally on Thor</span>
                          {recordingExpired && (
                            <span className="is-expired">
                              Recording expired
                            </span>
                          )}
                          {visualReference && (
                            <span className="is-visual-match">
                              Ranked by object appearance
                            </span>
                          )}
                          {item.grouped_intervals && (
                            <span>
                              {item.grouped_intervals.length} adjacent matches
                              grouped
                            </span>
                          )}
                        </div>
                        <details className="vi-result-method">
                          <summary>Why this matched</summary>
                          <p className="vi-result-why">{matchExplanation(item, Boolean(visualReference))}</p>
                        </details>
                      </div>
                      <div className="vi-result-actions">
                        <button
                          type="button"
                          aria-label={
                            recordingExpired
                              ? `Recording expired for ${evidenceLabel}`
                              : undefined
                          }
                          disabled={recordingExpired}
                          onClick={() => setSelectedEvidence(item)}
                        >
                          {recordingExpired ? (
                            <>
                              <IconClock size={16} /> Recording expired
                            </>
                          ) : (
                            <>
                              <IconPlayerPlay size={16} /> Play clip
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          className={isSelected ? "is-selected" : ""}
                          aria-pressed={isSelected}
                          aria-label={`${
                            recordingExpired
                              ? `Expired ${evidenceLabel} cannot be used as evidence`
                              : `${isSelected ? "Remove clip" : "Ask about this clip"}: ${evidenceLabel}`
                          }`}
                          disabled={recordingExpired}
                          onClick={() => {
                            if (isSelected) {
                              removeEvidence(identity);
                              return;
                            }
                            addEvidence(identity);
                          }}
                        >
                          {isSelected ? <IconX size={16} /> : <IconSparkles size={16} />}{" "}
                          {isSelected ? "Remove clip" : "Ask about this clip"}
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
              {visibleResults.length > shownResults.length && (
                <div className="vi-results-more">
                  <button
                    type="button"
                    onClick={() =>
                      setVisibleCount((count) => count + RESULTS_PAGE_SIZE)
                    }
                  >
                    Load more matches <span>↓</span>
                  </button>
                  <small>
                    Showing {shownResults.length} of {visibleResults.length}{" "}
                    matches
                  </small>
                </div>
              )}
            </div>
          ) : (
            <div className="vi-results-empty">
              {results.length && resultStatus === "usable"
                ? "Matching embeddings were found, but their recordings have expired. Choose All statuses to review the indexed history."
                : "No matching evidence was returned. Try a shorter description of the main action, or broaden the source and time filters."}
            </div>
          )}
        </div>
      )}

      {selectedEvidence && (
        <EvidenceViewer
          item={selectedEvidence}
          onAsk={() => {
            focusQuestionAfterViewer.current = true;
            addEvidence(resultIdentity(selectedEvidence));
            setSelectedEvidence(null);
          }}
          mdxWebApiUrl={mdxWebApiUrl}
          onClose={() => setSelectedEvidence(null)}
          onFindSimilar={searchByReference}
          query={evidenceSnapshots[resultIdentity(selectedEvidence)]?.query ?? submittedQuery}
          searchByImageEnabled={searchByImageEnabled}
          visualSearchResult={evidenceSnapshots[resultIdentity(selectedEvidence)]?.visual ?? Boolean(visualReference)}
          vstApiUrl={vstApiUrl}
        />
      )}
    </section>
  );
}
