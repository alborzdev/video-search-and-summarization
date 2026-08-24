// SPDX-License-Identifier: MIT

import handler from "../../../pages/api/vision/evidence";
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

describe("evidence API", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_VST_API_URL;
  });

  it("returns 410 without generating a clip when the recording has expired", async () => {
    const fetchMock = jest.fn(async () => ({
      ok: true,
      json: async () => [
        {
          startTime: "2026-08-17T12:49:32.333Z",
          endTime: "2026-08-17T18:07:51.433Z",
        },
      ],
    }));
    global.fetch = fetchMock as jest.Mock;
    const { json, response, status } = responseHarness();
    const request = {
      method: "GET",
      query: {
        sensorId: "live-camera",
        startTime: "2026-08-14T19:14:43.977Z",
        endTime: "2026-08-14T19:14:48.381Z",
      },
    } as unknown as NextApiRequest;

    await handler(request, response);

    expect(status).toHaveBeenCalledWith(410);
    expect(json).toHaveBeenCalledWith({
      error: "The recording for this result is no longer retained.",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/v1/storage/live-camera/timelines"
    );
  });

  it("returns a LAN-safe public VST clip URL when the direct clip is available", async () => {
    process.env.NEXT_PUBLIC_VST_API_URL = "http://10.88.8.175:7777/vst/api";
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            startTime: "2026-08-20T02:40:00.000Z",
            endTime: "2026-08-20T02:50:00.000Z",
          },
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          startTime: "2026-08-20T02:41:04.000Z",
          videoUrl:
            "http://127.0.0.1:30888/vst/storage/temp_files/evidence.mp4",
        }),
      }) as jest.Mock;
    const { json, response, status } = responseHarness();

    await handler(
      {
        method: "GET",
        query: {
          sensorId: "live-camera",
          startTime: "2026-08-20T02:41:04.000Z",
          endTime: "2026-08-20T02:41:19.000Z",
        },
      } as unknown as NextApiRequest,
      response
    );

    expect(status).toHaveBeenCalledWith(200);
    expect(json).toHaveBeenCalledWith({
      startTime: "2026-08-20T02:41:04.000Z",
      videoUrl:
        "http://10.88.8.175:7777/vst/storage/temp_files/evidence.mp4",
    });
  });
});
