# Preview-only RTSP onboarding — September 28

## Result

Codex integrated browser registered **Conveyor — Recorded Simulation (RTSP Replay)** through System → Sources → Add RTSP camera with AI analysis unchecked. Source ID: `6776f3a6-446f-4da8-832e-cfcf4507de8c`.

The camera modal played actual 1920-pixel video: readyState 4, paused false, error null; playback advanced from 14.65 to 31.65 seconds. [Browser evidence](conveyor-rtsp-preview.jpg). This is a recorded simulation replayed over RTSP, not a current Isaac Sim feed.

Agent status before and after restart: state paused, analysisActive false, embedding/detection/indexing false. The source is persisted in paused_source_ids. Final core status: 31 roles, no failures, 49.83 GiB available, memory guard active. Both detectors remain off.

## Implementation

- Camera dialog defaults to preview only. Enabling AI reveals analysis profiles; preview submission skips profile fetching and monitoring setup.
- API adds startAnalysis (legacy default true) and analysisPaused response. Preview registration persists pause before proxy activation and returns before model registration.
- Catalog reconciliation shares the registration lock, preventing discovery between creation and pause persistence. Failure cleanup removes durable state.
- Preview uses normal registered-source capacity. It does not promise that VIOS storage/recording is disabled.

## Validation and limits

- Three dialog tests and app typecheck passed.
- Actual-source AST contract probe passed: request defaults, pause before proxy, no model calls, failure cleanup. Saved beside this receipt; this is not a full imported-module pytest run.
- Agent Ruff lint passes. Changed rtsp_ingest.py format passes. Whole-source format flags five previously modified files outside this change.
- Configured mypy Python 3.11 conflicts with installed NumPy syntax. Python 3.13 runs still report repository type errors; no whole-agent typecheck pass is claimed.
- Final explicit error=None constructor argument is equivalent to its runtime default and was contract-tested after the restart check.
- Source inventory initially needed Refresh sources before showing the camera: onboarding refresh timing remains a UI follow-up.
- Sustained live analysis, automatic alerts and concurrent workloads remain unqualified. No AI ingestion was enabled in this pass. Disk remains about 13 GiB free; storage lifecycle needs attention before extended replay operation.
