# Planning Requirement Executors — Wave 10

This isolated package audits Wave 9's exact 41-row live-open remainder and
records six additional, disjoint static subsets. It performs only raw-file,
canonical-ledger-binding, set-accounting, and source-token checks.

| Planning requirement | Static subset checked | Evidence class |
| --- | --- | --- |
| `agent-mode-mocks` | Report-agent source retains the VA-MCP and uploaded-video mode-selection branches. | `static_protocol_subset_only` |
| `ui-chat-state` | Theme, sidebar, MP4/MKV upload, and Generate Report source surfaces remain visible. | `static_protocol_subset_only` |
| `smartcity-model-locks` | RT-DETR, GDINO, and NvDCF choices are visible while the required exact artifact locks remain absent. | `static_negative_contract_preserved` |
| `smartcity-vios-boundary` | A shipped VIOS configuration retains `always_recording: true`; the 100th/101st-stream boundary is not exercised. | `static_configuration_subset_only` |
| `systems-nvstreamer-file` | The documented upload-to-RTSP, conditional VIOS handoff, WebRTC, and removal surface remains visible. | `static_protocol_subset_only` |
| `systems-va-query-library` | Node/Express, Elasticsearch, optional Kafka, and the four exported library namespaces remain visible. | `static_protocol_subset_only` |

No result is a runtime pass. The source branches do not prove routing or UI
semantics, detector names are not artifact digest locks, one VIOS setting does
not prove the 100-stream boundary, documentation does not prove file lifecycle,
and exports do not prove query semantics. All 83 live-open requirements must
remain unpromoted, executor-not-ready, and runtime-evidence-empty. Every
selected oracle must remain `open_unexecuted` and evidence-empty.

Run the read-only executor from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/planning-requirement-executors-wave10/executor.py --json
```

Run its tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/planning-requirement-executors-wave10/tests
```

The executor performs no network, Docker, subprocess, lifecycle, download,
credential, or file-write action. It does not use Warehouse, edit shared
documentation or wrappers, or promote acceptance/capability/oracle ledgers.
