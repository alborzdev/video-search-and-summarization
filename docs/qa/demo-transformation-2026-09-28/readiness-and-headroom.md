# Capability readiness and runtime headroom

## Recorded-question readiness correction

The integrated-browser capability page showed “Ask about a clip — Choose a
source” while retained, indexed footage was confirmed. Its launch action already
opened recorded search, but its readiness calculation used the live
`current_visual_question` workload and skipped search coverage.

Changed `CapabilitiesWorkspace.tsx` to use `evidence_analysis` admission for
this task and the same fresh, same-source index/retention requirement as the
recorded search path. This reports evidence availability, not qualified model
accuracy. Service and admission failures still take precedence.

Extended the existing coverage regression to check the question task for
missing footage, available footage, and stale coverage. The capability suite
passed 4/4 with a 256 MiB Node heap cap. No full typecheck repeated for this
two-condition change at the narrow host margin.

Codex integrated browser verified the updated “Evidence available” label and
explanation, then “Find a clip to ask about” → Search video → one actual matching
result. No blank state/framework overlay; warning/error log empty. Screenshot:
`clip-capability-readiness.png`. Mobile layout was not rechecked for this text/status
change. No fresh vision inference was submitted.

## Headroom investigation (not a root-cause finding)

Core status passed all 31 roles and memory guard was active. Telemetry comparison
from 17:32:48 to 17:52:50 on September 28 showed available memory 51.056 →
48.790 GiB. UI server RSS was 1647 → 1650 MiB, insufficient to attribute this
drop to a UI server leak. Model-engine RSS increased by 117 and 106 MiB;
Prometheus increased by 98 MiB. Process replacement and allocations outside
RSS prevent a complete attribution. Docker/GPU/host figures must not be summed.

Minute medians were roughly 49.8–49.9 GiB from 17:40–17:48, then 48.888 at
17:50, 48.733 at 17:51, and 48.640 at 17:52. The later drop occurred during UI
work, not a fresh vision request. That timing is correlation, not proof of cause.
Closed the two completed agent-created verification tabs, keeping the current
audit tab; available memory subsequently sampled 48.843 and 48.91 GiB. This is
not a controlled experiment proving tab cleanup reclaimed a specific amount.

No memory budgets, guard threshold, service configuration, or model settings
changed. No model/service restart or cache reclaim performed. Latest check:
31 roles passed, 48.91 GiB available, same boot. Sustained workload qualification
and reliable headroom remain open; defer fresh visual workload at this margin.

Requested current Spark address, RTSP URLs, scene and reset/trigger instructions
through the asynchronous user-input tool. Recorded/UI work remains available
while those details are pending.
