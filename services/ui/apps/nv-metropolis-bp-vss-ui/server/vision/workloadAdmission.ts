// SPDX-License-Identifier: MIT

/**
 * The sole policy interface for admitting an expensive local visual workload.
 * It evaluates observations supplied by an adapter and has no I/O or side
 * effects, so callers cannot accidentally turn an admission check into a
 * workload transition.
 */
export const WORKLOAD_CLASSES = [
  "current_visual_question",
  "evidence_analysis",
  "live_vlm_alert",
  "long_video_history_build",
  "calibration",
  "experimental_audio",
] as const;

export type WorkloadClass = (typeof WORKLOAD_CLASSES)[number];
export type WorkloadDecision = "allow" | "queue" | "block";
export type AdmissionReasonCode =
  | "ALLOW"
  | "CALIBRATION_NOT_QUALIFIED"
  | "EXPERIMENTAL_AUDIO_NOT_QUALIFIED"
  | "VLM_UNAVAILABLE"
  | "VLM_STATUS_UNKNOWN"
  | "LIVE_ALERT_RESERVATION_ACTIVE"
  | "LIVE_ALERT_RESERVATION_UNKNOWN"
  | "LOCAL_COSMOS_RESERVATION_ACTIVE"
  | "LIVE_CAPTION_LANE_ACTIVE"
  | "LIVE_CAPTION_LANE_UNKNOWN"
  | "TELEMETRY_REQUIRED"
  | "GPU_BUSY";

export interface WorkloadAdmissionFacts {
  captions: {
    sourceIds: string[];
    state: "known" | "unknown";
  };
  localCosmosReservation: {
    active: boolean;
    waitingCount: number;
  };
  liveAlertReservations: {
    rules: Array<{ ruleId: string; sourceId: string }>;
    state: "known" | "unknown";
  };
  qualifications: {
    calibration: boolean;
    experimentalAudio: boolean;
  };
  telemetry: {
    gpuUtilizationPercent: number | null;
    state: "fresh" | "stale" | "unknown";
  };
  vlm: "ready" | "unavailable" | "unknown";
}

export interface WorkloadAdmission {
  active: Pick<
    WorkloadAdmissionFacts,
    "captions" | "liveAlertReservations" | "localCosmosReservation"
  >;
  decision: WorkloadDecision;
  explanation: string;
  reasonCode: AdmissionReasonCode;
  requiredAction: string | null;
  risk: {
    class: "interactive" | "continuous" | "very-heavy" | "experimental";
    requiresExclusiveVisualLane: boolean;
    telemetry: WorkloadAdmissionFacts["telemetry"]["state"];
  };
  workload: WorkloadClass;
}

export type WorkloadAdmissions = Record<WorkloadClass, WorkloadAdmission>;

interface WorkloadSpec {
  requiresQualification?: "calibration" | "experimentalAudio";
  requiresVlm: boolean;
  riskClass: WorkloadAdmission["risk"]["class"];
}

const SPECS: Record<WorkloadClass, WorkloadSpec> = {
  calibration: {
    requiresQualification: "calibration",
    requiresVlm: false,
    riskClass: "very-heavy",
  },
  current_visual_question: { requiresVlm: true, riskClass: "interactive" },
  evidence_analysis: { requiresVlm: true, riskClass: "interactive" },
  experimental_audio: {
    requiresQualification: "experimentalAudio",
    requiresVlm: true,
    riskClass: "experimental",
  },
  live_vlm_alert: { requiresVlm: true, riskClass: "continuous" },
  long_video_history_build: { requiresVlm: true, riskClass: "very-heavy" },
};

export function isWorkloadClass(value: unknown): value is WorkloadClass {
  return typeof value === "string" &&
    (WORKLOAD_CLASSES as readonly string[]).includes(value);
}

function result(
  workload: WorkloadClass,
  facts: WorkloadAdmissionFacts,
  decision: WorkloadDecision,
  reasonCode: AdmissionReasonCode,
  explanation: string,
  requiredAction: string | null
): WorkloadAdmission {
  const spec = SPECS[workload];
  return {
    active: {
      captions: facts.captions,
      liveAlertReservations: facts.liveAlertReservations,
      localCosmosReservation: facts.localCosmosReservation,
    },
    decision,
    explanation,
    reasonCode,
    requiredAction,
    risk: {
      class: spec.riskClass,
      requiresExclusiveVisualLane: true,
      telemetry: facts.telemetry.state,
    },
    workload,
  };
}

/**
 * Evaluates the current observation without reserving, starting, stopping, or
 * estimating a workload. A queued decision is not permission to pre-empt an
 * existing lane owner.
 */
export function evaluateWorkloadAdmission(
  workload: WorkloadClass,
  facts: WorkloadAdmissionFacts
): WorkloadAdmission {
  const spec = SPECS[workload];
  const isVeryHeavy =
    spec.riskClass === "very-heavy" || spec.riskClass === "experimental";

  if (
    spec.requiresQualification === "calibration" &&
    !facts.qualifications.calibration
  ) {
    return result(
      workload,
      facts,
      "block",
      "CALIBRATION_NOT_QUALIFIED",
      "Calibration remains disabled until this Thor has an explicit workload-admission qualification.",
      "Set THOR_WORKLOAD_ADMISSION_CALIBRATION_QUALIFIED=true only after the calibration workflow has been qualified."
    );
  }

  if (
    spec.requiresQualification === "experimentalAudio" &&
    !facts.qualifications.experimentalAudio
  ) {
    return result(
      workload,
      facts,
      "block",
      "EXPERIMENTAL_AUDIO_NOT_QUALIFIED",
      "Experimental audio remains disabled until this Thor has an explicit workload-admission qualification.",
      "Set THOR_WORKLOAD_ADMISSION_EXPERIMENTAL_AUDIO_QUALIFIED=true only after the audio path has been qualified."
    );
  }

  if (isVeryHeavy && facts.telemetry.state !== "fresh") {
    return result(
      workload,
      facts,
      "block",
      "TELEMETRY_REQUIRED",
      "A fresh Thor telemetry sample is required before this very-heavy workload can be considered.",
      "Restore a fresh tegrastats sample and evaluate admission again."
    );
  }

  if (spec.requiresVlm && facts.vlm === "unavailable") {
    return result(
      workload,
      facts,
      "block",
      "VLM_UNAVAILABLE",
      "The local Cosmos visual-reasoning service is not ready.",
      "Restore local visual-reasoning readiness before requesting this workload."
    );
  }

  if (spec.requiresVlm && facts.vlm === "unknown") {
    return result(
      workload,
      facts,
      "block",
      "VLM_STATUS_UNKNOWN",
      "Cosmos readiness could not be observed, so admission cannot safely claim capacity.",
      "Restore the local readiness probe and evaluate admission again."
    );
  }

  if (facts.liveAlertReservations.state === "unknown") {
    return result(
      workload,
      facts,
      isVeryHeavy ? "block" : "queue",
      "LIVE_ALERT_RESERVATION_UNKNOWN",
      "Local live-alert reservation state could not be read.",
      "Restore access to the local reservation store and evaluate admission again."
    );
  }

  if (facts.liveAlertReservations.rules.length) {
    return result(
      workload,
      facts,
      "block",
      "LIVE_ALERT_RESERVATION_ACTIVE",
      "A continuous live VLM alert currently owns the exclusive Cosmos lane.",
      "Remove the active live alert rule before requesting another visual workload."
    );
  }

  if (facts.localCosmosReservation.active) {
    return result(
      workload,
      facts,
      "queue",
      "LOCAL_COSMOS_RESERVATION_ACTIVE",
      "Another request is already holding or waiting for this UI process's Cosmos reservation.",
      "Wait for the existing reservation to finish, then evaluate admission again."
    );
  }

  if (facts.captions.state === "unknown") {
    return result(
      workload,
      facts,
      isVeryHeavy ? "block" : "queue",
      "LIVE_CAPTION_LANE_UNKNOWN",
      "Continuous-caption lane state could not be observed.",
      "Restore the local stream-state probe and evaluate admission again."
    );
  }

  if (facts.captions.sourceIds.length) {
    return result(
      workload,
      facts,
      "queue",
      "LIVE_CAPTION_LANE_ACTIVE",
      "Continuous captioning is using the Cosmos lane.",
      "Wait for caption ownership to be yielded by its orchestrator before starting this workload."
    );
  }

  if (
    facts.telemetry.gpuUtilizationPercent !== null &&
    facts.telemetry.gpuUtilizationPercent >= 85
  ) {
    return result(
      workload,
      facts,
      isVeryHeavy ? "block" : "queue",
      "GPU_BUSY",
      "The latest Thor telemetry sample reports a busy GPU.",
      "Wait for GPU utilization to fall and evaluate admission again."
    );
  }

  return result(
    workload,
    facts,
    "allow",
    "ALLOW",
    "No active exclusive visual lane or conservative admission gate blocks this workload.",
    null
  );
}

/**
 * Evaluates every supported class against one observation snapshot. Adapters
 * should call this instead of probing Thor once per row in a status surface.
 */
export function evaluateAllWorkloadAdmissions(
  facts: WorkloadAdmissionFacts
): WorkloadAdmissions {
  return Object.fromEntries(
    WORKLOAD_CLASSES.map((workload) => [
      workload,
      evaluateWorkloadAdmission(workload, facts),
    ])
  ) as WorkloadAdmissions;
}
