// SPDX-License-Identifier: MIT

export interface RecordingTimeline {
  endTime: string;
  startTime: string;
}

export function recordingIsRetained(
  startTime: string,
  endTime: string,
  timelines: RecordingTimeline[]
): boolean {
  const requestedStart = Date.parse(startTime);
  const requestedEnd = Date.parse(endTime);
  if (!Number.isFinite(requestedStart) || !Number.isFinite(requestedEnd)) {
    return false;
  }

  return timelines.some((timeline) => {
    const retainedStart = Date.parse(timeline.startTime);
    const retainedEnd = Date.parse(timeline.endTime);
    return (
      Number.isFinite(retainedStart) &&
      Number.isFinite(retainedEnd) &&
      requestedStart >= retainedStart &&
      requestedEnd <= retainedEnd
    );
  });
}
