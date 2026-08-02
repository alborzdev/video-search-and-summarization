// SPDX-License-Identifier: MIT
/**
 * Delete uploaded video via Agent API.
 *
 * Backend: DELETE /api/v1/videos/{video_id}
 * Handles VST (sensor + storage) and in "search" mode also ES + RTVI-CV.
 */

export interface DeleteVideoResult {
  status: 'success';
  message: string;
  video_id: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Delete an uploaded video by sensor/video ID (UUID) via Agent API.
 * DELETE /api/v1/videos/{video_id}
 *
 * @param agentApiUrl - Base URL of the agent API (e.g., http://<IP>:8000/api/v1)
 * @param videoId - The sensor/video UUID (e.g., from the upload response)
 * @param signal - Optional AbortSignal for cancellation
 */
export async function deleteVideo(
  agentApiUrl: string,
  videoId: string,
  signal?: AbortSignal
): Promise<DeleteVideoResult> {
  if (signal?.aborted) {
    throw new Error('Delete video was cancelled');
  }

  const response = await fetch(`${agentApiUrl}/videos/${encodeURIComponent(videoId)}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
    signal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(text || `Failed to delete video: ${response.statusText}`);
  }

  const result: unknown = await response.json();

  if (
    !isRecord(result) ||
    result.status !== 'success' ||
    result.video_id !== videoId
  ) {
    const message =
      isRecord(result) && typeof result.message === 'string'
        ? result.message
        : `Failed to delete video: ${videoId}`;
    throw new Error(message);
  }

  return result as unknown as DeleteVideoResult;
}
