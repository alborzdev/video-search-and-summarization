// SPDX-License-Identifier: MIT

import VisionIntelligenceApp from "../VisionIntelligenceApp";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";

jest.mock("@nv-metropolis-bp-vss-ui/all", () => ({
  VideoManagementComponent: () => <div>Dynamic management surface</div>,
}));

jest.mock("../OperationsWorkspace", () => ({
  OperationsWorkspace: (props: {
    initialStreamId?: string;
    initialView?: string;
    onInvestigate: (query: string) => void;
    onOpenActivity: () => void;
    onOpenInsights: () => void;
    onOpenRules: () => void;
    visualAnalystAvailable?: boolean | null;
  }) => (
    <div>
      <h1>Operations workspace</h1>
      <span>Initial view {props.initialView}</span>
      <span>Initial stream {props.initialStreamId || "none"}</span>
      <span>Visual analyst {String(props.visualAnalystAvailable)}</span>
      <button onClick={() => props.onInvestigate("person")}>
        Investigate person
      </button>
      <button onClick={props.onOpenActivity}>Open activity</button>
      <button onClick={props.onOpenInsights}>Open insights</button>
      <button onClick={props.onOpenRules}>Open rules</button>
    </div>
  ),
}));

jest.mock("../HomeWorkspace", () => ({
  HomeWorkspace: (props: {
    onExplore: (query: string) => void;
    onOpenEvents: () => void;
    onOpenLive: () => void;
  }) => (
    <div>
      <h1>Home workspace</h1>
      <button onClick={() => props.onExplore("person")}>Explore person</button>
      <button onClick={props.onOpenEvents}>Review events</button>
      <button onClick={props.onOpenLive}>Open live</button>
    </div>
  ),
}));

jest.mock("../CapabilitiesWorkspace", () => ({
  CapabilitiesWorkspace: () => <div>Capabilities workspace</div>,
}));

jest.mock("../InvestigateWorkspace", () => ({
  InvestigateWorkspace: (props: { initialRequest?: { query?: string } }) => (
    <div>Investigation workspace {props.initialRequest?.query || "empty"}</div>
  ),
}));

jest.mock("../ActivityInsightsWorkspace", () => ({
  ActivityInsightsWorkspace: (props: { initialMode: string }) => (
    <div>{props.initialMode} workspace</div>
  ),
}));

jest.mock("../AlertRulesWorkspace", () => ({
  AlertRulesWorkspace: (props: { onModeChange?: (mode: "monitor") => void }) => (
    <div>
      Native alert rules workspace
      <span>Rules navigation {props.onModeChange ? "enabled" : "disabled"}</span>
      {props.onModeChange && (
        <button onClick={() => props.onModeChange?.("monitor")}>Return to monitor</button>
      )}
    </div>
  ),
}));

const health = {
  checkedAt: "2026-08-19T12:00:00.000Z",
  services: [
    { key: "video", label: "Video I/O", latencyMs: 3, ok: true },
    { key: "agent", label: "Vision Agent", latencyMs: null, ok: false },
  ],
  status: "degraded",
  thor: {
    activeStreams: 2,
    gpuTemperatureC: 42,
    gpuUtilizationPercent: 18,
    memoryTotalBytes: 128 * 1024 ** 3,
    memoryUsedBytes: 80 * 1024 ** 3,
    powerWatts: 8.4,
    sampleAgeSeconds: 1,
  },
};

describe("VisionIntelligenceApp shell", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      json: async () => health,
      ok: true,
    } as Response);
  });

  afterEach(() => {
    jest.restoreAllMocks();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.removeProperty("color-scheme");
    window.localStorage.clear();
  });

  it("applies and persists a complete appearance preference", async () => {
    const firstRender = render(<VisionIntelligenceApp />);
    await screen.findByText("NVIDIA THOR · DEGRADED");

    fireEvent.click(screen.getByRole("button", { name: "Appearance: system" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Dark" }));

    expect(document.querySelector(".vi-app")).toHaveAttribute(
      "data-theme",
      "dark"
    );
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("ctai-vision-theme-v1")).toBe("dark");

    firstRender.unmount();
    render(<VisionIntelligenceApp />);
    await waitFor(() =>
      expect(document.querySelector(".vi-app")).toHaveAttribute(
        "data-theme-preference",
        "dark"
      )
    );
  });

  it("loads Home and exposes honest local readiness", async () => {
    render(<VisionIntelligenceApp />);
    expect(await screen.findByText("Home workspace")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("NVIDIA THOR · DEGRADED")).toBeInTheDocument()
    );
    expect(global.fetch).toHaveBeenCalledWith("/api/vision/health", {
      cache: "no-store",
    });

    fireEvent.click(screen.getByRole("button", { name: "System readiness" }));
    expect(screen.getByText("Thor readiness")).toBeInTheDocument();
    expect(screen.getByText("Video I/O")).toBeInTheDocument();
    expect(screen.getByText("3 ms")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("18% load")).toBeInTheDocument();
    expect(screen.getByText("80.0 GB / 128.0 GB")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Close system readiness" })
    );
    expect(screen.queryByText("Thor readiness")).not.toBeInTheDocument();
  });

  it("keeps navigation and in-workspace transitions coherent", async () => {
    render(<VisionIntelligenceApp />);
    await screen.findByText("NVIDIA THOR · DEGRADED");
    await screen.findByText("Home workspace");
    fireEvent.click(screen.getByRole("button", { name: "Explore person" }));
    expect(
      await screen.findByText("Investigation workspace person")
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Live" }));
    expect(await screen.findByText("Initial view grid")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open activity" }));
    expect(await screen.findByText("activity workspace")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Live" }));
    fireEvent.click(screen.getByRole("button", { name: "Open insights" }));
    expect(await screen.findByText("insights workspace")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Live" }));
    fireEvent.click(screen.getByRole("button", { name: "Open rules" }));
    expect(await screen.findByText("Rules navigation enabled")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Return to monitor" }));
    expect(await screen.findByText("Operations workspace")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "System" }));
    expect(
      await screen.findByRole("heading", { name: "Running locally on the edge" })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sources" }));
    expect(await screen.findByText("Dynamic management surface")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Alert rules" }));
    expect(
      await screen.findByText("Native alert rules workspace")
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Vision Intelligence home" })
    );
    expect(await screen.findByText("Home workspace")).toBeInTheDocument();
  });

  it("falls back to distraction-free presentation styling when fullscreen is denied", async () => {
    Object.defineProperty(document.documentElement, "requestFullscreen", {
      configurable: true,
      value: jest.fn().mockRejectedValue(new Error("fullscreen denied")),
    });
    render(<VisionIntelligenceApp />);
    await screen.findByText("NVIDIA THOR · DEGRADED");

    fireEvent.click(screen.getByRole("button", { name: "Presentation Mode" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Exit Presentation" })
      ).toBeInTheDocument()
    );
    expect(document.querySelector(".vi-app")).toHaveClass("is-presenting");
  });
});
