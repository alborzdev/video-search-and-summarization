# Planning Requirement Executors — Wave 9

This isolated package audits the exact 48 live-open planning requirements left
after Wave 8 and records six additional, disjoint static subsets. It performs
only raw-file, canonical-ledger-binding, set-accounting, and source-token checks.

The selected subsets are deliberately narrower than their live requirements:

| Planning requirement | Static subset checked | Evidence class |
| --- | --- | --- |
| `systems-report-persistence` | The documented in-memory, restart-loss limitation remains visible. | `static_negative_contract_preserved` |
| `systems-shared-gpu-memory` | The documented 48 GB/shared-layout sensitivity and shipped memory-fraction knob remain present. | `static_configuration_subset_only` |
| `va-mcp-semantic-fixture` | The seven-tool manifest/config/source registration remains present. | `static_protocol_subset_only` |
| `smartcity-config-uploads` | The 56-operation manifest and calibration/road-network upload route remain present. | `static_protocol_subset_only` |
| `orchestrator-lifecycle-oracle` | The nine-tool orchestrator surface and lifecycle authorization boundary remain present. | `static_protocol_subset_only` |
| `systems-va-optional-kafka` | The brokerless configuration and optional-Kafka documentation remain present. | `static_configuration_subset_only` |

No result is a runtime pass. The API surfaces do not prove request semantics;
the shared-GPU configuration does not prove Thor capacity; the brokerless
Kafka configuration does not reproduce absent-broker behavior; and the
orchestrator source does not authorize a lifecycle action. Every selected
requirement and oracle must remain open and evidence-empty for the executor to
pass.

Run the read-only executor from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/planning-requirement-executors-wave9/executor.py --json
```

Run its tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/planning-requirement-executors-wave9/tests
```

The executor performs no network, Docker, subprocess, lifecycle, download,
credential, or file-write action. It does not use Warehouse, edit shared
documentation or wrappers, or promote acceptance/capability/oracle ledgers.
