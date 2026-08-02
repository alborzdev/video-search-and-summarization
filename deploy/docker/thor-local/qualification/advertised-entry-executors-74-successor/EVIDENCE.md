# Phase 1 inventory and Phase 2 execution evidence

The compiler deterministically derived the checked artifacts from the current
gap plan, current manifest, fixed live predecessor, and the seven historical
executor waves.

## Locked current sources

| Source | SHA-256 |
|---|---|
| `advertised-entry-gaps/plan.json` | `2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c` |
| plan canonical payload | `93981c6e1f277932614694e532de1514c196551109e5850305d88daf740b3bb0` |
| `parity/manifest.json` | `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce` |
| fixed `official-capabilities.json` | `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0` |
| fixed `capability-oracles.json` | `c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90` |

## Derived artifact identities

| Artifact | Raw SHA-256 | Canonical payload SHA-256 |
|---|---|---|
| `inventory.json` | `a9774af207f612e6c07936637d1141f5bc8e77df607363cfbac33aa447e19cb7` | `663dbb0444d852dd866219bd5e1368fcf139bda07cc35558a210cfaea858d7c0` |
| `migration-map.json` | `d2107c0cad790472896d194d4b9e704ecc9724678485788d3b94f6799bd4dc50` | `25644a4b0f0f3369d398f88285206df7da60428c99ef8e1f58260d6bdc251dbd` |
| `inventory.schema.json` | `e0bad7baa44b288b49bc46118dc1aef92a7d809278b68e88f46e95234c6a8422` | — |
| `migration-map.schema.json` | `41d3cca41b0fead24b292c06827a3b0ac02267af1449a777be33619fb0c2b902` | — |
| `execution-receipt.json` | `acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c` | `1e2e603cf714c6ca29c1a7a937c61871d36f7faee7e0a237e3e04ba5ccbf4ef3` |
| `result.schema.json` | `9776016ef702a0437e1926d28a243a5a6e1a135dfd83226c2a9718546c584a43` | — |

## Proved invariants

```text
historical IDs = 87
current plan IDs = 74
candidate IDs = 71
external blocker IDs = 3
migrated IDs = 13

candidate ∩ blocker = empty
candidate ∪ blocker = current plan
historical - current plan = migrated
current plan - historical = empty

retained source-lock references = 182
unique retained source paths = 88
unique adapter IDs = 67
```

All 88 unique source-path digests matched. All 74 current rows matched their
current plan pointer, literal, proposed capability ID, and advertised hashes.
All current plan oracles remained open and had empty runtime evidence. None of
their 74 proposed IDs appeared in the fixed live ledger or fixed oracle registry.

Each of the 13 migrated gap IDs was absent from the current plan and mapped to
exactly one fixed live capability plus exactly one fixed live oracle. The map
also locks each complete live row canonically, preventing a title, state,
contract, or oracle-boundary change from being mistaken for the same migration.

## Phase 2 execution evidence

The consolidated dispatcher ran exactly 71 retained candidates twice each,
with per-wave counts `1, 18, 23, 5, 5, 8, 11`. All paired semantic outputs and
canonical hashes matched. All 182 per-case source references over 88 unique
paths matched before and after dispatch. Historical `execute()` and `main()`
were not called. Eight source files used nested selected-AST extraction; every
accepted AST shape is explicitly SHA-256 locked in the executor and reproduced
in the receipt.

The aggregate effect trace is:

```text
asyncio AF_UNIX socketpair bootstraps = 3
forbidden effect attempts = 0
```

This trace is evidence produced by an in-process integrity guard, not an OS
sandbox or a claim about credential/host confinement. The Warehouse sample
bundle was excluded.

## Test evidence

Focused validation at package creation:

```text
39 tests passed
215 subtests passed
```

The adversarial suite covers exact set algebra, per-wave counts, historical
input locks, row bindings, source locks, intentional adapter sharing, blocker
non-execution, remote-endpoint classification, direct dispatch, migration live
identities and state split, non-promotion, policy safety, artifact payload/raw
locks, determinism, duplicate keys, non-finite numbers, additional properties,
denominator tampering, wrong digests, plan-to-manifest literal mismatches,
unsafe paths, leaf/intermediate symlinks, single-read identity drift, exact
per-wave call signatures, invalid-selection pre-load rejection, historical
`execute`/`main` non-use, effect denials, the asyncio-only socket exception,
import/main-guard drift, nested AST/code registration, selected-case reader
capabilities, return-shape and nondeterminism failures, and result-schema
tampering.

## Claim boundary

This is deterministic candidate-adapter execution, not current-capability
runtime qualification. No row is promoted, all runtime-evidence arrays remain
empty, and the official capability/oracle/acceptance artifacts are unchanged.
