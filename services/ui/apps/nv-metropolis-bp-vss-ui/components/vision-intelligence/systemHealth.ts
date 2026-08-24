// SPDX-License-Identifier: MIT

export interface VisionServiceHealth {
  key: string;
  label: string;
  latencyMs: number | null;
  ok: boolean;
}

export interface ThorHealthMetrics {
  activeStreams: number | null;
  gpuTemperatureC: number | null;
  gpuUtilizationPercent: number | null;
  memoryTotalBytes: number | null;
  memoryUsedBytes: number | null;
  powerWatts: number | null;
  sampleAgeSeconds: number | null;
}

export interface SystemHealth {
  checkedAt: string;
  services: VisionServiceHealth[];
  status: "degraded" | "offline" | "online";
  thor?: ThorHealthMetrics | null;
}

export function formatMemory(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "Unavailable";
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function healthLabel(status: SystemHealth["status"]): string {
  if (status === "online") return "Healthy";
  if (status === "degraded") return "Needs attention";
  return "Offline";
}

