// SPDX-License-Identifier: MIT

import { sourceTimelineContext } from "../HomeWorkspace";
import type { VisionStream } from "../types";

const baseStream: VisionStream = {
  isMain: true,
  metadata: {},
  name: "Camera 1",
  sensorId: "sensor-1",
  streamId: "stream-1",
  type: "rtsp",
  url: "rtsp://camera.local/live",
  vodUrl: "",
};

describe("sourceTimelineContext", () => {
  it("does not render archival capture time as live recency", () => {
    expect(
      sourceTimelineContext(
        { ...baseStream, type: "file", url: "", vodUrl: "/recording.mp4" },
        "2025-01-01T00:00:00.000Z"
      )
    ).toBe("Indexed locally");
  });

  it("keeps a recency signal for live evidence", () => {
    jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-08-20T12:00:30.000Z"));
    expect(
      sourceTimelineContext(baseStream, "2026-08-20T12:00:00.000Z")
    ).toBe("30s ago");
  });
});
