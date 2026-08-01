# Global advertised-entry coverage ledger

This isolated package gives every one of the 500 strings in the locked VSS
3.2.1 manifest exactly one semantic mapping state. It is a deterministic,
read-only inventory compiler. It imports no VSS product code, starts no service,
uses no network or Docker API, emits no runtime evidence, and cannot promote a
capability or feature runtime state.

The checked denominator is:

| Mapping class | Count | Meaning |
| --- | ---: | --- |
| `exact_existing_capability` | 276 | A non-`manifest-entry.*` capability has a unique exact title, feature, source-claim, and oracle binding. |
| `canonical_entry_capability` | 13 | A deterministic `manifest-entry.*` capability and `oracle.<capability-id>` bind the exact entry. |
| `explicit_missing_entry_gap` | 74 | The exact pointer is present in the advertised-entry gap plan and still has no canonical capability/oracle. |
| `family_only_unreviewed` | 137 | The family has capabilities, but no capability has an exact reviewed binding to this string. |

The last two classes are the 211 literal semantic-completeness blockers. Exact
semantic mapping is not runtime qualification: all 500 rows carry
`mapping_is_runtime_evidence: false`, all runtime-evidence arrays are empty, and
464 required or alternate-local entries remain runtime blockers. The 36
`external_optional` entries are retained as exact or open semantic boundaries
but are excluded from the Thor-local runtime obligation; they cannot satisfy a
required or alternate-local entry. Each external row must default to, and have
the exact lane set, `["external-optional"]`. Required and alternate-local rows
may never default to `external-optional`.

## Inputs and fail-closed rules

`compiler.py` raw- and canonical-SHA-locks these five sources:

- `deploy/docker/thor-local/parity/manifest.json`
- `deploy/docker/thor-local/parity/official-capabilities.json`
- `deploy/docker/thor-local/parity/capability-oracles.json`
- `deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json`
- `deploy/docker/thor-local/qualification/runtime-lanes/runtime-lane-plan.json`

For an exact mapping, title equality alone is insufficient. The compiler also
requires a unique capability in the manifest family, matching `feature_id`, at
least one valid official source claim, the exact oracle identity and copied
ledger binding, planning-only readiness, zero evidence, and agreement with the
runtime-lane entry mapping and its entry-level locality. Canonical entries
additionally require the exact
deterministic `manifest-entry.<family>.<index>-<slug>` identity.

Gap rows must exactly match the gap plan and must not overlap an official
capability or oracle. Family-only rows must have family capability rows, no
exact title mapping, and no gap-plan entry. A zero-capability family entry that
is absent from the gap plan is rejected.

The Warehouse sample bundle is excluded at the ledger, gap, runtime-plan,
oracle-fixture, and oracle-execution-bound levels. Small operator-owned custom
data remains a separate runtime planning concern. Required cloud inference is
false.

## Validation

From the repository root:

```bash
python3 deploy/docker/thor-local/qualification/advertised-entry-coverage/compiler.py --check
pytest -q deploy/docker/thor-local/qualification/advertised-entry-coverage/tests/test_compiler.py
```

`--check` validates the strict Draft 2020-12 schema, payload and raw digests,
source locks, exact denominators, all cross-document invariants, canonical JSON
rendering, and byte equality with a fresh deterministic compilation.

`--write` only rewrites this package's `coverage.json`. It does not modify any
input, parity ledger, runtime plan, service, or host state.
