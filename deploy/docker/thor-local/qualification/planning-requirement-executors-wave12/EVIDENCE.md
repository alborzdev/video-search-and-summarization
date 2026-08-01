# Wave 12 evidence boundary

## Exact successor accounting

The executor recomputes and digest-locks every set from the live acceptance
inventory and predecessor inventories through Wave 11:

- 110 total planning requirements, 27 materialized and 83 live-open;
- 80 disjoint predecessor selections: 26 materialized and 54 still open;
- exact Wave 11 live-open remainder: 29;
- exact Wave 12 static selection: 6;
- exact remainder after Wave 12: 23.

The set digests are:

- `prior_80`: `127fd31fa4d7cfc7b84115e08500db2d93137eda3f8160468ae371d1128648e5`;
- `wave11_remaining_29`: `e86a4e00bd319b4fd822d0bbf4502e1ea4bfc45122efd73ddb9a488e8375ff0f`;
- `wave12_selected_6`: `0b77dc52e1347fffd454f55519702c72a4637905ee00f868cbdce5fc760d33fe`;
- `wave12_remaining_23`: `244182f25fed82f0f9e481563901fb48d87a1e61b24042a76ba7897920d562c9`.

The 23-row remainder contains 14 required/alternate-local runtime rows, three
external-optional rows, and six excluded `calibration-warehouse` rows. The
package does not reclassify or advance any of them.

`calibration-schema-static` is the 27th materialized requirement. Its
deterministic static binding is therefore outside this live-open remainder;
the Wave 12 candidate selection remains unchanged and non-promoting.

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

All six still-open `calibration-warehouse` rows in the audited remainder are
classified as `excluded_warehouse_requirement`; none enters the selected set.
No Warehouse sample, custom media, container, browser, service, or runtime path
is read or used. The three external-optional rows also remain unselected.

The executor fails closed on package identity drift, schema drift, baseline or
source byte drift, predecessor overlap, exact set-digest drift, canonical
binding drift, any promotion/evidence on the 83 live-open requirements,
selected-oracle state/evidence drift, missing source tokens, duplicate JSON
keys, unknown schema fields, unsafe paths, symlinks, or a Warehouse selection.

A successful result does not edit or advance live acceptance, capabilities,
oracles, the parity manifest, shared qualification documentation, or milestone
wrappers. Promotion requires separate reviewed runtime evidence.
