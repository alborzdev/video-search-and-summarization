// SPDX-License-Identifier: MIT

import { ActivityInsightsWorkspace, incidentRule } from "../ActivityInsightsWorkspace";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import type { MonitoringRule } from "../monitoringRules";

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
  it("does not attribute another rule's event to the only rule on the same source", () => {
    const rule = { id: "local-old", backendRuleId: "backend-old", sourceId: warehouseIncident.sensorId, sourceRuntimeName: warehouseIncident.sensorId, sourceName: "Warehouse", kind: "semantic" } as MonitoringRule;
    expect(incidentRule({ ...warehouseIncident, info: { ...warehouseIncident.info, alertRuleId: "backend-new" } }, [rule])).toBeNull();
    expect(incidentRule(warehouseIncident, [rule])).toBeNull();
    expect(incidentRule({ ...warehouseIncident, info: { ...warehouseIncident.info, alertRuleId: "backend-old" } }, [rule])).toBe(rule);
  });

  afterEach(() => jest.restoreAllMocks());

  it("explains missing insight evidence without presenting a zero confirmation rate", async () => {
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ incidents: [], investigations: [], rules: [], states: {} }) })) as jest.Mock;
    const onModeChange = jest.fn();
    const onOpenRules = jest.fn();
    render(<ActivityInsightsWorkspace initialMode="insights" onModeChange={onModeChange} onOpenRules={onOpenRules} />);
    await screen.findByText("No event evidence to summarize yet");
    expect(screen.queryByText("0% confirmed")).not.toBeInTheDocument();
    expect(screen.queryByText("Events over time")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check cameras" }));
    expect(onModeChange).toHaveBeenCalledWith("live");
    fireEvent.click(screen.getByRole("button", { name: "Review monitoring rules" }));
    expect(onOpenRules).toHaveBeenCalled();
  });

  it("separates model matches from review state and retains their footage path in insights", async () => {
    const match = { ...warehouseIncident, info: { verdict: "confirmed", alertCategory: "semantic", alertRuleId: "rule-1", triggerPhrase: "yes" } };
    global.fetch = jest.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () => String(input).includes("/incident-state")
        ? { states: { "incident-1": { state: "acknowledged" } } }
        : { incidents: [match], investigations: [], rules: [] },
    })) as jest.Mock;
    const { rerender } = render(<ActivityInsightsWorkspace initialMode="insights" onModeChange={jest.fn()} vstApiUrl="http://thor.test/vst/api" />);
    await screen.findByText("Event overview");
    expect(screen.getByText(/0 awaiting review; 1 direct model match/)).toBeInTheDocument();
    expect(screen.queryByText(/100% confirmed/)).not.toBeInTheDocument();
    expect(screen.getByText("Model outcomes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find footage" })).toBeEnabled();
    expect(screen.getByText("acknowledged")).toBeInTheDocument();
    rerender(<ActivityInsightsWorkspace initialMode="activity" onModeChange={jest.fn()} vstApiUrl="http://thor.test/vst/api" />);
    fireEvent.change(screen.getByLabelText("Activity filter"), { target: { value: "model_match" } });
    expect(screen.getByRole("button", { name: "Find footage" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Activity filter"), { target: { value: "confirmed" } });
    expect(screen.queryByRole("button", { name: "Find footage" })).not.toBeInTheDocument();
  });

  it.each([true, false])("retrieves source footage when attached media exists: %s", async (attachedMedia) => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/vision/incidents") {
        return {
          ok: true,
          json: async () => ({ incidents: [{ ...warehouseIncident, info: attachedMedia ? warehouseIncident.info : { verdict: "confirmed", alertCategory: "semantic", alertRuleId: "rule-1", triggerPhrase: "yes", prompt: "Original condition preserved" } }] }),
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
      await screen.findByRole("button", { name: attachedMedia ? "Open evidence" : "Find footage" })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Incident evidence",
    });
    if (!attachedMedia) {
      expect(dialog).toHaveTextContent("Model match");
      expect(dialog).toHaveTextContent("Original condition preserved");
      expect(dialog).toHaveTextContent("Rule record unavailable");
    }
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

  it("reveals older saved reports beyond the initial four", async () => {
    const records = Array.from({ length: 6 }, (_, index) => ({ id: `saved-${index}`, title: `Saved briefing ${index}`, created_at: "2026-09-28T10:00:00Z", severity: "low", disposition: "resolved", evidence: [], report_url: `/reports/${index}` }));
    global.fetch = jest.fn(async (input: RequestInfo | URL) => ({ ok: true, json: async () => String(input).includes("/investigations") ? { investigations: records } : { incidents: [], rules: [], states: {} } })) as jest.Mock;
    render(<ActivityInsightsWorkspace initialMode="activity" onModeChange={jest.fn()} onOpenRules={jest.fn()} />);
    await screen.findByText("Saved briefing 0");
    expect(screen.queryByText("Saved briefing 5")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show older reports" }));
    expect(screen.getByText("Saved briefing 5")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open report" })).toHaveLength(6);
    expect(screen.queryByRole("button", { name: "Show older reports" })).not.toBeInTheDocument();
  });

  it.each([true, false])("keeps saved investigations discoverable when analytics availability is %s", async (analyticsAvailable) => {
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
            ok: analyticsAvailable,
            status: analyticsAvailable ? 200 : 503,
            json: async () => ({ incidents: [warehouseIncident], error: analyticsAvailable ? undefined : "Analytics unavailable during test" }),
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
      await screen.findByRole("region", { name: "Saved reports" })
    ).toHaveTextContent("Warehouse restricted-zone review");
    if (!analyticsAvailable) {
      expect(screen.getByText("Event data unavailable")).toBeInTheDocument();
      expect(screen.queryByText("No detected events yet")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Open evidence" })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Open report" })).toHaveAttribute(
      "href",
      "/api/vision/investigations?id=11111111-1111-4111-8111-111111111111&format=html"
    );
  });
});
