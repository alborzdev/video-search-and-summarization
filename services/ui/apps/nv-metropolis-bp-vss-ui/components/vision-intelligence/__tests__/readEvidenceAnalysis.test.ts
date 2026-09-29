import { TextDecoder, TextEncoder } from "node:util";
import { readEvidenceAnalysis } from "../readEvidenceAnalysis";

Object.assign(global, { TextDecoder, TextEncoder });
function response(chunks: string[]) {
  let index = 0;
  return { ok: true, headers: { get: () => "application/x-ndjson" }, body: { getReader: () => ({
    read: async () => index < chunks.length ? { value: new TextEncoder().encode(chunks[index++]), done: false } : { done: true },
    releaseLock: jest.fn(),
  }) } } as unknown as Response;
}
it("delivers fragmented inspections before resolving the completed result", async () => {
  const seen = jest.fn();
  const result = { status: "complete", summary: "Comparison" };
  const completed = await readEvidenceAnalysis(response([
    '{"type":"inspection","inspection":{"evidence_id":"E',
    '1","observation":"Carrying a box"}}\n',
    JSON.stringify({ type: "complete", result }),
  ]), seen);
  expect(seen).toHaveBeenCalledWith({ evidence_id: "E1", observation: "Carrying a box" });
  expect(completed).toEqual(result);
});
it("rejects a truncated stream instead of saving partial results as complete", async () => {
  const seen = jest.fn();
  await expect(readEvidenceAnalysis(response(['{"type":"inspection","inspection":{"evidence_id":"E1"}}\n']), seen)).rejects.toThrow("interrupted");
  expect(seen).toHaveBeenCalledTimes(1);
});
it("surfaces an in-stream failure", async () => {
  await expect(readEvidenceAnalysis(response(['{"type":"error","error":"Model busy"}\n']), jest.fn())).rejects.toThrow("Model busy");
});
