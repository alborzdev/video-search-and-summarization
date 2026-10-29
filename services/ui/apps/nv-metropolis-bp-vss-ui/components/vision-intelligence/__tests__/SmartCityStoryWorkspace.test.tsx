import { SmartCityStoryWorkspace } from "../SmartCityStoryWorkspace";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

let frames: FrameRequestCallback[];
beforeEach(() => {
  frames = [];
  jest.spyOn(window, "requestAnimationFrame").mockImplementation((fn) => {
    frames.push(fn);
    return frames.length;
  });
  (window.matchMedia as jest.Mock).mockImplementation(() => ({
    matches: false,
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
  const onOpenDemo = jest.fn();
  render(
    <SmartCityStoryWorkspace
      onOpenDemo={onOpenDemo}
      onOpenGeneral={jest.fn()}
      systemHealth={null}
    />
  );
  const root = screen.getByTestId("smart-city-story");
  Object.defineProperty(root, "clientHeight", {
    configurable: true,
    value: 800,
  });
  root.scrollTo = jest.fn();
  return { root, onOpenDemo };
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
it("keeps the same diorama node while adding and reversing interpretation layers", () => {
  const { root } = setup();
  const image = screen.getByTestId("city-diorama");
  scroll(root, 2);
  expect(
    screen.getByRole("heading", { name: "Detect people and vehicles" })
  ).toBeVisible();
  scroll(root, 8);
  expect(
    screen.getByRole("heading", { name: "Flag gridlock blocking emergency access" })
  ).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("Emergency route blocked");
  expect(screen.getByTestId("city-diorama")).toBe(image);
  scroll(root, 2.2);
  const stage = root.querySelector("[data-step]") as HTMLElement;
  expect(stage.style.getPropertyValue("--detect")).toBe("1");
  expect(stage.style.getPropertyValue("--zone")).toBe("0");
  expect(screen.getByTestId("city-diorama")).toBe(image);
});
it("preserves the current concept when the viewport changes height", () => {
  const { root } = setup();
  scroll(root, 8);
  Object.defineProperty(root, "clientHeight", {
    configurable: true,
    value: 600,
  });
  fireEvent.scroll(root);
  act(() => {
    const pending = frames;
    frames = [];
    pending.forEach((fn) => fn(0));
  });
  expect(root.scrollTop).toBe(4800);
  expect(root).toHaveAttribute("data-active-chapter", "8");
});
it("progresses and navigates using the Smart City overview's shared scroller", () => {
  const { container } = render(
    <div data-city-scroll>
      <SmartCityStoryWorkspace embedded onOpenDemo={jest.fn()} onOpenGeneral={jest.fn()} systemHealth={null} />
    </div>
  );
  const scroller = container.querySelector("[data-city-scroll]") as HTMLElement;
  const story = screen.getByTestId("smart-city-story");
  Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 800 });
  scroller.scrollTo = jest.fn();
  scroller.getBoundingClientRect = () => ({ top: 0 } as DOMRect);
  story.getBoundingClientRect = () => ({ top: 600 - scroller.scrollTop } as DOMRect);
  scroller.scrollTop = 600 + 2 * 800;
  fireEvent.scroll(scroller);
  act(() => { const pending = frames; frames = []; pending.forEach((fn) => fn(0)); });
  expect(story).toHaveAttribute("data-active-chapter", "2");
  expect(screen.getByRole("heading", { name: "Detect people and vehicles" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Next step" }));
  expect(scroller.scrollTo).toHaveBeenCalledWith({ top: 600 + 3 * 800, behavior: "auto" });
  scroller.scrollTop = 200;
  fireEvent.scroll(scroller);
  act(() => { const pending = frames; frames = []; pending.forEach((fn) => fn(0)); });
  expect(story).toHaveAttribute("data-active-chapter", "0");
});
it("shows four cases with camera-linked observations and an explicit workspace action", () => {
  const { root, onOpenDemo } = setup();
  for (const [step, name, event] of [
    [5, "Crossing safety", "Crossing occupied"],
    [6, "Queue blockage", "Crossing blocked"],
    [7, "Wrong-way travel", "Direction mismatch"],
    [8, "Emergency access", "Emergency route blocked"],
  ] as const) {
    scroll(root, step);
    expect(screen.getByRole("region", { name })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(event);
    fireEvent.click(screen.getByRole("button", { name: "Hide observations" }));
    expect(screen.getByRole("status")).toHaveTextContent("Street scene");
    fireEvent.click(screen.getByRole("button", { name: "Show observations" }));
    expect(screen.getByRole("status")).toHaveTextContent(event);
  }
  scroll(root, 12);
  expect(onOpenDemo).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Open Smart City", exact: true })
  );
  expect(onOpenDemo).toHaveBeenCalledTimes(1);
});

it("advances the guided story and pauses immediately for manual scrolling", () => {
  jest.useFakeTimers();
  try {
    const { root } = setup();
    scroll(root, 0);
    fireEvent.click(
      screen.getByRole("button", { name: "Play story", exact: true })
    );
    act(() => {
      jest.advanceTimersByTime(6000);
    });
    expect(root.scrollTo).toHaveBeenLastCalledWith({
      top: 800,
      behavior: "auto",
    });
    scroll(root, 1);
    fireEvent.wheel(root);
    expect(
      screen.getByRole("button", { name: "Play story", exact: true })
    ).toHaveAttribute("aria-pressed", "false");
    (root.scrollTo as jest.Mock).mockClear();
    act(() => {
      jest.advanceTimersByTime(15000);
    });
    expect(root.scrollTo).not.toHaveBeenCalled();
  } finally {
    jest.useRealTimers();
  }
});

it("stops the guided story when the page becomes hidden", () => {
  jest.useFakeTimers();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  try {
    const { root } = setup();
    scroll(root, 0);
    fireEvent.click(
      screen.getByRole("button", { name: "Play story", exact: true })
    );
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    fireEvent(document, new Event("visibilitychange"));
    expect(
      screen.getByRole("button", { name: "Play story", exact: true })
    ).toHaveAttribute("aria-pressed", "false");
    act(() => {
      jest.advanceTimersByTime(15000);
    });
    expect(root.scrollTo).not.toHaveBeenCalled();
  } finally {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    jest.useRealTimers();
  }
});
