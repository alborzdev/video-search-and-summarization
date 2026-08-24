// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";
import { rm, unlink, writeFile } from "node:fs/promises";

const sourceId = "11111111-1111-4111-8111-111111111111";
const liveSourceId = "33333333-3333-4333-8333-333333333333";
const pausedSourceId = "44444444-4444-4444-8444-444444444444";
const knowledgeId = "22222222-2222-4222-8222-222222222222";
const storeDirectory = `/tmp/vss-video-history-test-${process.pid}`;

type Handler = (
  request: NextApiRequest,
  response: NextApiResponse
) => Promise<unknown>;

function responseHarness() {
  const state: { body?: unknown; statusCode: number } = { statusCode: 200 };
  const response = {
    json(body: unknown) {
      state.body = body;
      return response;
    },
    setHeader() {
      return response;
    },
    status(statusCode: number) {
      state.statusCode = statusCode;
      return response;
    },
  } as unknown as NextApiResponse;
  return { response, state };
}

function request(
  method: string,
  body: unknown = undefined,
  query: Record<string, string> = {}
): NextApiRequest {
  return { body, method, query } as unknown as NextApiRequest;
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    json: async () => body,
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

async function waitForReady(
  handler: Handler,
  targetSourceId: string
): Promise<ReturnType<typeof responseHarness>> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const status = responseHarness();
    await handler(
      request("GET", undefined, { sourceId: targetSourceId }),
      status.response
    );
    if (
      status.state.statusCode === 200 &&
      (status.state.body as { status?: string })?.status === "ready"
    )
      return status;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`History for ${targetSourceId} did not become ready.`);
}

describe("video history API", () => {
  let handler: Handler;
  let fetchMock: jest.Mock;
  const pausedAnalysisSources = new Set<string>();

  beforeAll(async () => {
    process.env.VISION_HISTORY_DIR = storeDirectory;
    process.env.LVS_BACKEND_URL = "http://lvs.test";
    process.env.VST_INTERNAL_API_URL = "http://vst.test";
    process.env.VISION_HISTORY_ELASTICSEARCH_URL = "http://captions.test";
    process.env.VISION_AGENT_INTERNAL_URL = "http://agent.test/api/v1";
    process.env.LVS_VLM_MODEL = "cosmos-test";
    process.env.RTVI_VLM_URL = "http://vlm.test";
    process.env.TEGRASTATS_METRICS_URL = "http://metrics.test/metrics";
    handler = (await import("../../../pages/api/vision/video-history")).default;
  });

  beforeEach(() => {
    pausedAnalysisSources.clear();
    let liveCaptioningStarted = false;
    fetchMock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "http://vlm.test/v1/health/ready") return jsonResponse({ ready: true });
      if (url === "http://vlm.test/v1/stream/get-stream-info") {
        return jsonResponse({ stream_list: [] });
      }
      if (url === "http://metrics.test/metrics") {
        return {
          ok: true,
          text: async () =>
            "jetson_tegrastats_up 1\n" +
            "jetson_tegrastats_sample_age_seconds 1\n" +
            "jetson_tegrastats_gpu_utilization_ratio 0.20\n",
        } as Response;
      }
      if (url.startsWith("http://agent.test/api/v1/rtsp-streams/")) {
        const targetSourceId = url.split("/rtsp-streams/")[1]?.split("/")[0];
        const active = !pausedAnalysisSources.has(targetSourceId);
        return jsonResponse({
          analysisActive: active,
          state: active ? "active" : "paused",
        });
      }
      if (
        url.endsWith(`/v1/storage/${sourceId}/timelines`)
      ) {
        return jsonResponse([
          {
            endTime: "2026-08-12T10:04:00.000Z",
            startTime: "2026-08-12T10:00:00.000Z",
          },
        ]);
      }
      if (url.endsWith(`/v1/storage/${liveSourceId}/timelines`)) {
        return jsonResponse([
          {
            endTime: "2026-08-12T10:04:00.000Z",
            startTime: "2026-08-12T08:00:00.000Z",
          },
        ]);
      }
      if (url.includes(`/v1/storage/file/${sourceId}/url?`)) {
        return jsonResponse({ videoUrl: "http://vst.test/video.mp4" });
      }
      if (url === "http://lvs.test/v1/summarize") {
        return jsonResponse({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  video_summary: "A forklift moves through the loading area.",
                }),
              },
            },
          ],
          video_id: knowledgeId,
        });
      }
      if (
        url ===
        `http://captions.test/default_${liveSourceId.replaceAll(
          "-",
          "_"
        )}/_search`
      ) {
        return jsonResponse({
          hits: {
            hits: liveCaptioningStarted
              ? [
                  {
                    _source: {
                      "@timestamp": new Date(Date.now() + 10_000).toISOString(),
                      metadata: {
                        content_metadata: {
                          end_ntp_float: (Date.now() + 10_000) / 1_000,
                        },
                      },
                    },
                  },
                ]
              : [],
            total: { value: liveCaptioningStarted ? 1 : 0 },
          },
        });
      }
      if (url === "http://lvs.test/v1/generate_captions") {
        liveCaptioningStarted = true;
        return jsonResponse({ id: liveSourceId, status: "accepted" });
      }
      if (url === `http://lvs.test/v1/qa/${liveSourceId}`)
        return jsonResponse({ deleted: true });
      if (url === "http://lvs.test/v1/stream_summarize") {
        return jsonResponse({
          choices: [
            {
              message: {
                content: JSON.stringify({
                  events: [{ type: "vehicle movement" }],
                  total_events: 1,
                  video_summary: "A vehicle crossed the monitored road.",
                }),
              },
            },
          ],
        });
      }
      if (url === "http://lvs.test/v1/chat/completions") {
        const requestBody = JSON.parse(String(init?.body || "{}")) as {
          messages?: Array<{ content?: string }>;
        };
        const question = requestBody.messages?.at(-1)?.content || "";
        return jsonResponse({
          choices: [
            {
              message: {
                content: question.includes("single moment")
                  ? "Observed at 2026-08-12T10:00:20.000Z."
                  : "Observed: a forklift moved through the loading area between 00:00:05 and 00:00:10.",
              },
            },
          ],
        });
      }
      if (url === `http://lvs.test/v1/qa/${knowledgeId}`) {
        return jsonResponse({ deleted: true });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock;
  });

  afterAll(async () => {
    await rm(storeDirectory, { force: true, recursive: true });
    delete process.env.VISION_HISTORY_DIR;
    delete process.env.LVS_BACKEND_URL;
    delete process.env.VST_INTERNAL_API_URL;
    delete process.env.VISION_HISTORY_ELASTICSEARCH_URL;
    delete process.env.VISION_AGENT_INTERNAL_URL;
    delete process.env.LVS_VLM_MODEL;
    delete process.env.RTVI_VLM_URL;
    delete process.env.TEGRASTATS_METRICS_URL;
  });

  it("builds replay graph history, answers with playable timestamps, and clears only graph knowledge", async () => {
    const build = responseHarness();
    await handler(
      request("POST", {
        action: "start",
        events: ["forklift movement", "pedestrian proximity"],
        scenario: "warehouse monitoring",
        source: {
          id: sourceId,
          kind: "replay",
          name: "Warehouse Main Floor",
        },
      }),
      build.response
    );

    expect(build.state).toEqual(expect.objectContaining({ statusCode: 202 }));
    expect(build.state.body).toEqual(
      expect.objectContaining({
        sourceId,
        status: "building",
      })
    );
    const ready = await waitForReady(handler, sourceId);
    expect(ready.state.body).toEqual(
      expect.objectContaining({ knowledgeId, sourceId, status: "ready" })
    );
    const summarizeRequest = fetchMock.mock.calls.find(
      ([input]) => String(input) === "http://lvs.test/v1/summarize"
    );
    expect(JSON.parse(String(summarizeRequest?.[1]?.body))).toEqual(
      expect.objectContaining({
        creation_time: "2026-08-12T10:00:00.000Z",
        enable_qa: true,
        model: "cosmos-test",
        url: "http://vst.test/video.mp4",
      })
    );

    const ask = responseHarness();
    await handler(
      request("POST", {
        action: "ask",
        messages: [{ content: "When did the forklift move?", role: "user" }],
        sourceId,
      }),
      ask.response
    );
    expect(ask.state.statusCode).toBe(200);
    expect(ask.state.body).toEqual(
      expect.objectContaining({
        citations: [
          expect.objectContaining({
            endTime: "2026-08-12T10:00:10.000Z",
            startTime: "2026-08-12T10:00:05.000Z",
          }),
        ],
      })
    );
    const questionRequest = fetchMock.mock.calls.find(
      ([input]) => String(input) === "http://lvs.test/v1/chat/completions"
    );
    expect(JSON.parse(String(questionRequest?.[1]?.body))).toEqual(
      expect.objectContaining({ id: knowledgeId, is_live: false })
    );
    expect(String(questionRequest?.[1]?.body)).toContain(
      "Cite exact supporting ISO time ranges"
    );

    const pointAsk = responseHarness();
    await handler(
      request("POST", {
        action: "ask",
        messages: [
          { content: "Show the single moment.", role: "user" },
        ],
        sourceId,
      }),
      pointAsk.response
    );
    expect(pointAsk.state.statusCode).toBe(200);
    expect(pointAsk.state.body).toEqual(
      expect.objectContaining({
        citations: [
          expect.objectContaining({
            endTime: "2026-08-12T10:00:30.000Z",
            label: "2026-08-12T10:00:20.000Z",
            startTime: "2026-08-12T10:00:15.000Z",
          }),
        ],
      })
    );
    expect(pointAsk.state.body).not.toEqual(
      expect.objectContaining({ warning: expect.any(String) })
    );

    const clear = responseHarness();
    await handler(request("DELETE", undefined, { sourceId }), clear.response);
    expect(clear.state.statusCode).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://lvs.test/v1/qa/${knowledgeId}`,
      expect.objectContaining({ method: "DELETE" })
    );

    const status = responseHarness();
    await handler(request("GET", undefined, { sourceId }), status.response);
    expect(status.state.statusCode).toBe(200);
    expect(status.state.body).toBeNull();
  });

  it("waits for a fresh live caption and rebuilds graph knowledge before reporting ready", async () => {
    const build = responseHarness();
    await handler(
      request("POST", {
        action: "start",
        events: ["vehicle movement"],
        scenario: "traffic monitoring",
        source: {
          id: liveSourceId,
          kind: "live",
          name: "Traffic camera",
        },
      }),
      build.response
    );

    expect(build.state).toEqual(expect.objectContaining({ statusCode: 202 }));
    expect(build.state.body).toEqual(
      expect.objectContaining({
        sourceId: liveSourceId,
        status: "building",
      })
    );
    const ready = await waitForReady(handler, liveSourceId);
    expect(ready.state.body).toEqual(
      expect.objectContaining({
        sourceId: liveSourceId,
        status: "ready",
        summary: "A vehicle crossed the monitored road.",
      })
    );
    const calls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(calls).toContain("http://lvs.test/v1/generate_captions");
    expect(calls.indexOf(`http://lvs.test/v1/qa/${liveSourceId}`)).toBeLessThan(
      calls.indexOf("http://lvs.test/v1/stream_summarize")
    );
    const summarizeRequest = fetchMock.mock.calls.find(
      ([input]) => String(input) === "http://lvs.test/v1/stream_summarize"
    );
    expect(JSON.parse(String(summarizeRequest?.[1]?.body))).toEqual(
      expect.objectContaining({
        enable_qa: true,
        end_time: "2026-08-12T10:04:00.000Z",
        id: liveSourceId,
        start_time: "2026-08-12T09:34:00.000Z",
      })
    );

    // Status checks are allowed to repair caption ownership after a server
    // restart, but repeated UI polling must not keep resubmitting the same
    // expensive Cosmos live-caption request.
    const repeatedStatus = responseHarness();
    await handler(
      request("GET", undefined, { sourceId: liveSourceId }),
      repeatedStatus.response
    );
    expect(repeatedStatus.state.body).toEqual(
      expect.objectContaining({ sourceId: liveSourceId, status: "ready" })
    );

    expect(
      fetchMock.mock.calls.filter(
        ([input]) => String(input) === "http://lvs.test/v1/generate_captions"
      )
    ).toHaveLength(2);

    const reservationPath = `${storeDirectory}/.live-alert-focused-rule.json`;
    await writeFile(
      reservationPath,
      JSON.stringify({ resumeHistory: true, sourceId: liveSourceId })
    );
    const focusedStatus = responseHarness();
    await handler(
      request("GET", undefined, { sourceId: liveSourceId }),
      focusedStatus.response
    );
    expect(
      fetchMock.mock.calls.filter(
        ([input]) => String(input) === "http://lvs.test/v1/generate_captions"
      )
    ).toHaveLength(2);
    await unlink(reservationPath);
  });

  it("does not restart live captioning when source analysis is paused", async () => {
    await writeFile(
      `${storeDirectory}/${pausedSourceId}.json`,
      JSON.stringify({
        events: ["vehicle movement"],
        knowledgeId: pausedSourceId,
        lastSynchronizedAt: "2026-08-12T10:04:00.000Z",
        scenario: "traffic monitoring",
        sourceId: pausedSourceId,
        sourceKind: "live",
        sourceName: "Paused traffic camera",
        startedAt: "2026-08-12T10:00:00.000Z",
        status: "ready",
        timelineEnd: "2026-08-12T10:04:00.000Z",
        timelineStart: "2026-08-12T10:00:00.000Z",
      })
    );
    pausedAnalysisSources.add(pausedSourceId);

    const status = responseHarness();
    await handler(
      request("GET", undefined, { sourceId: pausedSourceId }),
      status.response
    );

    expect(status.state.statusCode).toBe(200);
    expect(status.state.body).toEqual(
      expect.objectContaining({ sourceId: pausedSourceId, status: "ready" })
    );
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input) === "http://lvs.test/v1/generate_captions" &&
          JSON.parse(String(init?.body || "{}")).id === pausedSourceId
      )
    ).toHaveLength(0);
  });

  it("rejects a new history build before writing a building record without fresh telemetry", async () => {
    process.env.TEGRASTATS_METRICS_URL = "http://metrics.test/metrics";
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "http://vlm.test/v1/health/ready") return jsonResponse({ ready: true });
      if (url === "http://vlm.test/v1/stream/get-stream-info") return jsonResponse({ stream_list: [] });
      if (url === "http://metrics.test/metrics") return { ok: true, text: async () => "" } as Response;
      throw new Error(`Unexpected request: ${url}`);
    });
    const build = responseHarness();

    await handler(
      request("POST", {
        action: "start",
        events: ["forklift movement"],
        scenario: "warehouse monitoring",
        source: {
          id: "55555555-5555-4555-8555-555555555555",
          kind: "replay",
          name: "Warehouse Main Floor",
        },
      }),
      build.response
    );

    expect(build.state.statusCode).toBe(503);
    expect(build.state.body).toEqual(expect.objectContaining({
      code: "TELEMETRY_REQUIRED",
      admission: expect.objectContaining({ workload: "long_video_history_build" }),
    }));
  });
});
