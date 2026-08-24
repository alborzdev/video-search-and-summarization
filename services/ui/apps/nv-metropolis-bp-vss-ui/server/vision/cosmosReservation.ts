// SPDX-License-Identifier: MIT

import { readFile } from "node:fs/promises";
import path from "node:path";

import type { VideoHistoryRecord } from "../../components/vision-intelligence/videoHistory";
import { THOR_LIVE_CAPTION_PROFILE } from "./liveCaptionProfile";
import { isSourceLiveAlertFocused } from "./liveAlertReservation";

interface CaptionSession {
  events: string[];
  scenario: string;
  sourceId: string;
}

interface ActiveCaptionSource {
  sourceId: string;
  sourceName: string;
}

export class CosmosReservationError extends Error {
  constructor(message: string, readonly statusCode: number) {
    super(message);
  }
}

let reservationQueue: Promise<void> = Promise.resolve();
let queuedReservations = 0;

export interface CosmosReservationState {
  active: boolean;
  waitingCount: number;
}

/**
 * Reports only this UI process's queue. It deliberately does not acquire the
 * lane and cannot claim visibility into another process or the VLM's queue.
 */
export function readCosmosReservationState(): CosmosReservationState {
  return {
    active: queuedReservations > 0,
    waitingCount: Math.max(queuedReservations - 1, 0),
  };
}

function historyDirectory(): string {
  return process.env.VISION_HISTORY_DIR || "/tmp/vss-vision-intelligence-history";
}

function lvsUrl(): string {
  return (process.env.LVS_BACKEND_URL || "http://127.0.0.1:38111").replace(/\/$/, "");
}

function rtviVlmUrl(): string {
  return (process.env.RTVI_VLM_URL || "http://127.0.0.1:8018").replace(/\/$/, "");
}

function modelName(): string {
  return process.env.LVS_VLM_MODEL || "nim_nvidia_cosmos3-nano-reasoner_bf16-final";
}

async function activeCaptionSessions(): Promise<CaptionSession[]> {
  const response = await fetch(`${rtviVlmUrl()}/v1/stream/get-stream-info`, {
    cache: "no-store",
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) return [];
  const payload = (await response.json().catch(() => null)) as {
    stream_list?: Array<{
      asset_id?: string;
      camera_id?: string;
      camera_name?: string;
      inference_active?: boolean;
    }>;
  } | null;
  const activeSources: ActiveCaptionSource[] = (payload?.stream_list ?? [])
    .filter((stream) => stream.inference_active)
    .map((stream) => ({
      sourceId: stream.camera_id || stream.asset_id || "",
      sourceName: stream.camera_name || stream.camera_id || stream.asset_id || "",
    }))
    .filter((stream) => Boolean(stream.sourceId));
  const sessions: CaptionSession[] = [];
  for (const { sourceId, sourceName } of activeSources) {
    if (await isSourceLiveAlertFocused(sourceId)) {
      throw new CosmosReservationError(
        "Thor is focused on a continuous live alert for this source. Remove that rule before running an ad-hoc visual inspection.",
        409
      );
    }
    try {
      const record = JSON.parse(
        await readFile(path.join(historyDirectory(), `${sourceId}.json`), "utf8")
      ) as VideoHistoryRecord;
      if (
        record.sourceKind !== "live" ||
        !record.scenario?.trim() ||
        !Array.isArray(record.events) ||
        !record.events.length
      ) {
        sessions.push(defaultCaptionSession(sourceId, sourceName));
        continue;
      }
      sessions.push({
        events: record.events,
        scenario: record.scenario,
        sourceId,
      });
    } catch {
      // Live semantic indexing can be enabled before a user ever opens the
      // optional History workspace. Ad-hoc visual inspection must still be
      // able to borrow Cosmos and then restore captioning. Use the same
      // scenario-aware defaults as the History setup screen instead of
      // sending the operator through an unrelated first-use flow.
      sessions.push(defaultCaptionSession(sourceId, sourceName));
    }
  }
  return sessions;
}

function defaultCaptionSession(
  sourceId: string,
  sourceName: string
): CaptionSession {
  if (/traffic|road|intersection|vehicle|jaywalk/i.test(sourceName)) {
    return {
      events: [
        "pedestrian crossing",
        "stopped vehicle",
        "near collision",
        "unusual traffic activity",
      ],
      scenario: "traffic monitoring",
      sourceId,
    };
  }
  if (/warehouse|forklift|loading|dock|aisle/i.test(sourceName)) {
    return {
      events: [
        "person and vehicle proximity",
        "restricted-zone entry",
        "blocked aisle",
        "unusual activity",
      ],
      scenario: "warehouse monitoring",
      sourceId,
    };
  }
  return {
    events: ["notable activity", "safety risk", "movement changes"],
    scenario: "activity monitoring",
    sourceId,
  };
}

async function suspendCaptioning(session: CaptionSession): Promise<void> {
  const response = await fetch(
    `${rtviVlmUrl()}/v1/generate_captions/${encodeURIComponent(session.sourceId)}`,
    { method: "DELETE", signal: AbortSignal.timeout(30_000) }
  );
  if (!response.ok && response.status !== 404) {
    throw new CosmosReservationError(
      "Cosmos could not reserve the local visual model for this inspection.",
      503
    );
  }
}

async function resumeCaptioning(session: CaptionSession): Promise<boolean> {
  try {
    const response = await fetch(`${lvsUrl()}/v1/generate_captions`, {
      body: JSON.stringify({
        ...THOR_LIVE_CAPTION_PROFILE,
        enable_qa: true,
        events: session.events,
        id: session.sourceId,
        model: modelName(),
        objects_of_interest: [],
        scenario: session.scenario,
      }),
      headers: { "Content-Type": "application/json" },
      method: "POST",
      signal: AbortSignal.timeout(45_000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * RTVI-VLM on Thor runs one heavyweight Cosmos sequence at a time. A live
 * caption session is intentionally long-lived, so clip or current-frame
 * inspection must briefly yield that session or it can wait forever in the
 * model queue. Reservations are process-wide and serialized to avoid two UI
 * requests racing while captions are suspended.
 */
export async function withCosmosReservation<T>(operation: () => Promise<T>): Promise<T> {
  queuedReservations += 1;
  const previous = reservationQueue;
  let release: () => void = () => undefined;
  reservationQueue = new Promise<void>((resolve) => {
    release = resolve;
  });
  await previous;

  const suspended: CaptionSession[] = [];
  try {
    const sessions = await activeCaptionSessions();
    for (const session of sessions) {
      await suspendCaptioning(session);
      suspended.push(session);
    }
    return await operation();
  } finally {
    try {
      const restored = await Promise.all(suspended.map(resumeCaptioning));
      if (restored.some((ready) => !ready)) {
        console.error(
          "Visual inspection completed, but one or more live caption sessions could not be restored."
        );
      }
    } finally {
      // Never strand later callers if restoration or even failure reporting
      // throws unexpectedly. The Agent boundary independently enforces the
      // same invariant for direct, non-UI callers.
      release();
      queuedReservations -= 1;
    }
  }
}
