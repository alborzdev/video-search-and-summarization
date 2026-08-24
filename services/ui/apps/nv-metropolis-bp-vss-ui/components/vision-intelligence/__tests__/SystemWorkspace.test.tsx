// SPDX-License-Identifier: MIT

import { render, screen } from "@testing-library/react";
import React from "react";

import { SystemWorkspace } from "../SystemWorkspace";

describe("SystemWorkspace", () => {
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
