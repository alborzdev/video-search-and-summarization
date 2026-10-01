/** @jest-environment node */
// SPDX-License-Identifier: MIT

import { mkdtemp, mkdir, readFile, rm, symlink, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import type { VideoHistoryRecord } from "../../../components/vision-intelligence/videoHistory";
import { clearHistoryFiles, snapshotHistoryFiles, writeVideoHistoryRecord } from "../../../server/vision/historyFiles";
import { exclusiveIncidentState, readIncidentStates, writeIncidentStates } from "../../../server/vision/incidentStateStore";

const cutoff = "2026-10-01T12:00:00Z";
const oldTime = "2026-10-01T11:00:00Z";
const newTime = "2026-10-01T13:00:00Z";
const oldReport = "11111111-1111-4111-8111-111111111111";
const newReport = "22222222-2222-4222-8222-222222222222";
let temporary: string;
let reports: string;
let history: string;
let rules: string;
let environment: Record<string, string | undefined>;

function historyRecord(overrides: Partial<VideoHistoryRecord> = {}): VideoHistoryRecord {
  return {
    sourceId: "camera-1", sourceKind: "live", sourceName: "Warehouse", knowledgeId: "camera-1", status: "ready",
    startedAt: oldTime, lastSynchronizedAt: oldTime, summary: "Previous summary", scenario: "Warehouse monitoring",
    events: ["Forklift movement"], timelineStart: "2026-10-01T10:00:00Z", timelineEnd: oldTime, ...overrides,
  };
}
async function report(id: string, created_at = oldTime, more: Record<string, unknown> = {}) {
  await writeFile(path.join(reports, `${id}.json`), JSON.stringify({ id, created_at, ...more }));
  await utimes(path.join(reports, `${id}.json`), new Date(created_at), new Date(created_at));
}
async function savedHistory() { return JSON.parse(await readFile(path.join(history, "camera-1.json"), "utf8")) as VideoHistoryRecord; }

beforeEach(async () => {
  temporary = await mkdtemp(path.join(os.tmpdir(), "vss-history-files-test-"));
  reports = path.join(temporary, "reports"); history = path.join(temporary, "history"); rules = path.join(temporary, "rules");
  await Promise.all([mkdir(reports), mkdir(history), mkdir(rules)]);
  environment = { VISION_INVESTIGATIONS_DIR: process.env.VISION_INVESTIGATIONS_DIR, VISION_HISTORY_DIR: process.env.VISION_HISTORY_DIR, VISION_RULES_DIR: process.env.VISION_RULES_DIR };
  process.env.VISION_INVESTIGATIONS_DIR = reports; process.env.VISION_HISTORY_DIR = history; process.env.VISION_RULES_DIR = rules;
});
afterEach(async () => {
  await rm(temporary, { recursive: true, force: true });
  for (const [name, value] of Object.entries(environment)) { if (value === undefined) delete process.env[name]; else process.env[name] = value; }
});

it("snapshots only old records and clears them while preserving cameras, rules and active history setup", async () => {
  await report(oldReport); await report(newReport, newTime);
  await writeVideoHistoryRecord(historyRecord());
  await writeFile(path.join(history, "live-alert-rules.json"), JSON.stringify({ rules: ["keep"] }));
  await writeFile(path.join(rules, "monitoring-rules.json"), JSON.stringify([{ id: "rule-1" }]));
  await writeIncidentStates({ old: { incidentId: "old", state: "acknowledged", updatedAt: oldTime }, fresh: { incidentId: "fresh", state: "new", updatedAt: newTime } });
  const snapshot = await snapshotHistoryFiles(cutoff);
  expect(snapshot.counts).toEqual({ reports: 1, answers: 0, summaries: 1, incidentStates: 1 });
  expect(snapshot.errors).toEqual([]);
  const cleared = await clearHistoryFiles(snapshot.manifest);
  expect(cleared).toEqual({ deletedCounts: { reports: 1, answers: 0, summaries: 1, incidentStates: 1 }, errors: [] });
  await expect(readFile(path.join(reports, `${oldReport}.json`))).rejects.toMatchObject({ code: "ENOENT" });
  expect(JSON.parse(await readFile(path.join(reports, `${newReport}.json`), "utf8"))).toMatchObject({ id: newReport });
  expect(await savedHistory()).toEqual({ sourceId: "camera-1", sourceKind: "live", sourceName: "Warehouse", knowledgeId: "camera-1", status: "ready", startedAt: oldTime, scenario: "Warehouse monitoring", events: ["Forklift movement"] });
  expect(await readIncidentStates()).toEqual({ fresh: { incidentId: "fresh", state: "new", updatedAt: newTime } });
  expect(await readFile(path.join(history, "live-alert-rules.json"), "utf8")).toContain("keep");
  expect(await readFile(path.join(rules, "monitoring-rules.json"), "utf8")).toContain("rule-1");
});

it("preserves newly synchronized summaries and workflow updates after the preview", async () => {
  await writeVideoHistoryRecord(historyRecord());
  await writeIncidentStates({ old: { incidentId: "old", state: "acknowledged", updatedAt: oldTime } });
  const snapshot = await snapshotHistoryFiles(cutoff);
  const fresh = historyRecord({ summary: "New summary", lastSynchronizedAt: newTime, timelineEnd: newTime });
  await writeVideoHistoryRecord(fresh);
  await exclusiveIncidentState(async () => {
    const states = await readIncidentStates();
    states.old = { incidentId: "old", state: "resolved", updatedAt: newTime };
    await writeIncidentStates(states);
  });
  const cleared = await clearHistoryFiles(snapshot.manifest);
  expect(cleared.deletedCounts).toMatchObject({ summaries: 0, incidentStates: 0 });
  expect(await savedHistory()).toEqual(fresh);
  expect((await readIncidentStates()).old.state).toBe("resolved");
});

it("prevents an in-flight old summary write from restoring cleared history and accepts a new summary", async () => {
  const stale = historyRecord();
  await writeVideoHistoryRecord(stale);
  const { manifest } = await snapshotHistoryFiles(cutoff);
  await clearHistoryFiles(manifest);
  await writeVideoHistoryRecord({ ...stale, sourceName: "Renamed camera" });
  expect(await savedHistory()).toMatchObject({ sourceName: "Renamed camera", scenario: stale.scenario, status: "ready" });
  expect((await savedHistory()).summary).toBeUndefined();
  expect((await savedHistory()).timelineEnd).toBeUndefined();
  const fresh = historyRecord({ lastSynchronizedAt: newTime });
  await writeVideoHistoryRecord(fresh);
  expect(await savedHistory()).toEqual(fresh);
});

it("keeps changed immutable report files and reports the skipped deletion", async () => {
  await report(oldReport);
  const { manifest } = await snapshotHistoryFiles(cutoff);
  await report(oldReport, oldTime, { notes: "Changed after preview" });
  const result = await clearHistoryFiles(manifest);
  expect(result.deletedCounts.reports).toBe(0);
  expect(result.errors[0]).toContain("changed after preview");
  expect(await readFile(path.join(reports, `${oldReport}.json`), "utf8")).toContain("Changed after preview");
});

it("allows a new explicit rebuild with identical summary text after cleanup", async () => {
  const old = historyRecord();
  await writeVideoHistoryRecord(old);
  const { manifest } = await snapshotHistoryFiles(cutoff);
  await clearHistoryFiles(manifest);
  const rebuilt = { ...old, startedAt: newTime };
  await writeVideoHistoryRecord(rebuilt);
  expect(await savedHistory()).toEqual(rebuilt);
});

it("ignores symlinks and unrelated files and refuses invalid manifest paths", async () => {
  const outside = path.join(temporary, "keep.json");
  await writeFile(outside, JSON.stringify({ id: oldReport, created_at: oldTime }));
  await symlink(outside, path.join(reports, `${oldReport}.json`));
  await writeFile(path.join(reports, ".pending.tmp"), "unfinished report");
  const snapshot = await snapshotHistoryFiles(cutoff);
  expect(snapshot.counts.reports).toBe(0);
  const result = await clearHistoryFiles({ ...snapshot.manifest, reports: [{ filename: "../keep.json", hash: "", inode: 0, size: 0, modifiedAt: 0 }] });
  expect(result.errors).toContain("Invalid captured report filename.");
  expect(await readFile(outside, "utf8")).toContain(oldReport);
});

it("reports unreadable saved records without deleting them", async () => {
  await writeFile(path.join(reports, `${oldReport}.json`), "broken json");
  await utimes(path.join(reports, `${oldReport}.json`), new Date(oldTime), new Date(oldTime));
  const snapshot = await snapshotHistoryFiles(cutoff);
  expect(snapshot.errors).toHaveLength(1);
  expect(snapshot.manifest.reports).toEqual([]);
  expect(await readFile(path.join(reports, `${oldReport}.json`), "utf8")).toBe("broken json");
});

it("keeps a newly materialized report even if its creation field predates the cutoff", async () => {
  await report(oldReport);
  await utimes(path.join(reports, `${oldReport}.json`), new Date(newTime), new Date(newTime));
  const { manifest, counts } = await snapshotHistoryFiles(cutoff);
  expect(counts.reports).toBe(0);
  await clearHistoryFiles(manifest);
  expect(JSON.parse(await readFile(path.join(reports, `${oldReport}.json`), "utf8"))).toMatchObject({ id: oldReport });
});
