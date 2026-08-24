// SPDX-License-Identifier: MIT

import type {
  VideoHistoryAnswer,
  VideoHistoryAskRequest,
  VideoHistoryCitation,
  VideoHistoryRecord,
  VideoHistoryStartRequest,
} from "../../../components/vision-intelligence/videoHistory";
import type { NextApiRequest, NextApiResponse } from "next";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

import { THOR_LIVE_CAPTION_PROFILE } from "../../../server/vision/liveCaptionProfile";
import { isSourceLiveAlertFocused } from "../../../server/vision/liveAlertReservation";
import {
  admitWorkload,
  WorkloadAdmissionError,
  workloadAdmissionFailure,
} from "../../../server/vision/workloadAdmissionAdapter";

const STORE_DIR =
  process.env.VISION_HISTORY_DIR || "/tmp/vss-vision-intelligence-history";
const LVS_URL = (
  process.env.LVS_BACKEND_URL || "http://127.0.0.1:38111"
).replace(/\/$/, "");
const VST_URL = (
  process.env.VST_INTERNAL_API_URL || "http://127.0.0.1:30888/vst/api"
).replace(/\/$/, "");
const CAPTION_DB_URL = (
  process.env.VISION_HISTORY_ELASTICSEARCH_URL || "http://127.0.0.1:9200"
).replace(/\/$/, "");
const AGENT_URL = (
  process.env.VISION_AGENT_INTERNAL_URL || "http://127.0.0.1:8100/api/v1"
).replace(/\/$/, "");
const DEFAULT_MODEL =
  process.env.LVS_VLM_MODEL || "nim_nvidia_cosmos3-nano-reasoner_bf16-final";
const ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;
const historyBuildJobs = new Map<string, Promise<void>>();
const liveCaptionRepairJobs = new Map<string, Promise<void>>();
const liveCaptionRepairAttemptedAt = new Map<string, number>();
const LIVE_CAPTION_REPAIR_COOLDOWN_MS = 30_000;
const LIVE_HISTORY_WINDOW_MS =
  Math.min(
    24 * 60,
    Math.max(
      5,
      Number(process.env.VISION_HISTORY_LIVE_WINDOW_MINUTES || 30)
    )
  ) *
  60 *
  1_000;
const LIVE_HISTORY_BUILD_TIMEOUT_MS = Math.min(
  30 * 60_000,
  Math.max(
    5 * 60_000,
    Number(process.env.VISION_HISTORY_BUILD_TIMEOUT_MS || 10 * 60_000)
  )
);

class HistoryError extends Error {
  constructor(message: string, readonly statusCode = 400) {
    super(message);
  }
}

function single(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] || "" : value || "";
}

function recordPath(sourceId: string): string {
  return path.join(STORE_DIR, `${sourceId}.json`);
}

async function readRecord(sourceId: string): Promise<VideoHistoryRecord> {
  return JSON.parse(await readFile(recordPath(sourceId), "utf8"));
}

async function writeRecord(record: VideoHistoryRecord): Promise<void> {
  const temporary = path.join(
    STORE_DIR,
    `.${record.sourceId}.${process.pid}.${Date.now()}.tmp`
  );
  await writeFile(temporary, JSON.stringify(record, null, 2), {
    encoding: "utf8",
    flag: "wx",
  });
  await rename(temporary, recordPath(record.sourceId));
}

async function jsonRequest<T>(
  url: string,
  init: RequestInit,
  timeoutMs: number
): Promise<T> {
  const response = await fetch(url, {
    ...init,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const raw = await response.text();
  let payload: (T & { detail?: unknown; error?: string }) | null = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    throw new HistoryError(
      `The local video-history service returned unreadable data (${response.status}).`,
      502
    );
  }
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : Array.isArray(payload?.detail)
        ? "The video-history request was rejected by the local service."
        : payload?.error;
    throw new HistoryError(
      detail || `Video history returned ${response.status}.`,
      response.status === 503 ? 503 : 502
    );
  }
  return payload as T;
}

function validateStart(value: unknown): VideoHistoryStartRequest {
  if (!value || typeof value !== "object")
    throw new HistoryError("A valid source is required.");
  const request = value as Partial<VideoHistoryStartRequest>;
  const source = request.source;
  const scenario =
    typeof request.scenario === "string" ? request.scenario.trim() : "";
  const events = Array.isArray(request.events)
    ? request.events
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter(Boolean)
        .slice(0, 12)
    : [];
  if (
    request.action !== "start" ||
    !source ||
    !ID_PATTERN.test(source.id || "") ||
    (source.kind !== "live" && source.kind !== "replay") ||
    typeof source.name !== "string" ||
    source.name.trim().length < 1 ||
    source.name.length > 256 ||
    scenario.length < 2 ||
    scenario.length > 1_024 ||
    events.length < 1
  ) {
    throw new HistoryError(
      "Choose a valid source, scenario, and at least one event of interest."
    );
  }
  return {
    action: "start",
    events,
    scenario,
    source: { ...source, name: source.name.trim() },
  };
}

function validateAsk(value: unknown): VideoHistoryAskRequest {
  if (!value || typeof value !== "object")
    throw new HistoryError("A valid history question is required.");
  const request = value as Partial<VideoHistoryAskRequest>;
  const messages = Array.isArray(request.messages)
    ? request.messages
        .filter(
          (item): item is { content: string; role: "assistant" | "user" } =>
            Boolean(item) &&
            (item.role === "assistant" || item.role === "user") &&
            typeof item.content === "string" &&
            item.content.trim().length > 0
        )
        .slice(-8)
        .map((item) => ({
          ...item,
          content: item.content.trim().slice(0, 4_000),
        }))
    : [];
  if (
    request.action !== "ask" ||
    !ID_PATTERN.test(request.sourceId || "") ||
    !messages.length ||
    messages.at(-1)?.role !== "user"
  ) {
    throw new HistoryError("Enter a valid question for this video history.");
  }
  return { action: "ask", messages, sourceId: request.sourceId as string };
}

async function sourceTimeline(
  sourceId: string
): Promise<{ endTime: string; startTime: string }> {
  const response = await jsonRequest<
    Array<{ endTime: string; startTime: string }>
  >(
    `${VST_URL}/v1/storage/${encodeURIComponent(sourceId)}/timelines`,
    { method: "GET" },
    15_000
  );
  const timelines = response.filter(
    (item) =>
      Number.isFinite(Date.parse(item.startTime)) &&
      Number.isFinite(Date.parse(item.endTime)) &&
      Date.parse(item.endTime) > Date.parse(item.startTime)
  );
  if (!timelines.length)
    throw new HistoryError(
      "This source has no retained video history yet.",
      409
    );
  return {
    endTime: new Date(
      Math.max(...timelines.map((item) => Date.parse(item.endTime)))
    ).toISOString(),
    startTime: new Date(
      Math.min(...timelines.map((item) => Date.parse(item.startTime)))
    ).toISOString(),
  };
}

interface CaptionFreshness {
  count: number;
  latestIndexedAtMs?: number;
  latestEndMs?: number;
}

function captionIndex(sourceId: string): string {
  return `default_${sourceId.replaceAll("-", "_")}`;
}

async function captionFreshness(sourceId: string): Promise<CaptionFreshness> {
  const response = await fetch(
    `${CAPTION_DB_URL}/${encodeURIComponent(captionIndex(sourceId))}/_search`,
    {
      body: JSON.stringify({
        _source: ["@timestamp", "metadata.content_metadata.end_ntp_float"],
        query: {
          term: { "metadata.content_metadata.doc_type.keyword": "raw_events" },
        },
        size: 1,
        sort: [
          {
            "@timestamp": {
              order: "desc",
              unmapped_type: "date",
            },
          },
        ],
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
      signal: AbortSignal.timeout(5_000),
    }
  );
  if (response.status === 404) return { count: 0 };
  if (!response.ok)
    throw new HistoryError(
      `Caption readiness returned ${response.status}.`,
      503
    );
  const payload = (await response.json()) as {
    hits?: {
      hits?: Array<{
        _source?: {
          "@timestamp"?: string;
          metadata?: { content_metadata?: { end_ntp_float?: number } };
        };
      }>;
      total?: number | { value?: number };
    };
  };
  const total = payload.hits?.total;
  const count =
    typeof total === "number"
      ? total
      : typeof total?.value === "number"
      ? total.value
      : 0;
  const endSeconds =
    payload.hits?.hits?.[0]?._source?.metadata?.content_metadata?.end_ntp_float;
  const indexedAt = Date.parse(
    payload.hits?.hits?.[0]?._source?.["@timestamp"] || ""
  );
  return {
    count,
    ...(Number.isFinite(indexedAt) ? { latestIndexedAtMs: indexedAt } : {}),
    ...(Number.isFinite(endSeconds)
      ? { latestEndMs: Number(endSeconds) * 1_000 }
      : {}),
  };
}

async function waitForFreshCaption(
  sourceId: string,
  minimumEndMs: number
): Promise<CaptionFreshness> {
  const timeoutMs = Math.min(
    120_000,
    Math.max(
      10_000,
      Number(process.env.VISION_HISTORY_CAPTION_TIMEOUT_MS || 90_000)
    )
  );
  const deadline = Date.now() + timeoutMs;
  let latest: CaptionFreshness = { count: 0 };
  while (Date.now() < deadline) {
    latest = await captionFreshness(sourceId);
    if (
      latest.count > 0 &&
      typeof latest.latestIndexedAtMs === "number" &&
      latest.latestIndexedAtMs >= minimumEndMs
    )
      return latest;
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new HistoryError(
    latest.count
      ? "Cosmos captioning is active, but a fresh caption was not ready before the synchronization timeout. Try Sync new history again."
      : "Cosmos captioning started, but no searchable history was ready before the timeout. Check the source stream and try again.",
    504
  );
}

function streamSummaryText(content: string | undefined): string {
  if (!content?.trim()) return "";
  try {
    const parsed = JSON.parse(content) as {
      events?: unknown[];
      video_summary?: string;
    };
    const summary = parsed.video_summary?.trim();
    if (summary) return summary;
    if (Array.isArray(parsed.events) && parsed.events.length)
      return `${parsed.events.length} captioned event${
        parsed.events.length === 1 ? "" : "s"
      } indexed for source history.`;
    return "";
  } catch {
    return content.trim();
  }
}

async function startLiveCaptioning(
  sourceId: string,
  scenario: string,
  events: string[],
  timeoutMs = 45_000
): Promise<void> {
  await jsonRequest(
    `${LVS_URL}/v1/generate_captions`,
    {
      body: JSON.stringify({
        ...THOR_LIVE_CAPTION_PROFILE,
        enable_qa: true,
        events,
        id: sourceId,
        model: DEFAULT_MODEL,
        objects_of_interest: [],
        scenario,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    timeoutMs
  );
}

async function repairLiveCaptioning(
  sourceId: string,
  scenario: string,
  events: string[]
): Promise<void> {
  const activeRepair = liveCaptionRepairJobs.get(sourceId);
  if (activeRepair) return activeRepair;

  const attemptedAt = liveCaptionRepairAttemptedAt.get(sourceId) || 0;
  if (Date.now() - attemptedAt < LIVE_CAPTION_REPAIR_COOLDOWN_MS) return;

  // A ready-history GET is also the restart repair hook. Coalesce concurrent
  // requests and throttle normal UI polling so a status check cannot repeatedly
  // reserve the single local Cosmos lane.
  liveCaptionRepairAttemptedAt.set(sourceId, Date.now());
  const repair = startLiveCaptioning(
    sourceId,
    scenario,
    events,
    15_000
  ).finally(() => liveCaptionRepairJobs.delete(sourceId));
  liveCaptionRepairJobs.set(sourceId, repair);
  return repair;
}

async function isLiveAnalysisActive(sourceId: string): Promise<boolean> {
  try {
    const response = await fetch(
      `${AGENT_URL}/rtsp-streams/${encodeURIComponent(sourceId)}/analysis`,
      {
        cache: "no-store",
        method: "GET",
        signal: AbortSignal.timeout(5_000),
      }
    );
    if (!response.ok) return false;
    const payload = (await response.json()) as {
      analysisActive?: boolean;
      state?: string;
    };
    return payload.analysisActive === true && payload.state !== "paused";
  } catch {
    // History status is still useful when the Agent is restarting. Deferring
    // the optional caption repair is safer than violating an explicit pause.
    return false;
  }
}

async function buildLiveHistory(
  request: VideoHistoryStartRequest,
  previous?: VideoHistoryRecord
): Promise<VideoHistoryRecord> {
  const base = {
    events: request.events,
    scenario: request.scenario,
    sourceId: request.source.id,
    sourceKind: request.source.kind,
    sourceName: request.source.name,
    startedAt: previous?.startedAt || new Date().toISOString(),
  } as const;
  const synchronizationStartedMs = Date.now();
  // Reassert caption ownership on every sync. The LVS/RTVI boundary treats an
  // already-owned stream as an idempotent no-op, while this also repairs the
  // consumer after an LVS or Thor restart.
  await startLiveCaptioning(
    request.source.id,
    request.scenario,
    request.events
  );
  // A live Cosmos chunk is not searchable when RTVI merely accepts the
  // stream. Wait for the caption database itself to prove a fresh chunk.
  const currentCaption = await waitForFreshCaption(
    request.source.id,
    synchronizationStartedMs - 5_000
  );
  const timeline = await sourceTimeline(request.source.id);
  if (
    typeof currentCaption.latestEndMs === "number" &&
    currentCaption.latestEndMs < Date.parse(timeline.endTime)
  )
    timeline.endTime = new Date(currentCaption.latestEndMs).toISOString();
  // A live source can retain hours of captions. Rebuilding all of them turns a
  // quick operator action into hundreds of graph/embedding jobs and can exceed
  // the local Thor request budget. Graph history is intentionally a recent,
  // source-scoped memory; the full retained range remains available through
  // Investigate/search.
  const boundedStart = Math.max(
    Date.parse(timeline.startTime),
    Date.parse(timeline.endTime) - LIVE_HISTORY_WINDOW_MS
  );
  timeline.startTime = new Date(boundedStart).toISOString();
  // Graph ingestion is a full UUID-scoped rebuild. Clearing before a sync
  // prevents an earlier empty/partial Document from suppressing later chunks.
  await jsonRequest(
    `${LVS_URL}/v1/qa/${encodeURIComponent(request.source.id)}`,
    { method: "DELETE" },
    90_000
  );
  const summary = await jsonRequest<{
    choices?: Array<{ message?: { content?: string } }>;
  }>(
    `${LVS_URL}/v1/stream_summarize`,
    {
      body: JSON.stringify({
        camera_id: request.source.name,
        enable_qa: true,
        end_time: timeline.endTime,
        id: request.source.id,
        model: DEFAULT_MODEL,
        start_time: timeline.startTime,
        summarize_max_tokens: 512,
        summarize_temperature: 0,
        summarize_top_p: 1,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    LIVE_HISTORY_BUILD_TIMEOUT_MS
  );
  const summaryText = streamSummaryText(summary.choices?.[0]?.message?.content);
  if (!summaryText)
    throw new HistoryError(
      "No captioned events were available for this source yet. Cosmos is still warming up; try Sync new history again.",
      409
    );
  return {
    ...base,
    knowledgeId: request.source.id,
    lastSynchronizedAt: new Date().toISOString(),
    status: "ready",
    summary: summaryText,
    timelineEnd: timeline.endTime,
    timelineStart: timeline.startTime,
  };
}

async function buildReplayHistory(
  request: VideoHistoryStartRequest,
  previous?: VideoHistoryRecord
): Promise<VideoHistoryRecord> {
  const timeline = await sourceTimeline(request.source.id);
  const params = new URLSearchParams({
    container: "mp4",
    disableAudio: "true",
    endTime: timeline.endTime,
    expiryMinutes: "60",
    startTime: timeline.startTime,
  });
  const media = await jsonRequest<{ videoUrl?: string }>(
    `${VST_URL}/v1/storage/file/${encodeURIComponent(
      request.source.id
    )}/url?${params.toString()}`,
    { method: "GET" },
    60_000
  );
  if (!media.videoUrl)
    throw new HistoryError("The retained replay URL was not returned.", 502);
  const summary = await jsonRequest<{
    choices?: Array<{ message?: { content?: string } }>;
    video_id?: string;
  }>(
    `${LVS_URL}/v1/summarize`,
    {
      body: JSON.stringify({
        chunk_duration: 10,
        creation_time: timeline.startTime,
        enable_qa: true,
        events: request.events,
        max_tokens: 512,
        model: DEFAULT_MODEL,
        num_frames_per_second_or_fixed_frames_chunk: 20,
        objects_of_interest: [],
        scenario: request.scenario,
        seed: 1,
        temperature: 0,
        top_p: 1,
        url: media.videoUrl,
        use_fps_for_chunking: false,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    600_000
  );
  const knowledgeId = summary.video_id;
  if (!knowledgeId || !ID_PATTERN.test(knowledgeId))
    throw new HistoryError(
      "LVS did not return a durable history identity.",
      502
    );
  if (previous?.knowledgeId && previous.knowledgeId !== knowledgeId) {
    await fetch(
      `${LVS_URL}/v1/qa/${encodeURIComponent(previous.knowledgeId)}`,
      {
        method: "DELETE",
        signal: AbortSignal.timeout(60_000),
      }
    ).catch(() => undefined);
  }
  return {
    events: request.events,
    knowledgeId,
    lastSynchronizedAt: new Date().toISOString(),
    scenario: request.scenario,
    sourceId: request.source.id,
    sourceKind: "replay",
    sourceName: request.source.name,
    startedAt: previous?.startedAt || new Date().toISOString(),
    status: "ready",
    summary: summary.choices?.[0]?.message?.content || "Video history indexed.",
    timelineEnd: timeline.endTime,
    timelineStart: timeline.startTime,
  };
}

function startHistoryBuild(
  request: VideoHistoryStartRequest,
  previous: VideoHistoryRecord | undefined,
  building: VideoHistoryRecord
): boolean {
  if (historyBuildJobs.has(request.source.id)) return false;

  const job = (async () => {
    try {
      const ready =
        request.source.kind === "live"
          ? await buildLiveHistory(request, previous)
          : await buildReplayHistory(request, previous);
      await writeRecord(ready);
    } catch (buildError) {
      await writeRecord({
        ...building,
        error:
          buildError instanceof Error
            ? buildError.message
            : "Video history could not be built.",
        status: "error",
      });
    } finally {
      historyBuildJobs.delete(request.source.id);
    }
  })();
  historyBuildJobs.set(request.source.id, job);
  return true;
}

async function resumeHistoryBuild(
  record: VideoHistoryRecord
): Promise<VideoHistoryRecord> {
  if (record.status !== "building" || historyBuildJobs.has(record.sourceId))
    return record;

  // The job writes the ready record immediately before removing its in-memory
  // marker. A GET can observe the old building file, yield to that completion,
  // and then see no marker. Re-read before treating it as restart recovery or
  // the same GraphRAG build will be launched twice.
  const latest = await readRecord(record.sourceId);
  if (latest.status !== "building" || historyBuildJobs.has(record.sourceId))
    return latest;
  startHistoryBuild(
    {
      action: "start",
      events: record.events,
      scenario: record.scenario,
      source: {
        id: record.sourceId,
        kind: record.sourceKind,
        name: record.sourceName,
      },
    },
    latest,
    latest
  );
  return latest;
}

function secondsFromClock(value: string): number | null {
  const parts = value.split(":").map(Number);
  if (
    parts.some((part) => !Number.isFinite(part)) ||
    parts.length < 2 ||
    parts.length > 3
  )
    return null;
  return parts.length === 3
    ? parts[0] * 3_600 + parts[1] * 60 + parts[2]
    : parts[0] * 60 + parts[1];
}

function answerCitations(
  answer: string,
  record: VideoHistoryRecord
): VideoHistoryCitation[] {
  const citations: VideoHistoryCitation[] = [];
  const seen = new Set<string>();
  const add = (start: number, end: number, label: string) => {
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start)
      return;
    const boundedEnd = Math.min(end, start + 120_000);
    const key = `${start}:${boundedEnd}`;
    if (seen.has(key)) return;
    seen.add(key);
    citations.push({
      endTime: new Date(boundedEnd).toISOString(),
      label,
      startTime: new Date(start).toISOString(),
    });
  };
  const isoRange =
    /(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)\s*(?:-|–|to)\s*(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)/g;
  const rangeSpans: Array<[number, number]> = [];
  for (const match of answer.matchAll(isoRange)) {
    if (match.index !== undefined)
      rangeSpans.push([match.index, match.index + match[0].length]);
    add(Date.parse(match[1]), Date.parse(match[2]), match[0]);
  }
  // GraphRAG occasionally follows the grounding request with exact event
  // moments rather than ranges (for example, a list of crossing timestamps).
  // Treat each standalone ISO moment as a small playable evidence window so
  // the UI does not contradict a timestamped answer with a "no timestamp"
  // warning. Skip timestamps already consumed by an ISO range.
  const isoPoint = /(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)/g;
  const retainedStart = record.timelineStart
    ? Date.parse(record.timelineStart)
    : NaN;
  const retainedEnd = record.timelineEnd ? Date.parse(record.timelineEnd) : NaN;
  for (const match of answer.matchAll(isoPoint)) {
    const index = match.index ?? -1;
    if (rangeSpans.some(([start, end]) => index >= start && index < end))
      continue;
    const moment = Date.parse(match[1]);
    let start = moment - 5_000;
    let end = moment + 10_000;
    if (Number.isFinite(retainedStart)) start = Math.max(start, retainedStart);
    if (Number.isFinite(retainedEnd)) end = Math.min(end, retainedEnd);
    add(start, end, match[1]);
  }
  const base = record.timelineStart ? Date.parse(record.timelineStart) : NaN;
  const clockRange =
    /\[?(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:-|–|to|and)\s*(\d{1,2}:\d{2}(?::\d{2})?)\]?/gi;
  if (Number.isFinite(base)) {
    const midnight = new Date(base);
    midnight.setUTCHours(0, 0, 0, 0);
    for (const match of answer.matchAll(clockRange)) {
      const start = secondsFromClock(match[1]);
      const end = secondsFromClock(match[2]);
      if (start !== null && end !== null) {
        let startMs = midnight.getTime() + start * 1_000;
        let endMs = midnight.getTime() + end * 1_000;
        if (endMs <= startMs) endMs += 86_400_000;
        const timelineEnd = record.timelineEnd
          ? Date.parse(record.timelineEnd)
          : base + 86_400_000;
        // Live graph answers normally use wall-clock time, while recorded
        // assets can return clip-relative clocks. Resolve the notation against
        // the retained range so either form opens the right evidence moment.
        if (startMs < base - 60_000 || startMs > timelineEnd + 60_000) {
          startMs = base + start * 1_000;
          endMs = base + end * 1_000;
          if (endMs <= startMs) endMs += 86_400_000;
        }
        add(startMs, endMs, match[0]);
      }
    }
  }
  return citations.slice(0, 8);
}

async function askHistory(
  request: VideoHistoryAskRequest
): Promise<VideoHistoryAnswer> {
  const record = await readRecord(request.sourceId);
  if (record.status !== "ready")
    throw new HistoryError(
      "Build this source's video history before asking questions.",
      409
    );
  const userQuestion = request.messages.at(-1)?.content || "";
  // GraphRAG embeds the final user message verbatim. A long policy preamble
  // overwhelms the actual visual question and can push the right chunk below
  // its similarity threshold. Keep retrieval centered on the operator's words
  // while retaining the two response requirements the evidence UI needs.
  const groundedQuestion = [
    userQuestion,
    "Answer only from this source history. Cite exact supporting ISO time ranges and say when the history does not contain the answer.",
  ].join("\n");
  const messages = [
    ...request.messages.slice(0, -1),
    { content: groundedQuestion, role: "user" as const },
  ];
  const result = await jsonRequest<{
    choices?: Array<{ message?: { content?: string } }>;
  }>(
    `${LVS_URL}/v1/chat/completions`,
    {
      body: JSON.stringify({
        id: record.knowledgeId,
        is_live: record.sourceKind === "live",
        max_tokens: 768,
        messages,
        model: DEFAULT_MODEL,
        temperature: 0,
        top_p: 1,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    240_000
  );
  const answer = result.choices?.[0]?.message?.content?.trim();
  if (!answer) throw new HistoryError("Video history returned no answer.", 502);
  const citations = answerCitations(answer, record);
  return {
    answer,
    citations,
    generatedAt: new Date().toISOString(),
    knowledgeId: record.knowledgeId,
    ...(citations.length
      ? {}
      : {
          warning:
            "The graph answer did not include an exact timestamp. Use Investigate to retrieve playable clip evidence.",
        }),
  };
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  await mkdir(STORE_DIR, { recursive: true });
  const sourceId = single(req.query.sourceId);
  if (req.method === "GET") {
    if (!ID_PATTERN.test(sourceId))
      return res.status(422).json({ error: "A valid source is required." });
    try {
      let record = await readRecord(sourceId);
      record = await resumeHistoryBuild(record);
      if (record.sourceKind === "live" && record.status === "ready") {
        // Opening an existing live history repairs caption ownership after a
        // Thor/LVS reboot without forcing a destructive graph rebuild.
        if (
          !(await isSourceLiveAlertFocused(record.sourceId)) &&
          (await isLiveAnalysisActive(record.sourceId))
        ) {
          await repairLiveCaptioning(
            record.sourceId,
            record.scenario,
            record.events
          ).catch(() => undefined);
        }
      }
      return res.status(200).json(record);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        // A missing optional history is the normal first-use state. Returning
        // a successful empty probe keeps browser consoles clean while the UI
        // renders the explicit "History not built" setup screen.
        return res.status(200).json(null);
      }
      return res
        .status(500)
        .json({ error: "Video history status is unavailable." });
    }
  }
  if (req.method === "POST") {
    try {
      if ((req.body as { action?: string })?.action === "ask")
        return res.status(200).json(await askHistory(validateAsk(req.body)));
      const request = validateStart(req.body);
      let previous: VideoHistoryRecord | undefined;
      try {
        previous = await readRecord(request.source.id);
      } catch {
        previous = undefined;
      }
      if (historyBuildJobs.has(request.source.id)) {
        return res.status(202).json(
          previous || {
            events: request.events,
            knowledgeId: request.source.id,
            scenario: request.scenario,
            sourceId: request.source.id,
            sourceKind: request.source.kind,
            sourceName: request.source.name,
            startedAt: new Date().toISOString(),
            status: "building",
          }
        );
      }
      // Builds, unlike GraphRAG asks, can launch a long Cosmos/lane workload.
      // QUEUE is safe here because the existing source flow owns its caption
      // lifecycle; only a conservative BLOCK rejects the new build.
      await admitWorkload("long_video_history_build");
      const building: VideoHistoryRecord = {
        events: request.events,
        knowledgeId: previous?.knowledgeId || request.source.id,
        scenario: request.scenario,
        sourceId: request.source.id,
        sourceKind: request.source.kind,
        sourceName: request.source.name,
        startedAt: previous?.startedAt || new Date().toISOString(),
        status: "building",
      };
      await writeRecord(building);
      startHistoryBuild(request, previous, building);
      return res.status(202).json(building);
    } catch (error) {
      if (error instanceof WorkloadAdmissionError) {
        return res.status(error.statusCode).json(workloadAdmissionFailure(error));
      }
      const historyError =
        error instanceof HistoryError
          ? error
          : new HistoryError(
              error instanceof Error
                ? error.message
                : "Video history is unavailable.",
              502
            );
      return res
        .status(historyError.statusCode)
        .json({ error: historyError.message });
    }
  }
  if (req.method === "DELETE") {
    if (!ID_PATTERN.test(sourceId))
      return res.status(422).json({ error: "A valid source is required." });
    if (historyBuildJobs.has(sourceId))
      return res.status(409).json({
        error:
          "Video history is synchronizing. Wait for it to finish before clearing it.",
      });
    try {
      const record = await readRecord(sourceId);
      await jsonRequest(
        `${LVS_URL}/v1/qa/${encodeURIComponent(record.knowledgeId)}`,
        { method: "DELETE" },
        90_000
      );
      await unlink(recordPath(sourceId));
      liveCaptionRepairAttemptedAt.delete(sourceId);
      liveCaptionRepairJobs.delete(sourceId);
      return res.status(200).json({ deleted: true, sourceId });
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      const historyError =
        error instanceof HistoryError
          ? error
          : new HistoryError(
              code === "ENOENT"
                ? "Video history has already been cleared."
                : "Video history could not be cleared.",
              code === "ENOENT" ? 404 : 502
            );
      return res
        .status(historyError.statusCode)
        .json({ error: historyError.message });
    }
  }
  res.setHeader("Allow", "GET, POST, DELETE");
  return res.status(405).json({ error: "Method not allowed." });
}
