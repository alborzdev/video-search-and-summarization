// SPDX-License-Identifier: MIT

import { InvestigateWorkspace } from "../InvestigateWorkspace";
import type { VisionStream } from "../types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

const liveCamera: VisionStream = {
  isMain: true,
  metadata: {},
  name: "traffic-intersection",
  sensorId: "traffic-sensor",
  streamId: "traffic-stream",
  type: "rtsp",
  url: "rtsp://thor.test/traffic",
  vodUrl: "rtsp://thor.test/traffic",
};

const recordedCamera: VisionStream = {
  isMain: true,
  metadata: {},
  name: "warehouse-main",
  sensorId: "warehouse-sensor",
  streamId: "warehouse-stream",
  type: "FileDownload",
  url: "/warehouse.mp4",
  vodUrl: "/warehouse.mp4",
};

const resultPayload = [
  {
    critic_result: { result: "confirmed" as const },
    description: "Older confirmed vehicle",
    end_time: "2026-08-12T10:00:28Z",
    object_ids: ["vehicle-1"],
    screenshot_url: "/confirmed.jpg",
    sensor_id: "traffic-sensor",
    similarity: 0.72,
    start_time: "2026-08-12T10:00:00Z",
    video_name: "traffic-intersection_20260812_100000_clip.mp4",
  },
  {
    critic_result: { result: "unverified" as const },
    description: "Newest unverified person",
    end_time: "2026-08-12T12:00:28Z",
    object_ids: ["person-1"],
    screenshot_url: "/unverified.jpg",
    sensor_id: "traffic-sensor",
    similarity: 0.61,
    start_time: "2026-08-12T12:00:00Z",
    video_name: "traffic-intersection_20260812_120000_clip.mp4",
  },
  {
    critic_result: { result: "rejected" as const },
    description: "Rejected false positive",
    end_time: "2026-08-12T11:00:28Z",
    object_ids: [],
    screenshot_url: "/rejected.jpg",
    sensor_id: "traffic-sensor",
    similarity: 0.99,
    start_time: "2026-08-12T11:00:00Z",
    video_name: "traffic-intersection_20260812_110000_clip.mp4",
  },
];

function requestBody(
  fetchMock: jest.Mock,
  index: number
): Record<string, unknown> {
  return JSON.parse(String(fetchMock.mock.calls[index][1]?.body));
}

describe("InvestigateWorkspace", () => {
  let pauseSpy: jest.SpyInstance;

  beforeEach(() => {
    pauseSpy = jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({ data: resultPayload }),
    })) as jest.Mock;
  });

  afterEach(() => {
    pauseSpy.mockRestore();
    jest.restoreAllMocks();
  });

  it("broadens a zero-result camera-scoped search before declaring no evidence", async () => {
    const fetchMock = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        data: fetchMock.mock.calls.length === 1 ? [] : resultPayload,
      }),
    }));
    global.fetch = fetchMock as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ camera: recordedCamera, query: "person" }}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestBody(fetchMock, 0).min_cosine_similarity).toBe("0.25");
    expect(requestBody(fetchMock, 1).min_cosine_similarity).toBe("0.15");
    expect(
      await screen.findByRole("heading", { name: "Older confirmed vehicle" })
    ).toBeInTheDocument();
  });

  it("explains when local search is unavailable instead of exposing a bare 422", async () => {
    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 422,
      json: async () => ({
        code: "workflow_error",
        message: "500: Search error: All connection attempts failed",
      }),
    })) as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ camera: liveCamera, query: "robot" }}
      />
    );

    expect(
      await screen.findByText(
        /embedding service is offline\. Check System readiness, then retry/i
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/Search returned 422/i)).not.toBeInTheDocument();
  });

  it("uses broad recall and source-diverse relevance for all-source searches", async () => {
    const warehouseResults = Array.from({ length: 6 }, (_, index) => ({
      ...resultPayload[0],
      critic_result: undefined,
      description: `Warehouse person ${index + 1}`,
      end_time: `2025-01-01T00:00:${String(index + 5).padStart(2, "0")}Z`,
      sensor_id: "warehouse-sensor",
      similarity: 0.23 - index / 100,
      start_time: `2025-01-01T00:00:${String(index).padStart(2, "0")}Z`,
      video_name:
        "nvidia-warehouse-loading-dock-camera-01-4min_20250101_000000_demo.mp4",
    }));
    const crossSourceResults = [
      {
        ...resultPayload[0],
        critic_result: undefined,
        description: "Pedestrian crossing",
        sensor_id: "jaywalking-sensor",
        similarity: 0.166,
        video_name: "sample-sim-jaywalking_20250101_000000_demo.mp4",
      },
      {
        ...resultPayload[0],
        critic_result: undefined,
        description: "Person at intersection",
        sensor_id: "traffic-sensor",
        similarity: 0.125,
        video_name: "sample-sim-traffic_20250101_000000_demo.mp4",
      },
    ];
    const fetchMock = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        data: [...warehouseResults, ...crossSourceResults],
      }),
    }));
    global.fetch = fetchMock as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "person" }}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(
      fetchMock.mock.calls.map((_, index) => requestBody(fetchMock, index))
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          min_cosine_similarity: "0.12",
          source_type: "video_file",
          agent_mode: false,
          top_k: 18,
          use_critic: false,
          video_sources: [],
        }),
        expect.objectContaining({
          min_cosine_similarity: "0.12",
          source_type: "rtsp",
          agent_mode: false,
          top_k: 18,
          use_critic: false,
          video_sources: [],
        }),
      ])
    );
    expect(
      await screen.findByText("Traffic — Main Intersection")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Traffic — Pedestrian Crossing")
    ).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(3);
    expect(screen.getByText(/6 adjacent matches grouped/i)).toBeInTheDocument();
  });

  it("fuses retained incidents with honest provenance and verifier warnings", async () => {
    const fetchMock = jest.fn(async (url: string) => {
      if (url.endsWith("/v1/live/streams")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/search/fusion")) {
        return {
          ok: true,
          json: async () => ({
            data: [],
            search_messages: [
              "VLM verification unavailable. Returning search results without critic verification.",
            ],
          }),
        };
      }
      if (url === "/api/vision/incidents") {
        return {
          ok: true,
          json: async () => ({
            incidents: [
              {
                Id: "incident-1",
                end: "2026-08-17T19:40:02Z",
                info: {
                  reasoning: "A person is visible in the monitored area.",
                  verdict: "confirmed",
                },
                objectIds: ["person-42"],
                sensorId: liveCamera.name,
                timestamp: "2026-08-17T19:40:00Z",
              },
            ],
          }),
        };
      }
      if (url.includes("/timelines")) {
        return {
          ok: true,
          json: async () => [
            {
              startTime: "2026-08-17T19:00:00Z",
              endTime: "2026-08-17T20:00:00Z",
            },
          ],
        };
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ camera: liveCamera, query: "person" }}
        vstApiUrl="http://thor.test/vst"
      />
    );

    expect(
      await screen.findByRole("heading", {
        name: "Person observed in monitored area",
      })
    ).toBeInTheDocument();
    expect(screen.getByText("Confirmed Incident")).toBeInTheDocument();
    expect(screen.getByText("Detector Match")).toBeInTheDocument();
    expect(screen.getByText("VLM Verified")).toBeInTheDocument();
    expect(
      screen.getByText(/VLM verification unavailable/i)
    ).toBeInTheDocument();
  });

  it("preserves a live camera scope and source type when the operator resubmits", async () => {
    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ camera: liveCamera, query: "Find red vehicles" }}
      />
    );

    const fetchMock = global.fetch as jest.Mock;
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(requestBody(fetchMock, 0)).toEqual(
      expect.objectContaining({
        min_cosine_similarity: "0.25",
        query: "Find red vehicles",
        source_type: "rtsp",
        video_sources: ["traffic-intersection"],
      })
    );

    fireEvent.change(
      screen.getByRole("textbox", { name: "Search video evidence" }),
      {
        target: { value: "Find stopped vehicles" },
      }
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestBody(fetchMock, 1)).toEqual(
      expect.objectContaining({
        query: "Find stopped vehicles",
        source_type: "rtsp",
        video_sources: ["traffic-intersection"],
      })
    );
  });

  it("sends source, time, and footage controls to the VSS search API", async () => {
    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{
          camera: recordedCamera,
          query: "Find forklift activity",
        }}
      />
    );

    const fetchMock = global.fetch as jest.Mock;
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByRole("combobox", { name: "Search source" }), {
      target: { value: "all" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestBody(fetchMock, 1).video_sources).toEqual([]);

    fireEvent.change(screen.getByRole("combobox", { name: "Time range" }), {
      target: { value: "1h" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const timedRequest = requestBody(fetchMock, 2);
    expect(
      Date.parse(String(timedRequest.timestamp_end)) -
        Date.parse(String(timedRequest.timestamp_start))
    ).toBe(60 * 60 * 1000);
    expect(timedRequest.video_sources).toEqual([]);

    fireEvent.change(screen.getByRole("combobox", { name: "Footage type" }), {
      target: { value: "rtsp" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(requestBody(fetchMock, 3)).toEqual(
      expect.objectContaining({
        source_type: "rtsp",
        video_sources: [],
      })
    );
  });

  it("loads every VST source so a direct investigation can be camera-scoped", async () => {
    const fetchMock = jest.fn(async (url: string) => {
      if (url.endsWith("/v1/live/streams")) {
        const withoutSensor = ({
          sensorId: _sensorId,
          ...stream
        }: VisionStream) => stream;
        return {
          ok: true,
          json: async () => [
            { [recordedCamera.sensorId]: [withoutSensor(recordedCamera)] },
            { [liveCamera.sensorId]: [withoutSensor(liveCamera)] },
          ],
        };
      }
      if (url.endsWith("/search/fusion")) {
        return { ok: true, json: async () => ({ data: resultPayload }) };
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find safety activity" }}
        vstApiUrl="http://thor.test/vst"
      />
    );

    await screen.findByRole("option", { name: "Warehouse Main" });
    fireEvent.change(screen.getByRole("combobox", { name: "Search source" }), {
      target: { value: "warehouse-stream" },
    });

    await waitFor(() => {
      const searches = fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith("/search/fusion")
      );
      expect(searches).toHaveLength(3);
      expect(JSON.parse(String(searches[2][1]?.body))).toEqual(
        expect.objectContaining({
          source_type: "video_file",
          video_sources: ["warehouse-main"],
        })
      );
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Footage type" }), {
      target: { value: "rtsp" },
    });
    expect(
      await screen.findByRole("option", { name: "Traffic Intersection" })
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Search source" })).toHaveValue(
      "all"
    );
  });

  it("sorts and filters the returned evidence without hiding review state", async () => {
    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find safety activity" }}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Older confirmed vehicle")).toBeInTheDocument()
    );
    expect(
      screen
        .getAllByRole("heading", { level: 2 })
        .map((heading) => heading.textContent)
    ).toEqual(["Older confirmed vehicle", "Newest unverified person"]);
    expect(
      screen.queryByText("Rejected false positive")
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Newest first" }));
    expect(
      screen
        .getAllByRole("heading", { level: 2 })
        .map((heading) => heading.textContent)
    ).toEqual(["Newest unverified person", "Older confirmed vehicle"]);

    fireEvent.change(screen.getByRole("combobox", { name: "Review status" }), {
      target: { value: "all" },
    });
    expect(
      screen
        .getAllByRole("heading", { level: 2 })
        .map((heading) => heading.textContent)
    ).toEqual([
      "Newest unverified person",
      "Rejected false positive",
      "Older confirmed vehicle",
    ]);

    fireEvent.change(screen.getByRole("combobox", { name: "Review status" }), {
      target: { value: "confirmed" },
    });
    expect(
      screen
        .getAllByRole("heading", { level: 2 })
        .map((heading) => heading.textContent)
    ).toEqual(["Older confirmed vehicle"]);
  });

  it("keeps expired recordings out of usable evidence and labels them under all statuses", async () => {
    const fetchMock = jest.fn(async (url: string) => {
      if (url.endsWith("/v1/live/streams")) {
        return { ok: true, json: async () => [] };
      }
      if (url.endsWith("/search/fusion")) {
        return {
          ok: true,
          json: async () => ({ data: resultPayload.slice(0, 2) }),
        };
      }
      if (url.endsWith("/v1/storage/traffic-sensor/timelines")) {
        return {
          ok: true,
          json: async () => [
            {
              startTime: "2026-08-12T11:30:00Z",
              endTime: "2026-08-12T12:30:00Z",
            },
          ],
        };
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find safety activity" }}
        vstApiUrl="http://thor.test/vst"
      />
    );

    expect(
      await screen.findByRole("heading", { name: "Newest unverified person" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Older confirmed vehicle" })
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Review status" }), {
      target: { value: "all" },
    });

    expect(
      await screen.findByRole("heading", { name: "Older confirmed vehicle" })
    ).toBeInTheDocument();
    expect(
      screen.queryByAltText("Older confirmed vehicle")
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Recording expired")).toHaveLength(2);
    expect(
      screen.getByRole("button", {
        name: "Recording expired for Older confirmed vehicle",
      })
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Expired Older confirmed vehicle cannot be used as evidence",
      })
    ).toBeDisabled();
  });

  it("routes VST result pictures through the same-origin image proxy", async () => {
    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find safety activity" }}
        vstApiUrl="http://thor.test:30000"
      />
    );

    const image = await screen.findByAltText("Older confirmed vehicle");
    expect(image).toHaveAttribute(
      "src",
      "/api/vision/vst-image?path=%2Fconfirmed.jpg"
    );
  });

  it("keeps long result sets scannable and loads six more on demand", async () => {
    const manyResults = Array.from({ length: 14 }, (_, index) => ({
      ...resultPayload[0],
      description: `Evidence ${index + 1}`,
      similarity: 1 - index / 100,
      start_time: `2026-08-12T10:${String(index).padStart(2, "0")}:00Z`,
    }));
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ data: manyResults }),
    });

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find activity" }}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Evidence 1")).toBeInTheDocument()
    );
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(6);
    expect(screen.getByText("Showing 6 of 14 matches")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Load more matches/i }));
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(12);
    expect(screen.getByText("Showing 12 of 14 matches")).toBeInTheDocument();
  });

  it("visually inspects selected clips and renders citation-bearing analysis", async () => {
    const fetchMock = jest.fn(
      async (input: RequestInfo | URL, options?: RequestInit) => {
        if (String(input) === "/api/vision/evidence-analysis") {
          return {
            ok: true,
            json: async () => ({
              evidence: [
                {
                  client_id:
                    "traffic-sensor:2026-08-12T10:00:00Z:2026-08-12T10:00:28Z",
                  end_time: "2026-08-12T10:00:28Z",
                  evidence_id: "E1",
                  inspection_source: "retained_cosmos_caption",
                  match_type: "Verified event",
                  observation: "A vehicle crosses the monitored area.",
                  source_name: "Traffic — Main Intersection",
                  start_time: "2026-08-12T10:00:00Z",
                },
              ],
              interpretations: [
                {
                  evidence_ids: ["E1"],
                  text: "The movement may require an operator review.",
                },
              ],
              observations: [
                {
                  evidence_ids: ["E1"],
                  text: "A vehicle crosses the monitored area.",
                },
              ],
              query: "Find safety activity",
              question: "Find safety activity",
              status: "complete",
              suggested_questions: ["Was a person close to the vehicle?"],
              summary:
                "One selected clip shows a vehicle crossing the monitored area.",
              timeline: [
                {
                  end_time: "2026-08-12T10:00:28Z",
                  evidence_id: "E1",
                  label: "Vehicle crosses monitored area",
                  source_name: "Traffic — Main Intersection",
                  start_time: "2026-08-12T10:00:00Z",
                },
              ],
            }),
          };
        }
        if (String(input) === "/api/vision/investigations") {
          const request = JSON.parse(String(options?.body));
          return {
            ok: true,
            status: 201,
            json: async () => ({
              ...request,
              created_at: "2026-08-12T13:00:00Z",
              id: "11111111-1111-4111-8111-111111111111",
              report_url:
                "/api/vision/investigations?id=11111111-1111-4111-8111-111111111111&format=html",
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({ data: resultPayload }),
        };
      }
    );
    global.fetch = fetchMock as jest.Mock;

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find safety activity" }}
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Older confirmed vehicle")).toBeInTheDocument()
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Use Older confirmed vehicle as evidence",
      })
    );
    expect(
      screen.getByRole("button", {
        name: "Remove Older confirmed vehicle from evidence",
      })
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("region", { name: "Selected evidence workspace" })
    ).toHaveTextContent("1 selected clip");

    fireEvent.click(screen.getByRole("button", { name: "Analyze 1 selected" }));
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "Selected evidence workspace" })
      ).toHaveTextContent(
        "One selected clip shows a vehicle crossing the monitored area."
      )
    );
    expect(screen.getAllByRole("button", { name: "E1" })).not.toHaveLength(0);
    const analysisRequest = fetchMock.mock.calls.find(
      ([input]) => String(input) === "/api/vision/evidence-analysis"
    );
    expect(JSON.parse(String(analysisRequest?.[1]?.body))).toEqual(
      expect.objectContaining({
        evidence: [
          expect.objectContaining({
            sensor_id: "traffic-sensor",
            start_time: "2026-08-12T10:00:00Z",
          }),
        ],
        query: "Find safety activity",
      })
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: /Was a person close to the vehicle/i,
      })
    );
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([input]) => String(input) === "/api/vision/evidence-analysis"
        )
      ).toHaveLength(2)
    );
    const followUpRequest = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/vision/evidence-analysis"
    )[1];
    expect(JSON.parse(String(followUpRequest[1]?.body))).toEqual(
      expect.objectContaining({
        question: "Was a person close to the vehicle?",
      })
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Create incident and report" })
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Investigation severity" }),
      { target: { value: "high" } }
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Investigation notes" }),
      { target: { value: "Operator reviewed this movement." } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Save investigation" }));
    expect(await screen.findByText("Investigation saved")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View evidence report" })
    ).toHaveAttribute(
      "href",
      "/api/vision/investigations?id=11111111-1111-4111-8111-111111111111&format=html"
    );
    const investigationRequest = fetchMock.mock.calls.find(
      ([input]) => String(input) === "/api/vision/investigations"
    );
    expect(JSON.parse(String(investigationRequest?.[1]?.body))).toEqual(
      expect.objectContaining({
        disposition: "open",
        evidence: [
          expect.objectContaining({
            sensor_id: "traffic-sensor",
            start_time: "2026-08-12T10:00:00Z",
          }),
        ],
        notes: "Operator reviewed this movement.",
        severity: "high",
      })
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(
      screen.getByRole("button", {
        name: "Use Older confirmed vehicle as evidence",
      })
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("uses honest visitor-facing titles and clip-relative time when NVIDIA leaves descriptions empty", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [
          {
            ...resultPayload[0],
            critic_result: undefined,
            description: "",
            start_time: "2025-01-01T00:03:10Z",
            end_time: "2025-01-01T00:03:15Z",
            video_name:
              "nvidia-warehouse-loading-dock-camera-01-4min_20250101_000000_139b4.mp4",
          },
        ],
      }),
    });

    render(
      <InvestigateWorkspace
        agentApiUrl="http://thor.test/agent"
        initialRequest={{ query: "Find forklift activity" }}
      />
    );

    expect(
      await screen.findByRole("heading", { name: "Forklift activity" })
    ).toBeInTheDocument();
    expect(
      screen.getByText("3:10 into recording · 00:05 clip")
    ).toBeInTheDocument();
    expect(screen.getByText("Semantic Match")).toBeInTheDocument();
    expect(screen.getByText("Detector Match")).toBeInTheDocument();
    expect(
      screen.queryByText(/Model-ranked evidence/i)
    ).not.toBeInTheDocument();
  });

  it("selects a real detector box and sends exact visual-reference identity", async () => {
    const OriginalImage = globalThis.Image;
    (globalThis as any).Image = class MockImage {
      height = 1080;
      naturalHeight = 1080;
      naturalWidth = 1920;
      onerror: (() => void) | null = null;
      onload: (() => void) | null = null;
      width = 1920;
      set src(_value: string) {
        Promise.resolve().then(() => this.onload?.());
      }
    };

    const visualResults = [
      {
        critic_result: undefined,
        description: "Attribute match at 2025-01-01T00:03:55.383000Z",
        end_time: "2025-01-01T00:03:55.400Z",
        object_ids: ["53"],
        screenshot_url: "/visual.jpg",
        sensor_id: "warehouse-stream",
        similarity: 0.91,
        start_time: "2025-01-01T00:03:55.366Z",
        video_name: "warehouse-main",
      },
    ];
    const fetchMock = jest.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/search/fusion")) {
        return { ok: true, json: async () => ({ data: resultPayload }) };
      }
      if (url.includes("/api/vision/evidence?")) {
        return {
          ok: true,
          json: async () => ({
            startTime: "2026-08-12T10:00:00.000Z",
            videoUrl: "http://thor.test/evidence.mp4",
          }),
        };
      }
      if (url.includes("/frames?")) {
        return {
          ok: true,
          json: async () => ({
            frames: [
              {
                objects: [
                  {
                    bbox: {
                      bottomY: 500,
                      leftX: 100,
                      rightX: 420,
                      topY: 120,
                    },
                    id: "39",
                    type: "Person",
                  },
                ],
                timestamp: "2026-08-12T10:00:00.033Z",
              },
            ],
          }),
        };
      }
      if (url.endsWith("/search/image")) {
        return { ok: true, json: async () => ({ data: visualResults }) };
      }
      throw new Error(`Unexpected request: ${url} ${String(options?.method)}`);
    });
    global.fetch = fetchMock as jest.Mock;

    try {
      render(
        <InvestigateWorkspace
          agentApiUrl="http://thor.test/agent"
          initialRequest={{ camera: recordedCamera, query: "Find people" }}
          mdxWebApiUrl="http://thor.test/analytics"
          searchByImageEnabled
          vstApiUrl="http://thor.test/vst"
        />
      );

      await screen.findByText("Older confirmed vehicle");
      fireEvent.click(screen.getAllByRole("button", { name: /Play clip/i })[0]);
      fireEvent.click(
        await screen.findByRole("button", { name: /Find similar object/i })
      );
      fireEvent.click(
        await screen.findByRole("button", { name: "Select Person 39" })
      );
      fireEvent.click(screen.getByRole("button", { name: /^Find similar$/i }));

      await screen.findByText("Similar to selected person");
      expect(
        screen.getByText("Ranked by object appearance")
      ).toBeInTheDocument();
      expect(screen.queryByText(/% visual match/)).not.toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Visually similar person" })
      ).toBeInTheDocument();

      const imageRequest = fetchMock.mock.calls.find(([url]) =>
        String(url).endsWith("/search/image")
      );
      expect(JSON.parse(String(imageRequest?.[1]?.body))).toEqual({
        agent_mode: false,
        query: "Visually similar person",
        reference_object: {
          object_id: "39",
          sensor_id: "traffic-sensor",
          sensor_name: "traffic-intersection",
          timestamp: "2026-08-12T10:00:00.033Z",
        },
        source_type: "video_file",
        top_k: 24,
      });
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("keeps the box selector open when a detected object lacks an embedding", async () => {
    const OriginalImage = globalThis.Image;
    (globalThis as any).Image = class MockImage {
      height = 1080;
      naturalHeight = 1080;
      naturalWidth = 1920;
      onerror: (() => void) | null = null;
      onload: (() => void) | null = null;
      width = 1920;
      set src(_value: string) {
        Promise.resolve().then(() => this.onload?.());
      }
    };
    global.fetch = jest.fn(async (url: string) => {
      if (url.endsWith("/search/fusion")) {
        return { ok: true, json: async () => ({ data: resultPayload }) };
      }
      if (url.includes("/api/vision/evidence?")) {
        return {
          ok: true,
          json: async () => ({
            startTime: "2026-08-12T10:00:00.000Z",
            videoUrl: "http://thor.test/evidence.mp4",
          }),
        };
      }
      if (url.includes("/frames?")) {
        return {
          ok: true,
          json: async () => ({
            frames: [
              {
                objects: [
                  {
                    bbox: { bottomY: 500, leftX: 100, rightX: 420, topY: 120 },
                    id: "2",
                    type: "Pallet",
                  },
                ],
                timestamp: "2026-08-12T10:00:00.033Z",
              },
            ],
          }),
        };
      }
      if (url.endsWith("/search/image")) {
        return {
          ok: true,
          json: async () => ({
            data: [],
            search_messages: ["Reference object ID '2' not found"],
          }),
        };
      }
      throw new Error(`Unexpected request: ${url}`);
    }) as jest.Mock;

    try {
      render(
        <InvestigateWorkspace
          agentApiUrl="http://thor.test/agent"
          initialRequest={{ camera: recordedCamera, query: "Find pallets" }}
          mdxWebApiUrl="http://thor.test/analytics"
          searchByImageEnabled
          vstApiUrl="http://thor.test/vst"
        />
      );
      await screen.findByText("Older confirmed vehicle");
      fireEvent.click(screen.getAllByRole("button", { name: /Play clip/i })[0]);
      fireEvent.click(
        await screen.findByRole("button", { name: /Find similar object/i })
      );
      fireEvent.click(
        await screen.findByRole("button", { name: "Select Pallet 2" })
      );
      fireEvent.click(screen.getByRole("button", { name: /^Find similar$/i }));

      expect(
        await screen.findByText(/not in the visual-similarity index/i)
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Select Pallet 2" })
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Visual search could not complete")
      ).not.toBeInTheDocument();
    } finally {
      globalThis.Image = OriginalImage;
    }
  });
});
