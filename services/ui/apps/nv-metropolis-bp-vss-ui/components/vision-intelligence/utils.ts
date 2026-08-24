// SPDX-License-Identifier: MIT
import type { VisionStream, VisionStreamsApiResponse } from "./types";

export function parseVisionStreams(
  data: VisionStreamsApiResponse
): VisionStream[] {
  return data.flatMap((sensor) =>
    Object.entries(sensor).flatMap(([sensorId, streams]) =>
      streams.map((stream) => ({ ...stream, sensorId }))
    )
  );
}

export function isLiveStream(stream: VisionStream): boolean {
  return [stream.url, stream.vodUrl].some((value) =>
    (value ?? "").toLowerCase().startsWith("rtsp://")
  );
}

export function streamDisplayName(name: string): string {
  const normalized = name.toLowerCase().replace(/\.[a-z0-9]+$/i, "");
  if (normalized === "sample-sim-traffic") return "Traffic — Main Intersection";
  if (normalized === "sample-sim-jaywalking") return "Traffic — Pedestrian Crossing";
  if (normalized.includes("nvidia-warehouse-loading-dock")) return "Warehouse — Loading Dock";
  if (normalized === "pit-pov") return "Motorsport — Driver POV";

  const readable = name
    .replace(/\.[a-z0-9]+$/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .replace(/\bPov\b/g, "POV")
    .replace(/\bRtsp\b/g, "RTSP")
    .trim();

  return readable || "Unnamed camera";
}

export function sourceKind(stream: VisionStream): "Live" | "Replay" {
  return isLiveStream(stream) ? "Live" : "Replay";
}

export function createLiveWebSocketUrl(
  vstApiUrl: string,
  streamId: string,
  peerId: string
): string {
  const url = new URL(vstApiUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/v1/live/ws`;
  url.search = "";
  url.searchParams.set("connectionId", peerId);
  url.searchParams.set("streamId", streamId);
  return url.toString();
}

export function createPeerId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `vision-stream-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function proxyVstPictureUrl(url: string): string {
  try {
    const isAbsolute = /^https?:\/\//i.test(url);
    if (!isAbsolute) return url;
    const target = new URL(url);
    // Even when VST shares the browser origin through the LAN ingress, route
    // snapshots through the app proxy. The proxy converts transient VST 5xx
    // responses into a stable image placeholder; bypassing it makes an
    // otherwise healthy WebRTC stream emit false console errors.
    return `/api/vision/vst-image?path=${encodeURIComponent(
      `${target.pathname}${target.search}`
    )}`;
  } catch {
    return url;
  }
}
