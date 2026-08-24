// SPDX-License-Identifier: MIT

import { ActivityInsightsWorkspace } from "../ActivityInsightsWorkspace";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

const warehouseIncident = {
  Id: "incident-1",
  timestamp: "2025-01-01T00:03:07.600Z",
  end: "2025-01-01T00:03:09.633Z",
  sensorId: "nvidia-warehouse-loading-dock-camera-01-4min",
  objectIds: ["39"],
  info: {
    verdict: "confirmed",
    reasoning: "A person is visible in the monitored area.",
    snapshotUrls:
      '["http://localhost:30888/vst/storage/temp_files/evidence.jpg"]',
    videoSource: "http://localhost:30888/vst/storage/temp_files/expired.mp4",
  },
};

describe("ActivityInsightsWorkspace", () => {
  afterEach(() => jest.restoreAllMocks());

  it("regenerates incident clips from retained source footage instead of trusting expired temporary URLs", async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/vision/incidents") {
        return {
          ok: true,
          json: async () => ({ incidents: [warehouseIncident] }),
        } as Response;
      }
      if (url === "/api/vision/investigations") {
        return {
          ok: true,
          json: async () => ({ investigations: [] }),
        } as Response;
      }
      if (url.endsWith("/v1/live/streams")) {
        return {
          ok: true,
          json: async () => [
            {
              warehouse: [
                {
                  name: warehouseIncident.sensorId,
                  streamId: "warehouse-stream-id",
                },
              ],
            },
          ],
        } as Response;
      }
      if (
        url.includes("/api/vision/evidence?") &&
        url.includes("sensorId=warehouse-stream-id")
      ) {
        return {
          ok: true,
          json: async () => ({
            videoUrl:
              "http://thor.test/vst/storage/temp_files/fresh-evidence.mp4",
          }),
        } as Response;
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }) as jest.Mock;

    render(
      <ActivityInsightsWorkspace
        initialMode="activity"
        onModeChange={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Open evidence" })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Incident evidence",
    });
    await waitFor(() =>
      expect(dialog.querySelector("video")).toHaveAttribute(
        "src",
        "http://thor.test/vst/storage/temp_files/fresh-evidence.mp4"
      )
    );

    const clipRequest = (global.fetch as jest.Mock).mock.calls.find(
      ([input]) =>
        String(input).includes("/api/vision/evidence?") &&
        String(input).includes("sensorId=warehouse-stream-id")
    );
    expect(String(clipRequest?.[0])).toContain(
      "startTime=2025-01-01T00%3A03%3A07.600Z"
    );
    expect(String(clipRequest?.[0])).toContain(
      "endTime=2025-01-01T00%3A03%3A09.633Z"
    );
  });

  it("hides stale training diagnostics from the operator activity view", async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) =>
      String(input) === "/api/vision/investigations"
        ? ({
            ok: true,
            json: async () => ({ investigations: [] }),
          } as Response)
        : ({
            ok: true,
            json: async () => ({
              incidents: [
                warehouseIncident,
                {
                  ...warehouseIncident,
                  Id: "training-probe",
                  sensorId: "Training Room",
                },
                {
                  Id: "empty-confirmed-record",
                  timestamp: "2025-01-01T00:05:00Z",
                  sensorId: "raw-camera-uuid",
                  info: { verdict: "confirmed", verificationResponseStatus: "success" },
                },
                {
                  ...warehouseIncident,
                  Id: "dismissed-candidate",
                  timestamp: "2025-01-01T00:06:00Z",
                  end: "2025-01-01T00:06:02Z",
                  info: { ...warehouseIncident.info, verdict: "rejected" },
                },
              ],
            }),
          } as Response)
    ) as jest.Mock;

    render(
      <ActivityInsightsWorkspace
        initialMode="activity"
        onModeChange={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await screen.findByText("1 incident");
    expect(screen.queryByText("Training Room")).not.toBeInTheDocument();
    expect(screen.queryByText("raw-camera-uuid")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Activity filter"), {
      target: { value: "all" },
    });
    expect(await screen.findByText("4 incidents")).toBeInTheDocument();
  });

  it("keeps operator-created investigations discoverable after leaving search", async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) =>
      String(input) === "/api/vision/investigations"
        ? ({
            ok: true,
            json: async () => ({
              investigations: [
                {
                  created_at: "2026-08-12T13:00:00Z",
                  disposition: "under_review",
                  evidence: [{ client_id: "clip-1" }],
                  id: "11111111-1111-4111-8111-111111111111",
                  report_url:
                    "/api/vision/investigations?id=11111111-1111-4111-8111-111111111111&format=html",
                  severity: "high",
                  title: "Warehouse restricted-zone review",
                },
              ],
            }),
          } as Response)
        : ({
            ok: true,
            json: async () => ({ incidents: [warehouseIncident] }),
          } as Response)
    ) as jest.Mock;

    render(
      <ActivityInsightsWorkspace
        initialMode="activity"
        onModeChange={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    expect(
      await screen.findByRole("region", { name: "Saved investigations" })
    ).toHaveTextContent("Warehouse restricted-zone review");
    expect(screen.getByRole("link", { name: "Open report" })).toHaveAttribute(
      "href",
      "/api/vision/investigations?id=11111111-1111-4111-8111-111111111111&format=html"
    );
  });
});
