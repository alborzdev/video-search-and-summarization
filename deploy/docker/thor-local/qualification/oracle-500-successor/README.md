# Oracle 500 successor projection

This isolated candidate-only package deterministically projects the current 289
live capability oracles together with all 211 candidate oracle adapters. The
result is a 500-row successor document keyed semantically by capability ID. It
does not modify the live capability ledger, live oracle registry, qualification
wrapper, protocol registry, workload package, or any runtime surface.

The first 289 projected rows are deep copies of the live oracle array in its
original official-ledger order. The compiler compares their canonical bytes row
by row and records both a complete-array hash and 289 capability-keyed record
hashes. The remaining 211 rows are appended in strict parsed
`(feature_index, advertised_index)` manifest-pointer order, identical to the
candidate source and ledger-successor append order. Lexical capability-ID order
is explicitly rejected, and all three order hashes are schema constants. The
live and candidate integrity maps each admit only their exact capability-ID key
set. Candidate rows preserve every adapter field exactly and add only successor
provenance plus exact optional binding copies.

## Exact candidate bindings

- All 23 candidate `kind=protocol` rows consume their exact planning-only
  protocol-v2 binding. The protocol contract must equal the candidate oracle
  plan, the boundary must match, activation must be false, and readiness must
  remain `planning_only`.
- All 41 API and 19 deployment rows consume their exact workload. Candidate
  ID, manifest pointer, advertised literal, acceptance class, and workload kind
  must match the oracle row.
- The other 128 candidate rows remain exact adapter-only planning records and
  receive no invented protocol or workload default.

Every candidate fixture, required observation, adjacent-negative observation,
assertion, admission gate, cleanup contract, execution bound, and readiness
record is copied from the locked adapter without semantic changes. Fixture
materialization, request/action/duration bounds, executor, collectors, cleanup
targets, cleanup allowlist, cleanup executor, and cleanup collectors remain
null. Candidate evidence and promotions remain zero.

## Successor schema

The live v1 oracle schema remains authoritative for the preserved 289-row
source document and is validated before projection. A strict reviewed successor
schema is used for the combined artifact because exact candidate preservation
cannot be expressed by the live shape: candidate rows have a separate
adjacent-negative collection, `recorded_absent` assertions, null execution
bounds, and non-materialized cleanup fields. Existing projected rows are still
validated against the locked live schema and then checked for exact equality;
candidate successor rows reject additional properties and retain per-row
payload and source-binding hashes.

## Safety boundary

The compiler performs bounded static reads of raw-hash-locked regular repository
files. It rejects duplicate JSON keys, non-finite numbers, absolute and parent
paths, symlink traversal, non-regular files, duplicate IDs, set or source-lock
identity drift, lexical candidate reordering, wrong-class gap requirements,
binding kind swaps, loose nested records, and semantic mismatches. Atomic output
replacement rejects symlink targets and unsafe parents.

No runtime, network, cloud, Docker, service, GPU, model, or host inspection is
performed. External candidates remain unexecuted and require explicit operator
approval. Cloud inference is not required, and the Warehouse sample bundle is
excluded; custom-data planning descriptions remain non-materialized.

## Validate

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/oracle-500-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/oracle-500-successor/tests/test_compiler.py

ruff check \
  deploy/docker/thor-local/qualification/oracle-500-successor/compiler.py \
  deploy/docker/thor-local/qualification/oracle-500-successor/tests/test_compiler.py
```

`--write` regenerates only `capability-oracles-500.json` through a
same-directory regular temporary file.
