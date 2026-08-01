# Local runtime execution-bound audit

This package statically audits the exact 20 non-Warehouse planning requirements that still need authorized local runtime evidence. It does not execute them. It preserves the raw digest of the prior generic `max_requests: 2` baseline, derives each oracle's exact atomic envelope, and verifies the canonical integration in `verified-integrations.json`.

The verified bounds change no state, evidence, executor, collector, service, or host resource. All official oracles remain `open_unexecuted`. The compiler performs only bounded reads of files inside this repository; it has no Docker, network, download, subprocess, lifecycle, or live-runtime capability.

## Derivation rule

Each case locks the current canonical source by raw SHA-256, index, ID, capability ID, current oracle SHA-256, planning-requirement binding, open state, empty evidence, and unimplemented executor/collector state. Historical per-oracle and whole-file digests preserve the prior two-request baseline without treating it as current. Every atomic workflow step cites one or more resolvable JSON pointers in the current oracle.

The execution envelope is:

1. capture the required pre-state;
2. perform each distinct positive workflow transition;
3. exercise the required adjacent negative;
4. restore only oracle-owned state; and
5. verify cleanup postconditions.

Minimum request budget is the sum of the declared per-step request costs. Maximum action budget is the expanded workflow step count. Local render, lint, and media re-encode steps cost an action but no service request. The integrated workload uses one unit, zero hidden request overhead, and the derived request count; `max_actions` is represented separately.

## Exact result

| Planning requirement | Capability | Requests | Actions |
|---|---|---:|---:|
| `tiny-agent-media` | `runtime.workflow.base-chat-report` | 8 | 8 |
| `hitl-state-transcript` | `runtime.agent.base-hitl` | 11 | 11 |
| `lvs-multi-file` | `runtime.agent.lvs-profile` | 14 | 14 |
| `search-documents-and-bboxes` | `runtime.agent.search-profile` | 14 | 14 |
| `candidate-alerts` | `runtime.workflow.alert-verification` | 8 | 8 |
| `tiny-alert-stream` | `runtime.workflow.real-time-alerts` | 12 | 12 |
| `ui-alert-api` | `runtime.ui.alerts-tab` | 9 | 9 |
| `ui-search-api` | `runtime.ui.search-tab` | 13 | 13 |
| `ui-tiny-media` | `runtime.ui.video-management-tab` | 11 | 11 |
| `nemoclaw-lifecycle-mocks` | `deployment.nemoclaw.same-host-operating-path` | 7 | 9 |
| `nemoclaw-policy-network` | `security.nemoclaw.policy-provider-network-boundary` | 9 | 9 |
| `smartcity-ui-incidents` | `runtime.smart-city.chat-alert-dashboard` | 8 | 8 |
| `smartcity-synthetic-tracks` | `runtime.smart-city.traffic-analytics` | 14 | 14 |
| `smartcity-agent-pages` | `runtime.smart-city.agent-workflow` | 12 | 12 |
| `smartcity-manual-calibration` | `calibration.legacy.core` | 8 | 8 |
| `smartcity-gis-calibration` | `calibration.legacy.gis` | 8 | 8 |
| `systems-alert-worker-scaling` | `performance.alerts.worker-scaling` | 8 | 8 |
| `systems-vios-scaling` | `deployment.vios.horizontal-scaling` | 7 | 9 |
| `systems-elk-recovery` | `behavior.elk.disk-watermark-recovery` | 13 | 13 |
| `systems-vios-playback-remediation` | `behavior.vios.upload-playback-remediation` | 8 | 9 |

Totals are 202 minimum requests and 207 atomic actions. Every request minimum is greater than two.

## Static use

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/runtime-execution-bounds-audit/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/runtime-execution-bounds-audit/tests
```

Running the compiler without `--check` prints the same inert verification record to stdout. It never writes or applies anything.
