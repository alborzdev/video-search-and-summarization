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

This evidence can support a reviewed future integration step. By itself it does
not advance either live oracle from `open_unexecuted`, qualify a Warehouse
profile, or establish official AGX Thor Warehouse support.
