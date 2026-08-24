// SPDX-License-Identifier: MIT

import type { IncidentStateRecord, IncidentWorkflowState } from '../../../components/vision-intelligence/incidentState';
import type { NextApiRequest, NextApiResponse } from 'next';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const STORE_DIR = process.env.VISION_RULES_DIR || '/tmp/vss-vision-intelligence-rules';
const STORE_PATH = path.join(STORE_DIR, 'incident-state.json');
const VALID_STATES = new Set<IncidentWorkflowState>(['new', 'acknowledged', 'resolved']);

let mutationQueue: Promise<void> = Promise.resolve();

function exclusive<T>(operation: () => Promise<T>): Promise<T> {
  const previous = mutationQueue;
  let release: () => void = () => undefined;
  mutationQueue = new Promise<void>((resolve) => { release = resolve; });
  return previous.then(operation).finally(release);
}

async function readRecords(): Promise<Record<string, IncidentStateRecord>> {
  try {
    const value = JSON.parse(await readFile(STORE_PATH, 'utf8')) as unknown;
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, IncidentStateRecord>
      : {};
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return {};
    throw error;
  }
}

async function writeRecords(records: Record<string, IncidentStateRecord>): Promise<void> {
  await mkdir(STORE_DIR, { recursive: true });
  const temporary = path.join(STORE_DIR, `.incident-state-${randomUUID()}.tmp`);
  await writeFile(temporary, `${JSON.stringify(records, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, STORE_PATH);
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method === 'GET') {
    res.setHeader('Cache-Control', 'no-store');
    return res.status(200).json({ states: await readRecords() });
  }
  if (req.method === 'PUT') {
    const incidentId = String(req.body?.incidentId || '').trim();
    const state = req.body?.state as IncidentWorkflowState;
    if (!incidentId || incidentId.length > 256 || !VALID_STATES.has(state)) {
      return res.status(422).json({ error: 'Choose a valid incident and workflow state.' });
    }
    return exclusive(async () => {
      const records = await readRecords();
      const record = { incidentId, state, updatedAt: new Date().toISOString() };
      records[incidentId] = record;
      await writeRecords(records);
      return res.status(200).json({ record });
    });
  }
  res.setHeader('Allow', 'GET, PUT');
  return res.status(405).json({ error: 'Method not allowed.' });
}
