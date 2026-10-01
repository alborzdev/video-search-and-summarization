// SPDX-License-Identifier: MIT

import { act, renderHook } from "@testing-library/react";
import { isBeforeHistoryCutoff, useHistoryClear } from "../useHistoryClear";

it("compares answer timestamps to the confirmed cutoff, preserving newer answers", () => {
  const cutoff = "2026-10-01T12:00:00Z";
  expect(isBeforeHistoryCutoff("2026-10-01T11:59:59Z", cutoff)).toBe(true);
  expect(isBeforeHistoryCutoff(cutoff, cutoff)).toBe(true);
  expect(isBeforeHistoryCutoff("2026-10-01T12:00:01Z", cutoff)).toBe(false);
  expect(isBeforeHistoryCutoff(undefined, cutoff)).toBe(false);
});

it("refreshes only for terminal successful or partial jobs and cleans up its listener", () => {
  const listener = jest.fn();
  const { result, unmount } = renderHook(() => useHistoryClear(listener));
  const send = (status: string, cutoff = "2026-10-01T12:00:00Z") => act(() => {
    window.dispatchEvent(new CustomEvent("vision:history-cleared", { detail: { job: { status, cutoff } } }));
  });
  send("running"); send("failed"); send("complete", "invalid");
  expect(listener).not.toHaveBeenCalled();
  send("partial");
  expect(listener).toHaveBeenCalledWith("2026-10-01T12:00:00Z");
  send("complete", "2026-10-01T11:00:00Z");
  expect(result.current.current).toBe("2026-10-01T12:00:00Z");
  unmount();
  send("complete");
  expect(listener).toHaveBeenCalledTimes(2);
});
