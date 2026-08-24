// SPDX-License-Identifier: MIT

export function evidenceClipEndpoint(
  sensorId: string,
  startTime: string,
  endTime: string,
  configuration?: string
): string {
  const params = new URLSearchParams({ sensorId, startTime, endTime });
  if (configuration) params.set('configuration', configuration);
  return `/api/vision/evidence?${params.toString()}`;
}
