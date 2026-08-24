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
  detectionEnabled?: boolean;
  analysisProfileId?: string;
}

/**
 * Response from adding RTSP stream
 */
export interface AddRtspStreamResult {
  status: "success";
  message?: string;
  sensorId: string;
  name: string;
  detectionEnabled?: boolean;
  analysisProfileId: string;
  error?: string;
}

/**
 * Response from deleting RTSP stream
 */
export interface DeleteRtspStreamResult {
  status: "success";
  message: string;
  name: string;
  sensorId: string;
  error?: string;
}

export interface ResetRtspStreamResult {
  status: "success" | "partial" | "failure";
  message: string;
  sensorId: string;
  name: string;
  deletedDocuments: number;
  deletedByCategory: Record<string, number>;
  recordingsCleared: boolean;
  analysisResumed: boolean;
  resetAt: string;
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
      ...(request.analysisProfileId
        ? { analysisProfileId: request.analysisProfileId }
        : { detectionEnabled: request.detectionEnabled ?? false }),
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

  if (
    !isRecord(result) ||
    result.status !== "success" ||
    typeof result.sensorId !== "string" ||
    result.sensorId.length === 0 ||
    typeof result.analysisProfileId !== "string" ||
    result.analysisProfileId.length === 0 ||
    typeof result.name !== "string" ||
    result.name !== request.name
  ) {
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
    result.name !== sensorName ||
    typeof result.sensorId !== "string" ||
    result.sensorId.length === 0
  ) {
    throw new Error(
      (isRecord(result) && typeof result.message === "string" && result.message) ||
        (isRecord(result) && typeof result.error === "string" && result.error) ||
        `Failed to delete RTSP stream: ${sensorName}`
    );
  }

  return result as unknown as DeleteRtspStreamResult;
}

/**
 * Clear all generated analytics for a live source while leaving it connected.
 * The backend pauses producers, deletes exact source-owned records and optional
 * VIOS archive media, then resumes live analysis.
 */
export async function resetRtspStream(
  agentApiUrl: string,
  streamId: string,
  sensorName: string,
  clearRecordings: boolean,
  signal?: AbortSignal
): Promise<ResetRtspStreamResult> {
  if (signal?.aborted) {
    throw new Error("Reset live source was cancelled");
  }

  const response = await fetch(
    `${agentApiUrl}/rtsp-streams/${encodeURIComponent(streamId)}/reset`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: sensorName, clearRecordings }),
      signal,
    }
  );

  const result: unknown = await response.json().catch(() => null);
  if (!response.ok || !isRecord(result)) {
    throw new Error(
      (isRecord(result) && typeof result.message === "string" && result.message) ||
        `Failed to reset live source: ${response.statusText}`
    );
  }

  if (
    result.status !== "success" ||
    result.sensorId !== streamId ||
    result.name !== sensorName ||
    typeof result.deletedDocuments !== "number" ||
    result.analysisResumed !== true
  ) {
    throw new Error(
      (typeof result.message === "string" && result.message) ||
        `Failed to reset live source: ${sensorName}`
    );
  }

  return result as unknown as ResetRtspStreamResult;
}
