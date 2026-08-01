# Exact-title entry mapping successor

This package is the read-only, non-advancing successor to commit
`76596ccd1a2b02644506399b7e27ce36bbe3544b`. It proves that all 289 official
capabilities have one byte-identical advertised-title match in the same
manifest family and one bound oracle.

The predecessor compiler intentionally counted only 13 canonical
`manifest-entry.*` mappings. The current exact-title compiler recognizes 276
additional, already-existing non-`manifest-entry.*` capabilities. The global
inventory therefore moves from 13 exact / 487 missing / 413 family-only to
289 exact / 211 missing / 137 family-only. The scoped explicit gap plan stays
at 74 entries.

This is semantic inventory mapping, not runtime qualification. All 289
capability records and all 289 oracle records are byte-identical to the
predecessor; all capability and oracle evidence arrays remain empty; no
`passed_current` promotion occurs. The Warehouse sample bundle remains
excluded, while custom-data Warehouse capability stays in scope.

## Historical package substitution

The earlier `tooling-entry-ledger-successor` embeds the predecessor's 13/487
denominator. This package freezes that complete predecessor package by tree
OID and all seven file hashes and reports it as
`identity_verified_not_reexecuted`; it must not be replayed against the
current plan.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/exact-title-entry-mapping-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v \
  -s deploy/docker/thor-local/qualification/exact-title-entry-mapping-successor/tests
```

The verifier performs regular-file reads and bounded, shell-free local `git
rev-parse`, `git cat-file`, and `git show` reads only. It does not inspect the
host, use the network, run Docker or services, download artifacts, or create
runtime evidence.
