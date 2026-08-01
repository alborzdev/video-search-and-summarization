# Planning Requirement Executors — Wave 12

This isolated package audits Wave 11's exact 29-row live-open remainder and
records six additional, disjoint static subsets. All six selected requirements
are `required_local`; none is Warehouse or external-optional. The executor
performs only raw-file, canonical-ledger-binding, set-accounting, and
source-token checks.

| Planning requirement | Static subset checked | Evidence class |
| --- | --- | --- |
| `search-documents-and-bboxes` | Search sources retain the three index families, one-second attribute clip floor, multi-attribute mode, and default RRF configuration. | `static_protocol_subset_only` |
| `tiny-alert-stream` | Alert sources retain realtime stream rules, prompt configuration, idempotent repeated deletion, two-step UI confirmation, and opt-in OpenClaw relay wiring. | `static_protocol_subset_only` |
| `ui-alert-api` | UI sources retain the two alert views, declared fetch defaults, and uncached live-stream catalog query. | `static_configuration_subset_only` |
| `ui-search-api` | UI sources retain bbox/image endpoint configuration, similarity/top-k bounds, search defaults, and critic result states. | `static_configuration_subset_only` |
| `ui-tiny-media` | UI sources retain multi-file MP4/MKV selection, RTSP controls, progress presentation, and destructive confirmation. | `static_configuration_subset_only` |
| `systems-alert-worker-scaling` | Alert sources retain a bounded worker queue, worker pool, blocking backpressure, and Smart City single-chunk configuration. | `static_protocol_subset_only` |

No result is a runtime pass. Source routes and index strings do not prove
search results; alert types and handlers do not prove live chunk processing or
relay delivery; component configuration does not prove browser/API behavior;
and worker queue code does not prove Thor saturation, horizontal groups, or
Kafka partition coverage. All 83 live-open requirements remain unpromoted,
executor-not-ready, and runtime-evidence-empty. Every selected oracle remains
`open_unexecuted` and evidence-empty.

Run the read-only executor from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/planning-requirement-executors-wave12/executor.py --json
```

Run its tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/planning-requirement-executors-wave12/tests
```

The executor performs no network, Docker, subprocess, lifecycle, download,
credential, or file-write action. It does not use Warehouse, edit shared
documentation or wrappers, or promote acceptance/capability/oracle ledgers.
