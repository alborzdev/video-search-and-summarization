// SPDX-License-Identifier: MIT
// One illustrated record follows each scenario into the local VSS history.
export const cityStoryEvents = [
  { key: "queue", track: "V-21", title: "Crossing blocked", time: "08:14", asset: "intersection-queue.png", detail: "Stopped for 6 s", summary: "V-21 remained in the crossing for 6 seconds, exceeding the illustrative 5-second rule." },
  { key: "direction", track: "V-08", title: "Wrong-way travel", time: "09:32", asset: "intersection-direction.png", detail: "3 positions · 4 s", summary: "V-08 moved against the permitted lane direction across three tracked positions over 4 seconds." },
  { key: "emergency", track: "V-30 / V-22", title: "Emergency access", time: "10:06", asset: "intersection-emergency.png", detail: "Route obstructed", summary: "Ambulance V-30 approached vehicle V-22, stopped in the junction and obstructing its route." },
] as const;
