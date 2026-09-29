import React from "react";
import type { MonitoringRule } from "../monitoringRules";
import { fireEvent, render, screen } from "@testing-library/react";
import { EventReport, eventReportRequest } from "../EventReport";

const context = {
  incident: { Id: "event-1", sensorId: "source-name", timestamp: "2026-09-29T00:59:35.846Z", end: "2026-09-29T00:59:58.378Z", info: { alertCategory: "semantic", verdict: "confirmed", alertRuleId: "rule-1", triggerPhrase: "yes" } },
  rule: null, sensorId: "resolved-source-id", sourceName: "Conveyor replay",
};

afterEach(() => jest.restoreAllMocks());

it("preserves the exact event interval and resolved source without claiming fresh inspection", () => {
  const request = eventReportRequest(context, "Reviewed replay", "Box visible at start.");
  expect(request.evidence[0]).toMatchObject({ sensor_id: "resolved-source-id", start_time: context.incident.timestamp, end_time: context.incident.end });
  expect(request.analysis.evidence[0].inspection_source).toBe("retained_event_record");
  expect(request.analysis.summary).toContain("Model match");
  expect(request.analysis.summary).toContain("no new AI analysis");
  expect(request.analysis.summary).toContain("event-1");
  expect(request).toMatchObject({ disposition: "under_review", severity: "low", notes: "Box visible at start." });
});

it("rejects missing or invalid event intervals", () => {
  for (const end of [undefined, "invalid", context.incident.timestamp]) {
    expect(() => eventReportRequest({ ...context, incident: { ...context.incident, end } }, "Title", "")).toThrow("valid event interval");
  }
});

it("retains entered notes on failure and reports actual media retention after retry", async () => {
  global.fetch = jest.fn()
    .mockResolvedValueOnce({ ok: false, json: async () => ({ error: "Storage unavailable" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ evidence: [{ media_status: "source_retention" }], report_url: "/report/event-1" }) });
  render(<EventReport {...context} />);
  fireEvent.click(screen.getByRole("button", { name: "Save event report" }));
  fireEvent.change(screen.getByLabelText("Event report notes"), { target: { value: "Box visible at start." } });
  fireEvent.click(screen.getByRole("button", { name: "Save report with evidence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
  expect(screen.getByLabelText("Event report notes")).toHaveValue("Box visible at start.");
  fireEvent.click(screen.getByRole("button", { name: "Save report with evidence" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Video still depends on source retention");
  expect(screen.getByRole("link", { name: "Open event report" })).toHaveAttribute("href", "/report/event-1");
});

it("preserves the event's original condition even if the rule was edited or is unavailable", () => {
  const incident = { ...context.incident, info: { ...context.incident.info, prompt: "Original observed condition" } };
  for (const rule of [null, { prompt: "Edited condition", name: "Edited rule", severity: "info" } as MonitoringRule]) {
    const request = eventReportRequest({ ...context, incident, rule }, "Review", "");
    expect(request.query).toBe("Original observed condition");
    expect(request.analysis.question).toBe("Original observed condition");
  }
});
