# Wave 9 evidence boundary

## Exact denominator accounting

The executor recomputes and digest-locks all sets from the live acceptance
inventory and every predecessor inventory through Wave 8:

- 110 total planning requirements, 27 materialized and 83 live-open;
- 62 disjoint predecessor selections: 26 materialized and 36 still open;
- exact Wave 8 remainder: 47;
- exact Wave 9 static selection: 6;
- exact remainder after Wave 9: 41.

The canonical `calibration-schema-static` integration accounts for the new
materialized row. It is outside this live-open audit and does not alter the six
historical Wave 9 candidate selections.

It raw-locks the live acceptance inventory, official capability ledger,
capability-oracle ledger, `executor-cases`, `source-contract-cases`, and every
planning-requirement inventory from Wave 3 through Wave 8. Each selected row is
also bound to the canonical SHA-256 of its current planning payload, capability,
contract, and oracle.

## What the six matches mean

One match preserves a documented negative contract, two match configuration
subsets, and three match protocol/source surfaces. A match means only that the
reviewed static text and exact raw source files still agree with the locked
subset:

- report persistence remains documented as in-memory and lost across restart;
- shared-layout memory sensitivity and an explicit memory-utilization setting
  remain present, without claiming that the layout fits or runs on Thor;
- the VA-MCP seven-tool surface is registered, without claiming semantic tool
  behavior or successful MCP requests;
- the Video Analytics 56-operation manifest and generic upload route include
  calibration and road-network document types, without claiming successful
  upload, persistence, readback, or cleanup;
- the orchestrator nine-tool surface is present, while lifecycle-changing
  tools remain unexecuted and operator-gated;
- a brokerless Video Analytics configuration and optional-Kafka guidance are
  present, without claiming that any absent/unreachable-broker failure path was
  exercised.

Source, configuration, documentation, generated expected manifests, and mocks
are never transformed into runtime evidence. The result is always
`static_subset_match_candidate_only`; `runtime_evidence` remains empty.

## Exclusions and fail-closed behavior

All six live-open `calibration-warehouse` rows in the audited remainder are classified
as `excluded_warehouse_requirement` and none may enter the selected set. The
Warehouse sample bundle, custom Warehouse media, containers, and runtime paths
are not read or used.

The executor fails closed on any drift in package schemas, raw package files,
the eleven live/predecessor baselines, exact set digests, selected bindings,
open/evidence-empty state, source hashes, or semantic source tokens. It rejects
duplicate JSON keys, unknown schema fields, unsafe repository paths, symlinks,
overlapping prior selections, and any Warehouse selection.

A successful run does not edit or advance the live acceptance inventory,
official capabilities, capability oracles, manifest, shared qualification
README, or wrapper. Promotion requires a separate reviewed integration backed
by the evidence class actually required by each live oracle.
