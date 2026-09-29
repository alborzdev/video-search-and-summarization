// SPDX-License-Identifier: MIT
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HomeWorkspace } from "../HomeWorkspace";

let streams = [
  { name: "Offline camera", sensorId: "camera", streamId: "camera", type: "rtsp", url: "rtsp://camera", vodUrl: "", metadata: {}, isMain: true },
  { name: "Warehouse recording", sensorId: "recording", streamId: "recording", type: "file", url: "", vodUrl: "/recording.mp4", metadata: {}, isMain: true },
];
jest.mock("../useVisionStreams", () => ({ useVisionStreams: () => ({ streams, isLoading: false, error: null, refresh: jest.fn() }) }));
jest.mock("../VisionStreamCanvas", () => ({ VisionStreamCanvas: ({ stream }: any) => <div data-testid="featured-source">{stream.name}</div> }));

beforeEach(() => sessionStorage.clear());
afterEach(() => jest.restoreAllMocks());

it("leads with indexed recording and hands its exact source to Explore", async () => {
  global.fetch = jest.fn(async (input) => ({ ok: true, json: async () => String(input).includes("source-intelligence")
    ? { semanticSegments: String(input).includes("recording") ? 1 : 0 }
    : String(input).includes("/analysis") ? { state: "paused" } : { incidents: [] } })) as jest.Mock;
  const onExplore = jest.fn();
  const onOpenLive = jest.fn();
  const onOpenSystem = jest.fn();
  render(<HomeWorkspace agentApiUrl="/agent" onExplore={onExplore} onOpenLive={onOpenLive} onOpenEvents={jest.fn()} onOpenSystem={onOpenSystem} systemHealth={null} />);
  await waitFor(() => expect(screen.getByText("Warehouse Recording · Searchable")).toBeInTheDocument());
  expect(screen.getByTestId("featured-source")).toHaveTextContent("Warehouse recording");
  expect(screen.getByText("Paused")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Search this video" }));
  expect(onExplore).toHaveBeenCalledWith("", streams[1]);
  const sources = screen.getByText("Sources and connection status").closest("details");
  expect(sources).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("Sources and connection status"));
  fireEvent.click(screen.getByRole("button", { name: /Warehouse Recording Recorded video Searchable/ }));
  expect(onOpenLive).toHaveBeenCalledWith(streams[1]);
  fireEvent.click(screen.getByRole("button", { name: "System" }));
  expect(onOpenSystem).toHaveBeenCalledTimes(1);
});

it("switches the preview and suggested query together for the conveyor recording", async () => {
  const conveyor = { ...streams[1], name: "conveyor-box-movement-demo", sensorId: "conveyor", streamId: "conveyor" };
  streams.push(conveyor);
  try {
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ semanticSegments: 1, incidents: [] }) })) as jest.Mock;
    const onExplore = jest.fn();
    render(<HomeWorkspace onExplore={onExplore} onOpenLive={jest.fn()} onOpenEvents={jest.fn()} systemHealth={null} />);
    const choice = screen.getByRole("button", { name: "Conveyor — Box Movement", exact: true });
    fireEvent.click(choice);
    await waitFor(() => expect(screen.getByText("Conveyor — Box Movement · Searchable")).toBeInTheDocument());
    expect(choice).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("featured-source")).toHaveTextContent(conveyor.name);
    fireEvent.click(screen.getByRole("button", { name: "Find a box moving on the conveyor" }));
    expect(onExplore).toHaveBeenCalledWith("box moving on a conveyor belt", conveyor);
  } finally {
    streams.pop();
  }
});

it("offers a connected camera directly and excludes offline or unknown sources", async () => {
  global.fetch = jest.fn(async () => ({ok:true,json:async()=>({state:'paused',incidents:[]})})) as jest.Mock;
  const onOpenLive = jest.fn();
  const props = {agentApiUrl:'/agent',onExplore:jest.fn(),onOpenLive,onOpenEvents:jest.fn(),systemHealth:null,visualAnalystAvailable:true};
  const view = render(<HomeWorkspace {...props} />);
  expect(screen.queryByRole('button',{name:'Open camera stream'})).not.toBeInTheDocument();
  const connected = {...streams[0],name:'Conveyor — Recorded Simulation (RTSP Replay)',sensorId:'connected',streamId:'connected',connectionState:'online' as const};
  streams = [...streams, connected];
  try {
    view.rerender(<HomeWorkspace {...props} />);
    const action = await screen.findByRole('button',{name:'Open camera stream'});
    fireEvent.click(action);
    expect(onOpenLive).toHaveBeenCalledWith(connected);
    await screen.findByText(/Continuous analysis is paused/);
    view.rerender(<HomeWorkspace {...props} visualAnalystAvailable={false} />);
    expect(screen.getByText(/Local AI answers are currently unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/You can still preview the stream and ask/)).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Open camera stream'})).toBeEnabled();
    view.rerender(<HomeWorkspace {...props} visualAnalystAvailable={null} />);
    expect(screen.getByText('Preview the stream while local AI readiness is checked.')).toBeInTheDocument();
  } finally { streams = streams.slice(0, -1); }
});


it("keeps the chosen chapter after leaving the app and safely falls back if it disappears", async () => {
  const conveyor = { ...streams[1], name: "conveyor-box-movement-demo", sensorId: "conveyor", streamId: "conveyor" };
  streams = [...streams, conveyor];
  global.fetch = jest.fn(async () => ({ok:true,json:async()=>({semanticSegments:1,incidents:[]})})) as jest.Mock;
  const props = {onExplore:jest.fn(),onOpenLive:jest.fn(),onOpenEvents:jest.fn(),systemHealth:null};
  const first = render(<HomeWorkspace {...props} />);
  fireEvent.click(screen.getByRole("button", {name:"Conveyor — Box Movement", exact:true}));
  first.unmount();
  const returned = render(<HomeWorkspace {...props} />);
  expect(screen.getByTestId("featured-source")).toHaveTextContent(conveyor.name);
  fireEvent.click(screen.getByRole("button", {name:"Find a box moving on the conveyor"}));
  expect(props.onExplore).toHaveBeenCalledWith("box moving on a conveyor belt", conveyor);
  streams = streams.slice(0, -1);
  returned.rerender(<HomeWorkspace {...props} />);
  expect(screen.getByTestId("featured-source")).toHaveTextContent("Warehouse recording");
});

it("still allows chapter selection when session storage is unavailable", () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {throw new Error("disabled")});
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("disabled")});
  const conveyor = { ...streams[1], name: "conveyor-box-movement-demo", sensorId: "conveyor", streamId: "conveyor" };
  streams = [...streams, conveyor];
  try {
    global.fetch = jest.fn(async () => ({ok:true,json:async()=>({incidents:[]})})) as jest.Mock;
    render(<HomeWorkspace onExplore={jest.fn()} onOpenLive={jest.fn()} onOpenEvents={jest.fn()} systemHealth={null} />);
    fireEvent.click(screen.getByRole("button", {name:"Conveyor — Box Movement", exact:true}));
    expect(screen.getByTestId("featured-source")).toHaveTextContent(conveyor.name);
  } finally { streams = streams.slice(0, -1); }
});
