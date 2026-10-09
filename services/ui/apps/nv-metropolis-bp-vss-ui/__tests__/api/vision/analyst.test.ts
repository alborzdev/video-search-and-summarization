// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";
import { readFile } from "node:fs/promises";

import handler from "../../../pages/api/vision/analyst";
import { fetchUnifiedIncidents } from "../../../pages/api/vision/incidents";
import { fetchSourceIntelligence } from "../../../server/vision/sourceIntelligence";

jest.mock("../../../pages/api/vision/incidents", () => ({ fetchUnifiedIncidents: jest.fn() }));
jest.mock("../../../server/vision/sourceIntelligence", () => ({ fetchSourceIntelligence: jest.fn() }));

jest.mock("node:fs/promises", () => ({
  readFile: jest.fn(),
  readdir: jest.fn().mockResolvedValue([]),
}));

const readFileMock = readFile as jest.Mock;
const originalHardwareProfile = process.env.HARDWARE_PROFILE;
const originalMetricsUrl = process.env.TEGRASTATS_METRICS_URL;
const originalMediaUrl = process.env.EVIDENCE_CLIP_API_URL;

function responseHarness() {
  const json = jest.fn();
  const status = jest.fn(() => ({ json }));
  const setHeader = jest.fn();
  return {
    json,
    response: { setHeader, status } as unknown as NextApiResponse,
    setHeader,
    status,
  };
}

const request = {
  method: "POST",
  body: {
    askedAt: "2026-08-18T07:45:00.000Z",
    conversationId: "conversation-1",
    query: "What objects do you see?",
    scope: "selected-source",
    sources: [
      {
        kind: "live",
        name: "Main floor",
        sensorId: "camera-a",
        streamId: "camera-a",
      },
    ],
  },
} as unknown as NextApiRequest;

describe("Vision Analyst API", () => {
  beforeEach(() => {
    process.env.HARDWARE_PROFILE = "THOR";
    process.env.EVIDENCE_CLIP_API_URL = "http://127.0.0.1:8098";
    process.env.TEGRASTATS_METRICS_URL = "http://172.17.0.1:19101/metrics";
  });

  afterEach(() => {
    if (originalHardwareProfile === undefined) delete process.env.HARDWARE_PROFILE;
    else process.env.HARDWARE_PROFILE = originalHardwareProfile;
    if (originalMetricsUrl === undefined) delete process.env.TEGRASTATS_METRICS_URL;
    else process.env.TEGRASTATS_METRICS_URL = originalMetricsUrl;
    if (originalMediaUrl === undefined) delete process.env.EVIDENCE_CLIP_API_URL;
    else process.env.EVIDENCE_CLIP_API_URL = originalMediaUrl;
    jest.restoreAllMocks();
    jest.clearAllMocks();
  });

  it("briefly yields live captioning to current-source inspection and restores it", async () => {
    readFileMock.mockResolvedValue(
      JSON.stringify({
        events: ["person activity"],
        scenario: "warehouse safety",
        sourceId: "camera-a",
        sourceKind: "live",
        sourceName: "Main floor",
      })
    );
    const calls: string[] = [];
    global.fetch = jest.fn(async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.endsWith('/recording-window')) {
        return { ok: true, json: async () => [{ startTime: '2026-08-18T07:40:00Z', endTime: '2026-08-18T07:44:55Z' }] };
      }
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return {
          ok: true,
          json: async () => ({
            stream_list: [{ camera_id: "camera-a", inference_active: true }],
          }),
        };
      }
      if (url.includes("/api/v1/vision-inspection")) {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              answer: "A wheeled robot is visible.",
              evidence_tool: "video_understanding",
              observed_window: { start_time: "2026-08-18T07:44:52Z", end_time: "2026-08-18T07:44:55Z" },
            }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(request, response);

    expect(status).toHaveBeenCalledWith(200);
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({
        answer: "A wheeled robot is visible.",
        grounded: true,
        observedWindow: { startTime: "2026-08-18T07:44:52Z", endTime: "2026-08-18T07:44:55Z" },
        sourceNames: ["Main floor"],
      })
    );
    expect(calls).toEqual([
      "GET http://127.0.0.1:8018/v1/health/ready",
      "GET http://127.0.0.1:8018/v1/stream/get-stream-info",
      "GET http://172.17.0.1:19101/metrics",
      "GET http://127.0.0.1:8018/v1/stream/get-stream-info",
      "DELETE http://127.0.0.1:8018/v1/generate_captions/camera-a",
      "POST http://127.0.0.1:8098/recording-window",
      "POST http://127.0.0.1:8100/api/v1/vision-inspection",
      "POST http://127.0.0.1:38111/v1/generate_captions",
    ]);
    const inspectorCall = (global.fetch as jest.Mock).mock.calls.find(([input]) => String(input).includes('vision-inspection'));
    expect(JSON.parse(inspectorCall[1].body)).toEqual(expect.objectContaining({
      live_start_time: '2026-08-18T07:44:54.000Z', live_end_time: '2026-08-18T07:44:55.000Z',
      lookback_seconds: 1, frame_count: 1,
    }));
  });

  it.each([0, 61, 2.5, "2", null])("rejects invalid duration %p before reserving Cosmos or accessing footage", async (lookbackSeconds) => {
    global.fetch = jest.fn();
    const { response, status } = responseHarness();
    await handler({ ...request, body: { ...request.body, lookbackSeconds } }, response);
    expect(status).toHaveBeenCalledWith(422);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("passes an exact two-second window and two-frame budget to the inspector", async () => {
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/stream/get-stream-info")) return { ok: true, json: async () => ({ stream_list: [] }) };
      if (url.endsWith("/recording-window")) return { ok: true, json: async () => [{ startTime: "2026-08-18T07:44:52Z", endTime: "2026-08-18T07:44:55Z" }] };
      if (url.includes("vision-inspection")) return { ok: true, status: 200, text: async () => JSON.stringify({
        answer: "A forklift is visible.", evidence_tool: "video_understanding_iso",
        observed_window: { start_time: "2026-08-18T07:44:53Z", end_time: "2026-08-18T07:44:55Z" },
      }) };
      return { ok: true, status: 200, json: async () => ({}), text: async () => "jetson_tegrastats_up 1\n" };
    }) as jest.Mock;
    const { response, status } = responseHarness();
    await handler({ ...request, body: { ...request.body, lookbackSeconds: 2 } }, response);
    expect(status).toHaveBeenCalledWith(200);
    const call = (global.fetch as jest.Mock).mock.calls.find(([url]) => String(url).includes("vision-inspection"));
    expect(JSON.parse(call[1].body)).toEqual(expect.objectContaining({
      lookback_seconds: 2, frame_count: 2,
      live_start_time: "2026-08-18T07:44:53.000Z", live_end_time: "2026-08-18T07:44:55.000Z",
    }));
  });

  it('does not inspect guessed footage when the retained live timeline is unavailable', async () => {
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith('/v1/health/ready')) return { ok: true, json: async () => ({}) };
      if (url.endsWith('/v1/stream/get-stream-info')) return { ok: true, json: async () => ({ stream_list: [] }) };
      if (url.endsWith('/recording-window')) return { ok: true, json: async () => [] };
      return { ok: true, text: async () => 'jetson_tegrastats_up 1\n' };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();
    await handler(request, response);
    expect(status).toHaveBeenCalledWith(409);
    expect(json).toHaveBeenCalledWith({ error: expect.stringContaining('could not be verified') });
    expect((global.fetch as jest.Mock).mock.calls.some(([input]) => String(input).includes('vision-inspection'))).toBe(false);
  });

  it("rejects a visual inspection before reserving Cosmos when readiness is unavailable", async () => {
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/health/ready")) return { ok: false };
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return { ok: true, json: async () => ({ stream_list: [] }) };
      }
      return { ok: true, text: async () => "jetson_tegrastats_up 1\n" };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(request, response);

    expect(status).toHaveBeenCalledWith(503);
    expect(json).toHaveBeenCalledWith(expect.objectContaining({
      admission: expect.objectContaining({
        decision: "block",
        reasonCode: "VLM_UNAVAILABLE",
        workload: "current_visual_question",
      }),
      code: "VLM_UNAVAILABLE",
      error: expect.stringContaining("not ready"),
    }));
    expect((global.fetch as jest.Mock).mock.calls.some(
      ([input]) => String(input).includes("vision-inspection")
    )).toBe(false);
  });

  it("includes detector-backed rule events in all-source overviews", async () => {
    (fetchUnifiedIncidents as jest.Mock).mockResolvedValue({ incidents: [{
      Id: "area-event", sensorId: "camera-a", objectIds: ["17"],
      category: "Restricted Area Violation", timestamp: request.body.askedAt,
      info: { alertRuleId: "aisle-rule" },
    }], hasMore: false });
    (fetchSourceIntelligence as jest.Mock).mockResolvedValue(null);
    global.fetch = jest.fn();
    const { json, response, status } = responseHarness();
    await handler({ ...request, body: { ...request.body, scope: "all-sources", query: "Which cameras need attention?" } }, response);
    expect(status).toHaveBeenCalledWith(200);
    expect(json).toHaveBeenCalledWith(expect.objectContaining({ answer: expect.stringContaining("1 awaiting review") }));
    expect(fetchUnifiedIncidents).toHaveBeenCalledTimes(1);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it.each(["partial", "unavailable"])("does not claim an empty event history when coverage is %s", async (coverage) => {
    if (coverage === "partial") {
      (fetchUnifiedIncidents as jest.Mock).mockResolvedValue({ incidents: [], partial: true, errors: { detector: "warming up" } });
    } else (fetchUnifiedIncidents as jest.Mock).mockRejectedValue(new Error("services unavailable"));
    (fetchSourceIntelligence as jest.Mock).mockResolvedValue(null);
    const { json, response, status } = responseHarness();
    await handler({ ...request, body: { ...request.body, scope: "all-sources", query: "Which cameras need attention?" } }, response);
    expect(status).toHaveBeenCalledWith(200);
    expect(json.mock.calls[0][0].answer).toContain("Event coverage is incomplete");
    expect(json.mock.calls[0][0].answer).not.toContain("No operator events");
  });
});
