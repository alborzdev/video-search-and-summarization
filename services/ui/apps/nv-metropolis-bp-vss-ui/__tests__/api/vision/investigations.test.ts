// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";
import { rm } from "node:fs/promises";

const storeDirectory = `/tmp/vss-investigation-test-${process.pid}`;
const retainedKey = "a".repeat(64);

type Handler = (
  request: NextApiRequest,
  response: NextApiResponse
) => Promise<unknown>;

function responseHarness() {
  const headers = new Map<string, string>();
  const state: { body?: unknown; statusCode: number } = { statusCode: 200 };
  const response = {
    json(body: unknown) {
      state.body = body;
      return response;
    },
    send(body: unknown) {
      state.body = body;
      return response;
    },
    setHeader(name: string, value: string) {
      headers.set(name, value);
      return response;
    },
    status(statusCode: number) {
      state.statusCode = statusCode;
      return response;
    },
  } as unknown as NextApiResponse;
  return { headers, response, state };
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
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const analysis = {
  evidence: [
    {
      client_id: "clip-1",
      end_time: "2026-08-12T10:00:28Z",
      evidence_id: "E1",
      match_type: "VLM Verified",
      observation: "A forklift and a person share the marked area.",
      source_name: "Warehouse — Main Floor",
      start_time: "2026-08-12T10:00:00Z",
    },
  ],
  interpretations: [
    {
      evidence_ids: ["E1"],
      text: "This may warrant a safety review.",
    },
  ],
  observations: [
    {
      evidence_ids: ["E1"],
      text: "A forklift and a person share the marked area.",
    },
  ],
  query: "Find restricted-zone entries",
  question: "What happened?",
  status: "complete" as const,
  suggested_questions: [],
  summary: "One restricted-zone entry was found.",
  timeline: [
    {
      end_time: "2026-08-12T10:00:28Z",
      evidence_id: "E1",
      label: "Shared restricted-zone occupancy",
      source_name: "Warehouse — Main Floor",
      start_time: "2026-08-12T10:00:00Z",
    },
  ],
};

describe("vision investigations API", () => {
  let handler: Handler;

  beforeAll(async () => {
    process.env.VISION_INVESTIGATIONS_DIR = storeDirectory;
    process.env.EVIDENCE_CLIP_API_URL = "http://evidence.test";
    handler = (await import("../../../pages/api/vision/investigations")).default;
  });

  beforeEach(() => {
    global.fetch = jest.fn(async () => jsonResponse({ key: retainedKey }));
  });

  afterAll(async () => {
    await rm(storeDirectory, { force: true, recursive: true });
    delete process.env.VISION_INVESTIGATIONS_DIR;
    delete process.env.EVIDENCE_CLIP_API_URL;
  });

  it("persists, lists, and renders an evidence-linked investigation", async () => {
    const create = responseHarness();
    await handler(
      request("POST", {
        analysis,
        disposition: "under_review",
        evidence: [
          {
            client_id: "clip-1",
            end_time: "2026-08-12T10:00:28Z",
            image_url: "/api/vision/vst-image?path=%2Fsnapshot.jpg",
            match_type: "VLM Verified",
            sensor_id: "warehouse-sensor",
            source_name: "Warehouse — Main Floor",
            start_time: "2026-08-12T10:00:00Z",
            title: "Restricted zone occupied",
          },
        ],
        notes: "Reviewed by operator <script>alert(1)</script>",
        query: "Find restricted-zone entries",
        severity: "high",
        title: "Warehouse restricted-zone review",
      }),
      create.response
    );

    expect(create.state.statusCode).toBe(201);
    const record = create.state.body as {
      evidence: Array<{ media_status?: string; video_url?: string }>;
      id: string;
      report_url: string;
    };
    expect(record.id).toMatch(/^[a-f0-9-]{36}$/);
    expect(record.report_url).toContain(record.id);
    expect(record.evidence[0]).toEqual(
      expect.objectContaining({
        media_status: "retained",
        video_url: `/api/vision/evidence-media?key=${retainedKey}`,
      })
    );
    expect(global.fetch).toHaveBeenCalledWith(
      "http://evidence.test/prepare",
      expect.objectContaining({ method: "POST" })
    );
    expect(
      JSON.parse(
        String((global.fetch as jest.Mock).mock.calls[0]?.[1]?.body || "{}")
      )
    ).toEqual(
      {
        endTime: "2026-08-12T10:00:28Z",
        sensorId: "warehouse-sensor",
        startTime: "2026-08-12T10:00:00Z",
      }
    );

    const list = responseHarness();
    await handler(request("GET"), list.response);
    expect(list.state.statusCode).toBe(200);
    expect(list.state.body).toEqual(
      expect.objectContaining({
        investigations: [expect.objectContaining({ id: record.id })],
      })
    );

    const report = responseHarness();
    await handler(
      request("GET", undefined, { format: "html", id: record.id }),
      report.response
    );
    const html = String(report.state.body);
    expect(report.state.statusCode).toBe(200);
    expect(report.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(html).toContain("Observed facts");
    expect(html).toContain("AI interpretation");
    expect(html).toContain("Play exact clip");
    expect(html).toContain("Media retained locally on Thor");
    expect(html).toContain(`/api/vision/evidence-media?key=${retainedKey}`);
    expect(html).toContain("sensorId=warehouse-sensor");
    expect(html).toContain("startTime=2026-08-12T10%3A00%3A00Z");
    expect(html).toContain('data-local-time="2026-08-12T10:00:00Z"');
    expect(html).toContain("date.toLocaleString()");
    expect(html).toContain('rel="icon" href="data:image/svg+xml');
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain(
      "Reviewed by operator &lt;script&gt;alert(1)&lt;/script&gt;"
    );
  });

  it("rejects evidence with a zero-length interval", async () => {
    const response = responseHarness();
    await handler(
      request("POST", {
        analysis,
        disposition: "open",
        evidence: [
          {
            client_id: "clip-1",
            end_time: "2026-08-12T10:00:00Z",
            sensor_id: "warehouse-sensor",
            source_name: "Warehouse",
            start_time: "2026-08-12T10:00:00Z",
            title: "Invalid evidence",
          },
        ],
        query: "Find entries",
        severity: "low",
        title: "Invalid investigation",
      }),
      response.response
    );

    expect(response.state.statusCode).toBe(400);
    expect(response.state.body).toEqual(
      expect.objectContaining({ error: expect.stringContaining("invalid") })
    );
  });
});
