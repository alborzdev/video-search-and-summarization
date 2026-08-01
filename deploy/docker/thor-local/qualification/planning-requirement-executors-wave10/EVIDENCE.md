# Wave 10 evidence boundary

## Exact successor accounting

The executor recomputes and digest-locks every set from the live acceptance
inventory and predecessor inventories through Wave 9:

- 110 total planning requirements, 27 materialized and 83 live-open;
- 68 disjoint predecessor selections: 26 materialized and 42 still open;
- exact Wave 9 live-open remainder: 41;
- exact Wave 10 static selection: 6;
- exact remainder after Wave 10: 35.

The set digests are:

- `prior_68`: `843fde32fe7ee9f871451df0387326deff8e90a652b78d704c3d3581001f7d60`;
- `wave9_remaining_41`: `dc9c51cada03c13b4830d3062e89eb0dc5e2107d50d4958c84f5ed66f41e3b36`;
- `wave10_selected_6`: `a1041929edb70ab3d07ab5dd4e08cd64029e5b9365b91a26a3f252678e72cc98`;
- `wave10_remaining_35`: `e08aada14a3335ab53b1e15214b85cb72f0df42891fc6c8d62472e4a323fe42d`.

`calibration-schema-static` is the 27th materialized requirement. Its
deterministic static binding is therefore outside this live-open remainder;
the Wave 10 candidate selection remains unchanged and non-promoting.

The package raw-locks the live acceptance inventory, official capability
ledger, capability-oracle ledger, `executor-cases`, `source-contract-cases`,
and every planning-requirement inventory from Wave 3 through Wave 9. Each
selected row is also bound to canonical SHA-256 identities for its planning
payload, capability, contract, and oracle, plus raw SHA-256 locks for every
source used by its assertions.

## What the six matches mean

One match preserves a negative artifact-lock boundary, one matches a narrow
configuration subset, and four match source/protocol surfaces:

- report-agent source still contains distinct VA-MCP and uploaded-video modes;
- UI source still exposes selected theme, sidebar, upload, and report actions;
- Smart City source/configuration still names RT-DETR, GDINO, and NvDCF, while
  the canonical planning source continues to say exact artifacts are unlocked;
- one shipped VIOS configuration retains always-on recording;
- NvStreamer guidance still describes upload, RTSP lookup, conditional VIOS
  registration, downstream WebRTC, and removal;
- Video Analytics documentation and index modules retain the declared runtime,
  backing-service, optional-broker, and namespace surface.

These observations do not satisfy the runtime oracles. The result is always
`static_subset_match_candidate_only`; every result has an empty
`runtime_evidence` array and the package adds no live evidence.

## Exclusions and fail-closed behavior

All six still-open `calibration-warehouse` rows in the audited remainder are
classified as `excluded_warehouse_requirement`; none enters the selected set.
No Warehouse sample, custom media, container, or runtime path is read or used.

The executor fails closed on package identity drift, schema drift, baseline or
source byte drift, predecessor overlap, exact set-digest drift, canonical
binding drift, any promotion/evidence on the 83 live-open requirements,
selected-oracle state/evidence drift, missing source tokens, duplicate JSON
keys, unknown schema fields, unsafe paths, symlinks, or a Warehouse selection.

A successful result does not edit or advance live acceptance, capabilities,
oracles, the parity manifest, shared qualification documentation, or milestone
wrappers. Promotion requires separate reviewed runtime evidence.
