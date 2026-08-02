# Phase 1 evidence

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
| `inventory.json` | `d4e349b41594140b109bc548c566193d22dd7a29c317698a3b9efb588f6de6b2` | `2498e6656422323f25beed22b99bb2a4f7363af5c45466e7a20b34351ba69fae` |
| `migration-map.json` | `b1491eb3ccad2087a5fe0faebcc12aa49a94726011b4aa408dbe65b196003f65` | `03a0a1f9de551f6b9633f62cfb528bb38d9aa828b6c0a904dfd951817902f064` |
| `inventory.schema.json` | `0de8e7a75907761f943da0a435399dab30ad486e42aed36169a14f0572d38318` | — |
| `migration-map.schema.json` | `41d3cca41b0fead24b292c06827a3b0ac02267af1449a777be33619fb0c2b902` | — |

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

## Test evidence

Focused validation at package creation:

```text
23 tests passed
93 subtests passed
```

The adversarial suite covers exact set algebra, per-wave counts, historical
input locks, row bindings, source locks, intentional adapter sharing, blocker
non-execution, remote-endpoint classification, pending dispatch, migration live
identities and state split, non-promotion, policy safety, artifact payload/raw
locks, determinism, duplicate keys, non-finite numbers, additional properties,
denominator tampering, wrong digests, plan-to-manifest literal mismatches,
unsafe paths, and leaf/intermediate symlinks for both source and package files.

## Claim boundary

This is planning and static-source inventory evidence only. No consolidated
executor exists in Phase 1, and no row is promoted or runtime-qualified. The
package performed no Docker, network, subprocess, credentials, downloads,
service lifecycle, models, host inspection, or Warehouse sample action.
