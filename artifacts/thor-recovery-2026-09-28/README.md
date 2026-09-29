# Thor restoration and renewed app qualification — September 28

Core recovery and initial browser checks complete. Full simultaneous workloads and the remaining app audit are not yet qualified. Keep the 48 GiB guard.

Initial observation: 67 GiB used, 55 GiB available with models, agent, LVS and both detectors stopped. Last guard trip September 12 at 47.936 GiB. Kafka health probes failed with containerd-shim file-descriptor exhaustion. VIOS MCP had grown to 5.05 GiB.

Actions:
- Documented one-time idle reclaim with models stopped recovered about 40 GiB (55 → 95 GiB available). No data deletion; no periodic cache cleaner enabled.
- Restarted VIOS MCP: about 5.05 GiB → 40 MiB.
- Thor LAN address changed from 10.88.8.175 to 10.88.9.12. Updated generated local environment and candidate public-address state, plus candidate Kafka addresses. Recreated ingress/UI, Kafka, alert bridge, VIOS streamprocessing and analytics MCP selectively. Kafka became healthy; site returned HTTP200 at http://10.88.9.12:7777/.
- UI remains source-mounted Turbopack. Startup helper/status now report the configured address instead of hard-coding the old one.
- Staged model startup underway using the measured candidate and unchanged 48 GiB reserve. No claims of full-stack readiness until functional browser tests under load.

## Confirmed helper defect and fix

The installed MCP SDK's stateful request handler creates a retained transport when `/mcp` receives a request without a session header. The Docker probe made exactly that request every ten seconds, including while no operator used the helper. That supplies a concrete ongoing session-growth mechanism; it does not prove that every byte of the observed 5.05 GiB came from this mechanism.

Added `/health`, switched the Compose probe to it, source-mounted the helper for development, and imposed a 1 GiB no-swap memory ceiling. Existing restart policy is retained. The new probe checks HTTP liveness; it does not claim camera/backend readiness. `services/vios/mcp/tests/test_transport_health.py` made 100 health requests in the actual container SDK and found zero retained sessions. The running endpoint returns 200 and Docker reports healthy. A memory cap contains further growth; its suitability for unusually large requests remains to be measured.

## Current stage

Nemotron, Embed, Cosmos, LVS and Agent are ready. Core app idle headroom about 53 GiB. Both detectors remain stopped and live source desired states remain paused. Fresh ten-second upload succeeded and played to completion with no media error; available RAM during upload was about 51 GiB. Guard remains 48 GiB. This is not enough margin to qualify all detectors plus continuous collection alongside the full reasoning stack.

UI tests: 83 passed, 20 suites; app TypeScript check passed. Python helper compilation and `git diff --check` passed. Original source definitions preserved. Fresh fixture: `qa-recovery-20260928`, stream `edfe78cd-2a6d-47c2-8317-57e1ade9aafc`.

Search test found another operational failure: fresh embedding generation and Kafka publication succeeded but Logstash consumers retained old broker metadata after the address change. Restarting Logstash to reconnect and drain the index backlog; search recheck pending. Old indexed traffic matches correctly display the recording-expired state when their exact evidence window is unavailable.

Disk has only about 14 GB free (99% used). No recordings, model caches, images or volumes were deleted. Do not start extended collection without reviewing storage capacity.

## Final recovery checks

- Behavior-analytics consumers also retained the old broker coordinator address. Restarted both analytics consumers; reprocessed only the owned QA recording. Elasticsearch then contained its two fresh embedding documents, and browser source-scoped search returned one usable ten-second clip.
- A further development defect caused repeated page reloads and lost query/analysis state: `allowedDevOrigins` still contained only the old IP. It now derives the hostname from `NEXT_PUBLIC_VST_API_URL`. After the fix, the evidence-selection and analysis state persisted through a real Cosmos inspection and Nemotron briefing. Browser screenshot/AX state confirmed a cited warehouse-worker summary; semantic accuracy of every generated detail was not independently certified.
- Candidate manager defaults to `--profile core` (31 roles, excluding both detectors); `--profile full` is explicit and still unqualified for sustained workloads. `stop` continues to cover all candidate services regardless of profile. Core status finished with zero service/API failures and about 51 GiB available. No source ingestion was resumed.
- Ten-minute memory sampling recorded a 50.950 GiB minimum during recovery/upload work. Later visual-analysis spot checks stayed about 50–53 GiB. Do not interpret the earlier 53 GiB idle value as guaranteed workload headroom.
- The 48 GiB guard remained active. Trip timestamp stayed September 12; boot ID remained `ac75a3b5-980a-41c5-8301-200423326f72`. No reboot or guard trip during this recovery.

Next qualification work: improve interactive headroom before adding detector workloads; audit the remaining workflows on this restored environment; repair local live-source addressing without removing preserved history; separately qualify long history generation, sustained collection, and storage retention. A 31-service healthy status is deliberately not a claim that all capabilities work.
