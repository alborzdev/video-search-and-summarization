// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";

import handler from "../../../pages/api/vision/search-coverage";

function responseHarness() {
  const state: { body?: unknown; headers: Record<string, string>; statusCode: number } = {
    headers: {},
    statusCode: 200,
  };
  const response = {
    json(body: unknown) {
      state.body = body;
      return response;
    },
    setHeader(name: string, value: string) {
      state.headers[name] = value;
      return response;
    },
    status(statusCode: number) {
      state.statusCode = statusCode;
      return response;
    },
  } as unknown as NextApiResponse;
  return { response, state };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    json: async () => body,
    ok: status >= 200 && status < 300,
    status,
  } as Response;
}

function sourceIntelligenceResponse(sensorId: string, recent: string): Response {
  return jsonResponse({
    hits: {
      hits: [{ _source: { "@timestamp": recent, timestamp: recent } }],
      total: { value: sensorId === "camera-1" ? 4 : 0 },
    },
  });
}

describe("search coverage API", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it("reports searchability and retained media from real index and VIOS facts", async () => {
    const recent = new Date(Date.now() - 5_000).toISOString();
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.includes("/live/streams")) {
        return jsonResponse([
          {
            "camera-1": [
              { isMain: true, name: "Main Camera", streamId: "camera-1" },
            ],
          },
        ]);
      }
      if (url.includes("/v1/storage/camera-1/timelines")) {
        return jsonResponse([
          {
            endTime: "2026-08-23T12:05:00.000Z",
            startTime: "2026-08-23T12:00:00.000Z",
          },
        ]);
      }
      if (url.includes("/default_camera_1/_search")) {
        return sourceIntelligenceResponse("camera-1", recent);
      }
      if (url.includes("/mdx-embed-filtered-*/_search")) {
        return jsonResponse({ hits: { hits: [{ _source: { timestamp: recent } }] } });
      }
      if (url.includes("/mdx-embed-filtered-*/_count")) return jsonResponse({ count: 12 });
      if (url.includes("/mdx-raw-*/_count")) return jsonResponse({ count: 2 });
      if (url.includes("/mdx-incidents-*/_count")) return jsonResponse({ count: 1 });
      throw new Error(`Unexpected request: ${url}`);
    }) as jest.Mock;
    const { response, state } = responseHarness();

    await handler({ method: "GET" } as NextApiRequest, response);

    expect(state.statusCode).toBe(200);
    expect(state.headers["Cache-Control"]).toContain("max-age=15");
    expect(state.body).toEqual(
      expect.objectContaining({
        sources: [
          expect.objectContaining({
            indexStatus: "indexed",
            name: "Main Camera",
            recordingStatus: "retained",
            semanticSegments: 12,
            sensorId: "camera-1",
          }),
        ],
        summary: expect.objectContaining({
          configuredSources: 1,
          indexedSources: 1,
          retainedSources: 1,
        }),
      })
    );
  });

  it("keeps source-level uncertainty explicit when one index or timeline query fails", async () => {
    const recent = new Date(Date.now() - 5_000).toISOString();
    global.fetch = jest.fn(async (input, init) => {
      const url = String(input);
      if (url.includes("/live/streams")) {
        return jsonResponse([
          { "camera-1": [{ name: "Main Camera" }] },
          { "camera-2": [{ name: "Loading Dock" }] },
        ]);
      }
      if (url.includes("/v1/storage/camera-1/timelines")) {
        return jsonResponse([
          {
            endTime: "2026-08-23T12:05:00.000Z",
            startTime: "2026-08-23T12:00:00.000Z",
          },
        ]);
      }
      if (url.includes("/v1/storage/camera-2/timelines")) return jsonResponse({}, 502);
      if (
        url.includes("camera_2") ||
        String(init?.body ?? "").includes("camera-2")
      ) {
        throw new Error("index offline");
      }
      if (url.includes("/default_camera_1/_search")) {
        return sourceIntelligenceResponse("camera-1", recent);
      }
      if (url.includes("/mdx-embed-filtered-*/_search")) {
        return jsonResponse({ hits: { hits: [{ _source: { timestamp: recent } }] } });
      }
      if (url.includes("/mdx-embed-filtered-*/_count")) return jsonResponse({ count: 2 });
      if (url.includes("/mdx-raw-*/_count")) return jsonResponse({ count: 0 });
      if (url.includes("/mdx-incidents-*/_count")) return jsonResponse({ count: 0 });
      throw new Error(`Unexpected request: ${url}`);
    }) as jest.Mock;
    const { response, state } = responseHarness();

    await handler({ method: "GET" } as NextApiRequest, response);

    expect(state.statusCode).toBe(200);
    expect(state.body).toEqual(
      expect.objectContaining({
        sources: expect.arrayContaining([
          expect.objectContaining({
            indexStatus: "unknown",
            recordingStatus: "unavailable",
            sensorId: "camera-2",
          }),
        ]),
        summary: expect.objectContaining({
          unavailableRecordingSources: 1,
          unknownIndexSources: 1,
        }),
      })
    );
  });

  it("reports unavailable when the configured source catalog cannot be read", async () => {
    global.fetch = jest.fn(async () => {
      throw new Error("Video I/O offline");
    }) as jest.Mock;
    const { response, state } = responseHarness();

    await handler({ method: "GET" } as NextApiRequest, response);

    expect(state.statusCode).toBe(503);
    expect(state.body).toEqual({
      error: "Configured source coverage is unavailable. Check Video I/O, then refresh.",
    });
  });
});
