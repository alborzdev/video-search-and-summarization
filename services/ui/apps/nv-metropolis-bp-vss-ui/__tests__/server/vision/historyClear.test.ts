/** @jest-environment node */
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { clearHistoryFiles, snapshotHistoryFiles } from "../../../server/vision/historyFiles";
import { activeHistoryClearJob, cancelHistoryClearPreview, getHistoryClearJob, previewHistoryClear, startHistoryClear } from "../../../server/vision/historyClear";

jest.mock("../../../server/vision/historyFiles", () => ({
  snapshotHistoryFiles: jest.fn(), clearHistoryFiles: jest.fn(),
}));
const snapshot = snapshotHistoryFiles as jest.Mock;
const clear = clearHistoryFiles as jest.Mock;
const fetchMock = jest.fn();
const cutoff = "2026-10-01T10:00:00.000Z";
const backend = { planToken: "backend-private-token", cutoff, expiresAt: "2099-01-01T00:00:00.000Z", sourceIds: ["camera"], countsByCategory: { embeddings: 3, detections: 4, behavior: 2, recordings: 1, incidents: 1 }, failures: {}, retainedByCategory: { recordings: 1 } };
const result = { status: "success", cutoff, ingestionUnchanged: true, deletedByCategory: { embeddings: 3, detections: 4, behavior: 2, recordings: 1, incidents: 1 }, failures: {} };
const response = (payload: unknown, ok = true, status = 200) => ({ ok, status, json: async () => payload });
let folder: string;

async function finished(id: string) {
  for (let attempt = 0; attempt < 100; attempt++) {
    const job = await getHistoryClearJob(id);
    if (job.status !== "running") return job;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  throw new Error("Job did not finish");
}

beforeEach(async () => {
  folder = await mkdtemp(path.join(os.tmpdir(), "history-clear-job-test-"));
  process.env.VISION_HISTORY_DIR = folder;
  const runtime = (globalThis as unknown as Record<symbol, { plans: Map<string, unknown>; jobs: Map<string, unknown>; running: Map<string, unknown> }>)[Symbol.for("vss.vision.history-clear-runtime")];
  runtime.plans.clear(); runtime.jobs.clear(); runtime.running.clear();
  snapshot.mockReset().mockResolvedValue({ manifest: { cutoff, reports: [], summaries: [], incidentStates: [] }, counts: { reports: 2, answers: 0 }, errors: [] });
  clear.mockReset().mockResolvedValue({ deletedCounts: { reports: 2, answers: 0, summaries: 1, incidentStates: 1 }, errors: [] });
  fetchMock.mockReset().mockImplementation((url: string) => Promise.resolve(response(url.endsWith("/preview") ? backend : result)));
  global.fetch = fetchMock;
});
afterEach(async () => { await rm(folder, { recursive: true, force: true }); delete process.env.VISION_HISTORY_DIR; });

test("preview is read-only and shows the frozen cutoff, counts and protected recordings", async () => {
  const plan = await previewHistoryClear();
  expect(plan.counts).toMatchObject({ indexedMoments: 3, detections: 6, reports: 2, recordings: 1 });
  expect(plan.cutoff).toBe(cutoff);
  expect(plan.warnings.join(" ")).toContain("still being written");
  expect(JSON.stringify(plan)).not.toContain("backend-private-token");
  expect(clear).not.toHaveBeenCalled();
});

test("confirmation and an expiring server plan are required before any deletion", async () => {
  const plan = await previewHistoryClear();
  await expect(startHistoryClear(plan.planId, "yes")).rejects.toMatchObject({ status: 422 });
  await expect(startHistoryClear("00000000-0000-0000-0000-000000000000", "CLEAR_HISTORY")).rejects.toMatchObject({ status: 409 });
  expect(clear).not.toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("double submit shares one background job; progress survives module consumers", async () => {
  const plan = await previewHistoryClear();
  const [first, second] = await Promise.all([startHistoryClear(plan.planId, "CLEAR_HISTORY"), startHistoryClear(plan.planId, "CLEAR_HISTORY")]);
  expect(first.id).toBe(second.id);
  const job = await finished(first.id);
  expect(job.status).toBe("complete");
  expect(job.deletedCounts).toMatchObject({ indexedMoments: 3, reports: 2 });
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(clear).toHaveBeenCalledTimes(1);
  const third = await startHistoryClear(plan.planId, "CLEAR_HISTORY");
  expect(third.id).toBe(first.id);
  expect(clear).toHaveBeenCalledTimes(1);
});

test("category failure preserves acknowledged counts, clears other histories, and reports partial", async () => {
  fetchMock.mockImplementation((url: string) => Promise.resolve(response(url.endsWith("/preview") ? backend : { ...result, status: "partial", failures: { recordings: "Old recording cleanup failed" }, deletedByCategory: { embeddings: 3, recordings: 1 } })));
  const plan = await previewHistoryClear();
  const job = await finished((await startHistoryClear(plan.planId, "CLEAR_HISTORY")).id);
  expect(job.status).toBe("partial");
  expect(job.deletedCounts).toMatchObject({ indexedMoments: 3, recordings: 1, reports: 2 });
  expect(job.errors).toContain("Old recording cleanup failed");
  expect(job.steps[1].status).toBe("complete");
});

test("failed backend cannot claim success; completed report cleanup is still reported", async () => {
  fetchMock.mockImplementation((url: string) => Promise.resolve(response(url.endsWith("/preview") ? backend : { detail: "Local service unavailable" }, url.endsWith("/preview"), 503)));
  const plan = await previewHistoryClear();
  const job = await finished((await startHistoryClear(plan.planId, "CLEAR_HISTORY")).id);
  expect(job.status).toBe("partial");
  expect(job.errors).toContain("Local service unavailable");
  expect(job.deletedCounts.reports).toBe(2);
});


test("cancel only releases preview resources and invalidates the old confirmation", async () => {
  const plan = await previewHistoryClear();
  await cancelHistoryClearPreview(plan.planId);
  expect(fetchMock.mock.calls[1][1].method).toBe("DELETE");
  await expect(startHistoryClear(plan.planId, "CLEAR_HISTORY")).rejects.toMatchObject({ status: 409 });
  expect(clear).not.toHaveBeenCalled();
});

test("an active cleanup is discoverable without browser session storage and cannot be canceled", async () => {
  let release: (value: unknown) => void = () => undefined;
  const pending = new Promise((resolve) => { release = resolve; });
  fetchMock.mockImplementation((url: string) => url.endsWith("/preview") ? Promise.resolve(response(backend)) : pending);
  const plan = await previewHistoryClear();
  const job = await startHistoryClear(plan.planId, "CLEAR_HISTORY");
  expect(activeHistoryClearJob()?.id).toBe(job.id);
  await expect(cancelHistoryClearPreview(plan.planId)).rejects.toMatchObject({ status: 409 });
  release(response(result));
  expect((await finished(job.id)).status).toBe("complete");
  expect(activeHistoryClearJob()).toBeUndefined();
});

test("unreadable files found during preview cannot become a false successful reset", async () => {
  snapshot.mockResolvedValue({ manifest: { cutoff, reports: [], summaries: [], incidentStates: [] }, counts: { reports: 0, answers: 0 }, errors: ["Saved report unreadable"] });
  const plan = await previewHistoryClear();
  const job = await finished((await startHistoryClear(plan.planId, "CLEAR_HISTORY")).id);
  expect(job.status).toBe("partial");
  expect(job.errors).toContain("Saved report unreadable");
});
