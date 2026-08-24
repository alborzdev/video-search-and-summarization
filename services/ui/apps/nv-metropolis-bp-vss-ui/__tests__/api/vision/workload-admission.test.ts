// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";

jest.mock("../../../server/vision/cosmosReservation", () => ({
  readCosmosReservationState: jest.fn(() => ({
    active: false,
    waitingCount: 0,
  })),
}));
jest.mock("../../../server/vision/liveAlertReservation", () => ({
  readActiveLiveAlertReservations: jest.fn().mockResolvedValue([]),
}));

import handler from "../../../pages/api/vision/workload-admission";

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

describe("workload admission API", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    jest.clearAllMocks();
  });

  it("observes local facts and returns a non-mutating admission decision", async () => {
    const calls: Array<{ method?: string; url: string }> = [];
    global.fetch = jest.fn(async (input, init) => {
      const url = String(input);
      calls.push({ method: init?.method, url });
      if (url.endsWith("/v1/health/ready")) return { ok: true };
      if (url.endsWith("/v1/stream/get-stream-info")) {
        return { ok: true, json: async () => ({ stream_list: [] }) };
      }
      return {
        ok: true,
        text: async () =>
          "jetson_tegrastats_up 1\n" +
          "jetson_tegrastats_sample_age_seconds 1\n" +
          "jetson_tegrastats_gpu_utilization_ratio 0.20\n",
      };
    }) as jest.Mock;
    const { json, response, setHeader, status } = responseHarness();

    await handler(
      {
        method: "GET",
        query: { workload: "evidence_analysis" },
      } as unknown as NextApiRequest,
      response
    );

    expect(status).toHaveBeenCalledWith(200);
    expect(setHeader).toHaveBeenCalledWith("Cache-Control", "no-store");
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({
        decision: "allow",
        reasonCode: "ALLOW",
        workload: "evidence_analysis",
      })
    );
    expect(calls).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ url: expect.stringMatching(/health\/ready$/) }),
        expect.objectContaining({ url: expect.stringMatching(/get-stream-info$/) }),
      ])
    );
    expect(calls.every(({ method }) => !method || method === "GET")).toBe(true);
  });

  it("rejects an unknown workload class without probing local services", async () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(
      { method: "GET", query: { workload: "surprise" } } as unknown as NextApiRequest,
      response
    );

    expect(status).toHaveBeenCalledWith(400);
    expect(json).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Choose a supported workload class." })
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
