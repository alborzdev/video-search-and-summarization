// SPDX-License-Identifier: MIT

import { LiveDemoWorkspace } from "../LiveDemoWorkspace";
import type { VisionAnalystResponse } from "../analyst";
import type { VisionStream } from "../types";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";

let mockPlaybackStatus: "poster" | "playing" = "playing";
function MockCanvas({
  stream,
  onPlaybackStatus,
}: {
  stream: VisionStream;
  onPlaybackStatus?: (status: "poster" | "playing") => void;
}) {
  React.useEffect(() => {
    onPlaybackStatus?.(mockPlaybackStatus);
  }, [onPlaybackStatus]);
  return <div data-testid="live-preview">{stream.streamId}</div>;
}
const mockCanvas = jest.fn(MockCanvas);
const mockReport = jest.fn();
jest.mock("../VisionStreamCanvas", () => ({
  VisionStreamCanvas: (props: Parameters<typeof MockCanvas>[0]) =>
    mockCanvas(props),
}));
jest.mock("../LiveAnswerReport", () => ({
  LiveAnswerReport: (props: unknown) => {
    mockReport(props);
    return <div data-testid="answer-report">Save evidence report</div>;
  },
}));

const hospital: VisionStream = {
  name: "Spark Hospital Corridor",
  sensorId: "sensor-hospital",
  streamId: "stream-hospital",
  connectionState: "online",
  type: "rtsp",
  url: "rtsp://sim.test/digital-twin",
  vodUrl: "",
  metadata: {},
  isMain: true,
};
const other: VisionStream = {
  ...hospital,
  name: "Other camera",
  sensorId: "sensor-other",
  streamId: "stream-other",
  url: "rtsp://camera.test/live",
};
const answer: VisionAnalystResponse = {
  answer: "Two people are visible beside a medical cart.",
  evidenceTools: ["video_understanding_iso"],
  generatedAt: "2026-09-30T03:00:30Z",
  grounded: true,
  query: "Describe the people and their activity",
  scope: "selected-source",
  sourceNames: [hospital.name],
  observedWindow: {
    startTime: "2026-09-30T03:00:00Z",
    endTime: "2026-09-30T03:00:25Z",
  },
};

function savedReport(id: string, sensorId: string, title = id) {
  return {
    id,
    title,
    created_at: "2026-09-30T02:00:00Z",
    report_url: `/api/vision/investigations?id=${id}&format=html`,
    evidence: [
      {
        sensor_id: sensorId,
        source_name: hospital.name,
        media_status: "retained",
      },
    ],
  };
}

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, json: async () => body } as Response;
}

function mockApi({
  recordingStatus = "off",
  reports = [],
}: {
  recordingStatus?: "on" | "off";
  reports?: ReturnType<typeof savedReport>[];
} = {}) {
  const statuses: Record<string, "on" | "off"> = {
    [hospital.streamId]: recordingStatus,
    [other.streamId]: recordingStatus,
  };
  const fetchMock = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/vision/live-capture?") && !init?.method) {
        const id = new URL(url, "http://ui.test").searchParams.get("streamId")!;
        return jsonResponse({ streamId: id, recordingStatus: statuses[id] });
      }
      if (url === "/api/vision/live-capture" && init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        statuses[body.streamId] = body.action === "start" ? "on" : "off";
        return jsonResponse({
          streamId: body.streamId,
          recordingStatus: statuses[body.streamId],
        });
      }
      if (url === "/api/vision/investigations" && !init?.method)
        return jsonResponse({ investigations: reports });
      if (url === "/api/vision/analyst" && init?.method === "POST")
        return jsonResponse(answer);
      if (url.startsWith("/api/vision/evidence?"))
        return jsonResponse({ videoUrl: "/retained/inspected.mp4" });
      throw new Error(`Unexpected API call: ${url}`);
    }
  );
  global.fetch = fetchMock;
  return fetchMock;
}

function props(streams = [hospital]) {
  return {
    streams,
    analysisById: { [hospital.streamId]: "paused", [other.streamId]: "paused" },
    onExplore: jest.fn(),
    onOpenEvents: jest.fn(),
    onOpenLive: jest.fn(),
    onOpenRules: jest.fn(),
    visualAnalystAvailable: true,
    vstApiUrl: "/vst/api",
  };
}

async function askQuestion() {
  fireEvent.click(
    screen.getByRole("button", {
      name: "Describe the people and their activity",
    })
  );
  fireEvent.click(screen.getByRole("button", { name: "Ask the video" }));
  await screen.findByText(answer.answer);
}

async function waitForCaptureWindow() {
  await screen.findByRole("button", { name: "Stop capture" });
  await act(async () => {
    jest.advanceTimersByTime(30_000);
  });
  expect(screen.getByText("Live questions ready")).toBeInTheDocument();
}

describe("live demo workspace", () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    mockPlaybackStatus = "playing";
  });
  afterEach(() => {
    cleanup();
    jest.useRealTimers();
    global.fetch = originalFetch;
  });

  it("opens the Sim source with read-only capture/report calls and no automatic inference", async () => {
    const fetchMock = mockApi();
    render(<LiveDemoWorkspace {...props([other, hospital])} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).toBeEnabled()
    );
    expect(screen.getByTestId("live-preview")).toHaveTextContent(
      hospital.streamId
    );
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `/api/vision/live-capture?streamId=${hospital.streamId}`,
      "/api/vision/investigations",
    ]);
    for (const [, init] of fetchMock.mock.calls)
      expect(init?.method).toBeUndefined();
    expect(mockCanvas.mock.calls[0][0]).toEqual(
      expect.objectContaining({ stream: hospital, liveSnapshotEnabled: false })
    );
    expect(mockReport).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
  });

  it("labels a stored poster honestly when live playback is unavailable", async () => {
    mockPlaybackStatus = "poster";
    mockApi();
    render(<LiveDemoWorkspace {...props()} />);
    expect(
      await screen.findByText("Stored preview · live video unavailable")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Live preview", { exact: true })
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("live-preview")).toHaveTextContent(
      hospital.streamId
    );
  });

  it("requires thirty seconds of newly started capture before allowing a question", async () => {
    jest.useFakeTimers({ now: new Date("2026-09-30T03:00:00Z") });
    const fetchMock = mockApi();
    render(<LiveDemoWorkspace {...props()} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).toBeEnabled()
    );
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "What is visible?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start live capture" }));
    await screen.findByRole("button", { name: "Stop capture" });
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")
    ).toHaveLength(1);
    expect(
      JSON.parse(
        String(
          fetchMock.mock.calls.find(([, init]) => init?.method === "POST")?.[1]
            ?.body
        )
      )
    ).toEqual({ streamId: hospital.streamId, action: "start" });
    await act(async () => {
      jest.advanceTimersByTime(29_000);
    });
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    await act(async () => {
      jest.advanceTimersByTime(1_000);
    });
    expect(screen.getByRole("button", { name: "Ask the video" })).toBeEnabled();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")
    ).toHaveLength(1);
  });

  it("requires a newly observed on state to collect an interval on each mount", async () => {
    jest.useFakeTimers();
    const fetchMock = mockApi({ recordingStatus: "on" });
    const view = render(<LiveDemoWorkspace {...props()} />);
    await screen.findByRole("button", { name: "Stop capture" });
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "What is visible?" },
    });
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    await act(async () => {
      jest.advanceTimersByTime(29_000);
    });
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    await act(async () => {
      jest.advanceTimersByTime(1_000);
    });
    expect(screen.getByRole("button", { name: "Ask the video" })).toBeEnabled();
    view.unmount();
    render(<LiveDemoWorkspace {...props()} />);
    await screen.findByRole("button", { name: "Stop capture" });
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "What is visible now?" },
    });
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  it("does not let a status read begun before stop overwrite its verified off state", async () => {
    jest.useFakeTimers();
    const fetchMock = mockApi({ recordingStatus: "on" });
    const baseImplementation = fetchMock.getMockImplementation()!;
    let reads = 0;
    let resolvePoll!: (response: Response) => void;
    const delayedPoll = new Promise<Response>((resolve) => {
      resolvePoll = resolve;
    });
    fetchMock.mockImplementation((input, init) => {
      if (
        String(input).startsWith("/api/vision/live-capture?") &&
        ++reads === 2
      )
        return delayedPoll;
      return baseImplementation(input, init);
    });
    render(<LiveDemoWorkspace {...props()} />);
    await screen.findByRole("button", { name: "Stop capture" });
    await act(async () => {
      jest.advanceTimersByTime(15_000);
    });
    expect(reads).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "Stop capture" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).toBeEnabled()
    );
    await act(async () => {
      resolvePoll(jsonResponse({ recordingStatus: "on" }));
    });
    expect(
      screen.getByRole("button", { name: "Start live capture" })
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Stop capture" })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
  });

  it("blocks a second question until the current answer's clip preparation finishes", async () => {
    jest.useFakeTimers();
    const fetchMock = mockApi({ recordingStatus: "on" });
    const baseImplementation = fetchMock.getMockImplementation()!;
    let resolveClip!: (response: Response) => void;
    const delayedClip = new Promise<Response>((resolve) => {
      resolveClip = resolve;
    });
    fetchMock.mockImplementation((input, init) =>
      String(input).startsWith("/api/vision/evidence?")
        ? delayedClip
        : baseImplementation(input, init)
    );
    render(<LiveDemoWorkspace {...props()} />);
    await waitForCaptureWindow();
    await askQuestion();
    fireEvent.click(
      screen.getByRole("button", { name: "Replay inspected clip" })
    );
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "What changed?" },
    });
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    fireEvent.submit(screen.getByLabelText("Your question").closest("form")!);
    expect(
      fetchMock.mock.calls.filter(([url]) => url === "/api/vision/analyst")
    ).toHaveLength(1);
    await act(async () => {
      resolveClip(jsonResponse({ videoUrl: "/retained/first-answer.mp4" }));
    });
    expect(screen.getByRole("button", { name: "Ask the video" })).toBeEnabled();
    expect(screen.getByLabelText("Inspected video evidence")).toHaveAttribute(
      "src",
      "/retained/first-answer.mp4"
    );
  });

  it("blocks questions after stop cannot verify actual capture state", async () => {
    jest.useFakeTimers();
    const fetchMock = mockApi({ recordingStatus: "on" });
    const baseImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) =>
      String(input) === "/api/vision/live-capture" && init?.method === "POST"
        ? Promise.resolve(
            jsonResponse(
              { error: "Recording status could not be verified." },
              false
            )
          )
        : baseImplementation(input, init)
    );
    render(<LiveDemoWorkspace {...props()} />);
    await waitForCaptureWindow();
    fireEvent.change(screen.getByLabelText("Your question"), {
      target: { value: "What is visible?" },
    });
    expect(screen.getByRole("button", { name: "Ask the video" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Stop capture" }));
    await screen.findByRole("alert");
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    expect(screen.queryByText("Live questions ready")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Start live capture" })
    ).toBeDisabled();
  });

  it("stops capture explicitly without resuming analysis or changing model lanes", async () => {
    const fetchMock = mockApi({ recordingStatus: "on" });
    render(<LiveDemoWorkspace {...props()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Stop capture" })
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).toBeEnabled()
    );
    const posts = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST"
    );
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe("/api/vision/live-capture");
    expect(JSON.parse(String(posts[0][1]?.body))).toEqual({
      streamId: hospital.streamId,
      action: "stop",
    });
    expect(fetchMock.mock.calls.map(([url]) => url)).not.toEqual(
      expect.arrayContaining([
        expect.stringMatching(/source-analysis|generate_captions|workload/),
      ])
    );
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    expect(
      screen.getByText(/^Search uses earlier indexed video\./)
    ).toBeInTheDocument();
  });

  it("filters earlier evidence by exact sensor identity, regardless of matching names or partial IDs", async () => {
    mockApi({
      reports: [
        savedReport("same-name", other.sensorId, "Wrong scene with same name"),
        savedReport(
          "partial-id",
          `${hospital.sensorId}-old`,
          "Old similar identity"
        ),
        savedReport("right-scene", hospital.sensorId, "Hospital evidence"),
      ],
    });
    render(<LiveDemoWorkspace {...props()} />);
    const report = await screen.findByRole("link", {
      name: /Hospital evidence/,
    });
    expect(report).toHaveAttribute(
      "href",
      "/api/vision/investigations?id=right-scene&format=html"
    );
    expect(
      screen.queryByText("Wrong scene with same name")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Old similar identity")).not.toBeInTheDocument();
  });

  it("asks about exactly the selected source, replays its observed window and gives the report that provenance", async () => {
    jest.useFakeTimers();
    const fetchMock = mockApi({ recordingStatus: "on" });
    const actions = props([other, hospital]);
    render(<LiveDemoWorkspace {...actions} />);
    await waitForCaptureWindow();
    await askQuestion();
    const call = fetchMock.mock.calls.find(
      ([url]) => url === "/api/vision/analyst"
    )!;
    const payload = JSON.parse(String(call[1]?.body));
    expect(payload).toEqual(
      expect.objectContaining({
        scope: "selected-source",
        query: answer.query,
        sources: [
          {
            kind: "live",
            name: hospital.name,
            sensorId: hospital.sensorId,
            streamId: hospital.streamId,
          },
        ],
      })
    );
    expect(Number.isFinite(Date.parse(payload.askedAt))).toBe(true);
    expect(payload.conversationId).toEqual(expect.any(String));
    expect(
      screen.getByText("Recorded interval · 25 seconds")
    ).toBeInTheDocument();
    expect(mockReport).toHaveBeenLastCalledWith({
      result: answer,
      source: payload.sources[0],
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Replay inspected clip" })
    );
    const video = await screen.findByLabelText("Inspected video evidence");
    expect(video).toHaveAttribute("src", "/retained/inspected.mp4");
    const evidenceCall = fetchMock.mock.calls.find(([url]) =>
      String(url).startsWith("/api/vision/evidence?")
    )!;
    const params = new URL(String(evidenceCall[0]), "http://ui.test")
      .searchParams;
    expect(params.get("sensorId")).toBe(hospital.streamId);
    expect(params.get("startTime")).toBe(answer.observedWindow!.startTime);
    expect(params.get("endTime")).toBe(answer.observedWindow!.endTime);
    fireEvent.click(
      screen.getByRole("button", { name: "Find related moments" })
    );
    expect(actions.onExplore).toHaveBeenCalledWith(answer.query, hospital);
    fireEvent.click(screen.getByRole("button", { name: "Return to live" }));
    expect(
      screen.queryByLabelText("Inspected video evidence")
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("live-preview")).toHaveTextContent(
      hospital.streamId
    );
  });

  it("clears the previous answer and clip when switching source and reads the new source status", async () => {
    jest.useFakeTimers();
    const fetchMock = mockApi({
      recordingStatus: "on",
      reports: [
        savedReport("hospital", hospital.sensorId),
        savedReport("other", other.sensorId),
      ],
    });
    render(<LiveDemoWorkspace {...props([hospital, other])} />);
    await waitForCaptureWindow();
    await askQuestion();
    fireEvent.click(
      screen.getByRole("button", { name: "Replay inspected clip" })
    );
    await screen.findByLabelText("Inspected video evidence");
    fireEvent.change(screen.getByLabelText("Demo camera"), {
      target: { value: other.streamId },
    });
    await waitFor(() =>
      expect(screen.getByTestId("live-preview")).toHaveTextContent(
        other.streamId
      )
    );
    expect(screen.queryByText(answer.answer)).not.toBeInTheDocument();
    expect(screen.queryByTestId("answer-report")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Inspected video evidence")
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("");
    expect(await screen.findByRole("link", { name: /other/ })).toHaveAttribute(
      "href",
      "/api/vision/investigations?id=other&format=html"
    );
    expect(
      screen.queryByRole("link", { name: /hospital/ })
    ).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toContain(
      `/api/vision/live-capture?streamId=${other.streamId}`
    );
  });
});
