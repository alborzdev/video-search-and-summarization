// SPDX-License-Identifier: MIT

export const DEFAULT_LOOKBACK_SECONDS = 1;
export const MIN_LOOKBACK_SECONDS = 1;
export const MAX_LOOKBACK_SECONDS = 60;
export const MAX_QUESTION_FRAMES = 20;

export function validLookbackSeconds(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) &&
    value >= MIN_LOOKBACK_SECONDS && value <= MAX_LOOKBACK_SECONDS;
}

export function questionFrameCount(seconds: number): number {
  return Math.min(seconds, MAX_QUESTION_FRAMES);
}
