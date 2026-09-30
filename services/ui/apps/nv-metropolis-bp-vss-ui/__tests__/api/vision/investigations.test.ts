// SPDX-License-Identifier: MIT

import type { NextApiRequest, NextApiResponse } from "next";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { Script } from "node:vm";

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
  return { body, method, query, headers: { host: "thor.test:7777" } } as unknown as NextApiRequest;
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

  it("lists collections beyond 100 files without dropping records before sorting", async () => {
    await mkdir(storeDirectory, { recursive: true });
    const records = Array.from({ length: 101 }, (_, index) => ({ id: randomUUID(), created_at: new Date(Date.UTC(2026, 0, 1, 0, index)).toISOString() }));
    try {
      await Promise.all(records.map(record => writeFile(`${storeDirectory}/${record.id}.json`, JSON.stringify(record))));
      const list = responseHarness();
      await handler(request("GET"), list.response);
      expect(list.state.statusCode).toBe(200);
      const returned = (list.state.body as { investigations: typeof records }).investigations;
      expect(returned.map(record => record.id)).toEqual(expect.arrayContaining(records.map(record => record.id)));
      expect(returned.map(record => record.created_at)).toEqual(returned.map(record => record.created_at).sort().reverse());
    } finally {
      await Promise.all(records.map(record => rm(`${storeDirectory}/${record.id}.json`, { force: true })));
    }
  });

  it.each([undefined, "0:00 into recording"])("persists and renders evidence with offset %s", async (startLabel) => {
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
            ...(startLabel ? { start_label: startLabel } : {}),
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
        investigations: expect.arrayContaining([expect.objectContaining({ id: record.id })]),
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
    expect(html).toContain("Question asked");
    expect(html).toContain("What happened?");
    expect(html).toContain("AI observations");
    expect(html).toContain("AI interpretation");
    expect(html).toContain("Play exact clip");
    expect(html).toContain('onclick="copyBriefing(this)"');
    const copiedField = html.match(/<textarea[^>]*id="briefing-text"[^>]*>([\s\S]*?)<\/textarea>/)?.[1];
    expect(copiedField).toContain("Question: What happened?");
    expect(copiedField).toContain("AI interpretation:");
    expect(copiedField).toContain("[E1]");
    expect(copiedField).toContain("&lt;script&gt;");
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]);
    scripts.forEach(script => expect(() => new Script(script)).not.toThrow());
    const field = { value: "Saved briefing", dataset: {}, hidden: true, style: { cssText: "" }, focus: jest.fn(), select: jest.fn() };
    const copyStatus = { textContent: "" };
    const writeText = jest.fn(async (_text: string) => undefined);
    const sandbox = {
      URL,
      navigator: { clipboard: { writeText } },
      location: { href: `http://thor.test:7777${record.report_url}` },
      document: {
        getElementById: (id: string) => id === "briefing-text" ? field : copyStatus,
        querySelectorAll: (selector: string) => selector === ".evidence article" ? [{
          id: "E1", querySelector: (tag: string) => ({ textContent: tag === "b" ? "E1 · Clip" : "Warehouse · 0:00" }),
        }] : [],
      },
    };
    const copyScript = new Script(scripts.at(-1)! + ";copyBriefing({focus(){}})");
    await copyScript.runInNewContext(sandbox);
    await copyScript.runInNewContext(sandbox);
    expect(writeText).toHaveBeenCalledTimes(2);
    expect(writeText.mock.calls[0]).toEqual(writeText.mock.calls[1]);
    expect(writeText.mock.calls[0][0]).toContain(`\nhttp://thor.test:7777${record.report_url}#E1`);
    expect(copyStatus.textContent).toBe("Briefing copied, including evidence links.");
    writeText.mockRejectedValueOnce(new Error("Clipboard denied"));
    await copyScript.runInNewContext(sandbox);
    expect(field.hidden).toBe(false);
    expect(field.select).toHaveBeenCalled();
    expect(copyStatus.textContent).toContain("Briefing selected. Press Ctrl+C");
    expect(html).toContain("Media retained locally on this device");
    expect(html).toContain(`/api/vision/evidence-media?key=${retainedKey}`);
    expect(html).toContain("sensorId=warehouse-sensor");
    expect(html).toContain("startTime=2026-08-12T10%3A00%3A00Z");
    if (startLabel) {
      expect(html).toContain(`<time>${startLabel}</time>`);
      expect(html).not.toContain('data-local-time="2026-08-12T10:00:00Z"');
    } else {
      expect(html).toContain('data-local-time="2026-08-12T10:00:00Z"');
    }
    expect(html).toContain("date.toLocaleString()");
    expect(html).toContain('rel="icon" href="data:image/svg+xml');
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain(
      "Reviewed by operator &lt;script&gt;alert(1)&lt;/script&gt;"
    );
  });

  it("exports a self-contained briefing with absolute device evidence links and no duplicate answer", async () => {
    const source = {
      analysis, title: "Export check", query: analysis.query,
      severity: "low", disposition: "resolved", notes: "",
      evidence: [{ ...analysis.evidence[0], sensor_id: "warehouse-sensor", title: "Selected clip", image_url: "" }],
    };
    const create = responseHarness();
    await handler(request("POST", {
      ...source,
      analysis: { ...source.analysis, question: "What does <script> mean here?", summary: source.analysis.observations[0].text, interpretations: [] },
    }), create.response);
    const record = create.state.body as { id: string };
    const download = responseHarness();
    await handler(request("GET", undefined, { id: record.id, format: "html", download: "true" }), download.response);
    const html = String(download.state.body);
    expect(download.state.statusCode).toBe(200);
    expect(download.headers.get("Content-Disposition")).toContain("attachment;");
    expect(html).toContain(`href="http://thor.test:7777/api/vision/investigations?id=${record.id}&amp;format=html#E1"`);
    expect(html).toContain("Question asked");
    expect(html).toContain("What does &lt;script&gt; mean here?");
    expect(html).not.toContain("What does <script>");
    expect(html).toContain("Video stays on this device");
    expect(html).not.toContain("<video");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<h2>AI interpretation</h2>");
    expect(html).not.toContain("<h2>Observed facts</h2>");
    expect(html.split(source.analysis.observations[0].text).length - 1).toBe(1);
    expect(html).toContain('href="#E1"');
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
