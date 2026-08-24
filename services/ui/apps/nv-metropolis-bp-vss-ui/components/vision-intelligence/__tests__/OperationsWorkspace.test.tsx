// SPDX-License-Identifier: MIT

import { OperationsWorkspace } from "../OperationsWorkspace";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import React from "react";

const streamsResponse = [
  {
    warehouse: [
      {
        isMain: true,
        metadata: {},
        name: "warehouse-camera",
        streamId: "warehouse",
        type: "FileDownload",
        url: "/warehouse.mp4",
        vodUrl: "/warehouse.mp4",
      },
    ],
  },
  {
    traffic: [
      {
        isMain: true,
        metadata: {},
        name: "sample-sim-traffic",
        streamId: "traffic",
        type: "FileDownload",
        url: "/traffic.mp4",
        vodUrl: "/traffic.mp4",
      },
    ],
  },
];

describe("OperationsWorkspace", () => {
  beforeEach(() => {
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/v1/live/streams")) {
        return { ok: true, json: async () => streamsResponse } as Response;
      }
      if (url.includes("/timelines")) {
        return {
          ok: true,
          json: async () => [
            {
              startTime: "2025-01-01T00:00:00Z",
              endTime: "2025-01-01T00:01:00Z",
            },
          ],
        } as Response;
      }
      if (url.includes("/api/vision/source-intelligence")) {
        const warehouse = url.includes("warehouse-camera");
        return {
          ok: true,
          json: async () =>
            warehouse
              ? {
                  evidenceEvents: 6,
                  semanticSegments: 48,
                  trackedObservations: 3724,
                }
              : {
                  evidenceEvents: 0,
                  semanticSegments: 27,
                  trackedObservations: 0,
                },
        } as Response;
      }
      if (url === "/api/vision/incidents") {
        return {
          ok: true,
          json: async () => ({
            incidents: [
              {
                Id: "warehouse-event",
                timestamp: "2025-01-01T00:00:20Z",
                end: "2025-01-01T00:00:23Z",
                sensorId: "warehouse-camera",
                objectIds: ["1"],
                info: {
                  verdict: "confirmed",
                  reasoning: "A person is visible in the monitored area.",
                },
              },
            ],
          }),
        } as Response;
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }) as jest.Mock;
  });

  afterEach(() => jest.restoreAllMocks());

  it("loads on LAN HTTP origins where crypto.randomUUID is unavailable", async () => {
    const originalRandomUuid = globalThis.crypto.randomUUID;
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      configurable: true,
      value: undefined,
    });

    try {
      render(
        <OperationsWorkspace
          onInvestigate={jest.fn()}
          onOpenActivity={jest.fn()}
          onOpenInsights={jest.fn()}
          vstApiUrl="http://thor.test/vst/api"
        />
      );

      await waitFor(() =>
        expect(screen.getByText("Warehouse Camera")).toBeInTheDocument()
      );
    } finally {
      Object.defineProperty(globalThis.crypto, "randomUUID", {
        configurable: true,
        value: originalRandomUuid,
      });
    }
  });

  it("selects the strongest source and returns to the overview through the persistent Monitor tab", async () => {
    render(
      <OperationsWorkspace
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Warehouse Camera")).toBeInTheDocument()
    );
    expect(
      screen.queryByRole("button", { name: "Evidence layers" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sources" })).toBeInTheDocument();
    expect(
      screen.getByLabelText("Source intelligence status")
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Monitor" }));
    expect(screen.getByText("2 Sources")).toBeInTheDocument();
    expect(screen.getAllByText("Warehouse Camera").length).toBeGreaterThan(0);
  });

  it("opens the promised source-history workflow directly", async () => {
    render(
      <OperationsWorkspace
        initialPanel="history"
        initialView="focused"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    expect(
      await screen.findByRole("dialog", { name: "Video history" })
    ).toBeInTheDocument();
    expect(screen.getAllByText("Warehouse Camera").length).toBeGreaterThan(0);
  });

  it("does not advertise focused visual Q&A while its local model is offline", async () => {
    render(
      <OperationsWorkspace
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        visualAnalystAvailable={false}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Warehouse Camera")).toBeInTheDocument()
    );
    expect(
      within(screen.getByLabelText("Source intelligence status")).getByText(
        "Unavailable"
      )
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Ask Vision Analyst")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Send question" })
    ).toBeDisabled();
    expect(
      screen.getByPlaceholderText(
        "Visual reasoning is offline — check System readiness"
      )
    ).toBeInTheDocument();
  });

  it("keeps every supported camera visible in the overview up to eight sources", async () => {
    const onOpenRules = jest.fn();
    const fiveStreams = Array.from({ length: 5 }, (_, index) => ({
      isMain: true,
      metadata: {},
      name: `camera-${index + 1}`,
      streamId: `camera-${index + 1}`,
      type: "FileDownload",
      url: `/camera-${index + 1}.mp4`,
      vodUrl: `/camera-${index + 1}.mp4`,
    }));
    (global.fetch as jest.Mock).mockImplementation(
      async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/v1/live/streams")) {
          return {
            ok: true,
            json: async () => [{ cameras: fiveStreams }],
          } as Response;
        }
        if (url.includes("/api/vision/source-intelligence")) {
          return {
            ok: true,
            json: async () => ({
              evidenceEvents: 0,
              semanticSegments: 1,
              trackedObservations: 0,
            }),
          } as Response;
        }
        if (url === "/api/vision/incidents") {
          return {
            ok: true,
            json: async () => ({ incidents: [] }),
          } as Response;
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }
    );

    render(
      <OperationsWorkspace
        initialView="grid"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        onOpenRules={onOpenRules}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() =>
      expect(screen.getByText("5 Sources")).toBeInTheDocument()
    );
    for (let index = 1; index <= 5; index += 1) {
      expect(screen.getAllByText(`Camera ${index}`).length).toBeGreaterThan(0);
    }
    expect(
      screen.getByRole("navigation", { name: "Monitoring views" })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rules" }));
    expect(onOpenRules).toHaveBeenCalledWith();
    expect(
      screen.queryByRole("button", { name: "Focused view" })
    ).not.toBeInTheDocument();
  });

  it("answers analyst questions in Operations before offering a deliberate evidence investigation", async () => {
    const onInvestigate = jest.fn();
    (global.fetch as jest.Mock).mockImplementation(
      async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/v1/live/streams")) {
          return { ok: true, json: async () => streamsResponse } as Response;
        }
        if (url.includes("/api/vision/source-intelligence")) {
          const warehouse = url.includes("warehouse-camera");
          return {
            ok: true,
            json: async () =>
              warehouse
                ? {
                    evidenceEvents: 6,
                    semanticSegments: 48,
                    trackedObservations: 3724,
                  }
                : {
                    evidenceEvents: 0,
                    semanticSegments: 27,
                    trackedObservations: 0,
                  },
          } as Response;
        }
        if (url === "/api/vision/analyst") {
          return {
            ok: true,
            json: async () => ({
              answer: "A forklift moves across the warehouse floor.",
              evidenceTools: ["video_understanding"],
              generatedAt: "2026-08-12T12:00:00Z",
              grounded: true,
              observedRange: { startSeconds: 4, endSeconds: 12 },
              query: "What safety risks are visible?",
              scope: "selected-source",
              sourceNames: ["sample-sim-traffic"],
            }),
          } as Response;
        }
        if (
          url.includes("/api/vision/evidence?") &&
          url.includes("sensorId=warehouse")
        ) {
          return {
            ok: true,
            json: async () => ({
              videoUrl: "http://thor.test/vst/storage/temp_files/inspected.mp4",
            }),
          } as Response;
        }
        if (url.includes("/v1/storage/warehouse/timelines")) {
          return {
            ok: true,
            json: async () => [
              {
                startTime: "2025-01-01T00:00:00Z",
                endTime: "2025-01-01T00:01:00Z",
              },
            ],
          } as Response;
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }
    );
    render(
      <OperationsWorkspace
        onInvestigate={onInvestigate}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );
    await waitFor(() =>
      expect(screen.getByText("Warehouse Camera")).toBeInTheDocument()
    );
    fireEvent.click(
      screen.getByRole("button", { name: "What safety risks are visible?" })
    );
    expect(onInvestigate).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByText("A forklift moves across the warehouse floor.")
      ).toBeInTheDocument()
    );
    expect(screen.getByText("Observed 0:04–0:12")).toBeInTheDocument();
    const analystRequest = JSON.parse(
      String(
        (global.fetch as jest.Mock).mock.calls.find(
          ([input]) => String(input) === "/api/vision/analyst"
        )?.[1]?.body
      )
    );
    expect(analystRequest).toEqual(
      expect.objectContaining({
        askedAt: expect.any(String),
        conversationId: expect.any(String),
        scope: "selected-source",
      })
    );
    expect(analystRequest.sources[0].playback).toEqual(
      expect.objectContaining({ capturedAt: expect.any(String) })
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Play inspected clip/i })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Inspected evidence clip",
    });
    await waitFor(() =>
      expect(dialog.querySelector("video")).toHaveAttribute(
        "src",
        "http://thor.test/vst/storage/temp_files/inspected.mp4"
      )
    );
    const clipRequest = (global.fetch as jest.Mock).mock.calls.find(
      ([input]) =>
        String(input).includes("/api/vision/evidence?") &&
        String(input).includes("sensorId=warehouse") &&
        String(input).includes("startTime=2025-01-01T00%3A00%3A04.000Z")
    );
    expect(String(clipRequest?.[0])).toContain(
      "startTime=2025-01-01T00%3A00%3A04.000Z"
    );
    expect(String(clipRequest?.[0])).toContain(
      "endTime=2025-01-01T00%3A00%3A12.000Z"
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Find related clips/i })
    );
    expect(onInvestigate).toHaveBeenCalledWith(
      "What safety risks are visible?",
      expect.objectContaining({ streamId: "warehouse" })
    );
  });

  it("keeps source preview and selection as separate, non-nested controls", async () => {
    render(
      <OperationsWorkspace
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Warehouse Camera")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));

    const picker = screen.getByRole("complementary", {
      name: "Camera sources",
    });
    const preview = within(picker).getByRole("button", {
      name: "Play warehouse-camera",
    });
    const select = within(picker).getByRole("button", {
      name: "Select Warehouse Camera",
    });

    expect(preview.contains(select)).toBe(false);
    expect(select.contains(preview)).toBe(false);
    expect(preview.parentElement?.closest("button")).toBeNull();
    expect(select.parentElement?.closest("button")).toBeNull();
  });

  it("keeps verified event markers visible and exposes sources without a layer popover", async () => {
    render(
      <OperationsWorkspace
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Warehouse Camera")).toBeInTheDocument()
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Jump to verified event/i })
      ).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    expect(
      screen.getByRole("complementary", { name: "Camera sources" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Evidence layers" })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Jump to verified event/i })
    ).toBeInTheDocument();
  });

  it("switches a live camera from semantic analysis to the warehouse profile", async () => {
    let detectorEnabled = false;
    const realMediaStream = global.MediaStream;
    const realWebSocket = global.WebSocket;
    Object.defineProperty(global, "MediaStream", {
      configurable: true,
      value: class {
        addTrack = jest.fn();
      },
    });
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: class {
        static OPEN = 1;
        close = jest.fn();
        readyState = 0;
        send = jest.fn();
      },
    });
    const liveSource = [
      {
        "traffic-sensor": [
          {
            isMain: true,
            metadata: {},
            name: "Traffic Camera",
            streamId: "traffic-sensor",
            type: "rtsp",
            url: "rtsp://camera.test/live",
            vodUrl: "rtsp://camera.test/live",
          },
        ],
      },
    ];
    (global.fetch as jest.Mock).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/v1/live/streams"))
          return { ok: true, json: async () => liveSource } as Response;
        if (url.includes("/api/vision/source-intelligence"))
          return {
            ok: true,
            json: async () => ({
              captionSegments: 2,
              evidenceEvents: 0,
              semanticSegments: 8,
              trackedObservations: 0,
            }),
          } as Response;
        if (url === "/api/vision/incidents")
          return {
            ok: true,
            json: async () => ({ incidents: [] }),
          } as Response;
        if (url === "/api/vision/analysis-profiles")
          return {
            ok: true,
            json: async () => ({ profiles: [
              { id: "semantic-search", name: "Semantic search + Vision Analyst", shortName: "Search only", description: "Semantic", detectionEnabled: false, maxSources: 8, modelId: null, modelLabel: "Cosmos Embed + Cosmos Reason", objectTypes: [], ready: true, readyDetail: "Ready", resourceTier: "low", ruleKinds: ["semantic"], sceneTypes: ["general"] },
              { id: "warehouse-safety", name: "Warehouse safety", shortName: "Warehouse", description: "Warehouse", detectionEnabled: true, maxSources: 8, modelId: "warehouse", modelLabel: "NVIDIA RT-DETR Warehouse", objectTypes: ["Person", "Forklift"], ready: true, readyDetail: "Ready", resourceTier: "medium", ruleKinds: ["area-entry", "proximity"], sceneTypes: ["warehouse"] },
            ] }),
          } as Response;
        if (url.startsWith("/api/vision/analysis-profiles?sourceId="))
          return {
            ok: true,
            json: async () => ({ profile: detectorEnabled
              ? { id: "warehouse-safety", name: "Warehouse safety", shortName: "Warehouse", description: "Warehouse", detectionEnabled: true, maxSources: 8, modelId: "warehouse", modelLabel: "NVIDIA RT-DETR Warehouse", objectTypes: ["Person", "Forklift"], ready: true, readyDetail: "Ready", resourceTier: "medium", ruleKinds: ["area-entry", "proximity"], sceneTypes: ["warehouse"] }
              : { id: "semantic-search", name: "Semantic search + Vision Analyst", shortName: "Search only", description: "Semantic", detectionEnabled: false, maxSources: 8, modelId: null, modelLabel: "Cosmos Embed + Cosmos Reason", objectTypes: [], ready: true, readyDetail: "Ready", resourceTier: "low", ruleKinds: ["semantic"], sceneTypes: ["general"] } }),
          } as Response;
        if (url.startsWith("http://agent.test/") && !init?.method)
          return {
            ok: true,
            json: async () => ({
              analysisProfileId: detectorEnabled ? "warehouse-safety" : "semantic-search",
              detectionEnabled: detectorEnabled,
              state: "active",
            }),
          } as Response;
        if (url === "/api/vision/source-analysis") {
          expect(JSON.parse(String(init?.body))).toEqual(
            expect.objectContaining({
              action: "configure",
              analysisProfileId: "warehouse-safety",
              sourceId: "traffic-sensor",
            })
          );
          detectorEnabled = true;
          return {
            ok: true,
            json: async () => ({
              analysisProfileId: "warehouse-safety",
              detectionEnabled: true,
              state: "active",
            }),
          } as Response;
        }
        if (url.includes("/timelines"))
          return { ok: true, json: async () => [] } as Response;
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }
    );

    const view = render(
      <OperationsWorkspace
        agentApiUrl="http://agent.test/api/v1"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    const profile = await screen.findByRole("combobox", {
      name: "Source analysis profile",
    });
    await waitFor(() => expect(profile).toHaveValue("semantic-search"));
    fireEvent.change(profile, { target: { value: "warehouse-safety" } });
    await waitFor(() => expect(profile).toHaveValue("warehouse-safety"));
    await waitFor(() =>
      expect(
        screen.getByText("Ready — no observations yet")
      ).toBeInTheDocument()
    );
    view.unmount();
    Object.defineProperty(global, "MediaStream", {
      configurable: true,
      value: realMediaStream,
    });
    Object.defineProperty(global, "WebSocket", {
      configurable: true,
      value: realWebSocket,
    });
  });

  it("stages and reprocesses a recording with a different profile", async () => {
    let appliedProfile = "semantic-search";
    const semanticProfile = { id: "semantic-search", name: "Semantic search + Vision Analyst", shortName: "Search only", description: "Semantic", detectionEnabled: false, maxSources: 8, modelId: null, modelLabel: "Cosmos Embed + Cosmos Reason", objectTypes: [], ready: true, readyDetail: "Ready", resourceTier: "low", ruleKinds: ["semantic"], sceneTypes: ["general"] };
    const trafficProfile = { id: "traffic-monitoring", name: "Traffic and roadway", shortName: "Traffic", description: "Traffic", detectionEnabled: true, maxSources: 1, modelId: "traffic", modelLabel: "NVIDIA RT-DETR Intelligent Transportation", objectTypes: ["Person", "Car"], ready: true, readyDetail: "Ready", resourceTier: "medium", ruleKinds: ["area-entry", "proximity"], sceneTypes: ["traffic"] };
    (global.fetch as jest.Mock).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/v1/live/streams"))
          return { ok: true, json: async () => streamsResponse } as Response;
        if (url === "/api/vision/analysis-profiles")
          return { ok: true, json: async () => ({ profiles: [semanticProfile, trafficProfile] }) } as Response;
        if (url.startsWith("/api/vision/analysis-profiles?sourceId="))
          return { ok: true, json: async () => ({ profile: appliedProfile === "traffic-monitoring" ? trafficProfile : semanticProfile }) } as Response;
        if (url.includes("/api/vision/source-intelligence"))
          return { ok: true, json: async () => ({ evidenceEvents: 0, semanticSegments: 27, trackedObservations: 0 }) } as Response;
        if (url === "/api/vision/incidents")
          return { ok: true, json: async () => ({ incidents: [] }) } as Response;
        if (url === "/api/vision/source-analysis") {
          expect(JSON.parse(String(init?.body))).toEqual(expect.objectContaining({
            action: "configure",
            analysisProfileId: "traffic-monitoring",
            sourceId: "traffic",
            sourceKind: "recorded",
          }));
          appliedProfile = "traffic-monitoring";
          return { ok: true, json: async () => ({ analysisProfileId: appliedProfile, state: "active" }) } as Response;
        }
        if (url.includes("/timelines"))
          return { ok: true, json: async () => [] } as Response;
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }
    );

    render(
      <OperationsWorkspace
        agentApiUrl="http://agent.test/api/v1"
        initialStreamId="traffic"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    const profile = await screen.findByRole("combobox", { name: "Source analysis profile" });
    await waitFor(() => expect(profile).toHaveValue("semantic-search"));
    const apply = screen.getByRole("button", { name: "Apply and reprocess recording" });
    expect(apply).toBeDisabled();
    fireEvent.change(profile, { target: { value: "traffic-monitoring" } });
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    await waitFor(() => expect(profile).toHaveValue("traffic-monitoring"));
  });
});
