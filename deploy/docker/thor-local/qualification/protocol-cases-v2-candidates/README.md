# Protocol cases v2 candidate extension

This directory is an isolated, candidate-only design for expanding the Thor
protocol-case denominator from the seven live v1 cases to 30 cases. It does not
modify or integrate with `../protocol-cases/`, the live capability ledgers,
capability oracles, qualification wrappers, or runtime executors.

The compiler derives exactly 23 `kind=protocol` capability IDs from
`../remaining-advertised-entry-candidates/candidate.json`. It fails when the
design is missing an ID, adds an ID, or changes the source candidate boundary.

## Contract shape

`protocol-cases-v2-candidate.json` contains:

- seven `live_v1` wrappers. Each wrapper embeds the complete original case as
  `legacy_case`. The compiler compares canonical JSON bytes to the live source,
  preserving every existing capability ID, case ID, vector, mutation boundary,
  source claim, and limitation;
- 23 `candidate_manifest` wrappers. These expose `transport_components[]`,
  including composite transports, and one of the `local`, `alternate_local`, or
  `external` boundaries;
- readiness of `planning_only`, `executor_ready`, or `blocked`. All 23 added
  cases are `planning_only`, have no executor binding, and cannot activate;
- a one-to-one `bindings` projection for future oracle consumption. Each
  projection has a stable case ID, case-payload hash, binding hash, transport
  components, boundary, readiness, activation flag, source hashes, and either
  the preserved v1 vector IDs or the candidate's explicit planning-only vector
  contract.

The five `executor_ready` records are only the five cases already marked ready
by the live v1 executor. The two other live cases remain `blocked`. No proposed
runner family is treated as an executable binding.

External cases are always non-activating. The Warehouse 2D entry is retained
only as an `alternate_local` custom-data planning contract; the Warehouse sample
bundle is excluded.

## Static compilation

The compiler performs filesystem-only reads of checked-in inputs. It contains
no network, Docker, service, GPU, host, or runtime-evidence code.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 compiler.py --check
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_compiler.py
```

`--check` recompiles in memory and requires the checked output to match exactly.
`--write` is the only mode that replaces the candidate output. Source locks pin
the live contract, schema, validator and executor plus the advertised-entry
candidate contract, schema and compiler and this directory's design input.

## Non-integration boundary

This artifact is not runtime evidence and cannot advance a capability state. A
future integration must independently review the v2 schema, implement and test
real runner bindings, define lifecycle admission and cleanup for each new case,
and explicitly adapt `capability_oracles.py` to consume `bindings`. Copying this
candidate into a live ledger would be an unsupported promotion.
