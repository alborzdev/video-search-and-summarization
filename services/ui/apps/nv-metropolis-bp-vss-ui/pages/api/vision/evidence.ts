// SPDX-License-Identifier: MIT

import {
  recordingIsRetained,
  type RecordingTimeline,
} from "../../../utils/recordingAvailability";
import type { NextApiRequest, NextApiResponse } from "next";

const VST_API_URL = (
  process.env.VST_INTERNAL_API_URL || "http://127.0.0.1:30888/vst/api"
).replace(/\/$/, "");
const EVIDENCE_CLIP_API_URL = (
  process.env.EVIDENCE_CLIP_API_URL || "http://127.0.0.1:8098"
).replace(/\/$/, "");
const SENSOR_PATTERN = /^[A-Za-z0-9_.:-]{1,160}$/;

function single(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] || "" : value || "";
}

function validTimestamp(value: string): boolean {
  return Boolean(value) && Number.isFinite(Date.parse(value));
}

function browserSafeMediaUrl(value: string): string {
  try {
    const parsed = new URL(value, "http://vss.local");
    if (parsed.pathname.startsWith("/vst/")) {
      const publicVst = process.env.NEXT_PUBLIC_VST_API_URL;
      if (publicVst) {
        const publicOrigin = new URL(publicVst).origin;
        return new URL(`${parsed.pathname}${parsed.search}`, publicOrigin)
          .toString();
      }
      return `${parsed.pathname}${parsed.search}`;
    }
  } catch {
    // Preserve unusual URLs from VIOS; the existing client normalizer can handle them.
  }
  return value;
}

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed." });
  }

  const sensorId = single(req.query.sensorId);
  const startTime = single(req.query.startTime);
  const endTime = single(req.query.endTime);
  const configuration = single(req.query.configuration);
  const start = Date.parse(startTime);
  const end = Date.parse(endTime);
  if (
    !SENSOR_PATTERN.test(sensorId) ||
    !validTimestamp(startTime) ||
    !validTimestamp(endTime) ||
    end <= start ||
    end - start > 600_000
  ) {
    return res
      .status(422)
      .json({ error: "A valid source and evidence time range are required." });
  }

  const params = new URLSearchParams({
    startTime,
    endTime,
    expiryMinutes: "60",
    container: "mp4",
    disableAudio: "true",
    transcode: "full",
  });
  if (configuration) params.set("configuration", configuration);

  try {
    const timelineResponse = await fetch(
      `${VST_API_URL}/v1/storage/${encodeURIComponent(sensorId)}/timelines`,
      { signal: AbortSignal.timeout(10_000) }
    );
    if (timelineResponse.ok) {
      const timelines = (await timelineResponse.json()) as RecordingTimeline[];
      if (
        Array.isArray(timelines) &&
        !recordingIsRetained(startTime, endTime, timelines)
      ) {
        return res.status(410).json({
          error: "The recording for this result is no longer retained.",
        });
      }
    }
  } catch {
    // A timeline lookup outage must not block evidence that VIOS can still serve.
  }

  try {
    const directResponse = await fetch(
      `${VST_API_URL}/v1/storage/file/${encodeURIComponent(
        sensorId
      )}/url?${params.toString()}`,
      { signal: AbortSignal.timeout(45_000) }
    );
    if (directResponse.ok) {
      const direct = (await directResponse.json()) as {
        startTime?: string;
        videoUrl?: string;
      };
      if (direct.videoUrl) {
        return res.status(200).json({
          startTime: direct.startTime || startTime,
          videoUrl: browserSafeMediaUrl(direct.videoUrl),
        });
      }
    }
  } catch {
    // Duplicate or discontinuous RTSP timestamps can make VIOS's MP4 muxer fail.
    // The local fallback below regenerates timestamps from the retained MKV media.
  }

  try {
    const fallbackResponse = await fetch(`${EVIDENCE_CLIP_API_URL}/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sensorId, startTime, endTime }),
      signal: AbortSignal.timeout(320_000),
    });
    const fallback = (await fallbackResponse.json()) as {
      error?: string;
      key?: string;
      startTime?: string;
    };
    if (!fallbackResponse.ok || !fallback.key) {
      throw new Error(
        fallback.error || `Fallback returned ${fallbackResponse.status}.`
      );
    }
    return res.status(200).json({
      startTime: fallback.startTime || startTime,
      videoUrl: `/api/vision/evidence-media?key=${encodeURIComponent(
        fallback.key
      )}`,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Evidence clip is unavailable.";
    return res.status(502).json({ error: message });
  }
}
