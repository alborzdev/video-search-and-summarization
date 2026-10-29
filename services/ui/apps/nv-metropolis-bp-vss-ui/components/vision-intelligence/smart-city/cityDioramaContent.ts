// SPDX-License-Identifier: MIT
export const cityCases = [
  {
    name: "Crossing safety",
    camera: "Camera 01 · Crossing",
    before: "Two tracks approach",
    event: "Interaction to review",
    question: "Did the turning car leave enough space?",
    observe: "Car C08 turns toward pedestrian P12 in the crossing.",
    rule: "Compare calibrated trajectories and their timing. Save close interactions for review.",
    action:
      "Review the clip. Find repeat patterns that may need a safer turn or signal phase.",
    evidence: "C08 + P12 · Crossing · Shared time window",
    metric: "Two paths. One crossing.",
    source: "Bellevue · Safer Signals",
    url: "https://bellevuewa.gov/city-government/departments/transportation/safety-and-maintenance/traffic-safety/safer-signals-pilot-program",
  },
  {
    name: "Queue spillback",
    camera: "Camera 01 · East approach",
    before: "Queue within lane",
    event: "Crossing blocked",
    question: "Where is the queue causing a problem?",
    observe: "Stopped vehicles extend back into the pedestrian crossing.",
    rule: "Combine low-speed tracks with crossing occupancy and a configured duration.",
    action:
      "Review the blocked crossing. Compare repeated events to support traffic operations.",
    evidence: "Queue tracks · Crossing zone · Occupancy duration",
    metric: "The queue reaches the crossing.",
    source: "FHWA · Queue management",
    url: "https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter7.htm",
  },
  {
    name: "Wrong-way movement",
    camera: "Camera 02 · One-way approach",
    before: "Vehicle enters view",
    event: "Direction mismatch",
    question: "Is that vehicle going against the lane?",
    observe: "Vehicle C21 moves against the configured lane direction.",
    rule: "Compare the tracked direction with the configured lane. Require sustained motion.",
    action:
      "Send a candidate alert with the source clip to the operator for prompt review.",
    evidence: "C21 · Lane direction · Observed track",
    metric: "Expected ←  /  observed →",
    source: "Florida DOT · Wrong-way detection",
    url: "https://fdot.gov/traffic/teo-divisions.shtm/cmt/cmtp-overview",
  },
] as const;
