# Evidence boundary

Status: **exact ledger transition verified; non-advancing**.

The predecessor identity is anchored to commit
`f638eb3421ec5620fe22609590c5e9d5872d33d0`, root tree
`396686f4bbd0e0f10d344ac06dd629fdad425181`, all four core file hashes,
and plan payload `a50231e6…`. The current worktree is anchored to four exact
file hashes and plan payload `7a50b418…`. The plan retains the exact global
denominator split: 487 advertised entries lack an entry-specific mapping, of
which 413 are family-only entries outside the scoped 74-entry plan.

Set and record comparison establishes:

- 12 and only 12 gap IDs disappeared;
- their corresponding 12 and only 12 capability/oracle IDs appeared;
- 277 common capability records and 277 common oracle records are unchanged;
- all 74 surviving gap records are unchanged;
- 11 new local oracles are `open_unexecuted`, evidence-empty, and bound to
  `not_qualified` capabilities;
- AWS/GCS alone is `external_boundary_unexecuted` and `not_applicable`;
- the two family lanes were demoted from historical `passed_current` to
  `not_qualified`, with no family evidence copied into an entry oracle;
- the Warehouse sample is excluded throughout this tranche.

The frozen direct-dependency closure contains 20 exact package trees and 30
directly core-dependent files. Tree identity freezes every file in each
package; file SHA-256 plus literal predecessor-core-marker checks establish why
each listed artifact is in the closure. Historical executors are not rerun and
their old semantic results are not presented as current runtime evidence.

The output is deterministic and schema-locked. It cannot mark a capability
passed, contains no runtime evidence, and reports every historical package as
`identity_verified_not_reexecuted`.
