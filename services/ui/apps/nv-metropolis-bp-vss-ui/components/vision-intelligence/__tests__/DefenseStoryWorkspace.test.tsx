import { DefenseStoryWorkspace } from "../DefenseStoryWorkspace";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

jest.mock("../LocalVisionLauncher", () => ({
  LocalVisionLauncher: () => <button>Local vision</button>,
}));
let frames: FrameRequestCallback[];
let reduced = false;
beforeEach(() => {
  frames = [];
  reduced = false;
  jest.spyOn(window, "requestAnimationFrame").mockImplementation((fn) => {
    frames.push(fn);
    return frames.length;
  });
  (window.matchMedia as jest.Mock).mockImplementation(() => ({
    matches: reduced,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
  }));
  global.ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
});
function setup() {
  const onOpenDemo = jest.fn(),
    onOpenGeneral = jest.fn();
  render(
    <DefenseStoryWorkspace
      onOpenDemo={onOpenDemo}
      onOpenGeneral={onOpenGeneral}
      systemHealth={null}
    />
  );
  const root = screen.getByTestId("defense-story");
  Object.defineProperty(root, "clientHeight", {
    configurable: true,
    value: 800,
  });
  root.scrollTo = jest.fn();
  scroll(root, 0);
  return { root, onOpenDemo, onOpenGeneral };
}
function scroll(root: HTMLElement, step: number) {
  root.scrollTop = step * 800;
  fireEvent.scroll(root);
  act(() => {
    const pending = frames;
    frames = [];
    pending.forEach((fn) => fn(0));
  });
}
it("keeps the camera source while the site story advances and makes overlays optional", () => {
  const { root } = setup();
  scroll(root, 3);
  const image = screen.getByAltText(
    "Hangar gate with a person near the marked boundary"
  );
  fireEvent.click(screen.getByRole("button", { name: "Camera only" }));
  expect(
    screen.queryByLabelText("Illustrative person cue and hangar boundary")
  ).not.toBeInTheDocument();
  scroll(root, 4);
  expect(
    screen.getByAltText("Hangar gate with a person near the marked boundary")
  ).toBe(image);
  expect(
    screen.getByLabelText("Illustrative person cue and hangar boundary")
  ).toBeVisible();
  expect(
    screen.getByText(/still image alone cannot prove a crossing/)
  ).toBeVisible();
});
it("separates the real mask, detection box and source image", () => {
  const { root } = setup();
  scroll(root, 2);
  expect(
    screen.getByAltText("Recorded SAM mask of the pavement depression")
  ).toHaveAttribute("src", "/defense-story/v2/damage-mask.png");
  expect(screen.getByText(/654 ms/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Image", exact: true }));
  expect(
    screen.queryByAltText("Recorded SAM mask of the pavement depression")
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Box", exact: true }));
  expect(screen.getByLabelText("Recorded Moondream pothole box")).toBeVisible();
  expect(
    screen.queryByAltText("Recorded SAM mask of the pavement depression")
  ).not.toBeInTheDocument();
});
it("replaces a lost camera and clears its person overlay", () => {
  const { root } = setup();
  scroll(root, 6);
  fireEvent.click(screen.getByRole("button", { name: "Simulate camera loss" }));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Rear camera unavailable"
  );
  expect(
    screen.queryByAltText("Rear camera with a person behind the vehicle")
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Illustrative person cue behind the vehicle")
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Restore camera example" })
  );
  expect(
    screen.getByAltText("Rear camera with a person behind the vehicle")
  ).toBeVisible();
});
it("simulates lost remote sharing without declaring the local system offline", () => {
  const { root } = setup();
  scroll(root, 7);
  fireEvent.click(screen.getByRole("button", { name: "Simulate uplink loss" }));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Remote sharing: queued (illustration)"
  );
  expect(screen.getByText("Local processing", { exact: true })).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Restore simulated link" })
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Remote sharing: available"
  );
});
it("connects each deployment choice to a physical location and provides working exits", () => {
  const { root, onOpenDemo, onOpenGeneral } = setup();
  scroll(root, 8);
  fireEvent.click(
    screen.getByRole("button", { name: "Vehicle visibility", exact: true })
  );
  expect(
    screen.getByRole("heading", { name: "Inside the vehicle" })
  ).toBeVisible();
  expect(screen.getByText(/performance require testing/)).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Defense workspace", exact: true })
  );
  expect(onOpenDemo).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Inside VSS", exact: true })
  );
  expect(onOpenGeneral).toHaveBeenCalledTimes(1);
});
it("links the operational need to primary evidence", () => {
  const { root } = setup();
  scroll(root, 1);
  fireEvent.click(screen.getByText("Why this mission"));
  expect(
    screen.getByRole("link", { name: /Read the primary source/ })
  ).toHaveAttribute(
    "href",
    "https://www.afit.edu/EN/news.cfm?article=0360410F7B"
  );
});
it("supports keyboard navigation and preserves the chapter when resized", () => {
  const { root } = setup();
  scroll(root, 4);
  fireEvent.keyDown(root, { key: "ArrowRight" });
  expect(root.scrollTo).toHaveBeenLastCalledWith({
    top: 4000,
    behavior: "smooth",
  });
  fireEvent.keyDown(root, { key: "Home" });
  expect(root.scrollTo).toHaveBeenLastCalledWith({ top: 0, behavior: "auto" });
  Object.defineProperty(root, "clientHeight", {
    configurable: true,
    value: 600,
  });
  // Browsers can clamp the old offset before ResizeObserver runs.
  root.scrollTop = 1300;
  fireEvent.scroll(root);
  act(() => {
    const pending = frames;
    frames = [];
    pending.forEach((fn) => fn(0));
  });
  expect(root.scrollTop).toBe(2400);
  expect(root).toHaveAttribute("data-active-chapter", "4");
});
it("pauses autoplay on interaction and respects reduced motion", () => {
  jest.useFakeTimers();
  try {
    const { root } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Play story" }));
    act(() => {
      jest.advanceTimersByTime(9000);
    });
    expect(root.scrollTo).toHaveBeenLastCalledWith({
      top: 800,
      behavior: "smooth",
    });
    fireEvent.wheel(root);
    expect(screen.getByRole("button", { name: "Play story" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
    (root.scrollTo as jest.Mock).mockClear();
    reduced = true;
    fireEvent.click(screen.getByRole("button", { name: "Play story" }));
    act(() => {
      jest.advanceTimersByTime(30000);
    });
    expect(root.scrollTo).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Play story" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  } finally {
    jest.useRealTimers();
  }
});
it("stops automatic progression when the tab is hidden", () => {
  const { root } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Play story" }));
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  fireEvent(document, new Event("visibilitychange"));
  expect(root).toHaveAttribute("data-playing", "false");
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
});
it("carries the same diorama and accumulated findings through the missions", () => {
  const { root } = setup();
  const world = screen.getByTestId("defense-diorama-image");
  scroll(root, 1);
  const camera = screen.getByAltText("Drone view of damaged airfield pavement");
  scroll(root, 2);
  expect(screen.getByTestId("defense-diorama-image")).toBe(world);
  expect(screen.getByAltText("Drone view of damaged airfield pavement")).toBe(
    camera
  );
  expect(
    screen.getByRole("button", { name: "Damage finding", exact: true })
  ).toBeVisible();
  scroll(root, 4);
  expect(screen.getByTestId("defense-diorama-image")).toBe(world);
  expect(
    screen.getByRole("button", { name: "Damage finding", exact: true })
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Entry for review", exact: true })
  ).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", {
      name: "03 Vehicle visibility",
      exact: true,
    })
  );
  expect(root.scrollTo).toHaveBeenLastCalledWith({
    top: 4000,
    behavior: "smooth",
  });
});
