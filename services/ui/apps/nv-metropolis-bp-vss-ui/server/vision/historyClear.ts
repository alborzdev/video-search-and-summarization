// SPDX-License-Identifier: MIT

import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { clearHistoryFiles, snapshotHistoryFiles, type HistoryFilesManifest } from "./historyFiles";

export type HistoryCounts = Record<"indexedMoments" | "recordings" | "reports" | "answers" | "detections" | "events" | "captions", number | null>;
export interface HistoryJob {
  id: string;
  status: "running" | "complete" | "partial" | "failed";
  cutoff: string;
  steps: Array<{ id: string; label: string; status: "pending" | "running" | "complete" | "failed"; deleted?: number; error?: string }>;
  deletedCounts: HistoryCounts;
  errors: string[];
}
interface BackendPreview {
  planToken: string; cutoff: string; expiresAt: string; sourceIds: string[];
  countsByCategory: Record<string, number>; failures: Record<string, string>;
  retainedByCategory: Record<string, number>;
}
interface BackendResult {
  status: "success" | "partial"; cutoff: string; deletedByCategory: Record<string, number>;
  failures: Record<string, string>; ingestionUnchanged: boolean;
}
interface Plan {
  id: string; backend: BackendPreview; manifest: HistoryFilesManifest;
  counts: HistoryCounts; warnings: string[]; fileErrors: string[]; jobId?: string;
}
interface Runtime {
  plans: Map<string, Plan>; jobs: Map<string, HistoryJob>; running: Map<string, Promise<void>>;
}
const RUNTIME_KEY = Symbol.for("vss.vision.history-clear-runtime");
const globalRuntime = globalThis as unknown as { [key: symbol]: Runtime };
const runtime = globalRuntime[RUNTIME_KEY] ||= { plans: new Map(), jobs: new Map(), running: new Map() };
const EMPTY_COUNTS = (): HistoryCounts => ({ indexedMoments: 0, recordings: 0, reports: 0, answers: 0, detections: 0, events: 0, captions: 0 });
const directory = () => path.join(process.env.VISION_HISTORY_DIR || "/tmp/vss-vision-intelligence-history", ".history-clear");
const backendUrl = () => (process.env.VISION_HISTORY_CLEAR_URL || "http://127.0.0.1:8101/api/v1/history-clear").replace(/\/$/, "");
const ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

export class HistoryClearError extends Error {
  constructor(message: string, readonly status = 503) { super(message); }
}
async function persist(job: HistoryJob): Promise<void> {
  await mkdir(directory(), { recursive: true, mode: 0o700 });
  const temporary = path.join(directory(), `.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(job), { mode: 0o600, flag: "wx" });
  await rename(temporary, path.join(directory(), `${job.id}.json`));
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(init?.method === "POST" ? 20 * 60_000 : 60_000) });
  const payload = await response.json().catch(() => { throw new HistoryClearError("The local history service did not return a valid preview. Try again."); });
  if (!response.ok) throw new HistoryClearError(typeof payload.detail === "string" ? payload.detail : "The local history service is unavailable. Try again.", response.status);
  return payload as T;
}
function categoryCounts(values: Record<string, number>, failures: Record<string, string>): HistoryCounts {
  if (!values || Object.values(values).some((value) => !Number.isSafeInteger(value) || value < 0)) throw new HistoryClearError("History counts could not be verified.");
  const value = (...categories: string[]): number | null => categories.some((category) => failures[category]) ? null : categories.reduce((sum, category) => sum + (values[category] || 0), 0);
  return { ...EMPTY_COUNTS(), indexedMoments: value("embeddings"), recordings: value("recordings"),
    reports: value("agentReports"), detections: value("detections", "behavior"),
    events: value("incidents", "vlmIncidents"), captions: value("captions") };
}
const total = (counts: Record<string, number | null>) => Object.values(counts).reduce<number>((sum, value) => sum + (value || 0), 0);

export async function previewHistoryClear() {
  const active = [...runtime.jobs.values()].find((job) => job.status === "running");
  if (active) throw new HistoryClearError("History cleanup is already running. Reopen its progress before starting another reset.", 409);
  const backend = await request<BackendPreview>(`${backendUrl()}/preview`);
  if (!backend.planToken || !Number.isFinite(Date.parse(backend.cutoff)) || !Number.isFinite(Date.parse(backend.expiresAt)) || !Array.isArray(backend.sourceIds)) throw new HistoryClearError("History preview could not be verified.");
  const files = await snapshotHistoryFiles(backend.cutoff);
  const counts = categoryCounts(backend.countsByCategory, backend.failures);
  if (counts.reports !== null) counts.reports += files.counts.reports;
  counts.answers = files.counts.answers;
  const warnings = [...Object.values(backend.failures), ...files.errors];
  const activeRecordings = backend.retainedByCategory?.recordings || 0;
  if (activeRecordings) warnings.push("Recordings still being written, protected footage and uploaded source videos are kept.");
  const plan: Plan = { id: randomUUID(), backend, manifest: files.manifest, counts, warnings, fileErrors: files.errors };
  for (const [id, existing] of runtime.plans) if (!existing.jobId && Date.parse(existing.backend.expiresAt) < Date.now()) runtime.plans.delete(id);
  runtime.plans.set(plan.id, plan);
  return { planId: plan.id, cutoff: backend.cutoff, expiresAt: backend.expiresAt, counts,
    sourceCount: backend.sourceIds.length, warnings };
}

async function run(job: HistoryJob, plan: Plan): Promise<void> {
  try {
    job.steps[0].status = "running";
    await persist(job);
    try {
      const result = await request<BackendResult>(backendUrl(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ planToken: plan.backend.planToken, confirmation: "CLEAR_HISTORY" }) });
      if (!result.ingestionUnchanged || result.cutoff !== job.cutoff || !result.deletedByCategory || !["success", "partial"].includes(result.status)) throw new Error("The local cleanup result could not be verified.");
      // Actual acknowledged counts are useful even when another category failed.
      job.deletedCounts = categoryCounts(result.deletedByCategory, {});
      const errors = Object.values(result.failures || {});
      if (result.status === "partial" && !errors.length) errors.push("Some history could not be cleared. Preview the remaining history again.");
      job.errors.push(...errors);
      job.steps[0].status = errors.length ? "failed" : "complete";
      job.steps[0].deleted = total(result.deletedByCategory);
      if (errors.length) job.steps[0].error = errors.join(" ");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Video history cleanup failed.";
      job.steps[0].status = "failed"; job.steps[0].error = message; job.errors.push(message);
    }
    job.steps[1].status = "running";
    await persist(job);
    try {
      const result = await clearHistoryFiles(plan.manifest);
      job.deletedCounts.reports = (job.deletedCounts.reports || 0) + result.deletedCounts.reports;
      job.deletedCounts.answers = result.deletedCounts.answers;
      job.steps[1].deleted = total(result.deletedCounts);
      job.steps[1].status = result.errors.length ? "failed" : "complete";
      if (result.errors.length) job.steps[1].error = result.errors.join(" ");
      job.errors.push(...result.errors);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Saved history cleanup failed.";
      job.steps[1].status = "failed"; job.steps[1].error = message; job.errors.push(message);
    }
    job.status = job.errors.length ? (job.steps.some((step) => step.status === "complete" || (step.deleted || 0) > 0) ? "partial" : "failed") : "complete";
  } catch (error) {
    job.errors.push(error instanceof Error ? error.message : "History cleanup was interrupted.");
    job.status = total(job.deletedCounts) ? "partial" : "failed";
    for (const step of job.steps) if (step.status === "running" || step.status === "pending") { step.status = "failed"; step.error = job.errors[job.errors.length - 1]; }
  } finally {
    try { await persist(job); } catch { job.errors.push("Cleanup status could not be saved. Keep this window open to review the result."); if (job.status === "complete") job.status = "partial"; }
    runtime.running.delete(job.id);
  }
}

export async function startHistoryClear(planId: string, confirmation: string): Promise<HistoryJob> {
  if (confirmation !== "CLEAR_HISTORY" || !ID.test(planId)) throw new HistoryClearError("Preview and confirm the history to clear first.", 422);
  const plan = runtime.plans.get(planId);
  if (!plan) throw new HistoryClearError("The history preview is no longer available. Preview again.", 409);
  if (plan.jobId) return getHistoryClearJob(plan.jobId);
  if (Date.parse(plan.backend.expiresAt) <= Date.now()) throw new HistoryClearError("The history preview expired. Preview again.", 409);
  if ([...runtime.jobs.values()].some((job) => job.status === "running")) throw new HistoryClearError("History cleanup is already running.", 409);
  const job: HistoryJob = { id: randomUUID(), cutoff: plan.backend.cutoff, status: "running", errors: [...plan.fileErrors], deletedCounts: EMPTY_COUNTS(), steps: [
    { id: "video", label: "Video, search & activity history", status: "pending" },
    { id: "saved", label: "Saved answers, reports & event states", status: "pending" },
  ] };
  // Reserve before the first await: concurrent clicks reuse the same job.
  plan.jobId = job.id; runtime.jobs.set(job.id, job);
  try { await persist(job); }
  catch { plan.jobId = undefined; runtime.jobs.delete(job.id); throw new HistoryClearError("Cleanup could not save its progress. No history was cleared."); }
  const operation = run(job, plan);
  runtime.running.set(job.id, operation);
  void operation;
  return job;
}

export function activeHistoryClearJob(): HistoryJob | undefined {
  return [...runtime.jobs.values()].find((job) => job.status === "running");
}

export async function cancelHistoryClearPreview(planId: string): Promise<void> {
  if (!ID.test(planId)) throw new HistoryClearError("Unknown history preview.", 422);
  const plan = runtime.plans.get(planId);
  if (!plan) return;
  if (plan.jobId) throw new HistoryClearError("Cleanup has already started. It continues in the background.", 409);
  // Remove local confirmation authority before awaiting the resource release.
  runtime.plans.delete(planId);
  await request(backendUrl(), { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ planToken: plan.backend.planToken }) });
}

export async function getHistoryClearJob(id: string): Promise<HistoryJob> {
  if (!ID.test(id)) throw new HistoryClearError("Unknown cleanup operation.", 404);
  const existing = runtime.jobs.get(id);
  if (existing) return existing;
  try {
    const saved = JSON.parse(await readFile(path.join(directory(), `${id}.json`), "utf8")) as HistoryJob;
    if (saved.id !== id) throw new Error("Invalid job identity");
    if (saved.status === "running") {
      saved.status = "partial";
      saved.errors.push("The app restarted during cleanup. Some history may remain; preview again after the local service finishes.");
      for (const step of saved.steps) if (step.status !== "complete") { step.status = "failed"; step.error = saved.errors[saved.errors.length - 1]; }
    }
    runtime.jobs.set(id, saved);
    return saved;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") throw new HistoryClearError("This cleanup operation is no longer available. Preview the remaining history again.", 404);
    throw error;
  }
}
