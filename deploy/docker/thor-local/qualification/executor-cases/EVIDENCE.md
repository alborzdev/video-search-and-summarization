# File-only executor evidence — 2026-07-31

## Scope

The isolated candidate tranche binds 10 unique entries from
`qualification/acceptance_inventory.json#/wave3_contracts/planning_requirements`.
Each binding verifies the exact planning payload canonical SHA-256, owner
capability, materialized live static contract, empty runtime evidence, and
matching live capability planning ID before evaluating implementation files.

Materialized surfaces cover Alert Prometheus declarations, RTVI input/container
codec declarations, Kafka/Redis profile choice, NvSchema format selection and
Protobuf field tags, ELK configuration, Kafka/Redis Logstash ingestion, the VIOS
effective upload limit, LVS custom-model/prompt controls, and the Thor alert
warmup override.

## Result

`executor.py run-all` returns 8 matches and 2 mismatches across all 10
materialized, executor-ready cases. The corresponding live planning-requirement
materialized/executor-ready count is exactly 10. Every result carries
before/after hashes for every file read and an empty `runtime_evidence` array.

The NvSchema mismatch is exact and bounded: all selected Frame, VisionLLM, and
SpaceUtilization field/tag maps match; only the official Incident tag 7 name
differs (`analytics` documented, `analyticsModule` checked in). Both RTVI schema
copies independently match `analyticsModule = 7`, as do generated bindings and
JSON-facing code. The unchanged tag means this name drift alone is not binary
wire incompatibility. The alert warmup mismatch is also exact: official docs
and service source both default to enabled, while only the local Thor overlay
explicitly forces false.

The semantic review classifies Incident as an official-documentation-to-
repository name discrepancy and warmup as an explicit, unqualified Thor
override rather than a source conflict or missing implementation. Two exact
live discrepancy records preserve those boundaries. A digest-pinned
reconciler proves they are the only changes from the 45-record Wave 3 ledger to
the 47-record successor without modifying the historical Wave 3 receipt.
The final live-integration receipt then deterministically replays both
predecessors, binds the executor inventory/schema/executable/result schema and
all 10 expected outcomes, and locks the acceptance, oracle, ledger, manifest,
and oracle-schema outputs.

## Non-claims

No service was contacted or started. No container state was read or changed. No
model or sample data was downloaded. No environment variable was changed. No
Warehouse sample is included. These results do not establish runtime health,
performance, protocol interoperability, media decode success, or end-to-end
behavior, and they do not mark any capability `passed_current`.
