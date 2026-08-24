// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";
import { readFile } from "node:fs/promises";

import handler from "../../../pages/api/vision/analyst";

jest.mock("node:fs/promises", () => ({
  readFile: jest.fn(),
  readdir: jest.fn().mockResolvedValue([]),
}));

const readFileMock = readFile as jest.Mock;

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
  afterEach(() => {
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
              observed_range: { start_seconds: 0, end_seconds: 25 },
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
        sourceNames: ["Main floor"],
      })
    );
    expect(calls).toEqual([
      "GET http://127.0.0.1:8018/v1/health/ready",
      "GET http://127.0.0.1:8018/v1/stream/get-stream-info",
      "GET http://172.17.0.1:19101/metrics",
      "GET http://127.0.0.1:8018/v1/stream/get-stream-info",
      "DELETE http://127.0.0.1:8018/v1/generate_captions/camera-a",
      "POST http://127.0.0.1:8100/api/v1/vision-inspection",
      "POST http://127.0.0.1:38111/v1/generate_captions",
    ]);
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
});
