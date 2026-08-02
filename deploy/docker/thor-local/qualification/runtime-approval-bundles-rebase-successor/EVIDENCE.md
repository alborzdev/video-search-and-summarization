# Runtime approval-bundle rebase successor evidence boundary

## Raw-locked inputs

The checked contract locks fifteen exact provenance files:

- the predecessor `contract.json`, strict schema, and compiler;
- the finalized candidate approval mapping artifact, strict schema, compiler, and tests;
- the finalized activation receipt/schema and migration proof/schema;
- the candidate oracle adapter artifact, strict schema, and compiler;
- `deploy/docker/scripts/thor-local.sh`.

Every path is required to be a regular non-symlink inside the repository and every raw SHA-256 must match. Separate immutable byte locks protect all six files in the historical successor plus the canonical selector and staged descriptor. The compiler validates all JSON/schema pairs, proves the mapping consumes the exact activation and migration outputs, and checks both receipts forbid runtime promotion and contain zero runtime evidence/promotable candidates.

## What the artifact proves

The artifact proves a deterministic 16-bundle planning denominator. A full-object comparison against the historical successor rejects every difference except the new contract ID, candidate mapping/oracle provenance hashes, and source-lock provenance. Its first 14 bundle objects exactly equal the locked predecessor order and content. The final two objects are the exact firewall inspection and configuration scopes, in that order. The inspection bundle has no dependency. Configuration depends only on inspection. All placeholders and acknowledgement/recovery tokens are unique, approval inheritance is false, and all activation/evidence counts are zero.

The action disclosures are exact. Inspection enables only `host_inspection` and `subprocess`. Configuration enables only `host_inspection`, `subprocess`, `writes`, `lifecycle`, and `destructive`; network, Docker, downloads, and credentials remain false for both scopes.

## Transaction safety finding

The raw-locked script currently deletes a prior `cti_vss` table before applying a replacement. Its readiness-failure path deletes the table and its remove path deletes the table. It does not capture and restore exact prior table state. Therefore its existing apply/remove interface is not accepted as an authorization-safe transaction executor.

No mutation or recovery command is published by this package. Configuration stays blocked pending a future reviewed transaction executor and strict before/action/after/rollback receipt schema. The exact configuration token and recovery token shown in the contract are identifiers for future separate authorization workflows; their presence is not authorization.

## Prohibited inference

Compiler or test success is not approval, a receipt, host evidence, firewall inspection, firewall configuration, rollback evidence, capability admission, executable readiness, or runtime qualification. It does not prove that a firewall is present, absent, safe, effective, or removable. It does not change the candidate approval mapping or candidate oracle state. The Warehouse sample remains excluded.
