// SPDX-License-Identifier: MIT

import type { IncidentStateRecord } from "../../components/vision-intelligence/incidentState";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const QUEUE = Symbol.for("vss.vision.incident-state-mutation");
const shared = globalThis as unknown as { [key: symbol]: Promise<void> };

export function exclusiveIncidentState<T>(operation: () => Promise<T>): Promise<T> {
  const previous = shared[QUEUE] || Promise.resolve();
  let release: () => void = () => undefined;
  shared[QUEUE] = new Promise<void>((resolve) => { release = resolve; });
  return previous.then(operation).finally(release);
}

function storeDirectory(): string {
  return process.env.VISION_RULES_DIR || "/tmp/vss-vision-intelligence-rules";
}

export async function readIncidentStates(): Promise<Record<string, IncidentStateRecord>> {
  try {
    const value: unknown = JSON.parse(await readFile(path.join(storeDirectory(), "incident-state.json"), "utf8"));
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Incident workflow state is invalid.");
    return Object.assign(Object.create(null), value) as Record<string, IncidentStateRecord>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return Object.create(null);
    throw error;
  }
}

export async function writeIncidentStates(records: Record<string, IncidentStateRecord>): Promise<void> {
  const directory = storeDirectory();
  await mkdir(directory, { recursive: true });
  const temporary = path.join(directory, `.incident-state-${randomUUID()}.tmp`);
  await writeFile(temporary, `${JSON.stringify(records, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, path.join(directory, "incident-state.json"));
}
