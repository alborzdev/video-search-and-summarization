// SPDX-License-Identifier: MIT
export type DioramaCase = "boarding" | "crossing" | "queue" | "wrong-way";
export type DioramaActor = {
  id: string;
  sprite: number;
  x: number;
  y: number;
  size: number;
  turn?: number;
};
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const cubic = (a: number, b: number, c: number, d: number, t: number) =>
  (1 - t) ** 3 * a +
  3 * (1 - t) ** 2 * t * b +
  3 * (1 - t) * t * t * c +
  t ** 3 * d;
export function dioramaActors(
  scene: DioramaCase,
  progress: number
): DioramaActor[] {
  const t = Math.max(0, Math.min(1, progress));
  if (scene === "crossing")
    return [
      {
        id: "C08",
        sprite: 0,
        x: cubic(905, 740, 700, 787, t),
        y: cubic(365, 455, 515, 562, t),
        size: 112,
        turn: Math.max(0, Math.min(1, (t - 0.35) / 0.3)),
      },
      {
        id: "P12",
        sprite: 4,
        x: lerp(895, 838, t),
        y: lerp(544, 588, t),
        size: 60,
      },
    ];
  if (scene === "queue")
    return [
      { id: "C31", sprite: 0, x: 1015, y: 714, size: 108 },
      { id: "C32", sprite: 0, x: 943, y: 670, size: 108 },
      {
        id: "C33",
        sprite: 0,
        x: lerp(620, 868, t),
        y: lerp(474, 625, t),
        size: 108,
      },
      {
        id: "C34",
        sprite: 0,
        x: lerp(540, 793, t),
        y: lerp(426, 580, t),
        size: 108,
      },
    ];
  if (scene === "wrong-way")
    return [
      {
        id: "C21",
        sprite: 1,
        x: lerp(812, 1030, t),
        y: lerp(466, 333, t),
        size: 108,
      },
    ];
  return [
    {
      id: "B04",
      sprite: 3,
      x: lerp(1090, 982, t),
      y: lerp(295, 361, t),
      size: 185,
    },
    {
      id: "V17",
      sprite: 2,
      x: lerp(993, 849, t),
      y: lerp(354, 442, t),
      size: 130,
    },
  ];
}
