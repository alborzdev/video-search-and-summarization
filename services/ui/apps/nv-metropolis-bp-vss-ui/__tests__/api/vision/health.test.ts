// SPDX-License-Identifier: MIT

import handler from "../../../pages/api/vision/health";
import type { NextApiRequest, NextApiResponse } from "next";

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

describe("vision health API", () => {
  const originalEnv = { ...process.env };
  const originalFetch = global.fetch;
  afterEach(() => { process.env = { ...originalEnv }; global.fetch = originalFetch; });

  it("uses measured Spark capacity without probing or inventing Thor metrics", async () => {
    process.env.HARDWARE_PROFILE = "DGX-SPARK";
    process.env.SPARK_CAPACITY_URL = "http://capacity.test/capacity";
    process.env.HISTORY_METADATA_TOKEN = "test-local-token";
    const fetchMock = jest.fn(async (input) => String(input) === "http://capacity.test/capacity"
      ? { ok: true, json: async () => ({ hardwareProfile: "DGX-SPARK", guardActive: true, availableGiB: 36.5, reserveGiB: 24, sampledAt: Date.now() / 1000 }) }
      : { ok: true });
    global.fetch = fetchMock as jest.Mock;
    const { json, response } = responseHarness();
    await handler({ method: "GET" } as NextApiRequest, response);
    expect(json.mock.calls[0][0]).toEqual(expect.objectContaining({ hardwareProfile: "DGX-SPARK", thor: null, sparkCapacity: { state: "fresh", guardActive: true, availableGiB: 36.5, reserveGiB: 24 } }));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("19101"))).toBe(false);
    expect(JSON.stringify(json.mock.calls[0][0])).not.toContain("test-local-token");
  });

  it("includes both local reasoning models in overall readiness", async () => {
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.includes("19101/metrics")) {
        return {
          ok: true,
          text: async () => "jetson_tegrastats_up 1\n",
        };
      }
      if (url.includes("/vst/api/v1/live/streams")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler({ method: "GET" } as NextApiRequest, response);

    expect(status).toHaveBeenCalledWith(200);
    const payload = json.mock.calls[0][0];
    expect(payload.status).toBe("online");
    expect(payload.services).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "vlm",
          label: "Cosmos visual reasoning",
          ok: true,
        }),
        expect.objectContaining({
          key: "llm",
          label: "Nemotron synthesis",
          ok: true,
        }),
      ])
    );
  });

  it("reports degraded readiness while the visual model is unavailable", async () => {
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.includes("8018/v1/health/ready")) return { ok: false };
      if (url.includes("19101/metrics")) {
        return {
          ok: true,
          text: async () => "jetson_tegrastats_up 1\n",
        };
      }
      if (url.includes("/vst/api/v1/live/streams")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: true };
    }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler({ method: "GET" } as NextApiRequest, response);

    expect(status).toHaveBeenCalledWith(200);
    expect(json.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        status: "degraded",
        services: expect.arrayContaining([
          expect.objectContaining({ key: "vlm", ok: false }),
        ]),
      })
    );
  });
});
