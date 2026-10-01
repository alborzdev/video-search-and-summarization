// SPDX-License-Identifier: MIT

import type { VisionStreamsApiResponse } from "../../../components/vision-intelligence/types";
import {
  isLiveStream,
  parseVisionStreams,
} from "../../../components/vision-intelligence/utils";
import type { NextApiRequest, NextApiResponse } from "next";
import { readLiveRecordingWindow } from "../../../server/vision/liveRecordingWindow";
import { DEFAULT_LOOKBACK_SECONDS, validLookbackSeconds } from "../../../components/vision-intelligence/footageWindow";

import { visualQuestionBlockReason } from "../../../server/vision/visualQuestionReadiness";

const ID_PATTERN = /^[A-Za-z0-9._:-]{1,160}$/;

function sameOrigin(req: NextApiRequest): boolean {
  const origin = req.headers?.origin;
  if (origin === undefined) return true;
  if (typeof origin !== "string" || typeof req.headers.host !== "string")
    return false;
  try {
    const parsed = new URL(origin);
    const protocol =
      req.headers["x-forwarded-proto"] ||
      ((req.socket as { encrypted?: boolean })?.encrypted ? "https" : "http");
    return (
      parsed.origin === origin &&
      parsed.host === req.headers.host &&
      parsed.protocol === `${protocol}:`
    );
  } catch {
    return false;
  }
}

async function vstRequest(
  path: string,
  operation: string,
  init: RequestInit = {}
) {
  const base = (
    process.env.VST_INTERNAL_API_URL || "http://127.0.0.1:30888/vst/api"
  ).replace(/\/$/, "");
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      ...init,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new Error(
      `Video capture service could not ${operation}. Check its connection and retry.`
    );
  }
  if (!response.ok)
    throw new Error(
      `Video capture service could not ${operation} (HTTP ${response.status}).`
    );
  return response;
}

async function readJson(
  response: Response,
  description: string
): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new Error(
      `Video capture service returned an invalid ${description}.`
    );
  }
}

function validCatalog(data: unknown): data is VisionStreamsApiResponse {
  return (
    Array.isArray(data) &&
    data.every(
      (sensor) =>
        sensor &&
        typeof sensor === "object" &&
        !Array.isArray(sensor) &&
        Object.values(sensor).every(
          (streams) =>
            Array.isArray(streams) &&
            streams.every(
              (stream) =>
                stream &&
                typeof stream === "object" &&
                typeof stream.streamId === "string" &&
                (stream.url === undefined || typeof stream.url === "string") &&
                (stream.vodUrl === undefined ||
                  typeof stream.vodUrl === "string")
            )
        )
    )
  );
}

async function recordingStatus(streamId: string, transitionRetries = 0): Promise<{
  recordingStatus: "on" | "off";
  vstRecordingMode: string;
}> {
  const response = await vstRequest(
    `/v1/record/${encodeURIComponent(streamId)}/status`,
    "read recording status"
  );
  const payload = (await readJson(response, "recording status")) as {
    recordingStatus?: unknown;
  } | null;
  const mode = payload?.recordingStatus;
  // An acknowledged manual start can precede recorder/database initialization:
  // VIOS briefly emits "error" or "statusUnknown" before the real user mode.
  // Wait a bounded interval for verified state; persistent errors still fail.
  if ((mode === "statusUnknown" || mode === "error") && transitionRetries > 0) {
    await new Promise(resolve => setTimeout(resolve, 250));
    return recordingStatus(streamId, transitionRetries - 1);
  }
  // VIOS translateRecordStateToString emits modes, not a boolean. Event mode
  // can wait for a trigger and discard footage outside triggered intervals.
  if (mode === "event") {
    throw new Error(
      "Event-only recording does not establish continuous live capture. Start manual recording in System."
    );
  }
  if (mode === "off") return { recordingStatus: "off", vstRecordingMode: mode };
  if (
    mode === "user" ||
    mode === "schedule" ||
    mode === "alwaysOn" ||
    mode === "on"
  ) {
    return { recordingStatus: "on", vstRecordingMode: mode };
  }
  throw new Error(
    "Video capture service did not report a usable recording state. Check this source in System."
  );
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET" && req.method !== "POST") {
    res.setHeader("Allow", "GET, POST");
    return res.status(405).json({ error: "Method not allowed." });
  }
  if (req.method === "POST" && !sameOrigin(req)) {
    return res
      .status(403)
      .json({ error: "Start or stop live capture from this application." });
  }
  const body = req.body as { streamId?: unknown; action?: unknown; lookbackSeconds?: unknown } | null;
  const streamId = req.method === "GET" ? req.query.streamId : body?.streamId;
  const action = body?.action;
  const requestedSeconds = req.method === "GET" ? req.query.lookbackSeconds : body?.lookbackSeconds;
  const lookbackSeconds = requestedSeconds === undefined ? DEFAULT_LOOKBACK_SECONDS
    : req.method === "GET" && typeof requestedSeconds === "string" ? Number(requestedSeconds) : requestedSeconds;
  if (!validLookbackSeconds(lookbackSeconds)) {
    return res.status(422).json({ error: "Choose a whole number from 1 to 60 seconds of footage." });
  }
  if (
    typeof streamId !== "string" ||
    !ID_PATTERN.test(streamId) ||
    (req.method === "POST" && action !== "start" && action !== "stop")
  ) {
    return res
      .status(422)
      .json({ error: "Choose a valid live stream and capture action." });
  }
  try {
    const catalogResponse = await vstRequest(
      "/v1/live/streams",
      "check live sources"
    );
    const catalog = await readJson(catalogResponse, "live source catalog");
    if (!validCatalog(catalog))
      throw new Error(
        "Video capture service returned an invalid live source catalog."
      );
    const stream = parseVisionStreams(catalog).find(
      (candidate) => candidate.streamId === streamId
    );
    if (!stream || !isLiveStream(stream)) {
      return res.status(422).json({
        error: "Live capture requires a registered live RTSP stream.",
      });
    }
    let mutationFailure: string | null = null;
    if (req.method === "POST") {
      try {
        await vstRequest(
          `/v1/record/${encodeURIComponent(streamId)}/${action}`,
          `${action} recording`,
          {
            body: "{}",
            headers: { "Content-Type": "application/json", streamId },
            method: "POST",
          }
        );
      } catch (failure) {
        // VIOS rejects repeated start/stop commands. The verified final state
        // determines success, including when a completed request lost its reply.
        mutationFailure =
          failure instanceof Error
            ? failure.message
            : "Live capture could not complete.";
      }
    }
    let state: Awaited<ReturnType<typeof recordingStatus>>;
    try {
      state = await recordingStatus(streamId, req.method === "POST" && !mutationFailure ? 8 : 0);
    } catch (failure) {
      if (!mutationFailure) throw failure;
      return res.status(502).json({
        streamId,
        sensorId: stream.sensorId,
        error: mutationFailure,
        verificationError:
          failure instanceof Error
            ? failure.message
            : "Recording status could not be verified.",
      });
    }
    const status = state.recordingStatus;
    const result = {
      streamId,
      sensorId: stream.sensorId,
      ...state,
    };
    if (
      req.method === "POST" &&
      status !== (action === "start" ? "on" : "off")
    ) {
      return res.status(502).json({
        ...result,
        error:
          mutationFailure ||
          `Live capture did not ${action}; recording is still ${status}. Check the source connection and retry.`,
      });
    }
    const readiness = status === "on"
      ? await readLiveRecordingWindow(stream.sensorId, undefined, lookbackSeconds)
      : null;
    const questionBlockReason = await visualQuestionBlockReason();
    return res.status(200).json({
      ...result,
      questionReady: readiness?.ready === true,
      ...(questionBlockReason ? { questionBlockReason } : {}),
      remainingSeconds: readiness?.remainingSeconds ?? null,
      ...(readiness?.error ? { questionReadinessError: readiness.error } : {}),
    });
  } catch (error) {
    return res.status(502).json({
      error:
        error instanceof Error
          ? error.message
          : "Live capture could not complete.",
    });
  }
}
