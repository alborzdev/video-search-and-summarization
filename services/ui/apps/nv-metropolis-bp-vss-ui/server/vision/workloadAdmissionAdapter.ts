// SPDX-License-Identifier: MIT

import {
  evaluateWorkloadAdmission,
  type WorkloadAdmission,
  type WorkloadAdmissionFacts,
  type WorkloadClass,
} from "./workloadAdmission";
import { readCosmosReservationState } from "./cosmosReservation";
import { readActiveLiveAlertReservations } from "./liveAlertReservation";

function rtviVlmUrl(): string {
  return (process.env.RTVI_VLM_URL || "http://127.0.0.1:8018").replace(/\/$/, "");
}

function metricValue(metrics: string, name: string): number | null {
  const line = metrics
    .split("\n")
    .find((candidate) => candidate.startsWith(`${name} `));
  const value = line ? Number(line.slice(name.length).trim()) : Number.NaN;
  return Number.isFinite(value) ? value : null;
}

async function readVlmReadiness(): Promise<WorkloadAdmissionFacts["vlm"]> {
  try {
    const response = await fetch(`${rtviVlmUrl()}/v1/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3_000),
    });
    return response.ok ? "ready" : "unavailable";
  } catch {
    return "unknown";
  }
}

async function readCaptionLane(): Promise<WorkloadAdmissionFacts["captions"]> {
  try {
    const response = await fetch(`${rtviVlmUrl()}/v1/stream/get-stream-info`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3_000),
    });
    if (!response.ok) return { sourceIds: [], state: "unknown" };
    const payload = (await response.json()) as {
      stream_list?: Array<{
        asset_id?: string;
        camera_id?: string;
        inference_active?: boolean;
      }>;
    };
    const sourceIds = (payload.stream_list || [])
      .filter((stream) => stream.inference_active)
      .map((stream) => stream.camera_id || stream.asset_id || "")
      .filter(Boolean);
    return { sourceIds, state: "known" };
  } catch {
    return { sourceIds: [], state: "unknown" };
  }
}

async function readTelemetry(): Promise<WorkloadAdmissionFacts["telemetry"]> {
  try {
    const response = await fetch(
      process.env.TEGRASTATS_METRICS_URL || "http://172.17.0.1:19101/metrics",
      { cache: "no-store", signal: AbortSignal.timeout(1_500) }
    );
    if (!response.ok) return { gpuUtilizationPercent: null, state: "unknown" };
    const metrics = await response.text();
    if (metricValue(metrics, "jetson_tegrastats_up") !== 1) {
      return { gpuUtilizationPercent: null, state: "unknown" };
    }
    const sampleAgeSeconds = metricValue(metrics, "jetson_tegrastats_sample_age_seconds");
    const gpuRatio = metricValue(metrics, "jetson_tegrastats_gpu_utilization_ratio");
    return {
      gpuUtilizationPercent: gpuRatio === null ? null : gpuRatio * 100,
      state: sampleAgeSeconds === null || gpuRatio === null
        ? "unknown"
        : sampleAgeSeconds <= 15 ? "fresh" : "stale",
    };
  } catch {
    return { gpuUtilizationPercent: null, state: "unknown" };
  }
}

/**
 * Observes the local workload state without acquiring, yielding, or starting
 * a visual lane. Keeping the probes here lets status routes and enforcement
 * share exactly the same conservative policy input.
 */
export async function readWorkloadAdmissionFacts(): Promise<WorkloadAdmissionFacts> {
  const [vlm, captions, telemetry, alertResult] = await Promise.all([
    readVlmReadiness(),
    readCaptionLane(),
    readTelemetry(),
    readActiveLiveAlertReservations()
      .then((reservations) => ({
        rules: reservations.map(({ reservation, ruleId }) => ({
          ruleId,
          sourceId: reservation.sourceId,
        })),
        state: "known" as const,
      }))
      .catch(() => ({ rules: [], state: "unknown" as const })),
  ]);
  return {
    captions,
    liveAlertReservations: alertResult,
    localCosmosReservation: readCosmosReservationState(),
    qualifications: {
      calibration: process.env.THOR_WORKLOAD_ADMISSION_CALIBRATION_QUALIFIED === "true",
      experimentalAudio:
        process.env.THOR_WORKLOAD_ADMISSION_EXPERIMENTAL_AUDIO_QUALIFIED === "true",
    },
    telemetry,
    vlm,
  };
}

function admissionStatus(admission: WorkloadAdmission): number {
  switch (admission.reasonCode) {
    case "LIVE_ALERT_RESERVATION_ACTIVE":
      return 409;
    case "CALIBRATION_NOT_QUALIFIED":
    case "EXPERIMENTAL_AUDIO_NOT_QUALIFIED":
      return 422;
    default:
      // Unavailable/unknown readiness and missing required telemetry are local
      // capacity failures, not invalid operator input.
      return 503;
  }
}

export class WorkloadAdmissionError extends Error {
  constructor(readonly admission: WorkloadAdmission) {
    super([
      admission.explanation,
      admission.requiredAction,
    ].filter(Boolean).join(" "));
  }

  get statusCode(): number {
    return admissionStatus(this.admission);
  }
}

export interface WorkloadAdmissionFailure {
  admission: Pick<
    WorkloadAdmission,
    "decision" | "reasonCode" | "requiredAction" | "workload"
  >;
  code: WorkloadAdmission["reasonCode"];
  error: string;
}

/**
 * Throws only for BLOCK. QUEUE remains deliberately non-fatal because the
 * calling flows already serialize or hand off the local Cosmos lane.
 */
export async function admitWorkload(
  workload: WorkloadClass
): Promise<WorkloadAdmission> {
  const admission = evaluateWorkloadAdmission(
    workload,
    await readWorkloadAdmissionFacts()
  );
  if (admission.decision === "block") throw new WorkloadAdmissionError(admission);
  return admission;
}

export function workloadAdmissionFailure(
  error: WorkloadAdmissionError
): WorkloadAdmissionFailure {
  const { admission } = error;
  return {
    admission: {
      decision: admission.decision,
      reasonCode: admission.reasonCode,
      requiredAction: admission.requiredAction,
      workload: admission.workload,
    },
    code: admission.reasonCode,
    error: error.message,
  };
}
