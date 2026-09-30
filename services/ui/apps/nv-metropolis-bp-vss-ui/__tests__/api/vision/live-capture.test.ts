// SPDX-License-Identifier: MIT

import handler from "../../../pages/api/vision/live-capture";
import type { NextApiRequest, NextApiResponse } from "next";

const streamId = "live-stream";
const sensorId = "parent-sensor";
const base = "http://vst.test/vst/api";
const catalog = [
  { [sensorId]: [{ streamId, url: "rtsp://camera.test/live", vodUrl: "" }] },
];

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function request(
  method = "GET",
  overrides: Record<string, unknown> = {}
): NextApiRequest {
  return {
    method,
    headers: { host: "ui.test" },
    query: { streamId },
    body: { streamId, action: "start" },
    ...overrides,
  } as unknown as NextApiRequest;
}

function responseHarness() {
  const json = jest.fn();
  const status = jest.fn(() => ({ json }));
  const setHeader = jest.fn();
  return {
    json,
    status,
    setHeader,
    response: { status, setHeader } as unknown as NextApiResponse,
  };
}

describe("live capture API", () => {
  const originalFetch = global.fetch;
  const originalBase = process.env.VST_INTERNAL_API_URL;

  beforeEach(() => {
    process.env.VST_INTERNAL_API_URL = base;
  });
  afterEach(() => {
    global.fetch = originalFetch;
    if (originalBase === undefined) delete process.env.VST_INTERNAL_API_URL;
    else process.env.VST_INTERNAL_API_URL = originalBase;
  });

  it.each(["on", "off", "user", "schedule", "alwaysOn"])(
    "GET reads %s status without recording or inference mutations",
    async (recordingStatus) => {
      const fetchMock = jest
        .fn()
        .mockResolvedValueOnce(jsonResponse(catalog))
        .mockResolvedValueOnce(jsonResponse({ recordingStatus }));
      global.fetch = fetchMock;
      const h = responseHarness();
      await handler(request(), h.response);
      expect(h.status).toHaveBeenCalledWith(200);
      expect(h.json).toHaveBeenCalledWith({
        streamId,
        sensorId,
        recordingStatus: recordingStatus === "off" ? "off" : "on",
        vstRecordingMode: recordingStatus,
      });
      expect(h.setHeader).toHaveBeenCalledWith("Cache-Control", "no-store");
      expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
        `${base}/v1/live/streams`,
        `${base}/v1/record/${streamId}/status`,
      ]);
      for (const [, init] of fetchMock.mock.calls) {
        expect(init.method).toBeUndefined();
        expect(init).toEqual(
          expect.objectContaining({
            cache: "no-store",
            redirect: "error",
            signal: expect.anything(),
          })
        );
      }
    }
  );

  it.each([
    [
      "foreign source",
      [
        {
          other: [
            { streamId: "another-stream", url: "rtsp://camera.test/live" },
          ],
        },
      ],
    ],
    [
      "recorded source",
      [
        {
          [sensorId]: [
            {
              streamId,
              url: "/video.mp4",
              vodUrl: "/video.mp4",
              type: "FileDownload",
            },
          ],
        },
      ],
    ],
    [
      "sensor ID instead of stream ID",
      [
        {
          [streamId]: [
            { streamId: "actual-stream", url: "rtsp://camera.test/live" },
          ],
        },
      ],
    ],
  ])(
    "rejects a %s before changing recording",
    async (_description, sources) => {
      const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(sources));
      global.fetch = fetchMock;
      const h = responseHarness();
      await handler(request("POST"), h.response);
      expect(h.status).toHaveBeenCalledWith(422);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][0]).toBe(`${base}/v1/live/streams`);
    }
  );

  it.each([
    ["start", "on"],
    ["stop", "off"],
  ])(
    "POST %s verifies %s using only official VST capture APIs",
    async (action, recordingStatus) => {
      const fetchMock = jest
        .fn()
        .mockResolvedValueOnce(jsonResponse(catalog))
        .mockResolvedValueOnce(jsonResponse(null))
        .mockResolvedValueOnce(jsonResponse({ recordingStatus }));
      global.fetch = fetchMock;
      const h = responseHarness();
      await handler(
        request("POST", {
          body: { streamId, action },
          headers: { host: "ui.test", origin: "http://ui.test" },
        }),
        h.response
      );
      expect(h.status).toHaveBeenCalledWith(200);
      expect(h.json).toHaveBeenCalledWith({
        streamId,
        sensorId,
        recordingStatus,
        vstRecordingMode: recordingStatus,
      });
      expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
        `${base}/v1/live/streams`,
        `${base}/v1/record/${streamId}/${action}`,
        `${base}/v1/record/${streamId}/status`,
      ]);
      expect(fetchMock.mock.calls[1][1]).toEqual(
        expect.objectContaining({
          method: "POST",
          body: "{}",
          headers: { "Content-Type": "application/json", streamId },
          redirect: "error",
        })
      );
    }
  );

  it("reports the verified actual state when start returns success but recording remains off", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse(null))
      .mockResolvedValueOnce(jsonResponse({ recordingStatus: "off" }));
    const h = responseHarness();
    await handler(request("POST"), h.response);
    expect(h.status).toHaveBeenCalledWith(502);
    expect(h.json).toHaveBeenCalledWith(
      expect.objectContaining({
        streamId,
        sensorId,
        recordingStatus: "off",
        error: expect.stringContaining("did not start"),
      })
    );
  });

  it("verifies manual VIOS recording after start and preserves its raw user mode", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse(null))
      .mockResolvedValueOnce(jsonResponse({ recordingStatus: "user" }));
    const h = responseHarness();
    await handler(request("POST"), h.response);
    expect(h.status).toHaveBeenCalledWith(200);
    expect(h.json).toHaveBeenCalledWith({
      streamId,
      sensorId,
      recordingStatus: "on",
      vstRecordingMode: "user",
    });
  });

  it("does not enable continuous live questions from an event-only recording pipeline", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse({ recordingStatus: "event" }));
    const h = responseHarness();
    await handler(request(), h.response);
    expect(h.status).toHaveBeenCalledWith(502);
    expect(h.json).toHaveBeenCalledWith({
      error: expect.stringContaining("Event-only recording"),
    });
  });

  it.each(["error", "statusUnknown", "auto", "starting", undefined])(
    "rejects an unverified backend status (%s)",
    async (recordingStatus) => {
      global.fetch = jest
        .fn()
        .mockResolvedValueOnce(jsonResponse(catalog))
        .mockResolvedValueOnce(jsonResponse({ recordingStatus }));
      const h = responseHarness();
      await handler(request(), h.response);
      expect(h.status).toHaveBeenCalledWith(502);
      expect(h.json).toHaveBeenCalledWith({
        error: expect.stringContaining(
          "did not report a usable recording state"
        ),
      });
    }
  );

  it.each(["catalog", "mutation", "verification"])(
    "propagates %s failure without reporting success",
    async (stage) => {
      const fetchMock = jest.fn();
      if (stage !== "catalog")
        fetchMock.mockResolvedValueOnce(jsonResponse(catalog));
      if (stage === "verification")
        fetchMock.mockResolvedValueOnce(jsonResponse(null));
      fetchMock.mockResolvedValueOnce(
        jsonResponse({ error: "upstream failure" }, 503)
      );
      if (stage === "mutation")
        fetchMock.mockResolvedValueOnce(
          jsonResponse({ recordingStatus: "off" })
        );
      global.fetch = fetchMock;
      const h = responseHarness();
      await handler(request("POST"), h.response);
      expect(h.status).toHaveBeenCalledWith(502);
      expect(h.json).toHaveBeenCalledWith(
        expect.objectContaining({
          error: expect.stringContaining("HTTP 503"),
        })
      );
      expect(fetchMock).toHaveBeenCalledTimes(stage === "catalog" ? 1 : 3);
    }
  );

  it.each([
    ["stop", "off", 400],
    ["start", "user", 409],
  ])(
    "returns verified success when repeated %s fails but recording is already %s",
    async (action, mode, status) => {
      const fetchMock = jest
        .fn()
        .mockResolvedValueOnce(jsonResponse(catalog))
        .mockResolvedValueOnce(
          jsonResponse(
            { error: "Already in requested state" },
            status as number
          )
        )
        .mockResolvedValueOnce(jsonResponse({ recordingStatus: mode }));
      global.fetch = fetchMock;
      const h = responseHarness();
      await handler(
        request("POST", { body: { streamId, action } }),
        h.response
      );
      expect(h.status).toHaveBeenCalledWith(200);
      expect(h.json).toHaveBeenCalledWith({
        streamId,
        sensorId,
        recordingStatus: mode === "off" ? "off" : "on",
        vstRecordingMode: mode,
      });
      expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
        `${base}/v1/live/streams`,
        `${base}/v1/record/${streamId}/${action}`,
        `${base}/v1/record/${streamId}/status`,
      ]);
    }
  );

  it("preserves the original start failure and verified off state when the target was not reached", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse({ error: "Cannot start" }, 503))
      .mockResolvedValueOnce(jsonResponse({ recordingStatus: "off" }));
    const h = responseHarness();
    await handler(request("POST"), h.response);
    expect(h.status).toHaveBeenCalledWith(502);
    expect(h.json).toHaveBeenCalledWith({
      streamId,
      sensorId,
      recordingStatus: "off",
      vstRecordingMode: "off",
      error: "Video capture service could not start recording (HTTP 503).",
    });
  });

  it("preserves the mutation error without inventing state when status remains unknown", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse({ error: "Cannot stop" }, 409))
      .mockResolvedValueOnce(
        jsonResponse({ recordingStatus: "statusUnknown" })
      );
    const h = responseHarness();
    await handler(
      request("POST", { body: { streamId, action: "stop" } }),
      h.response
    );
    expect(h.status).toHaveBeenCalledWith(502);
    expect(h.json).toHaveBeenCalledWith({
      streamId,
      sensorId,
      error: "Video capture service could not stop recording (HTTP 409).",
      verificationError: expect.stringContaining(
        "did not report a usable recording state"
      ),
    });
    expect(h.json.mock.calls[0][0]).not.toHaveProperty("recordingStatus");
  });

  it("returns a useful connection failure without exposing backend exception details", async () => {
    global.fetch = jest
      .fn()
      .mockRejectedValue(new Error("private backend details"));
    const h = responseHarness();
    await handler(request(), h.response);
    expect(h.status).toHaveBeenCalledWith(502);
    expect(h.json).toHaveBeenCalledWith({
      error:
        "Video capture service could not check live sources. Check its connection and retry.",
    });
  });

  it.each(["catalog", "status"])(
    "rejects unreadable JSON from the %s endpoint",
    async (stage) => {
      const fetchMock = jest.fn();
      if (stage === "status")
        fetchMock.mockResolvedValueOnce(jsonResponse(catalog));
      fetchMock.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error("Invalid JSON");
        },
      });
      global.fetch = fetchMock;
      const h = responseHarness();
      await handler(request(), h.response);
      expect(h.status).toHaveBeenCalledWith(502);
      expect(h.json).toHaveBeenCalledWith({
        error: expect.stringContaining("returned an invalid"),
      });
    }
  );

  it("accepts a same-origin HTTPS request through the ingress", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse(null))
      .mockResolvedValueOnce(jsonResponse({ recordingStatus: "on" }));
    const h = responseHarness();
    await handler(
      request("POST", {
        headers: {
          host: "ui.test",
          origin: "https://ui.test",
          "x-forwarded-proto": "https",
        },
      }),
      h.response
    );
    expect(h.status).toHaveBeenCalledWith(200);
  });

  it.each([
    null,
    {},
    [{ [sensorId]: null }],
    [{ [sensorId]: [{ streamId, url: 42 }] }],
  ])("rejects malformed catalog data", async (sources) => {
    global.fetch = jest.fn().mockResolvedValueOnce(jsonResponse(sources));
    const h = responseHarness();
    await handler(request("POST"), h.response);
    expect(h.status).toHaveBeenCalledWith(502);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["GET", { query: { streamId: "../recorded" } }, 422],
    ["GET", { query: { streamId: [streamId, "another"] } }, 422],
    ["POST", { body: null }, 422],
    ["POST", { body: { streamId, action: "resume" } }, 422],
    ["DELETE", {}, 405],
    [
      "POST",
      { headers: { host: "ui.test", origin: "http://foreign.test" } },
      403,
    ],
    ["POST", { headers: { host: "ui.test", origin: "null" } }, 403],
  ])(
    "rejects invalid %s input before calling VST",
    async (method, overrides, code) => {
      global.fetch = jest.fn();
      const h = responseHarness();
      await handler(
        request(method as string, overrides as Record<string, unknown>),
        h.response
      );
      expect(h.status).toHaveBeenCalledWith(code);
      expect(global.fetch).not.toHaveBeenCalled();
    }
  );
});
