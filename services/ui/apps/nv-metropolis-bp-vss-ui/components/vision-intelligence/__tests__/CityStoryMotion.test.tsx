import { useCityStoryMotion } from "../smart-city/CityStoryMotion";
import { act, renderHook } from "@testing-library/react";
import React from "react";

const doc = document as Document & { startViewTransition?: jest.Mock };
let updates: Array<() => void>;
let skip: jest.Mock;
beforeEach(() => {
  updates = [];
  skip = jest.fn();
  doc.startViewTransition = jest.fn((update) => {
    updates.push(update);
    return { skipTransition: skip, ready: Promise.resolve(), finished: Promise.resolve() };
  });
  (window.matchMedia as jest.Mock).mockImplementation(() => ({ matches: false }));
});
afterEach(() => { delete doc.startViewTransition; });

function setup() {
  const setActive = jest.fn();
  const canvas = { current: document.createElement("div") };
  const hook = renderHook(() => useCityStoryMotion(setActive, canvas));
  return { ...hook, setActive };
}

it("discards superseded scene updates during rapid navigation", () => {
  const { result, setActive } = setup();
  act(() => { result.current(1); result.current(4); result.current(2); });
  act(() => updates.forEach(update => update()));
  expect(skip).toHaveBeenCalledTimes(2);
  expect(setActive).toHaveBeenCalledTimes(1);
  expect(setActive).toHaveBeenCalledWith(2);
});

it("changes immediately without snapshots when reduced motion is requested", () => {
  (window.matchMedia as jest.Mock).mockImplementation(() => ({ matches: true }));
  const { result, setActive } = setup();
  act(() => result.current(1));
  expect(doc.startViewTransition).not.toHaveBeenCalled();
  expect(setActive).toHaveBeenCalledWith(1);
});

it("cancels pending updates when the explainer is removed", () => {
  const { result, setActive, unmount } = setup();
  act(() => result.current(1));
  unmount();
  act(() => updates.forEach(update => update()));
  expect(skip).toHaveBeenCalledTimes(1);
  expect(setActive).not.toHaveBeenCalled();
});
