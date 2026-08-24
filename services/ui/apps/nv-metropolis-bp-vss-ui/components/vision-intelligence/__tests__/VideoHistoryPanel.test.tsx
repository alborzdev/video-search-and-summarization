// SPDX-License-Identifier: MIT

import { VideoHistoryPanel } from "../VideoHistoryPanel";
import type { VisionStream } from "../types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

const stream: VisionStream = {
  isMain: true,
  metadata: {},
  name: "sample-sim-traffic",
  sensorId: "11111111-1111-4111-8111-111111111111",
  streamId: "11111111-1111-4111-8111-111111111111",
  type: "FileDownload",
  url: "/traffic.mp4",
  vodUrl: "/traffic.mp4",
};

const record = {
  events: ["pedestrian crossing"],
  knowledgeId: "22222222-2222-4222-8222-222222222222",
  lastSynchronizedAt: "2026-08-12T10:05:00Z",
  scenario: "traffic monitoring",
  sourceId: stream.sensorId,
  sourceKind: "replay",
  sourceName: stream.name,
  startedAt: "2026-08-12T10:00:00Z",
  status: "ready",
  summary: JSON.stringify({
    video_summary: "Pedestrians and vehicles cross the intersection.",
  }),
  timelineEnd: "2026-08-12T10:04:00Z",
  timelineStart: "2026-08-12T10:00:00Z",
};

describe("VideoHistoryPanel", () => {
  afterEach(() => jest.restoreAllMocks());

  it("builds an unconfigured source with scenario-aware defaults", async () => {
    const fetchMock = jest.fn(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        if (String(input).includes("?sourceId=")) {
          return {
            ok: false,
            status: 404,
            json: async () => ({ error: "Not built" }),
          } as Response;
        }
        if (
          String(input) === "/api/vision/video-history" &&
          options?.method === "POST"
        ) {
          return { ok: true, json: async () => record } as Response;
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }
    );
    global.fetch = fetchMock;

    render(
      <VideoHistoryPanel
        onClose={jest.fn()}
        onInvestigate={jest.fn()}
        stream={stream}
      />
    );

    expect(
      await screen.findByRole("textbox", { name: "Video history scenario" })
    ).toHaveValue("traffic monitoring");
    fireEvent.click(
      screen.getByRole("button", { name: "Build searchable history" })
    );
    expect(await screen.findByText("History ready")).toBeInTheDocument();
    const buildRequest = fetchMock.mock.calls.find(
      ([input, options]) =>
        String(input) === "/api/vision/video-history" &&
        options?.method === "POST"
    );
    expect(JSON.parse(String(buildRequest?.[1]?.body))).toEqual(
      expect.objectContaining({
        events: expect.arrayContaining([
          "pedestrian crossing",
          "near collision",
        ]),
        scenario: "traffic monitoring",
        source: expect.objectContaining({ kind: "replay" }),
      })
    );
  });

  it("asks source-scoped history and opens an exact cited clip", async () => {
    const fetchMock = jest.fn(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        const url = String(input);
        if (
          url.includes("/api/vision/video-history?sourceId=") &&
          !options?.method
        ) {
          return { ok: true, json: async () => record } as Response;
        }
        if (url === "/api/vision/video-history" && options?.method === "POST") {
          return {
            ok: true,
            json: async () => ({
              answer: "A pedestrian crossed [00:00:05-00:00:10].",
              citations: [
                {
                  endTime: "2026-08-12T10:00:10.000Z",
                  label: "[00:00:05-00:00:10]",
                  startTime: "2026-08-12T10:00:05.000Z",
                },
              ],
              generatedAt: "2026-08-12T10:06:00Z",
              knowledgeId: record.knowledgeId,
            }),
          } as Response;
        }
        if (url.startsWith("/api/vision/evidence?")) {
          return {
            ok: true,
            json: async () => ({ videoUrl: "/vst/evidence.mp4" }),
          } as Response;
        }
        throw new Error(`Unexpected request: ${url}`);
      }
    );
    global.fetch = fetchMock;

    render(
      <VideoHistoryPanel
        onClose={jest.fn()}
        onInvestigate={jest.fn()}
        stream={stream}
      />
    );

    expect(
      await screen.findByText(
        "Pedestrians and vehicles cross the intersection."
      )
    ).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Ask video history" }),
      {
        target: { value: "When did a pedestrian cross?" },
      }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Ask video history question" })
    );
    expect(await screen.findByText(/A pedestrian crossed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Evidence 1/ }));
    const citation = await screen.findByRole("dialog", {
      name: "History citation",
    });
    await waitFor(() =>
      expect(citation.querySelector("video")).toHaveAttribute(
        "src",
        "/vst/evidence.mp4"
      )
    );
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url = String(input);
        return (
          url.includes("startTime=2026-08-12T10%3A00%3A05.000Z") &&
          url.includes("endTime=2026-08-12T10%3A00%3A10.000Z")
        );
      })
    ).toBe(true);
  });

  it("recovers when a live graph rebuild outlives the ingress response timeout", async () => {
    const liveRecord = { ...record, sourceKind: "live" as const };
    let buildStarted = false;
    const fetchMock = jest.fn(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/vision/video-history?sourceId=")) {
          return {
            ok: true,
            status: 200,
            json: async () =>
              buildStarted
                ? { ...liveRecord, lastSynchronizedAt: "2026-08-12T10:10:00Z" }
                : liveRecord,
          } as Response;
        }
        if (url === "/api/vision/video-history" && options?.method === "POST") {
          buildStarted = true;
          return {
            ok: false,
            status: 504,
            json: async () => {
              throw new SyntaxError("Unexpected token '<'");
            },
          } as unknown as Response;
        }
        throw new Error(`Unexpected request: ${url}`);
      }
    );
    global.fetch = fetchMock;

    render(
      <VideoHistoryPanel
        onClose={jest.fn()}
        onInvestigate={jest.fn()}
        stream={{ ...stream, type: "rtsp", url: "rtsp://camera.test/live" }}
      />
    );

    fireEvent.click(await screen.findByRole("button", { name: "Sync new history" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) =>
          String(input).includes("/api/vision/video-history?sourceId=")
        ).length
      ).toBeGreaterThanOrEqual(2)
    );
    expect(screen.getByText("History ready")).toBeInTheDocument();
    expect(screen.queryByText(/Unexpected token/i)).not.toBeInTheDocument();
  });

  it("polls an accepted background history build until it is ready", async () => {
    const buildingRecord = {
      ...record,
      knowledgeId: stream.sensorId,
      status: "building" as const,
    };
    let buildStarted = false;
    const fetchMock = jest.fn(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/vision/video-history?sourceId=")) {
          if (!buildStarted)
            return {
              ok: false,
              status: 404,
              json: async () => ({ error: "Not built" }),
            } as Response;
          return {
            ok: true,
            status: 200,
            json: async () => record,
          } as Response;
        }
        if (url === "/api/vision/video-history" && options?.method === "POST") {
          buildStarted = true;
          return {
            ok: true,
            status: 202,
            json: async () => buildingRecord,
          } as Response;
        }
        throw new Error(`Unexpected request: ${url}`);
      }
    );
    global.fetch = fetchMock;

    render(
      <VideoHistoryPanel
        onClose={jest.fn()}
        onInvestigate={jest.fn()}
        stream={stream}
      />
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Build searchable history" })
    );
    expect(await screen.findByText("History ready")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).includes("/api/vision/video-history?sourceId=")
      )
    ).toHaveLength(2);
  });
});
