# Remaining advertised-entry semantic candidates

This package reviews the 211 VSS 3.2.1 manifest strings that still lack an
exact capability-title and oracle mapping. It creates one source-bound,
same-family `manifest-entry.*` candidate for each string:

| Prior mapping state | Candidates |
| --- | ---: |
| explicit missing-entry gap | 74 |
| family-only unreviewed | 137 |
| **Total** | **211** |

These rows are candidate contracts, not additions to the official capability
ledger and not runtime qualification. They cannot change a capability state,
carry no evidence, and leave the checked official denominator at 289 until a
separate successor merge reviews the exact ledger/oracle transition.
The compiler does prove that appending all 211 proposed rows produces a
500-capability document that satisfies the current strict official-capability
schema and a candidate manifest with 500 unique same-family exact-title
mappings and zero missing mappings; it writes neither merged core document.

Each candidate binds the original manifest pointer and byte-exact advertised
literal to precise official source claims, implementation or documentation
surfaces, specific semantic requirements, reviewed dependency capabilities, an
adjacent-negative case, an execution boundary, and owned cleanup. Family-only
rows must retain at least one same-family dependency; explicit gaps may also
name valid cross-family prerequisites where the implementation truly composes
services. Every explicit gap also carries the byte-exact prior setup, evidence,
literal-success, and cleanup contract. The compiler rejects missing/duplicate
pointers, generic placeholders, invalid source or dependency identities, false
`wired` claims without a checked-in regular-file surface, synthetic
advertised-as-source locators, external/local boundary drift, evidence or
promotion text, and the excluded Warehouse sample datasets.

## Successor prerequisites

The candidate projection is intentionally not merge-ready runtime evidence.
Before the official ledger can move from 289 to 500 entries, the successor must:

- expand the seven-case protocol inventory for the 23 new protocol candidates,
  including composite and planning-only transports without pretending a runner
  exists;
- adapt all 211 exact fixture, observation, negative, cleanup, and execution
  boundaries into generated planning oracles; and
- preserve the existing 289 capability states and evidence byte-semantically
  while admitting the new 211 rows as unexecuted and evidence-free.

## Scope boundaries

- 159 candidates are required local, 46 use an alternate local lane, and six
  are external optional boundaries.
- Required cloud inference is false. External entries cannot satisfy local
  parity obligations.
- The optional large Warehouse sample bundle is excluded. Small operator-owned
  custom data remains in scope for Sparse4D, MV3DT, and Warehouse workflows.
- The package invokes no service, Docker API, network endpoint, model, download,
  host inspection, or runtime evidence collector.

## Validation

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/tests
```

`--write` deterministically regenerates only this package's `candidate.json`.
It does not edit the manifest, official capability/oracle ledgers, services, or
runtime evidence.
