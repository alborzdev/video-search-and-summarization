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
