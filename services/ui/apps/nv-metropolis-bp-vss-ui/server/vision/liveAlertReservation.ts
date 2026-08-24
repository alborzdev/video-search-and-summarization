// SPDX-License-Identifier: MIT

import { mkdir, readFile, readdir, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

export interface LiveAlertReservation {
  resumeHistory: boolean;
  sourceId: string;
}

const PREFIX = '.live-alert-';
const SUFFIX = '.json';

function historyDirectory(): string {
  return process.env.VISION_HISTORY_DIR || '/tmp/vss-vision-intelligence-history';
}

function reservationPath(ruleId: string): string {
  return path.join(historyDirectory(), `${PREFIX}${ruleId}${SUFFIX}`);
}

export async function readLiveAlertReservation(ruleId: string): Promise<LiveAlertReservation | null> {
  try {
    return JSON.parse(await readFile(reservationPath(ruleId), 'utf8')) as LiveAlertReservation;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}

export async function writeLiveAlertReservation(
  ruleId: string,
  value: LiveAlertReservation
): Promise<void> {
  await mkdir(historyDirectory(), { recursive: true });
  await writeFile(reservationPath(ruleId), JSON.stringify(value), { mode: 0o600 });
}

export async function removeLiveAlertReservation(ruleId: string): Promise<void> {
  await unlink(reservationPath(ruleId)).catch((error: NodeJS.ErrnoException) => {
    if (error.code !== 'ENOENT') throw error;
  });
}

export async function liveAlertReservationsForSource(
  sourceId: string
): Promise<Array<{ reservation: LiveAlertReservation; ruleId: string }>> {
  return (await readActiveLiveAlertReservations()).filter(
    ({ reservation }) => reservation.sourceId === sourceId
  );
}

/** Reads persisted local alert ownership without changing any rule or stream. */
export async function readActiveLiveAlertReservations(): Promise<
  Array<{ reservation: LiveAlertReservation; ruleId: string }>
> {
  let names: string[] = [];
  try {
    names = await readdir(historyDirectory());
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  const results: Array<{ reservation: LiveAlertReservation; ruleId: string }> = [];
  for (const name of names) {
    if (!name.startsWith(PREFIX) || !name.endsWith(SUFFIX)) continue;
    const ruleId = name.slice(PREFIX.length, -SUFFIX.length);
    const reservation = await readLiveAlertReservation(ruleId).catch(() => null);
    if (reservation) results.push({ reservation, ruleId });
  }
  return results;
}

export async function isSourceLiveAlertFocused(sourceId: string): Promise<boolean> {
  return (await liveAlertReservationsForSource(sourceId)).length > 0;
}
