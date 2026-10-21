// SPDX-License-Identifier: MIT

export interface VisionServiceHealth {
  key: string;
  label: string;
  latencyMs: number | null;
  ok: boolean;
  selected?: boolean;
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
  hardwareProfile?: string;
  demoProfile?: "clips" | "all" | null;
  videoEfficiency?: {
    sourceVersion: string | null;
    runtimeVersion: string | null;
    adaptiveEvsConfigured: boolean | null;
    adaptiveEvsCompatible: boolean | null;
  };
  sparkCapacity?: {
    state: "fresh" | "unknown";
    guardActive: boolean;
    availableGiB: number | null;
    reserveGiB: number | null;
  } | null;
}

const DEMO_SERVICE_DEPENDENCIES = [
  { label: "Play video", keys: ["video"] },
  { label: "Search recorded video", keys: ["video", "agent", "embedding"] },
  { label: "Ask about a video clip", keys: ["video", "agent", "vlm", "llm"] },
  { label: "Detect & track objects", keys: ["video", "perception"] },
];

// These are service probes, not a claim that a source is ingesting or qualified.
export function demoServiceChecks(health: SystemHealth) {
  return DEMO_SERVICE_DEPENDENCIES.map(({ label, keys }) => {
    const checks = keys.map((key) => health.services.find((service) => service.key === key));
    const status = checks.some((service) => service?.selected === false)
      ? "not-selected"
      : checks.some((service) => service?.ok === false)
      ? "unavailable"
      : checks.every((service) => service?.ok === true)
      ? "available"
      : "unknown";
    return { label, status };
  });
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
