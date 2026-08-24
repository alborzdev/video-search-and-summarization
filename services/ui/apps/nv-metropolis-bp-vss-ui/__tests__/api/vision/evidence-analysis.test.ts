// SPDX-License-Identifier: MIT

import handler from "../../../pages/api/vision/evidence-analysis";
import type { NextApiRequest, NextApiResponse } from "next";
import { readFile } from "node:fs/promises";

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

const evidence = {
  client_id: "camera-a:2026-08-17T14:00:00Z",
  sensor_id: "camera-a",
  source_name: "Main floor",
  start_time: "2026-08-17T14:00:00Z",
  end_time: "2026-08-17T14:00:10Z",
  search_description: "Person near a robot",
  match_type: "Semantic video match",
};

describe("evidence analysis API", () => {
  const originalEndpoint = process.env.EVIDENCE_ANALYSIS_API_URL;

  afterEach(() => {
    jest.restoreAllMocks();
    jest.clearAllMocks();
    if (originalEndpoint === undefined) {
      delete process.env.EVIDENCE_ANALYSIS_API_URL;
    } else {
      process.env.EVIDENCE_ANALYSIS_API_URL = originalEndpoint;
    }
  });

  it("forwards selected evidence to the local agent and disables caching", async () => {
    process.env.EVIDENCE_ANALYSIS_API_URL =
      "http://127.0.0.1:8100/api/v1/evidence-analysis";
    const payload = {
      status: "complete",
      query: "person near a robot",
      question: "person near a robot",
      summary: "A person is visible beside a wheeled robot.",
      observations: [{ text: "A person is visible.", evidence_ids: ["E1"] }],
      interpretations: [],
      timeline: [],
      evidence: [],
      suggested_questions: [],
      warning: null,
    };
    const fetchMock = jest.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }));
    global.fetch = fetchMock as jest.Mock;
    const { json, response, setHeader, status } = responseHarness();
    const request = {
      method: "POST",
      body: { query: "person near a robot", evidence: [evidence] },
    } as unknown as NextApiRequest;

    await handler(request, response);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8100/api/v1/evidence-analysis",
      expect.objectContaining({
        body: JSON.stringify(request.body),
        method: "POST",
      })
    );
    expect(setHeader).toHaveBeenCalledWith("Cache-Control", "no-store");
    expect(status).toHaveBeenCalledWith(200);
    expect(json).toHaveBeenCalledWith(payload);
  });

  it("rejects duplicate or invalid evidence before calling the agent", async () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as jest.Mock;
    const { json, response, status } = responseHarness();
    const request = {
      method: "POST",
      body: {
        query: "person",
        evidence: [evidence, { ...evidence }],
      },
    } as unknown as NextApiRequest;

    await handler(request, response);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(status).toHaveBeenCalledWith(400);
    expect(json).toHaveBeenCalledWith({
      error: "Selected clips must be unique.",
    });
  });

  it("preserves an honest upstream failure", async () => {
    const fetchMock = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/health/ready")) return { ok: true };
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return { ok: true, json: async () => ({ stream_list: [] }) };
      }
      if (url.includes("tegrastats")) {
        return { ok: true, text: async () => "jetson_tegrastats_up 1\n" };
      }
      return {
        ok: false,
        status: 502,
        json: async () => ({
          error: "The local visual evidence tool is unavailable",
        }),
      };
    });
    global.fetch = fetchMock as jest.Mock;
    const { json, response, status } = responseHarness();
    const request = {
      method: "POST",
      body: { query: "person", evidence: [evidence] },
    } as unknown as NextApiRequest;

    await handler(request, response);

    expect(status).toHaveBeenCalledWith(502);
    expect(json).toHaveBeenCalledWith({
      error: "The local visual evidence tool is unavailable",
    });
  });

  it("reserves Cosmos for clip inspection and restores live history", async () => {
    readFileMock.mockResolvedValue(
      JSON.stringify({
        events: ["person activity"],
        scenario: "warehouse safety",
        sourceId: "camera-a",
        sourceKind: "live",
        sourceName: "Main floor",
      })
    );
    const payload = {
      status: "complete",
      query: "person",
      question: "person",
      summary: "A person is visible.",
      observations: [{ text: "A person is visible.", evidence_ids: ["E1"] }],
      interpretations: [],
      timeline: [],
      evidence: [],
      suggested_questions: [],
      warning: null,
    };
    const calls: string[] = [];
    global.fetch = jest.fn(async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return {
          ok: true,
          json: async () => ({
            stream_list: [
              {
                camera_id: "camera-a",
                inference_active: true,
              },
            ],
          }),
        };
      }
      if (url.includes("/api/v1/evidence-analysis")) {
        return { ok: true, status: 200, json: async () => payload };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(
      {
        method: "POST",
        body: { query: "person", evidence: [evidence] },
      } as NextApiRequest,
      response
    );

    expect(status).toHaveBeenCalledWith(200);
    expect(json).toHaveBeenCalledWith(payload);
    expect(calls).toEqual([
      "GET http://127.0.0.1:8018/v1/health/ready",
      "GET http://127.0.0.1:8018/v1/stream/get-stream-info",
      "GET http://172.17.0.1:19101/metrics",
      "GET http://127.0.0.1:8018/v1/stream/get-stream-info",
      "DELETE http://127.0.0.1:8018/v1/generate_captions/camera-a",
      "POST http://127.0.0.1:8100/api/v1/evidence-analysis",
      "POST http://127.0.0.1:38111/v1/generate_captions",
    ]);
  });

  it("rejects evidence analysis before reserving Cosmos when readiness is unavailable", async () => {
    const fetchMock = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/health/ready")) return { ok: false };
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return { ok: true, json: async () => ({ stream_list: [] }) };
      }
      return { ok: true, text: async () => "jetson_tegrastats_up 1\n" };
    });
    global.fetch = fetchMock as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(
      {
        method: "POST",
        body: { query: "person", evidence: [evidence] },
      } as NextApiRequest,
      response
    );

    expect(status).toHaveBeenCalledWith(503);
    expect(json).toHaveBeenCalledWith(expect.objectContaining({
      admission: expect.objectContaining({
        reasonCode: "VLM_UNAVAILABLE",
        workload: "evidence_analysis",
      }),
      code: "VLM_UNAVAILABLE",
    }));
    expect(fetchMock.mock.calls.some(
      ([input]) => String(input).includes("evidence-analysis")
    )).toBe(false);
  });

  it("restores an active live caption session before History has been configured", async () => {
    readFileMock.mockRejectedValue(
      Object.assign(new Error("not found"), { code: "ENOENT" })
    );
    const payload = {
      status: "complete",
      query: "pedestrian",
      question: "pedestrian",
      summary: "A pedestrian is visible.",
      observations: [],
      interpretations: [],
      timeline: [],
      evidence: [],
      suggested_questions: [],
      warning: null,
    };
    let resumeBody: Record<string, unknown> | null = null;
    global.fetch = jest.fn(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return {
          ok: true,
          json: async () => ({
            stream_list: [
              {
                camera_id: "camera-a",
                camera_name: "Traffic intersection 01",
                inference_active: true,
              },
            ],
          }),
        };
      }
      if (url.includes("/api/v1/evidence-analysis")) {
        return { ok: true, status: 200, json: async () => payload };
      }
      if (url.endsWith("/v1/generate_captions") && init?.method === "POST") {
        resumeBody = JSON.parse(String(init.body));
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(
      {
        method: "POST",
        body: { query: "pedestrian", evidence: [evidence] },
      } as NextApiRequest,
      response
    );

    expect(status).toHaveBeenCalledWith(200);
    expect(json).toHaveBeenCalledWith(payload);
    expect(resumeBody).toEqual(
      expect.objectContaining({
        events: expect.arrayContaining(["pedestrian crossing", "near collision"]),
        id: "camera-a",
        scenario: "traffic monitoring",
      })
    );
  });
});
