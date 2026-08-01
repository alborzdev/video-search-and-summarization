# Wave 11 evidence boundary

## Exact successor accounting

The executor recomputes and digest-locks every set from the live acceptance
inventory and predecessor inventories through Wave 10:

- 110 total planning requirements, 26 materialized and 84 live-open;
- 74 disjoint predecessor selections: 26 materialized and 48 still open;
- exact Wave 10 remainder: 36;
- exact Wave 11 static selection: 6;
- exact remainder after Wave 11: 30.

The set digests are:

- `prior_74`: `9ce2f8de129be68b105e6d6da9df0bcfe22f4b4035de0f7689e74f9dd1b3b773`;
- `wave10_remaining_36`: `db6822446d2591213affcfa05d7d1b4f9b94ebc73ecf44c8bdb8265fac7ef33b`;
- `wave11_selected_6`: `04c47a18aae3ce92b78596fcd1fbd814269f6cf36b6445670ae0af73d259f280`;
- `wave11_remaining_30`: `c75592f2a54340507e4348a80fa17eb21a77f6a0e85170ffdfb05a997ed68813`.

The package raw-locks the live acceptance inventory, official capability
ledger, capability-oracle ledger, `executor-cases`, `source-contract-cases`,
and every planning-requirement inventory from Wave 3 through Wave 10. Each
selected row is also bound to canonical SHA-256 identities for its planning
payload, capability, contract, and oracle, plus raw SHA-256 locks for every
source used by its assertions.

## What the six matches mean

One match preserves a negative format-qualification boundary, one matches a
narrow dashboard configuration subset, and four match source/protocol
surfaces:

- Kibana discovery, iframe embedding, and the Thor dashboard importer remain
  present in shipped sources;
- Alerts documentation still describes verification, realtime, and on-demand
  modes;
- Alerts documentation still describes Elasticsearch persistence and optional
  Kafka output;
- Behavior Analytics documentation still describes broker input, configurable
  transforms, and emitted behavior/event/incident records;
- LVS source still names queued and processing states and increments pending
  query metrics;
- the canonical five-format claim remains runtime-unqualified, while the agent
  documents an opt-in codec boundary and the current common uploader accepts
  only MP4/MKV.

These observations do not satisfy the runtime oracles. The result is always
`static_subset_match_candidate_only`; every result has an empty
`runtime_evidence` array and the package adds no live evidence.

## Exclusions and fail-closed behavior

All seven `calibration-warehouse` rows in the audited remainder are classified
as `excluded_warehouse_requirement`; none enters the selected set. No Warehouse
sample, custom media, container, or runtime path is read or used.

The executor fails closed on package identity drift, schema drift, baseline or
source byte drift, predecessor overlap, exact set-digest drift, canonical
binding drift, any promotion/evidence on the 84 live-open requirements,
selected-oracle state/evidence drift, missing source tokens, duplicate JSON
keys, unknown schema fields, unsafe paths, symlinks, or a Warehouse selection.

A successful result does not edit or advance live acceptance, capabilities,
oracles, the parity manifest, shared qualification documentation, or milestone
wrappers. Promotion requires separate reviewed runtime evidence.
