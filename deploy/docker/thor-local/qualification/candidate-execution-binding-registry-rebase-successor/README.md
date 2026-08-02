# Candidate execution-binding registry rebase successor

This package is an inert, deterministic registry for the 208 mapped Metadata500
candidates. It separates useful semantic, planning-action, observer, and lane
projections from the authoritative executable bindings that do not yet exist.
It does not invoke any historical executor and cannot execute, deploy, inspect,
download, admit, or promote a candidate.

This sibling leaves `candidate-execution-binding-registry-successor` byte-exact
and rebinds its projection provenance to the final mapping-v2 rebase, final
runtime bundle rebase, and finalized Wave1 contract/receipt/successor chain.
All eight historical package files are independently hash-locked. A normalized
meaning-only comparison proves the 208 old and new rows retain identical order,
tiers, lanes, dependency closures, unresolved state, and empty authoritative
bindings. Exactly two protocol-backed record hashes are allowed to change.

Run its only CLI mode from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-execution-binding-registry-rebase-successor/compiler.py \
  --check
```

There is no default, emit, run, write, action, or execute mode.

## Exact denominator and tiers

The registry retains original mapping-v2 positions and oracle indexes while
excluding, but explicitly recording, the three static gaps at positions 101,
195, and 196. Every active row locks the exact candidate/oracle identity,
mapping position, manifest pointer, leaf, independently recomputed 16-bundle
closure, execution boundary, and source locators.

| Projection | Exact counts |
| --- | --- |
| Action | workload 58; protocol 23; oracle-only 127 |
| Observer | production subset 2; guarded adapter 68; absent 138 |
| Lane | exact external 4; family-single 176; family-multi 28 |
| Cross-tier | both 28; enriched 53; observer 42; oracle 85 |

Action projections are descriptive workload/protocol plans. Their canonical
records must equal mapping-v2’s exact binding hashes. Observer projections are
candidate-only static/in-process observations: the two Wave8 production-subset
rows take precedence while preserving both their Wave8 and guarded-receipt
locators. Neither observer source contains runtime evidence or can advance the
official capability state.

Lane projections are planning context. The four external rows require the exact
external entry scope; all 204 local/alternate rows require the reviewed family
scope. A lane, service path, or same-family observation is never an executable
binding.

## Direct locator locks

`locator-locks.json` normalizes the 389 implementation-surface occurrences into
269 unique locators and 235 exact base-file locks. Optional `#fragment` values
remain separate from the regular-file path. It also locks the 45 profile and
Compose references, 26 unique files, reachable through the seven lane IDs used
by the active 208 rows. The unused official-edge lane and its unique Compose
path are not projected.

The compiler rejects absolute/traversing paths, symlinks, non-regular files,
read-time mutation, hash drift, duplicate JSON keys, non-finite numbers,
changed source schemas, locator denominator drift, or any mismatch between the
checked locator artifact and current source bytes.

## What remains deliberately absent

Every row has `admission_grade=false`. Its authoritative binding has no
executor, action contract, service role, service-role/profile binding, profile
ID/path, Compose path, cleanup executor/target/rollback contract, postcondition
collector, evidence destination, or evidence record. All authoritative totals
are zero.

The projections therefore cannot be used by the empty receipt/admission package
to activate a candidate. Exact candidate-specific executors, service/profile
bindings, cleanup and rollback contracts, evidence destinations, reviewed
receipts, and runtime evidence remain future work.

The four external candidates are kept separate and cannot satisfy local parity.
Required cloud inference is false. The Warehouse sample bundle is excluded;
these locks grant neither sample-data access nor Warehouse execution authority.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-execution-binding-registry-rebase-successor/tests
python3 -m ruff check \
  deploy/docker/thor-local/qualification/candidate-execution-binding-registry-rebase-successor
python3 -m ruff format --check \
  deploy/docker/thor-local/qualification/candidate-execution-binding-registry-rebase-successor
```

Tests cover exact order/gaps/counts, action hashes, semantic locator locks,
bundle closure, observer overlap/precedence, lane scopes/files, external
separation, null authoritative fields, Warehouse/cloud inertness, strict
schemas, unsafe input/path rejection, and the check-only CLI boundary.
