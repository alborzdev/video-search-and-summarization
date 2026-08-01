# Detection mAP candidate evidence

## Exact binding

- Entry: `manifest-gap.spatial-ai-utils.03-detection-map`
- Proposed capability: `manifest-entry.spatial-ai-utils.03-detection-map`
- Oracle: `oracle.manifest-entry.spatial-ai-utils.03`
- Manifest pointer: `/features/29/advertised/3`
- Literal: `detection mAP`
- Acceptance effect: `none_candidate_only`

The executor resolves the live pointer and locks the canonical literal digest.
It intentionally avoids a whole-manifest raw digest so unrelated concurrent
manifest additions cannot silently redefine this exact entry. The source gap
plan is separately raw-locked and its one matching entry is canonical-locked.

## Deterministic evidence

The custom fixture is two JSON cases and is not derived from the excluded
Warehouse sample. Two independent runs produce identical receipts:

- `perfect-single-detection.json` -> Person AP and mAP `1.0`;
- `distance-threshold-miss.json` -> Person AP and mAP `0.0`;
- output tree SHA-256:
  `e3581ff503dd26b0acfd2b002a11725a2ac6b0458cddc076494d2f782546fc12`.

The checked-in `test_evaluate.py` supplies integration evidence for the real
loader + evaluator + save path. Exact digest and AST checks require both
end-to-end tests to retain their explicit Person AP `1.0` assertion. Exact
source locks also cover `evaluate.py`, `loaders.py`, `data_classes.py`, and the
declared `nuscenes-devkit==1.2.0` / `motmetrics==1.4.0` evaluation extra.

## Non-claims

This is static candidate evidence, not official acceptance. The receipt records
all of the following as false: production evaluator executed, local optional
evaluation dependencies verified, service runtime proven, Warehouse sample
used, network used, Docker used, subprocess used, lifecycle used, downloads
used, and credentials used. `runtime_evidence` remains empty.

Adversarial tests reject digest drift, manifest literal drift, duplicate or
promoted gap-plan entries, removal of the real AP assertion/call graph,
non-finite fixtures, expected-result tampering, output-lock tampering, claim
escalation, duplicate JSON keys, unsafe paths, symlinks, and cleanup failures.
