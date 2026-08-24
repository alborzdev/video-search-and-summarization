// SPDX-License-Identifier: MIT

import { earliestRetainedRecordingStart } from "../../components/vision-intelligence/InvestigateWorkspace";

describe("earliestRetainedRecordingStart", () => {
  const storage = {
    cameraA: {
      timelines: [
        { startTime: "2026-08-18T04:30:33.822Z" },
        { startTime: "2026-08-17T22:49:24.477Z" },
      ],
    },
    cameraB: {
      timelines: [{ startTime: "2026-08-18T01:02:03.000Z" }],
    },
    total: { remainingStorageDays: 0.1 },
  };

  it("returns the earliest retained recording across live sources", () => {
    expect(earliestRetainedRecordingStart(storage)).toBe(
      "2026-08-17T22:49:24.477Z"
    );
  });

  it("can scope the retention bound to one source", () => {
    expect(earliestRetainedRecordingStart(storage, "cameraA")).toBe(
      "2026-08-17T22:49:24.477Z"
    );
    expect(earliestRetainedRecordingStart(storage, "cameraB")).toBe(
      "2026-08-18T01:02:03.000Z"
    );
  });

  it("ignores malformed entries and absent sources", () => {
    expect(earliestRetainedRecordingStart({ cameraA: { timelines: [{}] } })).toBeNull();
    expect(earliestRetainedRecordingStart(storage, "missing")).toBeNull();
    expect(earliestRetainedRecordingStart(null)).toBeNull();
  });
});
