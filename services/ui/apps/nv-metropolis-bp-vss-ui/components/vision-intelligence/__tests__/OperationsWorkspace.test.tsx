// SPDX-License-Identifier: MIT

import * as reportComponent from "../LiveAnswerReport";
import { OperationsWorkspace } from "../OperationsWorkspace";
import * as streamCanvas from "../VisionStreamCanvas";
import type { SourceAnalysisProfile } from "../analysisProfiles";
import type { VisionStream } from "../types";
import {
  act,
  cleanup,
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

function OperationsTestWorkspace(
  props: Partial<React.ComponentProps<typeof OperationsWorkspace>>
) {
  return (
    <OperationsWorkspace
      onInvestigate={jest.fn()}
      onOpenActivity={jest.fn()}
      onOpenInsights={jest.fn()}
      onOpenRules={jest.fn()}
      visualAnalystAvailable={true}
      vstApiUrl="http://thor.test/vst/api"
      {...props}
    />
  );
}

describe("OperationsWorkspace", () => {
  it("opens an unknown-status source without claiming it is healthy", async () => {
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation(() => <div>Camera preview</div>);
    global.fetch = jest.fn(async (input) => {
      if (String(input).endsWith("/v1/live/streams"))
        return {
          ok: true,
          json: async () => [
            {
              camera: [
                {
                  streamId: "camera",
                  sensorId: "camera",
                  name: "Loading bay",
                  type: "Rtsp",
                  url: "rtsp://camera.test/live",
                  metadata: {},
                  isMain: true,
                },
              ],
            },
          ],
        };
      return { ok: true, json: async () => ({}) };
    }) as jest.Mock;
    const onOpenActivity = jest.fn();
    render(
      <OperationsTestWorkspace
        initialView="grid"
        onInvestigate={jest.fn()}
        onOpenActivity={onOpenActivity}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );
    const source = await screen.findByRole("button", {
      name: /Review source Loading Bay|Loading Bay.*Review source/i,
    });
    expect(screen.queryByText("No action needed")).not.toBeInTheDocument();
    await act(async () => {
      fireEvent.click(source);
    });
    expect(
      await screen.findByLabelText("Source intelligence status")
    ).toBeInTheDocument();
    expect(onOpenActivity).not.toHaveBeenCalled();
  });
  it("shows disconnected video even when analysis is paused", async () => {
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation(() => <div>Camera preview</div>);
    global.fetch = jest.fn(async (input) => {
      if (String(input).endsWith("/v1/live/streams"))
        return {
          ok: true,
          json: async () => [
            {
              camera: [
                {
                  streamId: "camera",
                  name: "Loading bay",
                  type: "Rtsp",
                  url: "rtsp://camera.test/live",
                  metadata: {},
                  isMain: true,
                },
              ],
            },
          ],
        };
      if (String(input).endsWith("/sensor/status"))
        return {
          ok: true,
          json: async () => ({ camera: { state: "offline" } }),
        };
      if (String(input).endsWith("/analysis"))
        return { ok: true, json: async () => ({ state: "paused" }) };
      return { ok: true, json: async () => ({}) };
    }) as jest.Mock;
    render(
      <OperationsTestWorkspace
        agentApiUrl="/agent"
        initialView="grid"
        onInvestigate={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );
    expect((await screen.findAllByText("Disconnected")).length).toBeGreaterThan(
      0
    );
    expect(
      screen.getAllByText(/Check the camera or simulator connection/).length
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText("Press play to check the live connection.", {
        exact: false,
      })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Camera preview")).not.toBeInTheDocument();
    const details = screen
      .getByText("1 disconnected cameras · Connection details")
      .closest("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(
      screen.getByText("1 disconnected cameras · Connection details")
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: /Review source Loading Bay|Loading Bay.*Review source/i,
      })
    );
    expect(
      await screen.findByLabelText("Source intelligence status")
    ).toBeInTheDocument();
    expect(
      screen.getByText("No live frames — camera disconnected")
    ).toBeInTheDocument();
    expect(screen.getByText("No live input")).toBeInTheDocument();
  });
  beforeEach(() => {
    jest
      .spyOn(HTMLMediaElement.prototype, "load")
      .mockImplementation(() => undefined);
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
                sensorId: "warehouse",
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

  afterEach(async () => {
    await act(async () => {});
    cleanup();
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it("loads on LAN HTTP origins where crypto.randomUUID is unavailable", async () => {
    const originalRandomUuid = globalThis.crypto.randomUUID;
    Object.defineProperty(globalThis.crypto, "randomUUID", {
      configurable: true,
      value: undefined,
    });

    try {
      render(
        <OperationsTestWorkspace
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

  it("keeps the camera usable when source intelligence rejects but analysis state succeeds", async () => {
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation(() => <div>Camera preview</div>);
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/live/streams"))
        return {
          ok: true,
          json: async () => [
            {
              camera: [
                {
                  streamId: "camera",
                  sensorId: "camera",
                  name: "Loading bay",
                  type: "Rtsp",
                  url: "rtsp://camera.test/live",
                  metadata: {},
                  isMain: true,
                },
              ],
            },
          ],
        };
      if (url.includes("/api/vision/source-intelligence"))
        throw new TypeError("Failed to fetch");
      if (url.endsWith("/analysis"))
        return { ok: true, json: async () => ({ state: "paused" }) };
      return { ok: true, json: async () => ({}) };
    }) as jest.Mock;
    render(
      <OperationsTestWorkspace
        agentApiUrl="/agent"
        initialView="focused"
        onInvestigate={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );
    expect(
      await screen.findByRole("button", { name: "Resume analysis" })
    ).toBeEnabled();
    expect(
      screen.getByLabelText("Source intelligence status")
    ).toBeInTheDocument();
    expect(screen.getByText("Camera preview")).toBeInTheDocument();
  });

  it("selects the strongest source and opens the source browser from its header", async () => {
    render(
      <OperationsTestWorkspace
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
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    expect(
      screen.getByRole("heading", { name: "All sources" })
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Ask Vision Analyst")
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Warehouse Camera").length).toBeGreaterThan(0);
  });

  it("opens the promised source-history workflow directly", async () => {
    render(
      <OperationsTestWorkspace
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
      <OperationsTestWorkspace
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
    const questionStatus = within(
      screen.getByLabelText("Source intelligence status")
    )
      .getByText("Ask this recording")
      .closest(".vi-intelligence-row")!;
    expect(
      within(questionStatus as HTMLElement).getByText("Unavailable")
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Ask Vision Analyst")).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Send question" })
    ).toBeDisabled();
    expect(
      screen.getByPlaceholderText(
        "Visual reasoning is offline — check System readiness"
      )
    ).toBeInTheDocument();
  });

  it("keeps live cameras visible in the overview", async () => {
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation(() => <div>Camera preview</div>);
    const onOpenRules = jest.fn();
    const fiveStreams = Array.from({ length: 5 }, (_, index) => ({
      isMain: true,
      metadata: {},
      name: `camera-${index + 1}`,
      streamId: `camera-${index + 1}`,
      type: "Rtsp",
      url: `rtsp://camera.test/${index + 1}`,
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
      <OperationsTestWorkspace
        initialView="grid"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        onOpenRules={onOpenRules}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    await waitFor(() =>
      expect(screen.getByText("Camera 5")).toBeInTheDocument()
    );
    for (let index = 1; index <= 5; index += 1) {
      expect(screen.getAllByText(`Camera ${index}`).length).toBeGreaterThan(0);
    }
    expect(
      screen.getByRole("region", { name: "Video source browser" })
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Monitoring rules for Camera 1/i })
    );
    expect(onOpenRules).toHaveBeenCalledWith(
      expect.objectContaining({ streamId: "camera-1" })
    );
    expect(
      screen.queryByLabelText("Ask Vision Analyst")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Focused view" })
    ).not.toBeInTheDocument();
  });

  it("replays the absolute inspected live interval without deriving offsets from a changing timeline", async () => {
    jest.useFakeTimers({ now: new Date("2026-09-30T03:00:00Z") });
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation(() => <div>Live preview</div>);
    global.fetch = jest.fn(async (input) => {
      const url = String(input);
      if (url.endsWith("/v1/live/streams"))
        return {
          ok: true,
          json: async () => [
            {
              camera: [
                {
                  streamId: "camera",
                  name: "Conveyor replay",
                  type: "Rtsp",
                  url: "rtsp://camera.test/live",
                  metadata: {},
                  isMain: true,
                },
              ],
            },
          ],
        };
      if (url.startsWith("/api/vision/live-capture?"))
        return {
          ok: true,
          json: async () => ({ streamId: "camera", recordingStatus: "on" }),
        };
      if (url.endsWith("/sensor/status"))
        return {
          ok: true,
          json: async () => ({ camera: { state: "online" } }),
        };
      if (url === "/api/vision/analyst")
        return {
          ok: true,
          json: async () => ({
            answer: "A box is visible.",
            evidenceTools: ["video_understanding_iso"],
            grounded: true,
            generatedAt: "2026-09-28T23:00:35Z",
            query: "What is visible?",
            scope: "selected-source",
            sourceNames: ["Conveyor replay"],
            observedWindow: {
              startTime: "2026-09-28T23:00:00Z",
              endTime: "2026-09-28T23:00:25Z",
            },
          }),
        };
      if (url.includes("/api/vision/evidence?"))
        return {
          ok: true,
          json: async () => ({
            videoUrl: "/vst/storage/temp_files/live-evidence.mp4",
          }),
        };
      return { ok: true, json: async () => ({}) };
    }) as jest.Mock;
    render(
      <OperationsTestWorkspace
        onInvestigate={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );
    const question = await screen.findByRole("textbox", {
      name: "Ask Vision Analyst",
    });
    await screen.findByRole("button", { name: "Stop capture" });
    await act(async () => {
      jest.advanceTimersByTime(30_000);
    });
    fireEvent.change(question, { target: { value: "What is visible?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    await screen.findByText("A box is visible.");
    fireEvent.click(
      screen.getByRole("button", { name: "Play inspected clip" })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Inspected evidence clip",
    });
    await waitFor(() =>
      expect(dialog.querySelector("video")).toHaveAttribute(
        "src",
        "http://thor.test/vst/storage/temp_files/live-evidence.mp4"
      )
    );
    expect(
      within(dialog).getByText(/not the current frame/)
    ).toBeInTheDocument();
    const request = (global.fetch as jest.Mock).mock.calls.find(([url]) =>
      String(url).includes("/api/vision/evidence?")
    );
    const params = new URL(String(request[0]), "http://thor.test").searchParams;
    expect(params.get("startTime")).toBe("2026-09-28T23:00:00Z");
    expect(params.get("endTime")).toBe("2026-09-28T23:00:25Z");
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
      <OperationsTestWorkspace
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
      screen.getByRole("button", { name: "What risks are visible?" })
    );
    expect(onInvestigate).not.toHaveBeenCalled();
    expect(
      screen.queryByText("A forklift moves across the warehouse floor.")
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask Vision Analyst")).toHaveValue(
      "What risks are visible?"
    );
    fireEvent.change(screen.getByLabelText("Ask Vision Analyst"), {
      target: { value: "What safety risks are visible?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
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

  it("opens source browsing with independent review and per-source alert controls", async () => {
    const onOpenRules = jest.fn();
    sourceApi([
      {
        ...liveReviewSource,
        name: "warehouse-camera",
        sensorId: "warehouse",
        streamId: "warehouse",
      },
    ]);
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation(() => <div>Camera preview</div>);
    render(<OperationsTestWorkspace onOpenRules={onOpenRules} />);
    await screen.findByText("Warehouse Camera");
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    expect(
      screen.getByRole("heading", { name: "All sources" })
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Ask Vision Analyst")
    ).not.toBeInTheDocument();
    const review = screen.getByRole("button", {
      name: /Review source Warehouse Camera/i,
    });
    const alert = screen.getByRole("button", {
      name: /Monitoring rules for Warehouse Camera/i,
    });
    expect(review.contains(alert)).toBe(false);
    expect(alert.contains(review)).toBe(false);
    fireEvent.click(alert);
    expect(onOpenRules).toHaveBeenCalledWith(
      expect.objectContaining({ streamId: "warehouse" })
    );
    await act(async () => {
      fireEvent.click(review);
    });
    expect(
      screen.getByLabelText("Source intelligence status")
    ).toBeInTheDocument();
  });

  it("keeps verified event markers visible and exposes sources without a layer popover", async () => {
    render(
      <OperationsTestWorkspace
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
      screen.getByRole("heading", { name: "All sources" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Evidence layers" })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Open recording Warehouse Camera/i })
    );
    expect(
      await screen.findByRole("button", { name: /Jump to verified event/i })
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
            json: async () => ({
              profiles: [
                {
                  id: "semantic-search",
                  name: "Semantic search + Vision Analyst",
                  shortName: "Search only",
                  description: "Semantic",
                  detectionEnabled: false,
                  maxSources: 8,
                  modelId: null,
                  modelLabel: "Cosmos Embed + Cosmos Reason",
                  objectTypes: [],
                  ready: true,
                  readyDetail: "Ready",
                  resourceTier: "low",
                  ruleKinds: ["semantic"],
                  sceneTypes: ["general"],
                },
                {
                  id: "warehouse-safety",
                  name: "Warehouse safety",
                  shortName: "Warehouse",
                  description: "Warehouse",
                  detectionEnabled: true,
                  maxSources: 8,
                  modelId: "warehouse",
                  modelLabel: "NVIDIA RT-DETR Warehouse",
                  objectTypes: ["Person", "Forklift"],
                  ready: true,
                  readyDetail: "Ready",
                  resourceTier: "medium",
                  ruleKinds: ["area-entry", "proximity"],
                  sceneTypes: ["warehouse"],
                },
              ],
            }),
          } as Response;
        if (url.startsWith("/api/vision/analysis-profiles?sourceId="))
          return {
            ok: true,
            json: async () => ({
              profile: detectorEnabled
                ? {
                    id: "warehouse-safety",
                    name: "Warehouse safety",
                    shortName: "Warehouse",
                    description: "Warehouse",
                    detectionEnabled: true,
                    maxSources: 8,
                    modelId: "warehouse",
                    modelLabel: "NVIDIA RT-DETR Warehouse",
                    objectTypes: ["Person", "Forklift"],
                    ready: true,
                    readyDetail: "Ready",
                    resourceTier: "medium",
                    ruleKinds: ["area-entry", "proximity"],
                    sceneTypes: ["warehouse"],
                  }
                : {
                    id: "semantic-search",
                    name: "Semantic search + Vision Analyst",
                    shortName: "Search only",
                    description: "Semantic",
                    detectionEnabled: false,
                    maxSources: 8,
                    modelId: null,
                    modelLabel: "Cosmos Embed + Cosmos Reason",
                    objectTypes: [],
                    ready: true,
                    readyDetail: "Ready",
                    resourceTier: "low",
                    ruleKinds: ["semantic"],
                    sceneTypes: ["general"],
                  },
            }),
          } as Response;
        if (url.startsWith("http://agent.test/") && !init?.method)
          return {
            ok: true,
            json: async () => ({
              analysisProfileId: detectorEnabled
                ? "warehouse-safety"
                : "semantic-search",
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
      <OperationsTestWorkspace
        agentApiUrl="http://agent.test/api/v1"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    fireEvent.click(await screen.findByText("Processing details"));
    const profile = await screen.findByRole("combobox", {
      name: "Source analysis profile",
    });
    await waitFor(() => expect(profile).toHaveValue("semantic-search"));
    fireEvent.change(profile, { target: { value: "warehouse-safety" } });
    await waitFor(() => expect(profile).toHaveValue("warehouse-safety"));
    await waitFor(() =>
      expect(screen.getByText("0 observations")).toBeInTheDocument()
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
    const semanticProfile = {
      id: "semantic-search",
      name: "Semantic search + Vision Analyst",
      shortName: "Search only",
      description: "Semantic",
      detectionEnabled: false,
      maxSources: 8,
      modelId: null,
      modelLabel: "Cosmos Embed + Cosmos Reason",
      objectTypes: [],
      ready: true,
      readyDetail: "Ready",
      resourceTier: "low",
      ruleKinds: ["semantic"],
      sceneTypes: ["general"],
    };
    const trafficProfile = {
      id: "traffic-monitoring",
      name: "Traffic and roadway",
      shortName: "Traffic",
      description: "Traffic",
      detectionEnabled: true,
      maxSources: 1,
      modelId: "traffic",
      modelLabel: "NVIDIA RT-DETR Intelligent Transportation",
      objectTypes: ["Person", "Car"],
      ready: true,
      readyDetail: "Ready",
      resourceTier: "medium",
      ruleKinds: ["area-entry", "proximity"],
      sceneTypes: ["traffic"],
    };
    (global.fetch as jest.Mock).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/v1/live/streams"))
          return { ok: true, json: async () => streamsResponse } as Response;
        if (url === "/api/vision/analysis-profiles")
          return {
            ok: true,
            json: async () => ({ profiles: [semanticProfile, trafficProfile] }),
          } as Response;
        if (url.startsWith("/api/vision/analysis-profiles?sourceId="))
          return {
            ok: true,
            json: async () => ({
              profile:
                appliedProfile === "traffic-monitoring"
                  ? trafficProfile
                  : semanticProfile,
            }),
          } as Response;
        if (url.includes("/api/vision/source-intelligence"))
          return {
            ok: true,
            json: async () => ({
              evidenceEvents: 0,
              semanticSegments: 27,
              trackedObservations: 0,
            }),
          } as Response;
        if (url === "/api/vision/incidents")
          return {
            ok: true,
            json: async () => ({ incidents: [] }),
          } as Response;
        if (url === "/api/vision/source-analysis") {
          expect(JSON.parse(String(init?.body))).toEqual(
            expect.objectContaining({
              action: "configure",
              analysisProfileId: "traffic-monitoring",
              sourceId: "traffic",
              sourceKind: "recorded",
            })
          );
          appliedProfile = "traffic-monitoring";
          return {
            ok: true,
            json: async () => ({
              analysisProfileId: appliedProfile,
              state: "active",
            }),
          } as Response;
        }
        if (url.includes("/timelines"))
          return { ok: true, json: async () => [] } as Response;
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }
    );

    render(
      <OperationsTestWorkspace
        agentApiUrl="http://agent.test/api/v1"
        initialStreamId="traffic"
        onInvestigate={jest.fn()}
        onOpenActivity={jest.fn()}
        onOpenInsights={jest.fn()}
        vstApiUrl="http://thor.test/vst/api"
      />
    );

    fireEvent.click(await screen.findByText("Processing details"));
    const profile = await screen.findByRole("combobox", {
      name: "Source analysis profile",
    });
    await waitFor(() => expect(profile).toHaveValue("semantic-search"));
    const apply = screen.getByRole("button", {
      name: "Apply and reprocess recording",
    });
    expect(apply).toBeDisabled();
    fireEvent.change(profile, { target: { value: "traffic-monitoring" } });
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    await waitFor(() => expect(profile).toHaveValue("traffic-monitoring"));
  });
});

const reviewSource: VisionStream = {
  isMain: true,
  metadata: {},
  name: "Camera 1",
  sensorId: "camera-1",
  streamId: "storage-1",
  type: "FileDownload",
  url: "/one.mp4",
  vodUrl: "/one.mp4",
};
const secondSource: VisionStream = {
  ...reviewSource,
  name: "Camera 10",
  sensorId: "camera-10",
  streamId: "storage-10",
  url: "/ten.mp4",
  vodUrl: "/ten.mp4",
};
const liveReviewSource: VisionStream = {
  ...reviewSource,
  type: "Rtsp",
  url: "rtsp://sim.test/live",
  vodUrl: "",
};
const searchProfile: SourceAnalysisProfile = {
  id: "semantic-search",
  name: "Semantic search",
  shortName: "Search only",
  description: "Semantic search",
  detectionEnabled: false,
  maxSources: 8,
  modelId: null,
  modelLabel: "Cosmos",
  objectTypes: [],
  ready: true,
  readyDetail: "Ready",
  resourceTier: "low",
  ruleKinds: ["semantic"],
  sceneTypes: ["general"],
};
const detectorProfile: SourceAnalysisProfile = {
  ...searchProfile,
  id: "warehouse-safety",
  name: "Warehouse safety",
  shortName: "Warehouse",
  detectionEnabled: true,
  modelId: "warehouse",
  modelLabel: "Warehouse detector",
};
function responseJson(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}
function pendingResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function reviewedAnswer(name = reviewSource.name, query = "What is visible?") {
  return {
    answer: `${name}: a cart is visible.`,
    evidenceTools: ["video_understanding"],
    generatedAt: "2026-09-30T03:00:30Z",
    grounded: true,
    query,
    scope: "selected-source",
    sourceNames: [name],
    observedRange: { startSeconds: 4, endSeconds: 12 },
  };
}
function sourceApi(sources = [reviewSource, secondSource]) {
  const state = { analysis: "paused", profile: searchProfile, capture: "off" };
  const base = async (
    input: RequestInfo | URL,
    init?: RequestInit
  ): Promise<Response> => {
    const url = String(input);
    if (url.endsWith("/v1/live/streams"))
      return responseJson(
        sources.map((source) => ({ [source.sensorId]: [source] }))
      );
    if (url.endsWith("/sensor/status"))
      return responseJson(
        Object.fromEntries(
          sources.map((source) => [source.sensorId, { state: "online" }])
        )
      );
    if (url === "/api/vision/analysis-profiles")
      return responseJson({
        profiles: [
          searchProfile,
          detectorProfile,
          { ...detectorProfile, id: "offline-profile", ready: false },
        ],
      });
    if (url.startsWith("/api/vision/analysis-profiles?"))
      return responseJson({ profile: state.profile });
    if (url.includes("/api/vision/source-intelligence?"))
      return responseJson({
        semanticSegments: 5,
        evidenceEvents: 0,
        trackedObservations: null,
        captionSegments: null,
      });
    if (url.endsWith("/analysis"))
      return responseJson({
        state: state.analysis,
        analysisProfileId: state.profile.id,
      });
    if (url.startsWith("/api/vision/live-capture?"))
      return responseJson({
        streamId: liveReviewSource.streamId,
        recordingStatus: state.capture,
      });
    if (url === "/api/vision/live-capture" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      state.capture = body.action === "start" ? "on" : "off";
      return responseJson({
        streamId: body.streamId,
        recordingStatus: state.capture,
      });
    }
    if (url === "/api/vision/incidents") return responseJson({ incidents: [] });
    if (url === "/api/vision/analyst") return responseJson(reviewedAnswer());
    if (url.includes("/timelines"))
      return responseJson([
        { startTime: "2025-01-01T00:00:00Z", endTime: "2025-01-01T00:01:00Z" },
      ]);
    if (url.startsWith("/api/vision/video-history?"))
      return responseJson(null, 404);
    if (url.startsWith("/api/vision/evidence?"))
      return responseJson({ videoUrl: "/retained/evidence.mp4" });
    return responseJson({}, 404);
  };
  const fetchMock = jest.fn(base);
  global.fetch = fetchMock;
  return { fetchMock, base, state };
}
async function selectSecondSource() {
  fireEvent.click(screen.getByRole("button", { name: "Sources" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Open recording Camera 10/i })
  );
  await screen.findByLabelText("Source intelligence status");
}
function submitQuestion(query = "What is visible?") {
  fireEvent.change(screen.getByLabelText("Ask Vision Analyst"), {
    target: { value: query },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
}

describe("Operations selected-source safety", () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    jest
      .spyOn(HTMLMediaElement.prototype, "load")
      .mockImplementation(() => undefined);
    jest.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    jest
      .spyOn(HTMLMediaElement.prototype, "pause")
      .mockImplementation(() => undefined);
    jest
      .spyOn(streamCanvas, "VisionStreamCanvas")
      .mockImplementation((props) => (
        <div data-testid="camera-preview">
          {props.stream.streamId}
          <button
            onClick={() =>
              props.onPlaybackContext?.({
                capturedAt: "2026-09-30T03:00:00Z",
                currentTimeSeconds: 73,
                durationSeconds: 120,
              })
            }
          >
            Set inspected playback
          </button>
          {props.evidenceEvents?.map((event) => (
            <span key={event.id}>{event.id}</span>
          ))}
        </div>
      ));
  });
  afterEach(async () => {
    await act(async () => {});
    cleanup();
    jest.useRealTimers();
    jest.restoreAllMocks();
    global.fetch = originalFetch;
  });

  it("reads source and capture state on mount without resuming analysis or starting capture", async () => {
    const { fetchMock } = sourceApi([liveReviewSource]);
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    expect(
      await within(
        await screen.findByRole("region", { name: "Live recording" })
      ).findByRole("button", { name: "Start live capture" })
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Resume analysis" })
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Send question" })
    ).toBeDisabled();
    expect(screen.getByTestId("camera-preview")).toHaveTextContent(
      liveReviewSource.streamId
    );
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes(
          `/api/vision/live-capture?streamId=${liveReviewSource.streamId}`
        )
      )
    ).toBe(true);
    expect(
      fetchMock.mock.calls.filter(
        ([, init]) => init?.method && init.method !== "GET"
      )
    ).toEqual([]);
  });

  it("requires capture warmup, then submits the exact source and preserves absolute answer evidence", async () => {
    jest.useFakeTimers({ now: new Date("2026-09-30T03:00:00Z") });
    const { fetchMock, base } = sourceApi([liveReviewSource]);
    const liveAnswer = {
      ...reviewedAnswer(),
      observedRange: undefined,
      observedWindow: {
        startTime: "2026-09-30T03:00:00Z",
        endTime: "2026-09-30T03:00:25Z",
      },
    };
    const report = jest
      .spyOn(reportComponent, "LiveAnswerReport")
      .mockImplementation(() => <div>Save source report</div>);
    fetchMock.mockImplementation((input, init) =>
      String(input) === "/api/vision/analyst"
        ? Promise.resolve(responseJson(liveAnswer))
        : base(input, init)
    );
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    await within(
      await screen.findByRole("region", { name: "Live recording" })
    ).findByRole("button", { name: "Start live capture" });
    fireEvent.change(screen.getByLabelText("Ask Vision Analyst"), {
      target: { value: "What is visible?" },
    });
    fireEvent.click(
      within(screen.getByRole("region", { name: "Live recording" })).getByRole(
        "button",
        { name: "Start live capture" }
      )
    );
    await screen.findByRole("button", { name: "Stop capture" });
    await act(async () => {
      jest.advanceTimersByTime(29_000);
    });
    expect(
      screen.getByRole("button", { name: "Send question" })
    ).toBeDisabled();
    await act(async () => {
      jest.advanceTimersByTime(1_000);
    });
    expect(screen.getByRole("button", { name: "Send question" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    await screen.findByText(liveAnswer.answer);
    const request = fetchMock.mock.calls.find(
      ([url]) => String(url) === "/api/vision/analyst"
    )!;
    expect(JSON.parse(String(request[1]?.body))).toEqual(
      expect.objectContaining({
        scope: "selected-source",
        sources: [
          expect.objectContaining({
            sensorId: liveReviewSource.sensorId,
            streamId: liveReviewSource.streamId,
            kind: "live",
          }),
        ],
      })
    );
    expect(report).toHaveBeenLastCalledWith(
      expect.objectContaining({
        source: expect.objectContaining({
          sensorId: liveReviewSource.sensorId,
        }),
        result: liveAnswer,
      }),
      expect.anything()
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Play inspected clip" })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Inspected evidence clip",
    });
    await waitFor(() =>
      expect(dialog.querySelector("video")).toHaveAttribute(
        "src",
        "http://thor.test/retained/evidence.mp4"
      )
    );
    const clip = fetchMock.mock.calls.find(([url]) =>
      String(url).startsWith("/api/vision/evidence?")
    )!;
    const params = new URL(String(clip[0]), "http://ui.test").searchParams;
    expect(params.get("sensorId")).toBe(liveReviewSource.streamId);
    expect(params.get("startTime")).toBe(liveAnswer.observedWindow.startTime);
    expect(params.get("endTime")).toBe(liveAnswer.observedWindow.endTime);
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => String(url) === "/api/vision/source-analysis"
      )
    ).toEqual([]);
  });

  it("discards a late source-A answer and resets playback and conversation before asking source B", async () => {
    const { fetchMock, base } = sourceApi();
    const first = pendingResponse();
    let questions = 0;
    fetchMock.mockImplementation((input, init) => {
      if (String(input) === "/api/vision/analyst")
        return ++questions === 1
          ? first.promise
          : Promise.resolve(
              responseJson(
                reviewedAnswer(secondSource.name, "What is visible here?")
              )
            );
      return base(input, init);
    });
    render(<OperationsTestWorkspace initialStreamId={reviewSource.streamId} />);
    await screen.findByLabelText("Ask Vision Analyst");
    fireEvent.click(
      screen.getByRole("button", { name: "Set inspected playback" })
    );
    submitQuestion();
    await waitFor(() => expect(questions).toBe(1));
    await selectSecondSource();
    expect(
      screen.queryByLabelText("Vision Analyst answer")
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask Vision Analyst")).toBeEnabled();
    submitQuestion("What is visible here?");
    await screen.findByText(`${secondSource.name}: a cart is visible.`);
    await act(async () => {
      first.resolve(responseJson(reviewedAnswer()));
    });
    expect(
      screen.queryByText(`${reviewSource.name}: a cart is visible.`)
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(`${secondSource.name}: a cart is visible.`)
    ).toBeInTheDocument();
    const requests = fetchMock.mock.calls
      .filter(([url]) => String(url) === "/api/vision/analyst")
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(requests[0].sources[0].playback.currentTimeSeconds).toBe(73);
    expect(requests[1].sources).toEqual([
      expect.objectContaining({
        sensorId: secondSource.sensorId,
        streamId: secondSource.streamId,
      }),
    ]);
    expect(requests[1].sources[0].playback?.currentTimeSeconds).toBeUndefined();
    expect(requests[1].conversationId).not.toBe(requests[0].conversationId);
  });

  it("closing an unfinished answer prevents its late reply from replacing a new question", async () => {
    const { fetchMock, base } = sourceApi([reviewSource]);
    const oldQuestion = pendingResponse();
    const newQuestion = pendingResponse();
    let count = 0;
    fetchMock.mockImplementation((input, init) =>
      String(input) === "/api/vision/analyst"
        ? ++count === 1
          ? oldQuestion.promise
          : newQuestion.promise
        : base(input, init)
    );
    render(<OperationsTestWorkspace />);
    await screen.findByLabelText("Ask Vision Analyst");
    submitQuestion("First question");
    expect(screen.getByLabelText("Vision Analyst answer")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Close Vision Analyst answer" })
    );
    expect(
      screen.queryByLabelText("Vision Analyst answer")
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask Vision Analyst")).toBeEnabled();
    submitQuestion("Second question");
    await act(async () => {
      oldQuestion.resolve(
        responseJson({ ...reviewedAnswer(), answer: "Old closed answer" })
      );
    });
    expect(screen.queryByText("Old closed answer")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Send question" })
    ).toBeDisabled();
    await act(async () => {
      newQuestion.resolve(
        responseJson({
          ...reviewedAnswer(),
          answer: "Current answer",
          query: "Second question",
        })
      );
    });
    expect(screen.getByText("Current answer")).toBeInTheDocument();
    const requests = fetchMock.mock.calls
      .filter(([url]) => String(url) === "/api/vision/analyst")
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(requests[1].conversationId).not.toBe(requests[0].conversationId);
  });

  it("keeps camera-10 events out of camera-1's inspected evidence", async () => {
    const { fetchMock, base } = sourceApi();
    const event = (sensorId: string, Id: string) => ({
      sensorId,
      Id,
      timestamp: "2026-09-30T03:00:00Z",
      end: "2026-09-30T03:00:04Z",
      info: { verdict: "confirmed", reasoning: "A person is visible." },
    });
    fetchMock.mockImplementation((input, init) =>
      String(input) === "/api/vision/incidents"
        ? Promise.resolve(
            responseJson({
              incidents: [
                event(reviewSource.sensorId, "matching-event"),
                event(secondSource.sensorId, "other-camera-event"),
              ],
            })
          )
        : base(input, init)
    );
    render(<OperationsTestWorkspace initialStreamId={reviewSource.streamId} />);
    expect(await screen.findByText("matching-event")).toBeInTheDocument();
    expect(screen.queryByText("other-camera-event")).not.toBeInTheDocument();
    await selectSecondSource();
    expect(screen.getByText("other-camera-event")).toBeInTheDocument();
    expect(screen.queryByText("matching-event")).not.toBeInTheDocument();
  });

  it("rejects a stale paused poll after an explicit resume succeeds", async () => {
    jest.useFakeTimers();
    const { fetchMock, base, state } = sourceApi([liveReviewSource]);
    const oldPoll = pendingResponse();
    let deferNext = false;
    let deferred = false;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/analysis") && deferNext) {
        deferNext = false;
        deferred = true;
        return oldPoll.promise;
      }
      if (url === "/api/vision/source-analysis") {
        state.analysis = "active";
        return Promise.resolve(responseJson({ state: "active" }));
      }
      return base(input, init);
    });
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    await screen.findByRole("button", { name: "Resume analysis" });
    deferNext = true;
    await act(async () => {
      jest.advanceTimersByTime(15_000);
    });
    expect(deferred).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Resume analysis" }));
    await screen.findByRole("button", { name: "Pause analysis" });
    await act(async () => {
      oldPoll.resolve(
        responseJson({ state: "paused", analysisProfileId: searchProfile.id })
      );
    });
    expect(
      screen.getByRole("button", { name: "Pause analysis" })
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Resume analysis" })
    ).not.toBeInTheDocument();
    const request = fetchMock.mock.calls.find(
      ([url]) => String(url) === "/api/vision/source-analysis"
    )!;
    expect(JSON.parse(String(request[1]?.body))).toEqual(
      expect.objectContaining({
        action: "resume",
        sourceId: liveReviewSource.sensorId,
      })
    );
  });

  it("keeps a verified new profile when an older profile poll settles late", async () => {
    jest.useFakeTimers();
    const { fetchMock, base, state } = sourceApi([liveReviewSource]);
    const oldPoll = pendingResponse();
    let deferNext = false;
    let deferred = false;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/analysis") && deferNext) {
        deferNext = false;
        deferred = true;
        return oldPoll.promise;
      }
      if (url === "/api/vision/source-analysis") {
        state.profile = detectorProfile;
        return Promise.resolve(
          responseJson({
            state: "paused",
            analysisProfileId: detectorProfile.id,
          })
        );
      }
      return base(input, init);
    });
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    fireEvent.click(await screen.findByText("Processing details"));
    const profile = await screen.findByRole("combobox", {
      name: "Source analysis profile",
    });
    await waitFor(() => expect(profile).toHaveValue(searchProfile.id));
    expect(
      within(profile).getByRole("option", { name: /offline/ })
    ).toBeDisabled();
    deferNext = true;
    await act(async () => {
      jest.advanceTimersByTime(15_000);
    });
    expect(deferred).toBe(true);
    fireEvent.change(profile, { target: { value: detectorProfile.id } });
    await waitFor(() => expect(profile).toHaveValue(detectorProfile.id));
    await act(async () => {
      oldPoll.resolve(
        responseJson({ state: "paused", analysisProfileId: searchProfile.id })
      );
    });
    expect(profile).toHaveValue(detectorProfile.id);
    const request = fetchMock.mock.calls.find(
      ([url]) => String(url) === "/api/vision/source-analysis"
    )!;
    expect(JSON.parse(String(request[1]?.body))).toEqual(
      expect.objectContaining({
        action: "configure",
        analysisProfileId: detectorProfile.id,
        sourceId: liveReviewSource.sensorId,
      })
    );
  });

  it("surfaces a failed lifecycle error and preserves the backend's verified paused state", async () => {
    jest.useFakeTimers();
    const { fetchMock, base } = sourceApi([liveReviewSource]);
    fetchMock.mockImplementation((input, init) =>
      String(input) === "/api/vision/source-analysis"
        ? Promise.resolve(
            responseJson(
              {
                error:
                  "Remove this source's live alert rule before restarting analysis.",
              },
              409
            )
          )
        : base(input, init)
    );
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Resume analysis" })
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    expect(
      await screen.findByText(
        "Remove this source's live alert rule before restarting analysis."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Resume analysis" })
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Pause analysis" })
    ).not.toBeInTheDocument();
  });

  it("reconciles a failed pause response when the backend already reached paused", async () => {
    jest.useFakeTimers();
    const { fetchMock, base, state } = sourceApi([liveReviewSource]);
    state.analysis = "active";
    fetchMock.mockImplementation((input, init) => {
      if (String(input) === "/api/vision/source-analysis") {
        state.analysis = "paused";
        return Promise.resolve(
          responseJson({ error: "Some services could not be paused." }, 502)
        );
      }
      return base(input, init);
    });
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Pause analysis" })
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    expect(
      await screen.findByRole("button", { name: "Resume analysis" })
    ).toBeEnabled();
    expect(
      screen.queryByText("Some services could not be paused.")
    ).not.toBeInTheDocument();
  });

  it.each([false, null, undefined])(
    "does not advertise questions when visual model readiness is %s",
    async (visualAnalystAvailable) => {
      const { fetchMock } = sourceApi([reviewSource]);
      render(
        <OperationsTestWorkspace
          visualAnalystAvailable={visualAnalystAvailable}
        />
      );
      await screen.findByLabelText("Ask Vision Analyst");
      fireEvent.change(screen.getByLabelText("Ask Vision Analyst"), {
        target: { value: "What is visible?" },
      });
      expect(
        screen.getByRole("button", { name: "Send question" })
      ).toBeDisabled();
      expect(screen.getByLabelText("Ask Vision Analyst")).toBeEnabled();
      fireEvent.submit(
        screen.getByLabelText("Ask Vision Analyst").closest("form")!
      );
      expect(
        fetchMock.mock.calls.filter(
          ([url]) => String(url) === "/api/vision/analyst"
        )
      ).toEqual([]);
    }
  );

  it("does not turn unavailable intelligence into zero counts or disable readable video", async () => {
    const { fetchMock, base } = sourceApi([liveReviewSource]);
    fetchMock.mockImplementation((input, init) =>
      String(input).includes("/api/vision/source-intelligence?")
        ? Promise.resolve(responseJson({ error: "Index is unavailable." }, 502))
        : base(input, init)
    );
    render(<OperationsTestWorkspace agentApiUrl="/agent" />);
    await screen.findByRole("button", { name: "Resume analysis" });
    expect(screen.getByTestId("camera-preview")).toHaveTextContent(
      liveReviewSource.streamId
    );
    const status = screen.getByLabelText("Source intelligence status");
    expect(within(status).getAllByText("Unavailable").length).toBeGreaterThan(
      0
    );
    expect(within(status).queryByText("0 moments")).not.toBeInTheDocument();
    expect(
      within(status).queryByText("0 observations")
    ).not.toBeInTheDocument();
  });

  it("opens history read-only for the newly selected exact source", async () => {
    const { fetchMock } = sourceApi();
    render(<OperationsTestWorkspace initialStreamId={reviewSource.streamId} />);
    await screen.findByLabelText("Ask Vision Analyst");
    await selectSecondSource();
    fireEvent.click(screen.getByRole("button", { name: "Video history" }));
    expect(
      await screen.findByRole("dialog", { name: "Video history" })
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url]) =>
            String(url) ===
            `/api/vision/video-history?sourceId=${secondSource.sensorId}`
        )
      ).toBe(true)
    );
    expect(
      fetchMock.mock.calls.filter(
        ([url, init]) =>
          String(url).startsWith("/api/vision/video-history") &&
          init?.method === "POST"
      )
    ).toEqual([]);
  });
});
