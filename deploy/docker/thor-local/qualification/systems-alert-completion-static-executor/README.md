# Systems alert completion static executor

This isolated package evaluates the bounded static subset of exactly three open Wave 3 `systems` planning requirements:

- `systems-alert-workflow-modes` → `runtime.alerts.workflow-modes`
- `systems-alert-nvschema` → `protocol.alerts.nvschema-ingestion`
- `systems-alert-persistence` → `runtime.alerts.persistence-output`

It imports the checked-in product implementation and uses deterministic fakes only at the external Redis, Elasticsearch, Kafka, and VLM-client boundaries. It checks DirectMedia verification/context/classification output, Incident and Behavior JSON↔Protobuf semantics (including the documented Incident `analytics` alias and released `analyticsModule` wire name), Elasticsearch and Kafka delivery receipts, the terminal-store cancellation publish gate, and eight adjacent negatives.

The executor performs no network access, model calls, downloads, subprocesses, Docker operations, service lifecycle operations, or Warehouse sample use. Its only writes are DirectMedia download-directory creation beneath executor-owned private temporary directories, which are checked for cleanup.

Run:

```bash
python3 deploy/docker/thor-local/qualification/systems-alert-completion-static-executor/executor.py --json
python3 -m pytest -q deploy/docker/thor-local/qualification/systems-alert-completion-static-executor/tests
```

A pass is deliberately non-advancing: the only success result is `candidate_static_pass_non_advancing`; `runtime_evidence` remains empty and the canonical planning rows, capability ledger, and oracles remain open/unmodified. This is deterministic file/static evidence, not runtime service evidence.
