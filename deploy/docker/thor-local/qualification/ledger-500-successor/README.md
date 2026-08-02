# Ledger 500 successor

This package is an isolated, candidate-only projection of the current
Thor-local manifest and official capability ledger. It leaves the live parity
files unchanged.

The compiler emits three deterministic artifacts:

- `projected-manifest.json`, with the 211 candidate IDs appended to the correct
  feature `official_capability_ids` arrays in manifest-pointer order;
- `projected-official-capabilities.json`, with the 289 current capability
  records preserved in order and the exact 211 proposed records appended; and
- `projection.json`, a strict proof binding the inputs, append order,
preservation hashes, exact-title mapping, source claim-hash transition,
candidate oracle adapter, and 500-oracle successor.

The proof schema pins the exact append rows, source transitions and source-ID
partitions, blocker rows, and reviewed external distinctions. Duplicate,
replacement, overlap, or reordering mutations fail schema validation. The
projected-manifest schema requires every feature's complete
`official_capability_ids` array.

The complete projection has one byte-identical same-family title mapping for
all 500 advertised literals, with no missing or ambiguous mapping. Candidate
acceptance classes remain 159 required-local, 46 alternate-local, and 6
external-optional; candidate runtime boundaries remain 205 not-qualified and
6 not-applicable.

## Preservation and derived source hashes

All 289 current capability records remain exact and ordered. All manifest
feature fields, statuses, gaps, evidence fields, upstream metadata, and skills
remain exact; only `official_capability_ids` receives candidate suffixes.

Source identity, order, and every non-derived field remain exact. Because the
source `claim_set_sha256` field is defined over every capability claim,
appending the candidates requires a deterministic rehash: 17 source hashes
change and 109 remain unchanged. The proof records every before/after hash and
uses the same canonical algorithm as `verify_official_capabilities.py`.

The current 289 oracle states and empty evidence arrays are independently
bound through the locked live oracle registry and candidate adapter. The
separate oracle-500 successor is also locked and must contain the same 500
capability IDs in the same order as the projected ledger.

## Candidate-only boundary

This projection is not a live merge and is deliberately non-advancing. It has
zero runtime evidence, zero `passed_current` records, no executor-ready
candidate, no required cloud inference, and no Warehouse sample dependency.
Custom-data Warehouse capability remains in scope.

`live_merge_ready` remains false for exactly two machine-recorded verifier
categories:

- nine feature-family status aggregates would differ if recomputed over 500
  rows, while this package intentionally preserves the current family fields;
- eight feature families need additional acceptance scenario coverage.

The six external-optional candidate capability rows with wired/partial Thor
state are recorded as a reviewed, nonblocking distinction. Capability-level
Thor state describes shipped/local implementation while the family-level
external boundary remains `external_optional`; all six runtime states remain
`not_applicable`.

## Check

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/ledger-500-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/ledger-500-successor/tests/test_compiler.py
```

The compiler performs checked-in filesystem reads only. It does not use the
network, Docker, services, models, subprocesses, or host inspection.
Atomic regeneration rejects symlinked or non-directory output parents,
symlinked targets, and non-regular targets.
