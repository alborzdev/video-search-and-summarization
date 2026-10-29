// SPDX-License-Identifier: MIT
import { spawn } from 'node:child_process';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import type { ScenarioObservation, ScenarioObservationFrame } from '../../components/vision-intelligence/smart-city/scenarioObservation';

export interface ObservationLaneState { nextAt: number; observation?: ScenarioObservation }
const directory = () => path.join(process.env.VISION_HISTORY_DIR || '/tmp/vss-vision-intelligence-history', '.city-observation');
export async function readObservationLane(): Promise<ObservationLaneState> {
  try { const value = JSON.parse(await readFile(path.join(directory(), 'latest.json'), 'utf8')); return Number.isFinite(value.nextAt) ? value : { nextAt: 0 }; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { nextAt: 0 }; throw error; }
}
export async function writeObservationLane(state: ObservationLaneState): Promise<void> {
  const temporary = path.join(directory(), `${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(state), { flag: 'wx', mode: 0o600 });
  await rename(temporary, path.join(directory(), 'latest.json'));
}
export function sharedObservation(state: ObservationLaneState, frame: ScenarioObservationFrame): ScenarioObservation | null {
  const value = state.observation;
  if (!value || !['epoch', 'runId', 'scenarioId', 'sourceId', 'sessionId'].every(key =>
    value[key as keyof ScenarioObservation] === frame[key as keyof ScenarioObservationFrame]) ||
    !/^\d{1,24}$/.test(value.sourceTimeNs) || Date.now() - Date.parse(value.observedAt) > 8000 ||
    Date.parse(value.observedAt) > Date.now() + 1000) return null;
  return value;
}
/** Both source-mounted UI servers share the history mount. An OS flock covers
 * their distinct Node processes and releases on process death, unlike a JS
 * mutex. The persisted deadline keeps a crashed caller's GPU work quarantined.
 * No queued camera images, lock-file deletion or model budget changes. */
export async function acquireObservationLane(): Promise<(() => Promise<void>) | null> {
  await mkdir(directory(), { recursive: true, mode: 0o700 });
  return new Promise((resolve, reject) => {
    const child = spawn('flock', ['-n', path.join(directory(), 'inference.lock'), process.execPath, '-e',
      "process.stdout.write('locked');process.stdin.resume();process.stdin.on('end',()=>process.exit(0));setTimeout(()=>process.exit(0),90000);"], { stdio: ['pipe', 'pipe', 'ignore'] });
    let settled = false;
    const timeout = setTimeout(() => { if (!settled) { settled = true; child.kill(); reject(new Error('Observation lock timed out')); } }, 2000);
    child.once('error', error => { clearTimeout(timeout); if (!settled) { settled = true; reject(error); } });
    child.once('exit', code => { clearTimeout(timeout); if (!settled) { settled = true; if (code === 1) resolve(null); else reject(new Error('Observation lock unavailable')); } });
    child.stdout.once('data', () => {
      if (settled) return;
      settled = true; clearTimeout(timeout);
      resolve(() => new Promise<void>(done => {
        if (child.exitCode !== null) { done(); return; }
        child.once('exit', () => done()); child.stdin.end();
      }));
    });
  });
}
