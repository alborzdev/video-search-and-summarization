// SPDX-License-Identifier: MIT

import type { VideoHistoryRecord } from "../../components/vision-intelligence/videoHistory";
import { createHash, randomUUID } from "node:crypto";
import { lstat, mkdir, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { exclusiveIncidentState, readIncidentStates, writeIncidentStates } from "./incidentStateStore";

interface FileVersion { filename: string; hash: string; inode: number; size: number; modifiedAt: number }
interface SummaryVersion { filename: string; sourceId: string; version: string }
export interface HistoryFilesManifest {
  cutoff: string;
  reports: FileVersion[];
  summaries: SummaryVersion[];
  incidentStates: Array<{ id: string; version: string }>;
}
const UUID_FILE = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.json$/i;
const HISTORY_FILE = /^[A-Za-z0-9_:-][A-Za-z0-9._:-]{0,159}\.json$/;
const SUMMARY_FIELDS = ["summary", "timelineStart", "timelineEnd", "lastSynchronizedAt"] as const;
const QUEUE = Symbol.for("vss.vision.history-file-mutation");
const shared = globalThis as unknown as { [key: symbol]: Promise<void> };

function exclusive<T>(operation: () => Promise<T>): Promise<T> {
  const previous = shared[QUEUE] || Promise.resolve();
  let release: () => void = () => undefined;
  shared[QUEUE] = new Promise<void>((resolve) => { release = resolve; });
  return previous.then(operation).finally(release);
}
function historyDirectory() { return process.env.VISION_HISTORY_DIR || "/tmp/vss-vision-intelligence-history"; }
function reportsDirectory() { return process.env.VISION_INVESTIGATIONS_DIR || "/tmp/vss-vision-intelligence-investigations"; }
function hash(value: string): string { return createHash("sha256").update(value).digest("hex"); }
function summaryVersion(record: VideoHistoryRecord): string {
  // An explicit rebuild can produce identical text for the same recorded clip.
  // Its new build identity must survive tombstones for the prior generation.
  return hash(JSON.stringify([record.startedAt, ...SUMMARY_FIELDS.map((field) => record[field] ?? null)]));
}
function stripSummary(record: VideoHistoryRecord): VideoHistoryRecord {
  const result = { ...record };
  for (const field of SUMMARY_FIELDS) delete result[field];
  return result;
}
async function files(directory: string): Promise<string[]> {
  try { return await readdir(directory); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
}
async function atomicJson(filename: string, value: unknown): Promise<void> {
  await mkdir(path.dirname(filename), { recursive: true });
  const temporary = path.join(path.dirname(filename), `.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(value, null, 2), { mode: 0o600, flag: "wx" });
  await rename(temporary, filename);
}
async function readSummaryTombstones(): Promise<Record<string, string[]>> {
  try { return JSON.parse(await readFile(path.join(historyDirectory(), ".cleared-summary-versions.json"), "utf8")); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return {}; throw error; }
}

// The API writer and cleanup share a queue. Captured summary versions are kept
// on disk so an in-flight build/status write cannot restore the cleared fields.
// A newly synchronized summary has a new version and passes through unchanged.
export async function writeVideoHistoryRecord(record: VideoHistoryRecord): Promise<void> {
  if (!HISTORY_FILE.test(`${record.sourceId}.json`)) throw new Error("Invalid history source identity.");
  await exclusive(async () => {
    const tombstones = await readSummaryTombstones();
    const safeRecord = tombstones[`source:${record.sourceId}`]?.includes(summaryVersion(record)) ? stripSummary(record) : record;
    await atomicJson(path.join(historyDirectory(), `${record.sourceId}.json`), safeRecord);
  });
}

export async function snapshotHistoryFiles(cutoff: string): Promise<{ manifest: HistoryFilesManifest; counts: { reports: number; answers: number; summaries: number; incidentStates: number }; errors: string[] }> {
  const cutoffMs = Date.parse(cutoff);
  if (!Number.isFinite(cutoffMs)) throw new Error("A valid history cleanup cutoff is required.");
  const manifest: HistoryFilesManifest = { cutoff, reports: [], summaries: [], incidentStates: [] };
  const errors: string[] = [];
  for (const filename of await files(reportsDirectory())) {
    if (!UUID_FILE.test(filename)) continue;
    try {
      const absolute = path.join(reportsDirectory(), filename);
      const before = await lstat(absolute);
      if (!before.isFile() || before.isSymbolicLink() || before.mtimeMs > cutoffMs) continue;
      const content = await readFile(absolute, "utf8");
      const record = JSON.parse(content) as { id?: string; created_at?: string };
      if (`${record.id}.json` !== filename || !Number.isFinite(Date.parse(record.created_at || ""))) throw new Error("Report identity or creation time is invalid.");
      if (Date.parse(record.created_at!) <= cutoffMs) manifest.reports.push({ filename, hash: hash(content), inode: before.ino, size: before.size, modifiedAt: before.mtimeMs });
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") errors.push(`Report ${filename}: ${error instanceof Error ? error.message : "unavailable"}`); }
  }
  for (const filename of await files(historyDirectory())) {
    if (!HISTORY_FILE.test(filename)) continue;
    try {
      const absolute = path.join(historyDirectory(), filename);
      const info = await lstat(absolute);
      if (!info.isFile() || info.isSymbolicLink()) continue;
      const record = JSON.parse(await readFile(absolute, "utf8")) as VideoHistoryRecord;
      if (`${record.sourceId}.json` !== filename) continue;
      const generated = Date.parse(record.lastSynchronizedAt || record.startedAt || "");
      if (Number.isFinite(generated) && generated <= cutoffMs && SUMMARY_FIELDS.some((field) => record[field] !== undefined)) manifest.summaries.push({ filename, sourceId: record.sourceId, version: summaryVersion(record) });
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") errors.push(`Source history ${filename}: ${error instanceof Error ? error.message : "unavailable"}`); }
  }
  try {
    await exclusiveIncidentState(async () => {
      const states = await readIncidentStates();
      for (const [id, record] of Object.entries(states)) {
        const updated = Date.parse(record.updatedAt || "");
        if (Number.isFinite(updated) && updated <= cutoffMs) manifest.incidentStates.push({ id, version: hash(JSON.stringify(record)) });
      }
    });
  } catch (error) { errors.push(`Incident workflow: ${error instanceof Error ? error.message : "unavailable"}`); }
  return { manifest, counts: { reports: manifest.reports.length, answers: 0, summaries: manifest.summaries.length, incidentStates: manifest.incidentStates.length }, errors };
}

export async function clearHistoryFiles(manifest: HistoryFilesManifest): Promise<{ deletedCounts: { reports: number; answers: number; summaries: number; incidentStates: number }; errors: string[] }> {
  const deletedCounts = { reports: 0, answers: 0, summaries: 0, incidentStates: 0 };
  const errors: string[] = [];
  for (const report of manifest.reports) {
    if (!UUID_FILE.test(report.filename)) { errors.push("Invalid captured report filename."); continue; }
    try {
      const absolute = path.join(reportsDirectory(), report.filename);
      const info = await lstat(absolute);
      if (!info.isFile() || info.isSymbolicLink() || info.ino !== report.inode || info.size !== report.size || info.mtimeMs !== report.modifiedAt || hash(await readFile(absolute, "utf8")) !== report.hash) { errors.push(`Report ${report.filename} changed after preview and was kept.`); continue; }
      await unlink(absolute);
      deletedCounts.reports += 1;
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") errors.push(`Report ${report.filename}: ${error instanceof Error ? error.message : "cleanup failed"}`); }
  }
  await exclusive(async () => {
    const tombstones = await readSummaryTombstones();
    for (const summary of manifest.summaries) {
      if (!HISTORY_FILE.test(summary.filename) || `${summary.sourceId}.json` !== summary.filename) { errors.push("Invalid captured history filename."); continue; }
      const key = `source:${summary.sourceId}`;
      tombstones[key] = Array.from(new Set([...(tombstones[key] || []), summary.version]));
    }
    if (manifest.summaries.length) await atomicJson(path.join(historyDirectory(), ".cleared-summary-versions.json"), tombstones);
    for (const summary of manifest.summaries) {
      if (!HISTORY_FILE.test(summary.filename) || `${summary.sourceId}.json` !== summary.filename) continue;
      try {
        const absolute = path.join(historyDirectory(), summary.filename);
        const info = await lstat(absolute);
        if (!info.isFile() || info.isSymbolicLink()) { errors.push(`Source history ${summary.filename} changed type and was kept.`); continue; }
        const record = JSON.parse(await readFile(absolute, "utf8")) as VideoHistoryRecord;
        if (record.sourceId === summary.sourceId && summaryVersion(record) === summary.version) { await atomicJson(absolute, stripSummary(record)); deletedCounts.summaries += 1; }
      } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") errors.push(`Source history ${summary.filename}: ${error instanceof Error ? error.message : "cleanup failed"}`); }
    }
  }).catch((error) => errors.push(`Source history cleanup: ${error instanceof Error ? error.message : "failed"}`));
  try {
    await exclusiveIncidentState(async () => {
      const states = await readIncidentStates();
      for (const state of manifest.incidentStates) {
        if (states[state.id] && hash(JSON.stringify(states[state.id])) === state.version) { delete states[state.id]; deletedCounts.incidentStates += 1; }
      }
      if (deletedCounts.incidentStates) await writeIncidentStates(states);
    });
  } catch (error) { deletedCounts.incidentStates = 0; errors.push(`Incident workflow cleanup: ${error instanceof Error ? error.message : "failed"}`); }
  return { deletedCounts, errors };
}
