// SPDX-License-Identifier: MIT

import {
  evaluateAllWorkloadAdmissions,
  evaluateWorkloadAdmission,
  WORKLOAD_CLASSES,
  type WorkloadAdmissionFacts,
} from "../../../server/vision/workloadAdmission";

function facts(
  overrides: Partial<WorkloadAdmissionFacts> = {}
): WorkloadAdmissionFacts {
  return {
    captions: { sourceIds: [], state: "known" },
    liveAlertReservations: { rules: [], state: "known" },
    localCosmosReservation: { active: false, waitingCount: 0 },
    qualifications: { calibration: false, experimentalAudio: false },
    telemetry: { gpuUtilizationPercent: 24, state: "fresh" },
    vlm: "ready",
    ...overrides,
  };
}

describe("workload admission", () => {
  it("evaluates every class from one shared observation snapshot", () => {
    const admissions = evaluateAllWorkloadAdmissions(facts());

    expect(Object.keys(admissions)).toEqual(WORKLOAD_CLASSES);
    expect(admissions.current_visual_question.decision).toBe("allow");
    expect(admissions.calibration.reasonCode).toBe(
      "CALIBRATION_NOT_QUALIFIED"
    );
    expect(admissions.experimental_audio.reasonCode).toBe(
      "EXPERIMENTAL_AUDIO_NOT_QUALIFIED"
    );
  });

  it("allows an interactive current visual question with an idle, observed lane", () => {
    const admission = evaluateWorkloadAdmission(
      "current_visual_question",
      facts()
    );

    expect(admission).toMatchObject({
      decision: "allow",
      reasonCode: "ALLOW",
      requiredAction: null,
      risk: {
        class: "interactive",
        requiresExclusiveVisualLane: true,
        telemetry: "fresh",
      },
    });
    expect(admission.active).toEqual(
      expect.objectContaining({
        captions: { sourceIds: [], state: "known" },
        localCosmosReservation: { active: false, waitingCount: 0 },
      })
    );
  });

  it("queues a visual question behind active continuous captioning", () => {
    const admission = evaluateWorkloadAdmission(
      "current_visual_question",
      facts({ captions: { sourceIds: ["camera-a"], state: "known" } })
    );

    expect(admission).toMatchObject({
      decision: "queue",
      reasonCode: "LIVE_CAPTION_LANE_ACTIVE",
      requiredAction: expect.stringContaining("caption ownership"),
    });
    expect(admission.active.captions.sourceIds).toEqual(["camera-a"]);
  });

  it("blocks every competing class when a live alert reservation owns Cosmos", () => {
    const admission = evaluateWorkloadAdmission(
      "evidence_analysis",
      facts({
        liveAlertReservations: {
          rules: [{ ruleId: "rule-1", sourceId: "camera-a" }],
          state: "known",
        },
      })
    );

    expect(admission).toMatchObject({
      decision: "block",
      reasonCode: "LIVE_ALERT_RESERVATION_ACTIVE",
      requiredAction: expect.stringContaining("Remove the active live alert rule"),
    });
  });

  it.each([
    ["calibration", "CALIBRATION_NOT_QUALIFIED"],
    ["experimental_audio", "EXPERIMENTAL_AUDIO_NOT_QUALIFIED"],
  ] as const)("keeps %s blocked until explicitly qualified", (workload, reasonCode) => {
    const admission = evaluateWorkloadAdmission(workload, facts());

    expect(admission).toMatchObject({
      decision: "block",
      reasonCode,
      risk: { class: workload === "calibration" ? "very-heavy" : "experimental" },
    });
    expect(admission.requiredAction).toContain("THOR_WORKLOAD_ADMISSION");
  });

  it("fails safe for a very-heavy history build without fresh telemetry", () => {
    const admission = evaluateWorkloadAdmission(
      "long_video_history_build",
      facts({ telemetry: { gpuUtilizationPercent: null, state: "unknown" } })
    );

    expect(admission).toMatchObject({
      decision: "block",
      reasonCode: "TELEMETRY_REQUIRED",
      risk: { telemetry: "unknown" },
    });
    expect(JSON.stringify(admission)).not.toContain("memory");
  });

  it("does not require telemetry for a bounded live alert, but still requires VLM readiness", () => {
    const admission = evaluateWorkloadAdmission(
      "live_vlm_alert",
      facts({
        telemetry: { gpuUtilizationPercent: null, state: "unknown" },
        vlm: "unavailable",
      })
    );

    expect(admission).toMatchObject({
      decision: "block",
      reasonCode: "VLM_UNAVAILABLE",
      risk: { class: "continuous", telemetry: "unknown" },
    });
  });
});
