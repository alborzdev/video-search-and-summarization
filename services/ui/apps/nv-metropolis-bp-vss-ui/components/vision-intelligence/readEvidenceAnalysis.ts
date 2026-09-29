// SPDX-License-Identifier: MIT
import type { EvidenceAnalysisResponse, EvidenceVisualInspection } from "./evidenceAnalysis";

/** Consume completed inspections without treating them as a finished answer. */
export async function readEvidenceAnalysis(
  response: Response,
  onInspection: (inspection: EvidenceVisualInspection) => void,
): Promise<EvidenceAnalysisResponse> {
  if (!response.headers?.get("content-type")?.includes("application/x-ndjson")) {
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || `Evidence analysis returned ${response.status}.`);
    return payload;
  }
  if (!response.ok || !response.body) throw new Error("Evidence analysis stream is unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result: EvidenceAnalysisResponse | undefined;
  function consume(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "error") throw new Error(event.error || "Evidence analysis failed.");
    if (event.type === "inspection") onInspection(event.inspection);
    if (event.type === "complete") result = event.result;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split("\n");
      pending = lines.pop() || "";
      for (const line of lines) consume(line);
      if (done) break;
    }
    consume(pending);
  } finally { reader.releaseLock(); }
  if (!result) throw new Error("Inspection was interrupted before the final answer. Try again.");
  return result;
}
