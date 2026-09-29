// SPDX-License-Identifier: MIT

import { render, screen, within } from "@testing-library/react";
import React from "react";

import { SystemWorkspace } from "../SystemWorkspace";

describe("SystemWorkspace", () => {
  it("shows file spans without synthetic calendar dates and keeps live timestamps", () => {
    const base = {
      indexStatus: "indexed" as const,
      lastSemanticAt: "2025-01-01T00:00:05.000Z",
      recordingStatus: "retained" as const,
      remediation: "Recorded evidence is available.",
      semanticSegments: 2,
      timelineStart: "2025-01-01T00:00:00.000Z",
      timelineEnd: "2025-01-01T00:00:10.000Z",
    };
    render(<SystemWorkspace
      health={null} panel="overview" onPanelChange={jest.fn()} onRefreshHealth={jest.fn()}
      rules={null} sources={null} searchCoverageUnavailable={false}
      workloadAdmissions={null} workloadCheckedAt={null}
      searchCoverage={{
        generatedAt: "2026-09-29T00:00:00Z",
        sources: [
          { ...base, sensorId: "file", name: "conveyor-box-movement-demo", sourceKind: "recording" },
          { ...base, sensorId: "live", name: "Live feed", sourceKind: "live" },
          { ...base, sensorId: "missing", name: "File with no timeline", sourceKind: "recording", timelineStart: null },
        ],
        summary: { configuredSources: 3, indexedSources: 3, retainedSources: 3, expiredIndexedSources: 0, unknownIndexSources: 0, unavailableRecordingSources: 0 },
      }}
    />);
    const file = screen.getByText("Conveyor — Box Movement").closest("article")!;
    expect(file).toHaveTextContent("Recorded file · retained recording window spans 0:10");
    expect(file).not.toHaveTextContent(/latest indexed|retained through|2025|2024/);
    const live = screen.getByText("Live Feed").closest("article")!;
    expect(within(live).getByText(/latest indexed/)).toHaveTextContent("retained through");
    const missing = screen.getByText("File With No Timeline").closest("article")!;
    expect(missing).toHaveTextContent("Recorded file");
    expect(missing).not.toHaveTextContent(/window spans|retained through|NaN/);
  });

  it("shows search, retention, and remediation facts without estimating coverage", () => {
    render(
      <SystemWorkspace
        health={null}
        onPanelChange={jest.fn()}
        onRefreshHealth={jest.fn()}
        panel="overview"
        rules={null}
        searchCoverage={{
          generatedAt: "2026-08-23T12:00:00.000Z",
          sources: [
            {
              indexStatus: "indexed",
              lastSemanticAt: "2026-08-23T11:59:00.000Z",
              name: "Main Camera",
              recordingStatus: "expired",
              remediation:
                "Indexed moments remain searchable, but their recording is no longer retained for playback.",
              semanticSegments: 12,
              sensorId: "camera-1",
              timelineEnd: null,
              timelineStart: null,
            },
          ],
          summary: {
            configuredSources: 1,
            expiredIndexedSources: 1,
            indexedSources: 1,
            retainedSources: 0,
            unavailableRecordingSources: 0,
            unknownIndexSources: 0,
          },
        }}
        searchCoverageUnavailable={false}
        sources={null}
        workloadAdmissions={null}
        workloadCheckedAt={null}
      />
    );

    expect(
      screen.getByRole("heading", { name: "What remains usable as evidence" })
    ).toBeInTheDocument();
    expect(screen.getByText("Main Camera")).toBeInTheDocument();
    expect(screen.getByText("Searchable")).toBeInTheDocument();
    expect(screen.getByText("Media expired")).toBeInTheDocument();
    expect(
      screen.getByText(/recording is no longer retained for playback/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/source counts, not an estimated coverage percentage/i)).toBeInTheDocument();
  });
});
