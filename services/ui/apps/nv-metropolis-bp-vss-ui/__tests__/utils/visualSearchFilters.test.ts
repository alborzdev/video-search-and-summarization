import { visualSearchRequests } from "../../components/vision-intelligence/InvestigateWorkspace";
import type { VisionStream } from "../../components/vision-intelligence/types";

const reference = {
  objectId: "816", objectType: "Forklift",
  sensorId: "3688c328-7e71-493c-a1c7-011ad2fb3893",
  sensorName: "SparkHospitalCorridor", timestamp: "2026-10-01T18:52:43Z",
};

describe("visual object search filters", () => {
  beforeEach(() => jest.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-01T18:55:00Z")));

  it("sends Last 15 minutes and Live archive with the selected camera", () => {
    const camera = { name: "SparkHospitalCorridor", url: "rtsp://warehouse/live" } as VisionStream;
    const requests = visualSearchRequests(reference, {
      camera, reviewStatus: "usable", sourceType: "rtsp", timeRange: "15m",
    });
    expect(requests).toHaveLength(1);
    expect(requests[0]).toEqual(expect.objectContaining({
      source_type: "rtsp", video_sources: ["SparkHospitalCorridor"],
      timestamp_start: "2026-10-01T18:40:00.000Z", timestamp_end: "2026-10-01T18:55:00.000Z",
      reference_object: expect.objectContaining({ object_id: "816", timestamp: reference.timestamp }),
    }));
  });

  it("gives both footage requests the same window without scoping all sources to the seed", () => {
    const requests = visualSearchRequests(reference, {
      reviewStatus: "usable", sourceType: "all", timeRange: "1h",
    });
    expect(requests.map((request) => request.source_type)).toEqual(["video_file", "rtsp"]);
    for (const request of requests) {
      expect(request.video_sources).toEqual([]);
      expect(request.timestamp_start).toBe("2026-10-01T17:55:00.000Z");
      expect(request.timestamp_end).toBe("2026-10-01T18:55:00.000Z");
    }
  });

  it("keeps recorded-only searches and All time explicit", () => {
    const [request] = visualSearchRequests(reference, {
      reviewStatus: "all", sourceType: "video_file", timeRange: "all",
    });
    expect(request.source_type).toBe("video_file");
    expect(request.timestamp_start).toBeNull();
    expect(request.timestamp_end).toBeNull();
  });
});
