# File-only executor evidence — 2026-07-31

## Scope

The isolated candidate tranche binds 10 unique entries from
`qualification/acceptance_inventory.json#/wave3_contracts/planning_requirements`.
Each binding verifies the exact planning payload canonical SHA-256, owner
capability, unmaterialized source state, empty runtime evidence, and matching
live capability planning ID before evaluating implementation files.

Materialized surfaces cover Alert Prometheus declarations, RTVI input/container
codec declarations, Kafka/Redis profile choice, NvSchema format selection and
Protobuf field tags, ELK configuration, Kafka/Redis Logstash ingestion, the VIOS
effective upload limit, LVS custom-model/prompt controls, and the Thor alert
warmup override.

## Result

`executor.py run-all` returns 8 matches and 2 mismatches across all 10
candidate-materialized, candidate executor-ready cases. The corresponding live
requirement materialized/executor-ready count remains zero. Every result carries
before/after hashes for every file read and an empty `runtime_evidence` array.

The NvSchema mismatch is exact and bounded: all selected Frame, VisionLLM, and
SpaceUtilization field/tag maps match; only Incident tag 7 differs in field name
(`analytics` expected, `analyticsModule` checked in). The alert warmup mismatch
is also exact: the official default is enabled, while the local Thor overlay is
intentionally disabled.

The warmup result is a local conformance finding already covered by the live
capability's partial/not-qualified gap, not a new cross-source discrepancy. The
Incident field-name result is a candidate discrepancy requiring semantic review
before any live discrepancy-ledger change.

## Non-claims

No service was contacted or started. No container state was read or changed. No
model or sample data was downloaded. No environment variable was changed. No
Warehouse sample is included. These results do not establish runtime health,
performance, protocol interoperability, media decode success, or end-to-end
behavior, and they do not mark any capability `passed_current`.
