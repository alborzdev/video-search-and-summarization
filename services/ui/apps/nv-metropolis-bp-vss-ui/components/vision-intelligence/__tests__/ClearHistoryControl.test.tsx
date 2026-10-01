// SPDX-License-Identifier: MIT

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { ClearHistoryControl, openClearHistory, type HistoryClearJob } from "../ClearHistoryControl";

const preview = {
  planId: "preview-1", cutoff: "2026-10-01T12:00:00Z", expiresAt: "2099-01-01T00:00:00Z", sourceCount: 1,
  counts: { indexedMoments: 42, recordings: 8, reports: 2, answers: 3, detections: 14, events: 4, captions: null }, warnings: [],
};
const running: HistoryClearJob = {
  id: "job-1", status: "running", cutoff: preview.cutoff, deletedCounts: {}, errors: [],
  steps: [{ id: "moments", label: "Indexed moments", status: "running" }, { id: "events", label: "Past events", status: "pending" }],
};
const reply = (payload: unknown, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(payload) } as Response);
let fetchMock: jest.Mock;

beforeEach(() => {
  window.sessionStorage.clear();
  fetchMock = jest.fn();
  global.fetch = fetchMock;
});

afterEach(() => { jest.useRealTimers(); });

it("renders outside the header's stacking context while keeping the app theme", async () => {
  fetchMock.mockImplementation(() => reply(preview));
  render(<div className="vi-app" data-theme="light"><header><ClearHistoryControl /></header></div>);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  const modal = screen.getByRole("dialog");
  expect(modal.closest("header")).toBeNull();
  expect(modal.closest(".vi-app")).toHaveAttribute("data-theme", "light");
});

it("shows the counted scope and keeps cancellation read only", async () => {
  fetchMock.mockImplementation(() => reply(preview));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  expect(await screen.findByText("42")).toBeInTheDocument();
  expect(screen.getByText("Unavailable")).toBeInTheDocument();
  expect(screen.getByText("Capture and indexing are unchanged")).toBeInTheDocument();
  expect(screen.getByText(/Active capture and indexing keep running/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[0][1].method).toBeUndefined();
  expect(fetchMock.mock.calls[1][1].method).toBe("DELETE");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ planId: preview.planId });
});

it("starts only after confirmation and reports background progress through completion", async () => {
  jest.useFakeTimers();
  const listener = jest.fn();
  window.addEventListener("vision:history-cleared", listener);
  fetchMock.mockImplementation((url, options) => {
    if (options?.method === "POST") return reply({ job: running });
    if (url.includes("jobId=")) return reply({ job: { ...running, status: "complete", steps: running.steps.map((step) => ({ ...step, status: "complete", deleted: 4 })) } });
    return reply(preview);
  });
  render(<ClearHistoryControl hideTrigger />);
  act(() => openClearHistory());
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Clear all previous history" }));
  fireEvent.click(screen.getByRole("button", { name: "Starting cleanup…" }));
  await screen.findByRole("heading", { name: "Clearing previous history" });
  const mutations = fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(mutations).toHaveLength(1);
  expect(JSON.parse(mutations[0][1].body)).toEqual({ planId: "preview-1", confirmation: "CLEAR_HISTORY" });
  expect(window.sessionStorage.getItem("vision-history-clear-job-v1")).toBe("job-1");
  fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
  await act(async () => { jest.advanceTimersByTime(1500); });
  act(() => openClearHistory());
  expect(screen.getByRole("heading", { name: "History cleared" })).toBeInTheDocument();
  expect(screen.getByText(/New moments can appear/)).toBeInTheDocument();
  expect(listener).toHaveBeenCalledTimes(1);
  expect(window.sessionStorage.getItem("vision-history-clear-job-v1")).toBeNull();
  window.removeEventListener("vision:history-cleared", listener);
});

it("shows partial failures without claiming history was cleared", async () => {
  fetchMock.mockImplementation((_url, options) => options?.method === "POST" ? reply({ job: { ...running, status: "partial", errors: ["Recording cleanup is unavailable."], steps: [{ id: "media", label: "Recordings", status: "failed", error: "Video I/O timed out." }] } }) : reply(preview));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Clear all previous history" }));
  expect(await screen.findByRole("heading", { name: "Some history remains" })).toBeInTheDocument();
  expect(screen.getByText("Recording cleanup is unavailable.")).toBeInTheDocument();
  expect(screen.getByText("Video I/O timed out.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "History cleared" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Review remaining history" })).toBeInTheDocument();
});

it("blocks deletion when the preview fails and allows a read only retry", async () => {
  fetchMock.mockImplementation(() => reply({ error: "Could not count recordings." }, false));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not count recordings.");
  expect(screen.queryByRole("button", { name: "Clear all previous history" })).not.toBeInTheDocument();
  fetchMock.mockImplementation(() => reply(preview));
  fireEvent.click(screen.getByRole("button", { name: "Refresh count" }));
  expect(await screen.findByText("42")).toBeInTheDocument();
  expect(fetchMock.mock.calls.every(([, options]) => options?.method !== "POST")).toBe(true);
});

it("refuses an expired confirmation and requires a fresh preview", async () => {
  fetchMock.mockImplementation(() => reply({ ...preview, expiresAt: "2000-01-01T00:00:00Z" }));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Clear all previous history" }));
  expect(screen.getByRole("alert")).toHaveTextContent("expired");
  expect(screen.getByRole("button", { name: "Refresh count" })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[1][1].method).toBe("DELETE");
});

it("never reuses an old count when a fresh opening fails", async () => {
  fetchMock.mockImplementation(() => reply(preview));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fetchMock.mockImplementation(() => reply({ error: "Preview unavailable." }, false));
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Preview unavailable.");
  expect(screen.queryByRole("button", { name: "Clear all previous history" })).not.toBeInTheDocument();
});

it("keeps tracking a running job after a failed progress request", async () => {
  jest.useFakeTimers();
  let polls = 0;
  fetchMock.mockImplementation((url, options) => {
    if (options?.method === "POST") return reply({ job: running });
    if (url.includes("jobId=")) {
      polls += 1;
      return polls === 1 ? Promise.reject(new Error("Connection interrupted.")) : reply({ job: { ...running, status: "complete" } });
    }
    return reply(preview);
  });
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Clear all previous history" }));
  await screen.findByRole("heading", { name: "Clearing previous history" });
  await act(async () => { jest.advanceTimersByTime(1000); });
  expect(screen.getByRole("alert")).toHaveTextContent("Retrying automatically");
  expect(screen.queryByRole("button", { name: "Clear all previous history" })).not.toBeInTheDocument();
  await act(async () => { jest.advanceTimersByTime(1500); });
  expect(screen.getByRole("heading", { name: "History cleared" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("resumes a saved job after a reload and stops polling when unmounted", async () => {
  jest.useFakeTimers();
  window.sessionStorage.setItem("vision-history-clear-job-v1", "job-1");
  fetchMock.mockImplementation(() => reply({ job: running }));
  const { unmount } = render(<ClearHistoryControl />);
  await act(async () => { jest.advanceTimersByTime(1); });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/vision/history-clear?jobId=job-1", expect.anything()));
  unmount();
  const calls = fetchMock.mock.calls.length;
  await act(async () => { jest.advanceTimersByTime(5000); });
  expect(fetchMock).toHaveBeenCalledTimes(calls);
});

it("recovers an active cleanup when the browser has lost its saved job ID", async () => {
  jest.useFakeTimers();
  fetchMock.mockImplementation(() => reply({ activeJob: running }));
  const { unmount } = render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  expect(await screen.findByRole("heading", { name: "Clearing previous history" })).toBeInTheDocument();
  expect(window.sessionStorage.getItem("vision-history-clear-job-v1")).toBe(running.id);
  expect(screen.queryByRole("button", { name: "Clear all previous history" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
  unmount();
  expect(fetchMock.mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
});

it("keeps core zero counts and hides optional zero saved-answer and caption tiles", async () => {
  fetchMock.mockImplementation(() => reply({ ...preview, counts: { ...preview.counts, reports: 0, answers: 0, captions: 0 } }));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  expect(screen.queryByText("Saved answers", { exact: true })).not.toBeInTheDocument();
  expect(screen.queryByText("Captions", { exact: true })).not.toBeInTheDocument();
  expect(screen.getByText("Reports").parentElement).toHaveTextContent("0");
  expect(screen.getByText("Indexed moments").parentElement!.parentElement!.children).toHaveLength(5);
  expect(screen.getByRole("button", { name: "Clear all previous history" })).toBeVisible();
});

it("explains an all-zero stored history while still allowing browser answers to be cleared", async () => {
  fetchMock.mockImplementation(() => reply({ ...preview, counts: { indexedMoments: 0, recordings: 0, reports: 0, answers: 0, detections: 0, events: 0, captions: 0 } }));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  expect(await screen.findByText(/No previous stored history \(0 items\)/)).toHaveTextContent("answers shown in this browser");
  expect(screen.getByRole("button", { name: "Clear all previous history" })).toBeEnabled();
});

it("releases an unused preview before replacing its count", async () => {
  let previews = 0;
  fetchMock.mockImplementation((_url, options) => options?.method === "DELETE" ? reply({ released: true }) : reply({ ...preview, planId: `preview-${++previews}` }));
  render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Refresh count" }));
  await screen.findByText("42");
  const releases = fetchMock.mock.calls.filter(([, options]) => options?.method === "DELETE");
  expect(releases).toHaveLength(1);
  expect(JSON.parse(releases[0][1].body)).toEqual({ planId: "preview-1" });
  expect(previews).toBe(2);
});

it.each(["close", "unmount"])("releases a preview that arrives after %s", async (action) => {
  let resolvePreview!: (response: Response) => void;
  fetchMock.mockImplementation((_url, options) => options?.method === "DELETE" ? reply({ released: true }) : new Promise<Response>((resolve) => { resolvePreview = resolve; }));
  const { unmount } = render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  if (action === "close") fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  else unmount();
  await act(async () => { resolvePreview(await reply(preview)); });
  const releases = fetchMock.mock.calls.filter(([, options]) => options?.method === "DELETE");
  expect(releases).toHaveLength(1);
  expect(JSON.parse(releases[0][1].body)).toEqual({ planId: preview.planId });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("releases a loaded unused plan on unmount", async () => {
  fetchMock.mockImplementation(() => reply(preview));
  const { unmount } = render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  unmount();
  expect(fetchMock.mock.calls.filter(([, options]) => options?.method === "DELETE")).toHaveLength(1);
});

it("does not release a plan once its clear request has started", async () => {
  let resolveJob!: (response: Response) => void;
  fetchMock.mockImplementation((_url, options) => options?.method === "POST" ? new Promise<Response>((resolve) => { resolveJob = resolve; }) : reply(preview));
  const { unmount } = render(<ClearHistoryControl />);
  fireEvent.click(screen.getByRole("button", { name: "Clear history" }));
  await screen.findByText("42");
  fireEvent.click(screen.getByRole("button", { name: "Clear all previous history" }));
  unmount();
  await act(async () => { resolveJob(await reply({ job: running })); });
  expect(fetchMock.mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
  expect(window.sessionStorage.getItem("vision-history-clear-job-v1")).toBe(running.id);
});
