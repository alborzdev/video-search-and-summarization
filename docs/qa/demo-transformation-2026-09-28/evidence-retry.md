# Evidence question retry — September 28

## Reproduction

Explore → People moving → Use as evidence → ask “What is the worker holding?”
with `/api/vision/evidence-analysis` temporarily intercepted to return HTTP 503.
The first payload included that question; the retry omitted it and would have
requested general analysis. The selected real recording interval was 0–10 s.

## Correction

InvestigateWorkspace retains the last submitted question. EvidenceAnalysisPanel
has a dedicated retry callback instead of calling the general-analysis callback.
On a general-analysis request, the remembered question is explicitly undefined.
Changing selected evidence clears the error, preventing retry of a stale selection.

## Verification

- 19 tests passed across InvestigateWorkspace and EvidenceAnalysisPanel.
- New test selects two clips and proves initial and retry requests are identical;
  a later explicit general analysis does not carry the prior question.
- App TypeScript and git diff whitespace checks passed.
- Running-browser injected-failure check confirmed both payloads contained the
  same question and identical source/time interval. Interception removed in finally.
- Browser hot reload reset local workspace state during validation; the real search
  and selection were repeated before checking the final behavior.

No model inference, report mutation, live ingestion or runtime restart was needed.
The two-clip test uses fixtures; it does not establish successful real multi-clip
analysis or customer-story quality. Those acceptance items remain open.
