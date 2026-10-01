// SPDX-License-Identifier: MIT

import { GuidedDemoWorkspace } from "../GuidedDemoWorkspace";
import { useVisionStreams } from "../useVisionStreams";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

const mockLiveMounted = jest.fn();
const mockSearchMounted = jest.fn();
const mockMonitorProps = jest.fn();
const mockReviewProps = jest.fn();

jest.mock("../useVisionStreams", () => ({ useVisionStreams: jest.fn() }));
jest.mock("next/dynamic", () => ({
  __esModule: true,
  default: (loader: () => Promise<any>) => {
    const React = require("react");
    return function DynamicTool(props: any) {
      const [Component, setComponent] = React.useState(null);
      React.useEffect(() => {
        let active = true;
        loader().then((component) => {
          if (active) setComponent(() => component);
        });
        return () => {
          active = false;
        };
      }, []);
      return Component ? React.createElement(Component, props) : null;
    };
  },
}));
jest.mock("../LiveDemoWorkspace", () => ({
  LiveDemoWorkspace: (props: any) => {
    const React = require("react");
    const [question, setQuestion] = React.useState("");
    React.useEffect(() => {
      mockLiveMounted();
    }, []);
    return (
      <section aria-label="Live desk">
        <input
          aria-label="Live question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
        {props.guidePhase === "watch" && props.guideWatchPanel}
        <button onClick={() => props.onExplore("medical cart")}>
          Explore observed cart
        </button>
      </section>
    );
  },
}));
jest.mock("../InvestigateWorkspace", () => ({
  InvestigateWorkspace: (props: any) => {
    const React = require("react");
    const [query, setQuery] = React.useState(props.initialRequest.query);
    React.useEffect(() => {
      mockSearchMounted();
    }, []);
    return (
      <section
        aria-label="Search desk"
        data-source={props.initialRequest.camera.sensorId}
        data-suggestions={props.suggestedQueries.join("|")}
      >
        <input
          aria-label="Retained search query"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </section>
    );
  },
}));
jest.mock("../AlertRulesWorkspace", () => ({
  AlertRulesWorkspace: (props: any) => {
    const React = require("react");
    const [wizard, setWizard] = React.useState(false);
    mockMonitorProps(props);
    return (
      <section aria-label="Monitoring desk">
        <span>{props.source.sensorId}</span>
        <button onClick={() => setWizard(true)}>Create monitoring rule</button>
        {wizard && <div role="dialog" aria-label="Monitoring wizard" />}
      </section>
    );
  },
}));
jest.mock("../ActivityInsightsWorkspace", () => ({
  ActivityInsightsWorkspace: (props: any) => {
    mockReviewProps(props);
    return <section aria-label="Review desk">{props.source.sensorId}</section>;
  },
}));

const source = {
  name: "Spark Hospital Corridor",
  sensorId: "hospital-sensor",
  streamId: "hospital-stream",
  url: "rtsp://camera/digital-twin",
  vodUrl: "",
  isMain: true,
  metadata: {},
  connectionState: "online" as const,
};
const other = {
  ...source,
  name: "Other camera",
  sensorId: "other-sensor",
  streamId: "other-stream",
  url: "rtsp://camera/other",
};
const props = {
  agentApiUrl: "http://agent.test/api/v1",
  vstApiUrl: "http://video.test",
  visualAnalystAvailable: true,
  searchByImageEnabled: true,
  onOpenLive: jest.fn(),
  onOpenSystem: jest.fn(),
  onOpenExplainer: jest.fn(),
};

beforeEach(() => {
  jest.clearAllMocks();
  (useVisionStreams as jest.Mock).mockReturnValue({
    streams: [other, source],
    isLoading: false,
    error: null,
    refresh: jest.fn(),
  });
  Object.defineProperty(HTMLElement.prototype, "scrollTo", {
    configurable: true,
    value: jest.fn(),
  });
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.includes("source-intelligence")
      ? {
          semanticSegments: 42,
          semanticFresh: true,
          lastSemanticAt: "2026-09-30T21:00:00Z",
        }
      : url.includes("analysis-profiles")
      ? { profile: { id: "warehouse-safety", detectionEnabled: true } }
      : url.includes("monitoring-rules")
      ? { rules: [] }
      : { state: "active" };
    return { ok: true, json: async () => payload } as Response;
  }) as jest.Mock;
});

it("loads selected-camera status read-only without starting analysis or a rule wizard", async () => {
  render(<GuidedDemoWorkspace {...props} />);
  expect(
    screen.getByRole("combobox", { name: "Workflow camera" })
  ).toHaveValue("hospital-stream");
  expect(await screen.findByText("42")).toBeInTheDocument();
  expect(screen.getByText("Index up to date")).toBeInTheDocument();
  const calls = (global.fetch as jest.Mock).mock.calls;
  expect(calls).toHaveLength(4);
  expect(
    calls.some(([url]) => String(url).includes("sensorId=hospital-sensor"))
  ).toBe(true);
  expect(
    calls.some(
      ([url]) =>
        String(url) ===
        "http://agent.test/api/v1/rtsp-streams/hospital-sensor/analysis"
    )
  ).toBe(true);
  expect(
    calls.some(([url]) =>
      String(url).includes("analysis-profiles?sourceId=hospital-sensor")
    )
  ).toBe(true);
  expect(calls.every(([, init]) => !init.method || init.method === "GET")).toBe(
    true
  );
  expect(mockMonitorProps).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps live question state mounted across every guide chapter", async () => {
  render(<GuidedDemoWorkspace {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Step 2: Ask" }));
  fireEvent.change(screen.getByLabelText("Live question"), {
    target: { value: "Are people visible?" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Step 5: Monitor" }));
  await screen.findByRole("region", { name: "Monitoring desk" });
  fireEvent.click(screen.getByRole("button", { name: "Step 2: Ask" }));
  expect(screen.getByLabelText("Live question")).toHaveValue(
    "Are people visible?"
  );
  expect(mockLiveMounted).toHaveBeenCalledTimes(1);
});

it("retains search state between Find and Follow and scopes searches to the selected camera", async () => {
  render(<GuidedDemoWorkspace {...props} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Explore observed cart" })
  );
  const query = await screen.findByLabelText("Retained search query");
  expect(query).toHaveValue("medical cart");
  expect(screen.getByRole("region", { name: "Search desk" })).toHaveAttribute(
    "data-source",
    "hospital-sensor"
  );
  expect(screen.getByRole("region", { name: "Search desk" })).toHaveAttribute(
    "data-suggestions", "pallets and storage racks|person walking through a warehouse aisle|forklift near a pallet"
  );
  fireEvent.change(query, { target: { value: "beds by the window" } });
  fireEvent.click(screen.getByRole("button", { name: "Step 4: Follow" }));
  expect(screen.getByLabelText("Retained search query")).toHaveValue(
    "beds by the window"
  );
  fireEvent.click(screen.getByRole("button", { name: "Step 2: Ask" }));
  fireEvent.click(screen.getByRole("button", { name: "Step 3: Find" }));
  expect(screen.getByLabelText("Retained search query")).toHaveValue(
    "beds by the window"
  );
  expect(mockSearchMounted).toHaveBeenCalledTimes(1);
});

it("passes explicit source selection into monitoring and review without opening a wizard automatically", async () => {
  render(<GuidedDemoWorkspace {...props} />);
  fireEvent.change(
    screen.getByRole("combobox", { name: "Workflow camera" }),
    { target: { value: "other-stream" } }
  );
  fireEvent.click(screen.getByRole("button", { name: "Step 5: Monitor" }));
  await screen.findByRole("region", { name: "Monitoring desk" });
  expect(mockMonitorProps).toHaveBeenLastCalledWith(
    expect.objectContaining({ source: other })
  );
  expect(
    screen.queryByRole("dialog", { name: "Monitoring wizard" })
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Create monitoring rule" })
  );
  expect(
    screen.getByRole("dialog", { name: "Monitoring wizard" })
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Step 6: Review" }));
  await screen.findByRole("region", { name: "Review desk" });
  expect(mockReviewProps).toHaveBeenLastCalledWith(
    expect.objectContaining({ source: other, initialMode: "activity" })
  );
  await waitFor(() =>
    expect(
      (global.fetch as jest.Mock).mock.calls.some(([url]) =>
        String(url).includes("sensorId=other-sensor")
      )
    ).toBe(true)
  );
});

it('keeps the current camera, chapter, and question when connection health changes', async () => {
  const first = { ...source, name: 'Camera One', url: 'rtsp://camera/one' };
  (useVisionStreams as jest.Mock).mockReturnValue({ streams: [first, other], isLoading: false, error: null, refresh: jest.fn() });
  const view = render(<GuidedDemoWorkspace {...props} />);
  await screen.findByText('42');
  fireEvent.click(screen.getByRole('button', { name: 'Step 2: Ask' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Live question' }), { target: { value: 'Keep this question' } });
  (useVisionStreams as jest.Mock).mockReturnValue({ streams: [{ ...first, connectionState: 'offline' }, other], isLoading: false, error: null, refresh: jest.fn() });
  view.rerender(<GuidedDemoWorkspace {...props} />);
  expect(screen.getByRole('combobox', { name: 'Workflow camera' })).toHaveValue(first.streamId);
  expect(screen.getByRole('button', { name: 'Step 2: Ask' })).toHaveAttribute('aria-current', 'step');
  expect(screen.getByRole('textbox', { name: 'Live question' })).toHaveValue('Keep this question');
  expect(mockLiveMounted).toHaveBeenCalledTimes(1);
});
