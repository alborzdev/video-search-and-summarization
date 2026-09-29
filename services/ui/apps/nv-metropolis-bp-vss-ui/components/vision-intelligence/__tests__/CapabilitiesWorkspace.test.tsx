// SPDX-License-Identifier: MIT

import { CapabilitiesWorkspace } from "../CapabilitiesWorkspace";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { evaluateAllWorkloadAdmissions } from "../../../server/vision/workloadAdmission";

const healthyServices = {
  checkedAt: new Date().toISOString(), status: "online" as const,
  services: ["agent", "embedding", "video", "vlm", "llm", "analytics"].map(key => ({key, label:key, ok:true, latencyMs:1})),
};
const admissions = evaluateAllWorkloadAdmissions({
  captions: { state: "known", sourceIds: [] },
  localCosmosReservation: { active: false, waitingCount: 0 },
  liveAlertReservations: { state: "known", rules: [] },
  qualifications: { calibration: false, experimentalAudio: false },
  telemetry: { state: "unknown", gpuUtilizationPercent: null },
  vlm: "ready",
});

const callbacks = { onExplore: jest.fn(), onOpenEvents: jest.fn(), onOpenLive: jest.fn(), onOpenRules: jest.fn() };

describe("CapabilitiesWorkspace", () => {
  it("shows history admission refusal even when all model services are healthy", () => {
    render(<CapabilitiesWorkspace {...callbacks} systemHealth={healthyServices} admissions={admissions} />);
    fireEvent.click(screen.getByRole("button", { name: /Review activity over time/ }));
    expect(screen.getByRole("status")).toHaveTextContent("fresh Thor telemetry");
    expect(screen.getByRole("button", { name: /Review activity over time/ })).toHaveTextContent("Unavailable now");
    fireEvent.click(screen.getByRole("button", { name: /Watch camera activity/ }));
    expect(screen.getByRole("status")).toHaveTextContent("whether analysis is running");
  });

  it("requires retained and indexed evidence on the same source", () => {
    const source = { lastSemanticAt: null, name: "Warehouse", remediation: "", semanticSegments: 2, sensorId: "a", timelineEnd: null, timelineStart: null };
    const coverage = {
      generatedAt: new Date().toISOString(),
      summary: {configuredSources:2, expiredIndexedSources:1, indexedSources:1, retainedSources:1, unknownIndexSources:0, unavailableRecordingSources:0},
      sources: [
        {...source, indexStatus: "indexed" as const, recordingStatus: "expired" as const},
        {...source, sensorId:"b", indexStatus: "not-indexed" as const, recordingStatus: "retained" as const},
      ],
    };
    const view = render(<CapabilitiesWorkspace {...callbacks} systemHealth={healthyServices} admissions={admissions} searchCoverage={coverage} />);
    expect(screen.getByRole("button", { name: /Find a moment/ })).toHaveTextContent("Footage needed");
    expect(screen.getByRole("button", { name: /Ask about a clip/ })).toHaveTextContent("Footage needed");
    const usable = {...coverage, sources:[{...coverage.sources[0], recordingStatus: "retained" as const}]};
    view.rerender(<CapabilitiesWorkspace {...callbacks} systemHealth={healthyServices} admissions={admissions} searchCoverage={usable} />);
    expect(screen.getByRole("button", { name: /Find a moment/ })).toHaveTextContent("Evidence available");
    expect(screen.getByRole("button", { name: /Ask about a clip/ })).toHaveTextContent("Evidence available");
    view.rerender(<CapabilitiesWorkspace {...callbacks} systemHealth={healthyServices} admissions={admissions} searchCoverage={{...usable, generatedAt:"2020-01-01T00:00:00Z"}} />);
    expect(screen.getByRole("button", { name: /Find a moment/ })).toHaveTextContent("Checking evidence");
    expect(screen.getByRole("button", { name: /Ask about a clip/ })).toHaveTextContent("Checking evidence");
  });
  it("does not equate healthy services with a ready end-to-end demo", () => {
    render(<CapabilitiesWorkspace
      onExplore={jest.fn()} onOpenEvents={jest.fn()} onOpenLive={jest.fn()} onOpenRules={jest.fn()}
      systemHealth={{checkedAt: new Date().toISOString(), status: "online", services:
        ["agent", "embedding", "video", "vlm", "llm", "analytics"].map(key => ({key, label:key, ok:true, latencyMs:1}))}}
    />);
    expect(screen.queryAllByText("Ready on this Thor")).toHaveLength(0);
  });
  it("launches each guided demo at the product surface it promises", () => {
    const onExplore = jest.fn();
    const onOpenEvents = jest.fn();
    const onOpenLive = jest.fn();
    const onOpenRules = jest.fn();

    render(
      <CapabilitiesWorkspace
        onExplore={onExplore}
        onOpenEvents={onOpenEvents}
        onOpenLive={onOpenLive}
        onOpenRules={onOpenRules}
        systemHealth={null}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Search existing footage" })
    );
    expect(onExplore).toHaveBeenCalledWith(
      "person carrying a box"
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Ask about a clip/ })
    );
    fireEvent.click(screen.getByRole("button", { name: "Find a clip to ask about" }));
    expect(onExplore).toHaveBeenLastCalledWith("person carrying a box");
    expect(onOpenLive).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: /Watch camera activity/ })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Check connected cameras" })
    );
    expect(onOpenLive).toHaveBeenCalledWith("grid");

    fireEvent.click(screen.getByRole("button", { name: /Review and share/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Choose footage to review" })
    );
    expect(onExplore).toHaveBeenCalledWith(
      "person carrying a box"
    );

    fireEvent.click(screen.getByRole("button", { name: /Review activity over time/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Check source history" })
    );
    expect(onOpenLive).toHaveBeenCalledWith("history");

    fireEvent.click(screen.getByRole("button", { name: /Flag activity for review/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Set up an alert rule" })
    );
    expect(onOpenRules).toHaveBeenCalledTimes(1);
    expect(onOpenEvents).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Review and share/ }));
    fireEvent.click(screen.getByRole("button", { name: "View saved reports" }));
    expect(onOpenEvents).toHaveBeenCalledTimes(1);
  });
});
