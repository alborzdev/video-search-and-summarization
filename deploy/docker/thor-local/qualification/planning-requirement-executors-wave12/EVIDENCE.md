# Wave 12 evidence boundary

## Exact successor accounting

The executor recomputes and digest-locks every set from the live acceptance
inventory and predecessor inventories through Wave 11:

- 110 total planning requirements, 26 materialized and 84 live-open;
- 80 disjoint predecessor selections: 26 materialized and 54 still open;
- exact Wave 11 remainder: 30;
- exact Wave 12 static selection: 6;
- exact remainder after Wave 12: 24.

The set digests are:

- `prior_80`: `127fd31fa4d7cfc7b84115e08500db2d93137eda3f8160468ae371d1128648e5`;
- `wave11_remaining_30`: `c75592f2a54340507e4348a80fa17eb21a77f6a0e85170ffdfb05a997ed68813`;
- `wave12_selected_6`: `0b77dc52e1347fffd454f55519702c72a4637905ee00f868cbdce5fc760d33fe`;
- `wave12_remaining_24`: `ff8a6b3bfb1c308a3533ca25f05b7b84baa29d08acd699fca3920755681e151e`.

The 24-row remainder contains 14 required/alternate-local runtime rows, three
external-optional rows, and seven excluded `calibration-warehouse` rows. The
package does not reclassify or advance any of them.

The package raw-locks the live acceptance inventory, official capability
ledger, capability-oracle ledger, `executor-cases`, `source-contract-cases`,
and every planning-requirement inventory from Wave 3 through Wave 11. Each
selected row is also bound to canonical SHA-256 identities for its planning
payload, capability, contract, and oracle, plus raw SHA-256 locks for every
source used by its assertions.

## What the six matches mean

Three matches cover source/protocol subsets and three cover static UI
configuration subsets:

- Search code retains the declared index-family, attribute, and RRF surfaces.
- Realtime alert sources retain prompt-bearing rules, repeated-delete
  idempotence, two-step confirmation, and disabled-by-default OpenClaw wiring.
- Alerts UI sources retain the two views, numeric defaults, and live-stream
  catalog endpoint.
- Search UI sources retain configured image dependencies, numeric bounds,
  defaults, and critic result vocabulary.
- Video Management sources retain MP4/MKV multi-selection, RTSP management,
  progress display, and destructive confirmation.
- Alert worker code retains a bounded queue and blocking worker acquisition;
  the Smart City example remains configured for one worker and one-item chunks.

These observations do not satisfy any runtime oracle. The result is always
`static_subset_match_candidate_only`; every result has an empty
`runtime_evidence` array and the package adds no live evidence.

## Exclusions and fail-closed behavior

All seven `calibration-warehouse` rows in the audited remainder are classified
as `excluded_warehouse_requirement`; none enters the selected set. No Warehouse
sample, custom media, container, browser, service, or runtime path is read or
used. The three external-optional rows also remain unselected.

The executor fails closed on package identity drift, schema drift, baseline or
source byte drift, predecessor overlap, exact set-digest drift, canonical
binding drift, any promotion/evidence on the 84 live-open requirements,
selected-oracle state/evidence drift, missing source tokens, duplicate JSON
keys, unknown schema fields, unsafe paths, symlinks, or a Warehouse selection.

A successful result does not edit or advance live acceptance, capabilities,
oracles, the parity manifest, shared qualification documentation, or milestone
wrappers. Promotion requires separate reviewed runtime evidence.
