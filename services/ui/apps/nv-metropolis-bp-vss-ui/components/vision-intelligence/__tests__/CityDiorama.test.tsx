import { CityDiorama } from "../smart-city/CityDiorama";
import { cityDemoBeats, cityDemoCases } from "../smart-city/cityDemoStory";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";

it("closes with scenarios, local analytics and reviewable evidence before real deployment", () => {
  render(<CityDiorama active={12} beat={cityDemoBeats[12]} />);
  expect(screen.getByRole("heading", { name: "Validate before you deploy" })).toBeVisible();
  expect(screen.getByText("Isaac Sim on DGX Spark")).toBeVisible();
  expect(screen.getByAltText("Anvil T5 edge computer")).toBeVisible();
  expect(screen.getByText("Saved video, events and reports")).toBeVisible();
  expect(screen.getByText("Connect real cameras to the same Anvil T5")).toBeVisible();
  expect(screen.queryByLabelText("Four virtual cameras inside the digital twin")).not.toBeInTheDocument();
});
it.each(cityDemoCases.map((item, i) => [item, i + 5] as const))(
  "keeps source linkage and makes the observations reversible for %p",
  (item, active) => {
    const onInteract = jest.fn();
    const { container } = render(
      <CityDiorama
        active={active}
        beat={cityDemoBeats[active]}
        onInteract={onInteract}
      />
    );
    expect(screen.getByRole("status")).toHaveTextContent(item.status);
    expect(screen.getByText("Event focus")).toBeVisible();
    const focusedIds: Record<string, string[]> = {
      crossing: ["P-17", "P-23", "P-31"], queue: ["V-21"],
      direction: ["V-08"], emergency: ["V-30", "V-22"],
    };
    expect(within(screen.getByTestId("case-observations")).getAllByText(/^[PV]-\d+$/).map(node => node.textContent)).toEqual(focusedIds[item.id]);
    expect(screen.getByText(`CAM ${item.camera}`)).toBeVisible();
    const scene = screen.getByTestId("city-diorama");
    expect(
      container.querySelector('[data-testid="case-observations"]')
    ).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Hide observations" }));
    expect(screen.queryByTestId("case-observations")).not.toBeInTheDocument();
    expect(screen.queryByText("Event focus")).not.toBeInTheDocument();
    expect(screen.getByText("Original view")).toBeVisible();
    expect(screen.getByTestId("city-diorama")).toBe(scene);
    fireEvent.click(
      screen.getByRole("button", { name: "Replay", exact: true })
    );
    expect(screen.getByTestId("case-observations")).toBeInTheDocument();
    expect(onInteract).toHaveBeenCalledTimes(2);
  }
);
it("shows street imagery and lets visitors compare original video with observations", () => {
  render(<CityDiorama active={2} beat={cityDemoBeats[2]} />);
  expect(screen.getByRole("img", { name: "Illustrated street camera with three pedestrians and two cars" })).toBeVisible();
  expect(screen.getByText("People and vehicles with IDs")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "See original view" }));
  expect(screen.getByText("Original camera video")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Show AI observations" }));
  expect(screen.getByText("People and vehicles with IDs")).toBeVisible();
});

it("changes the zone and evidence together when selecting a street area", () => {
  const onInteract = jest.fn();
  render(<CityDiorama active={4} beat={cityDemoBeats[4]} onInteract={onInteract} />);
  expect(screen.getByRole("status")).toHaveTextContent("3 people in the crossing");
  fireEvent.click(screen.getByRole("button", { name: "Blocked crossing", exact: true }));
  expect(screen.getByRole("status")).toHaveTextContent("Vehicle blocking the crossing");
  expect(screen.getByRole("img", { name: "Illustrated camera with a marked blocked crossing zone" })).toBeVisible();
  expect(screen.getByText("Stays past the limit")).toBeVisible();
  expect(onInteract).toHaveBeenCalledTimes(1);
});

it("shows both people and vehicle identities together in both camera views", () => {
  render(<CityDiorama active={3} beat={cityDemoBeats[3]} />);
  for (const id of ["P-17", "P-23", "P-31", "V-08", "V-12"]) expect(screen.getByRole("status")).toHaveTextContent(id);
  for (const camera of ["01", "02"]) expect(screen.getByRole("img", { name: `Camera ${camera}: pedestrians P-17, P-23, P-31 and cars V-08 (red), V-12 (silver)` })).toBeVisible();
});

it("switches the activity chart's metric, units and interpretation together", () => {
  const onInteract = jest.fn();
  render(<CityDiorama active={11} beat={cityDemoBeats[11]} onInteract={onInteract} />);
  expect(screen.getByText("Crossings per 15 minutes")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Stopped time", exact: true }));
  expect(screen.getByRole("button", { name: "Stopped time", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Average stopped time · seconds")).toBeVisible();
  expect(screen.getByRole("img", { name: /Average stopped time.*Illustrative 15-minute intervals/ })).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Stopped time builds up");
  expect(onInteract).toHaveBeenCalledTimes(1);
});

it("opens a saved event with its matching footage and report, pausing the guided story", () => {
  const onInteract = jest.fn();
  render(<CityDiorama active={10} beat={cityDemoBeats[10]} onInteract={onInteract} />);
  expect(screen.getByRole("article", { name: "Saved report: Crossing blocked" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /09:32.*Wrong-way travel/ }));
  expect(screen.getByRole("button", { name: /Wrong-way travel/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("article", { name: "Saved report: Wrong-way travel" })).toBeVisible();
  expect(screen.getByRole("img", { name: "Source footage illustration: Wrong-way travel" })).toHaveAttribute("src", expect.stringContaining("intersection-direction.png"));
  expect(screen.queryByRole("article", { name: "Saved report: Crossing blocked" })).not.toBeInTheDocument();
  expect(onInteract).toHaveBeenCalledTimes(1);
});


it("connects virtual cameras on Spark through RTSP to analytics on Anvil before deployment", () => {
  render(<CityDiorama active={1} beat={cityDemoBeats[1]} />);
  expect(screen.getByRole("img", { name: "NVIDIA DGX Spark" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Test in a digital twin" })).toBeVisible();
  expect(screen.getByText("Runs the environment and virtual cameras")).toBeVisible();
  expect(screen.getByText("RTSP", { exact: true })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Run the full pipeline" })).toBeVisible();
  expect(screen.getByText("Your real analytics software + VSS")).toBeVisible();
  expect(screen.queryByText("Connect real cameras")).not.toBeInTheDocument();
  expect(screen.getByText("Anvil T5", { exact: true })).toBeVisible();
});

it("times the illustrative crossing excerpt, stops at its end, and resets on replay", () => {
  jest.useFakeTimers();
  try {
    const { unmount } = render(<CityDiorama active={5} beat={cityDemoBeats[5]} />);
    expect(screen.getByRole("timer")).toHaveAccessibleName("0 seconds occupied");
    act(() => { jest.advanceTimersByTime(6000); });
    expect(screen.getByRole("timer")).toHaveAccessibleName("6 seconds occupied");
    act(() => { jest.advanceTimersByTime(6000); });
    expect(screen.getByRole("timer")).toHaveAccessibleName("6 seconds occupied");
    fireEvent.click(screen.getByRole("button", { name: "Replay", exact: true }));
    expect(screen.getByRole("timer")).toHaveAccessibleName("0 seconds occupied");
    fireEvent.click(screen.getByRole("button", { name: "Hide observations" }));
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
    unmount();
    expect(jest.getTimerCount()).toBe(0);
  } finally { jest.useRealTimers(); }
});

it("checks stopped time before the illustrative blockage rule is met, and replays cleanly", () => {
  jest.useFakeTimers();
  try {
    const { unmount } = render(<CityDiorama active={6} beat={cityDemoBeats[6]} />);
    expect(screen.getByRole("timer")).toHaveAccessibleName("0 seconds stopped");
    expect(screen.getByText("Checking duration")).toBeVisible();
    act(() => jest.advanceTimersByTime(5000));
    expect(screen.getByText("5 s rule met")).toBeVisible();
    act(() => jest.advanceTimersByTime(6000));
    expect(screen.getByRole("timer")).toHaveAccessibleName("6 seconds stopped");
    fireEvent.click(screen.getByRole("button", { name: "Replay", exact: true }));
    expect(screen.getByRole("timer")).toHaveAccessibleName("0 seconds stopped");
    unmount();
    expect(jest.getTimerCount()).toBe(0);
  } finally { jest.useRealTimers(); }
});

it("builds a direction history from three timed observations", () => {
  jest.useFakeTimers();
  try {
    const { unmount } = render(<CityDiorama active={7} beat={cityDemoBeats[7]} />);
    expect(screen.getByLabelText("1 tracked positions")).toBeVisible();
    act(() => jest.advanceTimersByTime(2000));
    expect(screen.getByLabelText("2 tracked positions")).toBeVisible();
    act(() => jest.advanceTimersByTime(2000));
    expect(screen.getByLabelText("3 tracked positions")).toBeVisible();
    unmount();
    expect(jest.getTimerCount()).toBe(0);
  } finally { jest.useRealTimers(); }
});
