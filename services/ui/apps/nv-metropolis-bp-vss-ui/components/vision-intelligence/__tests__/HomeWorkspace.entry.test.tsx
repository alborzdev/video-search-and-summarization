// SPDX-License-Identifier: MIT

import { HomeWorkspace } from "../HomeWorkspace";
import type { VisionStream } from "../types";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import React from "react";

const recording: VisionStream = {
  name: "Warehouse recording",
  sensorId: "recording",
  streamId: "recording",
  type: "file",
  url: "",
  vodUrl: "/recording.mp4",
  metadata: {},
  isMain: true,
};
let streams: VisionStream[] = [recording];
jest.mock("../useVisionStreams", () => ({
  useVisionStreams: () => ({
    streams,
    isLoading: false,
    error: null,
    refresh: jest.fn(),
  }),
}));
jest.mock("../VisionStreamCanvas", () => ({
  VisionStreamCanvas: ({ stream }: any) => (
    <div data-testid="featured-source">{stream.name}</div>
  ),
}));

beforeEach(() => {
  sessionStorage.clear();
  streams = [recording];
});
afterEach(() => jest.restoreAllMocks());

it("leads with indexed recording and hands its exact source to Explore", async () => {
  global.fetch = jest.fn(async (input) => ({
    ok: true,
    json: async () =>
      String(input).includes("source-intelligence")
        ? { semanticSegments: String(input).includes("recording") ? 1 : 0 }
        : String(input).includes("/analysis")
        ? { state: "paused" }
        : { incidents: [] },
  })) as jest.Mock;
  const onExplore = jest.fn();
  const onOpenLive = jest.fn();
  const onOpenSystem = jest.fn();
  render(
    <HomeWorkspace
      agentApiUrl="/agent"
      onExplore={onExplore}
      onOpenLive={onOpenLive}
      onOpenEvents={jest.fn()}
      onOpenSystem={onOpenSystem}
      systemHealth={null}
    />
  );
  await waitFor(() =>
    expect(
      screen.getByText("Warehouse Recording · Searchable")
    ).toBeInTheDocument()
  );
  expect(screen.getByTestId("featured-source")).toHaveTextContent(
    "Warehouse recording"
  );
  fireEvent.click(screen.getByRole("button", { name: "Search this video" }));
  expect(onExplore).toHaveBeenCalledWith("", streams[0]);
  const sources = screen
    .getByText("Sources and connection status")
    .closest("details");
  expect(sources).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("Sources and connection status"));
  fireEvent.click(
    screen.getByRole("button", {
      name: /Warehouse Recording Recorded video Searchable/,
    })
  );
  expect(onOpenLive).toHaveBeenCalledWith(streams[0]);
  fireEvent.click(screen.getByRole("button", { name: "System" }));
  expect(onOpenSystem).toHaveBeenCalledTimes(1);
});

it("switches the preview and suggested query together for the conveyor recording", async () => {
  const conveyor = {
    ...streams[0],
    name: "conveyor-box-movement-demo",
    sensorId: "conveyor",
    streamId: "conveyor",
  };
  streams.push(conveyor);
  try {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({ semanticSegments: 1, incidents: [] }),
    })) as jest.Mock;
    const onExplore = jest.fn();
    render(
      <HomeWorkspace
        onExplore={onExplore}
        onOpenLive={jest.fn()}
        onOpenEvents={jest.fn()}
        systemHealth={null}
      />
    );
    const choice = screen.getByRole("button", {
      name: "Conveyor — Box Movement",
    });
    fireEvent.click(choice);
    await waitFor(() =>
      expect(
        screen.getByText("Conveyor — Box Movement · Searchable")
      ).toBeInTheDocument()
    );
    expect(choice).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("featured-source")).toHaveTextContent(
      conveyor.name
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Find a box moving on the conveyor" })
    );
    expect(onExplore).toHaveBeenCalledWith(
      "box moving on a conveyor belt",
      conveyor
    );
  } finally {
    streams.pop();
  }
});

it.each(["online", "unknown", "offline"] as const)(
  "leads with a %s RTSP source and never starts capture or AI on mount",
  async (connectionState) => {
    const live: VisionStream = {
      ...recording,
      name: "Spark Hospital Corridor",
      sensorId: "hospital-sensor",
      streamId: "hospital-stream",
      type: "rtsp",
      url: "rtsp://sim.test/digital-twin",
      vodUrl: "",
      connectionState,
    };
    streams = [recording, live];
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return {
        ok: true,
        json: async () =>
          url.includes("live-capture")
            ? { recordingStatus: "off" }
            : url.endsWith("/investigations")
            ? { investigations: [] }
            : url.includes("source-intelligence")
            ? { semanticSegments: 1 }
            : url.endsWith("/analysis")
            ? { state: "paused" }
            : { incidents: [] },
      } as Response;
    });
    global.fetch = fetchMock;
    render(
      <HomeWorkspace
        agentApiUrl="/agent"
        onExplore={jest.fn()}
        onOpenLive={jest.fn()}
        onOpenEvents={jest.fn()}
        systemHealth={null}
        visualAnalystAvailable
      />
    );
    expect(screen.getByLabelText("Live digital twin demo")).toBeInTheDocument();
    expect(screen.getByTestId("featured-source")).toHaveTextContent(live.name);
    expect(
      screen.queryByRole("button", { name: "Search this video" })
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls.map(([url]) => String(url))).toContain(
        `/api/vision/live-capture?streamId=${live.streamId}`
      )
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).not.toHaveTextContent("Updating")
    );
    expect(
      screen.getByRole("button", { name: "Ask the video" })
    ).toBeDisabled();
    if (connectionState === "offline")
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).toBeDisabled();
    else
      expect(
        screen.getByRole("button", { name: "Start live capture" })
      ).toBeEnabled();
    expect(
      fetchMock.mock.calls.every(
        (call) =>
          !(call as unknown as [unknown, RequestInit?])[1]?.method ||
          (call as unknown as [unknown, RequestInit?])[1]?.method === "GET"
      )
    ).toBe(true);
    expect(fetchMock.mock.calls.map(([url]) => String(url))).not.toEqual(
      expect.arrayContaining([
        expect.stringMatching(/analyst|source-analysis|generate_captions/),
      ])
    );
  }
);

it("keeps the chosen chapter after leaving the app and safely falls back if it disappears", async () => {
  const conveyor = {
    ...streams[0],
    name: "conveyor-box-movement-demo",
    sensorId: "conveyor",
    streamId: "conveyor",
  };
  streams = [...streams, conveyor];
  global.fetch = jest.fn(async () => ({
    ok: true,
    json: async () => ({ semanticSegments: 1, incidents: [] }),
  })) as jest.Mock;
  const props = {
    onExplore: jest.fn(),
    onOpenLive: jest.fn(),
    onOpenEvents: jest.fn(),
    systemHealth: null,
  };
  let first: ReturnType<typeof render>;
  await act(async () => {
    first = render(<HomeWorkspace {...props} />);
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Conveyor — Box Movement" })
  );
  first!.unmount();
  let returned: ReturnType<typeof render>;
  await act(async () => {
    returned = render(<HomeWorkspace {...props} />);
  });
  expect(screen.getByTestId("featured-source")).toHaveTextContent(
    conveyor.name
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Find a box moving on the conveyor" })
  );
  expect(props.onExplore).toHaveBeenCalledWith(
    "box moving on a conveyor belt",
    conveyor
  );
  streams = streams.slice(0, -1);
  await act(async () => {
    returned!.rerender(<HomeWorkspace {...props} />);
  });
  expect(screen.getByTestId("featured-source")).toHaveTextContent(
    "Warehouse recording"
  );
});

it("still allows chapter selection when session storage is unavailable", async () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("disabled");
  });
  const conveyor = {
    ...streams[0],
    name: "conveyor-box-movement-demo",
    sensorId: "conveyor",
    streamId: "conveyor",
  };
  streams = [...streams, conveyor];
  try {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({ incidents: [] }),
    })) as jest.Mock;
    await act(async () => {
      render(
        <HomeWorkspace
          onExplore={jest.fn()}
          onOpenLive={jest.fn()}
          onOpenEvents={jest.fn()}
          systemHealth={null}
        />
      );
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Conveyor — Box Movement",
      })
    );
    expect(screen.getByTestId("featured-source")).toHaveTextContent(
      conveyor.name
    );
  } finally {
    streams = streams.slice(0, -1);
  }
});
