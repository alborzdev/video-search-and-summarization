// SPDX-License-Identifier: MIT

/** Host-observed progress, independent of camera clock offsets. Bounded per process. */
type Observation = { value: number; advancedAt: number | null };
// Next bundles API routes separately; capture polling and asking must share
// the same observed timeline, including through source-mounted hot reloads.
const shared = globalThis as typeof globalThis & { __vssObservedProgress?: Map<string, Observation> };
const observations = shared.__vssObservedProgress ??= new Map<string, Observation>();
export function observedProgress(key: string, value: number, ttlMs: number, now = Date.now()): boolean {
  if (!Number.isFinite(value)) return false;
  const previous = observations.get(key);
  const advancedAt = previous && value > previous.value ? now : previous?.advancedAt ?? null;
  if (!observations.has(key) && observations.size >= 512) observations.delete(observations.keys().next().value!);
  observations.set(key, { value, advancedAt });
  return advancedAt !== null && now >= advancedAt && now - advancedAt <= ttlMs;
}
