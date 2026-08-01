# Candidate evidence boundary

The bounded executor produces two byte-identical temporary output trees and
validates all of the following before returning `observed_match_candidate_only`:

- exact source, manifest-entry, fixture, and dependency-declaration hashes;
- exactly two safe camera IDs and no path escape or symlink output;
- two 3x4 finite projection matrices represented by 12 flattened values;
- exact model class IDs, heights, and radii;
- exact MQTT broker and `/trck/<camera>` publication topics;
- deterministic, sorted, non-self peer subscriptions for both cameras;
- byte-identical camInfo, pub/sub, and complete tree hashes across both runs;
- removal of the exact owned temporary root with adjacent state unchanged.

The adjacent negative tests cover path-traversing and duplicate sensor IDs,
nonfinite matrix values, nonfinite/nonpositive model dimensions, negative or
duplicate class IDs, direct-call model-validation bypasses, symlink outputs and
symlinked output ancestors (including `symlink/../escape`), empty camera input,
duplicate or unsafe camera filenames, invalid brokers, invalid overlap
thresholds, and deterministic tie-breaking.

The result always carries:

```text
candidate_only: true
official_capability_effect: none_candidate_only
runtime_evidence: []
warehouse_sample_bundle_used: false
network_used/docker_used/subprocess_used/lifecycle_used: false
```

The result is integrated into exactly the two matching live oracle records as
`bounded_static_tool_observation_subset_only`. Both bindings retain
`can_advance_capability: false`, `can_mark_passed_current: false`, and empty
runtime evidence. They intentionally leave `contract_identity` and contract
assertions 05-08 uncovered because those fields describe the broader Warehouse
planning state rather than either generator's observed behavior. Both full
oracles therefore remain `planning_index_only` and `open_unexecuted`; this does
not qualify a Warehouse profile or establish official AGX Thor Warehouse
support.

The integration binds the raw SHA-256 of `execution-receipt.json`, validates it
against `result.schema.json`, and rehashes all four source locks before reading
the result. Observation status, run count, selected output hashes, semantic
objects, and dependency observations come from that receipt. Its dependency
digest is `f8b538e36776da71af95af5a667426dbd5cbb3e3fa482c2c5850ba9306888e80`.
All four observed distributions differ from the reviewed declarations, and the
binding marks that observation non-normative rather than claiming a dependency
match.
