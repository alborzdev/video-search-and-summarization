// SPDX-License-Identifier: MIT
/**
 * Shared RTSP stream utilities
 * Agent API RTSP add/delete - single API calls that handle VST and RTVI services internally
 *
 * API Endpoints:
 * - Add:    POST   /api/v1/rtsp-streams/add     { sensorUrl, name, username, password }
 * - Delete: DELETE /api/v1/rtsp-streams/delete/{sensorName}
 */

/**
 * Request body for adding RTSP stream
 */
export interface AddRtspStreamRequest {
  sensorUrl: string;
  name?: string;
  username?: string;
  password?: string;
}

/**
 * Response from adding RTSP stream
 */
export interface AddRtspStreamResult {
  status: "success";
  message?: string;
  sensorId?: string;
  vst_sensor_id?: string;
  streamId?: string;
  name?: string;
  url?: string;
  error?: string;
}

/**
 * Response from deleting RTSP stream
 */
export interface DeleteRtspStreamResult {
  status: "success";
  message: string;
  name: string;
  error?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * Add RTSP stream via Agent API
 * POST /api/v1/rtsp-streams/add
 *
 * Backend handles VST and conditionally calls RTVI-embed/RTVI-CV for search profile
 */
export async function addRtspStream(
  agentApiUrl: string,
  request: AddRtspStreamRequest,
  signal?: AbortSignal
): Promise<AddRtspStreamResult> {
  if (signal?.aborted) {
    throw new Error("Add RTSP stream was cancelled");
  }

  const response = await fetch(`${agentApiUrl}/rtsp-streams/add`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sensorUrl: request.sensorUrl,
      ...(request.name ? { name: request.name } : {}),
      username: request.username ?? "",
      password: request.password ?? "",
    }),
    signal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      text || `Failed to add RTSP stream: ${response.statusText}`
    );
  }

  const result: unknown = await response.json();

  if (!isRecord(result) || result.status !== "success") {
    throw new Error(
      (isRecord(result) && typeof result.message === "string" && result.message) ||
        (isRecord(result) && typeof result.error === "string" && result.error) ||
        "Failed to add RTSP stream"
    );
  }

  return result as unknown as AddRtspStreamResult;
}

/**
 * Delete RTSP stream via Agent API
 * DELETE /api/v1/rtsp-streams/delete/{sensorName}
 *
 * @param agentApiUrl - Base URL of the agent API (e.g., http://<IP>:8000/api/v1)
 * @param sensorName - The sensor name used when the stream was created
 * @param signal - Optional AbortSignal for cancellation
 */
export async function deleteRtspStream(
  agentApiUrl: string,
  sensorName: string,
  signal?: AbortSignal
): Promise<DeleteRtspStreamResult> {
  if (signal?.aborted) {
    throw new Error("Delete RTSP stream was cancelled");
  }

  const response = await fetch(
    `${agentApiUrl}/rtsp-streams/delete/${encodeURIComponent(sensorName)}`,
    {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
      signal,
    }
  );

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      text || `Failed to delete RTSP stream: ${response.statusText}`
    );
  }

  const result: unknown = await response.json();

  if (
    !isRecord(result) ||
    result.status !== "success" ||
    result.name !== sensorName
  ) {
    throw new Error(
      (isRecord(result) && typeof result.message === "string" && result.message) ||
        (isRecord(result) && typeof result.error === "string" && result.error) ||
        `Failed to delete RTSP stream: ${sensorName}`
    );
  }

  return result as unknown as DeleteRtspStreamResult;
}
