import { VssStoryWorkspace } from "../VssStoryWorkspace";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";

let pending: FrameRequestCallback[];
let reduced = false;
beforeEach(() => {
  pending = [];
  jest.spyOn(window, "requestAnimationFrame").mockImplementation((fn) => {
    pending.push(fn);
    return pending.length;
  });
  (window.matchMedia as jest.Mock).mockImplementation((query: string) => ({
    matches: query.includes("reduce") && reduced,
  }));
  global.ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
});
const flush = () =>
  act(() => {
    const frames = pending;
    pending = [];
    frames.forEach((fn) => fn(0));
  });
function setup(openDemo?: jest.Mock) {
  const leave = jest.fn();
  render(
    <VssStoryWorkspace
      onOpenDemo={openDemo}
      systemHealth={null}
      onExplore={leave}
      onOpenEvents={leave}
      onOpenLive={leave}
      onOpenRules={leave}
    />
  );
  const root = screen.getByTestId("vss-story");
  Object.defineProperty(root, "clientHeight", {
    configurable: true,
    value: 856,
  });
  root.scrollTo = jest.fn();
  return { root, leave };
}
function scroll(root: HTMLElement, step: number) {
  root.scrollTop = step * 800;
  fireEvent.scroll(root);
  flush();
}
it("introduces embedding and storage before a query, and reverses through the same context", () => {
  const { root } = setup();
  scroll(root, 2);
  expect(
    screen.getByRole("heading", { name: "Give that moment a fingerprint." })
  ).toBeInTheDocument();
  expect(screen.queryByText("You search")).not.toBeInTheDocument();
  scroll(root, 3);
  expect(screen.getByText("Local video index")).toBeInTheDocument();
  expect(screen.queryByText("You search")).not.toBeInTheDocument();
  scroll(root, 4);
  expect(screen.getByText("You search")).toBeInTheDocument();
  scroll(root, 2);
  expect(screen.queryByText("You search")).not.toBeInTheDocument();
  expect(
    screen.getByAltText(
      "A person in an orange vest carries a box across a warehouse"
    )
  ).toBeInTheDocument();
});
it("keeps chapter actions in the story and respects reduced motion", () => {
  reduced = true;
  const { root, leave } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Spot an event" }));
  expect(root.scrollTo).toHaveBeenCalledWith({ top: 8800, behavior: "auto" });
  expect(leave).not.toHaveBeenCalled();
  scroll(root, 22);
  fireEvent.click(screen.getByRole("button", { name: "Back to start" }));
  expect(root.scrollTo).toHaveBeenLastCalledWith({ top: 0, behavior: "auto" });
  reduced = false;
});

it("offers the real guided demo at the end, only after an explicit click", () => {
  const openDemo = jest.fn();
  const { root } = setup(openDemo);
  scroll(root, 22);
  expect(openDemo).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Explore your video" }));
  expect(openDemo).toHaveBeenCalledTimes(1);
});

it("supports presenter arrow keys and skips intermediate beats on a distant jump", () => {
  const { root } = setup();
  fireEvent.keyDown(root, { key: "ArrowRight" });
  expect(root.scrollTo).toHaveBeenLastCalledWith({
    top: 800,
    behavior: "smooth",
  });
  fireEvent.click(screen.getByRole("button", { name: "Ask", exact: true }));
  expect(root.scrollTo).toHaveBeenLastCalledWith({
    top: 7200,
    behavior: "auto",
  });
});
it("shows the observations behind a summary", () => {
  const { root } = setup();
  scroll(root, 10);
  expect(screen.getByText("Prepared history")).toBeInTheDocument();
  expect(screen.getByText("Clip 00:00")).toBeInTheDocument();
  expect(screen.getByText("Clip 00:04")).toBeInTheDocument();
  expect(screen.getByText("Clip 00:08")).toBeInTheDocument();
});

it("continues from the technical story through four scenarios and a closing scene", () => {
  const { root, leave } = setup();
  scroll(root, 13);
  expect(screen.getByRole("button", { name: "Next step" })).toBeInTheDocument();
  for (const [step, title] of [
    [14, "A crossing worth a closer look."],
    [16, "Did the required check happen before packing?"],
    [18, "A spill should not wait for a complaint."],
    [20, "One stopped vehicle. A growing queue."],
  ] as const) {
    scroll(root, step);
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    scroll(root, step + 1);
    expect(screen.getByText("WHAT YOUR TEAM DOES NEXT")).toBeInTheDocument();
  }
  scroll(root, 22);
  expect(
    screen.getByText("What moment would you want your cameras to find?")
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /RETAIL OPERATIONS Give staff/ })
  );
  expect(root.scrollTo).toHaveBeenLastCalledWith({
    top: 14400,
    behavior: "auto",
  });
  expect(leave).not.toHaveBeenCalled();
});

it("compares moments and opens research without changing the story", () => {
  const { root, leave } = setup();
  scroll(root, 17);
  const inspection = screen.getByRole("button", { name: "01 · Inspection" });
  fireEvent.click(inspection);
  expect(inspection).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(
    screen.getByRole("button", { name: /Research behind this example/ })
  );
  const dialog = screen.getByRole("dialog", {
    name: "Research behind this example",
  });
  expect(dialog).toHaveTextContent("Pegatron");
  expect(root).toHaveAttribute("data-active-chapter", "17");
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  scroll(root, 21);
  expect(
    screen.getByRole("button", { name: "02 · Signal green" })
  ).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "01 · Signal red" }));
  expect(
    screen.getByRole("button", { name: "01 · Signal red" })
  ).toHaveAttribute("aria-pressed", "true");
  expect(leave).not.toHaveBeenCalled();
});
