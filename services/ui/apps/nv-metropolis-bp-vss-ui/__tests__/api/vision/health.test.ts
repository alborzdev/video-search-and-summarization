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

  it.each([
    ["3.2.1", "false", false, false],
    ["3.3.0", "true", true, true],
    [undefined, undefined, null, null],
  ])("distinguishes source support from configured runtime facts: %s", async (runtime, enabled, compatible, configured) => {
    process.env.HARDWARE_PROFILE = "DGX-SPARK";
    process.env.VSS_SOURCE_VERSION = "3.3.0";
    if (runtime) process.env.VSS_RTVI_RUNTIME_VERSION = runtime;
    else delete process.env.VSS_RTVI_RUNTIME_VERSION;
    if (enabled) process.env.VSS_ADAPTIVE_EVS_ENABLED = enabled;
    else delete process.env.VSS_ADAPTIVE_EVS_ENABLED;
    global.fetch = jest.fn(async () => ({ ok: true })) as jest.Mock;
    const { json, response } = responseHarness();
    await handler({ method: "GET" } as NextApiRequest, response);
    expect(json.mock.calls[0][0].videoEfficiency).toEqual({ sourceVersion: "3.3.0", runtimeVersion: runtime || null,
      adaptiveEvsCompatible: compatible, adaptiveEvsConfigured: configured });
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

  it("scores selected clip services and explicitly labels the disabled detector without probing it", async () => {
    process.env.HARDWARE_PROFILE = "DGX-SPARK";
    process.env.VSS_DEMO_PROFILE = "clips";
    process.env.VSS_DETECTOR_ENABLED = "false";
    const fetchMock = jest.fn(async (_input: RequestInfo | URL) => ({ ok: true }));
    global.fetch = fetchMock as jest.Mock;
    const { json, response } = responseHarness();
    await handler({ method: "GET" } as NextApiRequest, response);
    const payload = json.mock.calls[0][0];
    expect(payload.status).toBe("online");
    expect(payload.demoProfile).toBe("clips");
    expect(payload.services).toHaveLength(7);
    expect(payload.services.filter((service: { selected: boolean }) => service.selected)).toHaveLength(6);
    expect(payload.services).toContainEqual({ key: "perception", label: "Detection + tracking", latencyMs: null, ok: false, selected: false });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("get-dsready-state"))).toBe(false);
  });

  it.each([undefined, "true", "invalid"])("retains detector outage checks unless explicitly disabled: %s", async enabled => {
    process.env.HARDWARE_PROFILE = "DGX-SPARK";
    delete process.env.VSS_DEMO_PROFILE;
    if (enabled === undefined) delete process.env.VSS_DETECTOR_ENABLED;
    else process.env.VSS_DETECTOR_ENABLED = enabled;
    global.fetch = jest.fn(async (input) => ({ ok: !String(input).includes("get-dsready-state") })) as jest.Mock;
    const { json, response } = responseHarness();
    await handler({ method: "GET" } as NextApiRequest, response);
    const payload = json.mock.calls[0][0];
    expect(payload.status).toBe("degraded");
    expect(payload.services.filter((service: { selected: boolean }) => service.selected)).toHaveLength(7);
    expect(payload.services).toEqual(expect.arrayContaining([expect.objectContaining({ key: "perception", ok: false, selected: true })]));
  });

  it.each([[false, "offline", 503], [true, "degraded", 200]])("does not hide selected model outages in clip mode: other roles healthy=%s", async (othersHealthy, readiness, statusCode) => {
    process.env.HARDWARE_PROFILE = "DGX-SPARK";
    process.env.VSS_DEMO_PROFILE = "clips";
    process.env.VSS_DETECTOR_ENABLED = "false";
    global.fetch = jest.fn(async (input) => ({ ok: othersHealthy && !String(input).includes("8018/v1/health/ready") })) as jest.Mock;
    const { json, response, status } = responseHarness();
    await handler({ method: "GET" } as NextApiRequest, response);
    expect(status).toHaveBeenCalledWith(statusCode);
    expect(json.mock.calls[0][0].status).toBe(readiness);
    expect(json.mock.calls[0][0].services).toEqual(expect.arrayContaining([expect.objectContaining({ key: "vlm", selected: true, ok: false })]));
  });
});

describe("DASH runtime capability", () => {
  const original = process.env.VSS_DASH_PLAYBACK_ENABLED;
  const originalFetch = global.fetch;
  afterEach(() => { if (original === undefined) delete process.env.VSS_DASH_PLAYBACK_ENABLED; else process.env.VSS_DASH_PLAYBACK_ENABLED = original; global.fetch = originalFetch; });
  it.each([["true", true], ["false", false], [undefined, false], ["yes", false]])("requires explicit qualified runtime metadata: %s", async (value, enabled) => {
    if (value === undefined) delete process.env.VSS_DASH_PLAYBACK_ENABLED;
    else process.env.VSS_DASH_PLAYBACK_ENABLED = value;
    global.fetch = jest.fn(async () => ({ ok: true })) as jest.Mock;
    const { json, response } = responseHarness();
    await handler({ method: "GET" } as NextApiRequest, response);
    expect(json.mock.calls[0][0].videoPlayback).toEqual({ dashEnabled: enabled });
  });
});
