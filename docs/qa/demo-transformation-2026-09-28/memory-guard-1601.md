# September 28, 16:01 EDT reserve-guard interruption

During the UI audit, camera setup returned proxy HTML with HTTP 503. Current
runtime status confirmed Cosmos, Nemotron, embeddings, Agent and LVS had exited.
Guard receipt records 47.659 GiB available against the unchanged 48 GiB floor at
16:01:58 EDT. Boot ID remained ac75a3b5-980a-41c5-8301-200423326f72.

The preceding samples were around 49.5–49.8 GiB available. The last process
snapshot was two seconds before the trip and does not establish which workload
caused the transient drop. UI tests/typechecks and hot reload had occurred during
this audit; causation is not proven. This is another interruption during normal
iteration, and invalidates any claim of robust demo readiness from idle health.

Recovery uses the documented one-time idle cache reclaim with models stopped,
then `python3 artifacts/thor-memory-2026-09-09/manage.py start --profile core`.
The guard remains active. No floor, model budgets, detector state, live ingestion
or persistent application records were changed. Staged startup began with about
101 GiB available. Do not run more test/typecheck jobs during model startup.

Source setup also had a separate error-presentation defect: non-JSON errors were
rendered as raw proxy HTML. A regression test first reproduced that exact output;
the profile helper now uses its actionable fallback for unstructured responses,
while preserving structured service explanations. Four focused package tests and
app TypeScript passed before later model startup stages. The real unavailable
state was verified in Codex browser. Recording display alias is now consistent in
source inventory and customer-facing pages; backend identity is unchanged.

[Telemetry](memory-guard-1601.json) · [Corrected form error](camera-profile-unavailable.png).

Recovery completed at 16:12 EDT: startup manager exited 0; 31 roles passed its
container/API checks, 52.76 GiB available. Codex browser reopening Add RTSP camera
loaded the actual profile catalog: semantic search available, detector profiles
correctly disabled because detector workers remain stopped. No camera submitted.
[Recovered form](camera-profiles-recovered.png). This restores availability;
it does not resolve the transient reserve-pressure cause or qualify sustained use.
