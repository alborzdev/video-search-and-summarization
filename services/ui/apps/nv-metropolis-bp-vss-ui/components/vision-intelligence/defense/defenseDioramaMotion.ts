// SPDX-License-Identifier: MIT
// All steps share one scene; only the framing changes. Values use its 1672×941 coordinates.
const frames = [
  [1, 0, 0],
  [1.25, 10, 60],
  [1.25, 10, 60],
  [1.25, -220, -120],
  [1.25, -220, -120],
  [1.4, 200, -170],
  [1.4, 200, -170],
  [1, 0, 0],
  [1, 0, 0],
] as const;
export function defenseWorldFrame(progress: number) {
  const p = Math.max(
    0,
    Math.min(frames.length - 1, Number.isFinite(progress) ? progress : 0)
  );
  const index = Math.floor(p),
    next = Math.min(index + 1, frames.length - 1);
  const t = p - index,
    eased = t * t * (3 - 2 * t);
  const lerp = (i: number) =>
    frames[index][i] + (frames[next][i] - frames[index][i]) * eased;
  return { scale: lerp(0), x: lerp(1), y: lerp(2) };
}
