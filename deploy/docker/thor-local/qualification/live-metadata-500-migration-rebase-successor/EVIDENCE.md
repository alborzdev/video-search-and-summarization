# Final static evidence

Status: final frozen composition compiled, generated, and exactly pinned.

The package provides:

- a self-contained compiler with deterministic JSON, canonical digest, Git
  blob ID, strict JSON, schema, and bounded write helpers;
- exact SHA-256 preservation locks for all seven predecessor package files,
  its five projected members, and the selected Metadata-500 descriptor/selector;
- a deterministic five-member predecessor-to-successor journal with
  changed/unchanged membership and rollback bindings;
- exact source, output, and proof pin validation before check or write;
- a seven-file package-local staged transaction with injected-failure rollback;
- adversarial tests for preservation, semantic selector/descriptor binding,
  wrong-pin write rejection, output isolation, strict parsing, and absence of
  runtime/network/Docker/subprocess imports.

## Frozen final-chain inputs

| Input | Raw SHA-256 |
| --- | --- |
| Live official capabilities | `61c2a4c0bc9d23940d954311f93824dc55c18cfc58caca002162cc1ef6808098` |
| Live capability oracles | `24214553cbd669eb80efa7b4a602ac52328e00bd43241c839b43b10d05e22e8e` |
| Projected 500 ledger | `8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13` |
| Oracle successor | `e682282735476830659582bd551fddc3e140580324e856ceaea4507ca5e706c2` |
| Oracle successor schema | `759c36ade481c6024815df95738a7fca13e92c66ae70649154bb7cb85b439057` |
| Composition | `8db4dea3425fc0ea1252e6ceac40d32aef9fda41546b14661e79f1bdefe801f2` |
| Composition schema | `126896936bd45a7eebf0baa09e93986932993aa75317ba51de474d9612e65370` |

## Generated outputs

| Output | Raw SHA-256 |
| --- | --- |
| `post-state-official-capabilities.json` | `8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13` |
| `post-state-manifest.json` | `c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93` |
| `post-state-acceptance-inventory.json` | `69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0` |
| `post-state-capability-oracles.json` | `911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021` |
| `post-state-capability-oracles.schema.json` | `b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233` |
| `migration.json` | `771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c` |
| `migration.schema.json` | `45c41fc02b60fa466689ab2ece0e87487287a20e3d247ba0f62293c649a349c0` |

The proof payload SHA-256 is
`408ae46b8863e8f2161018b928303ff85ceb803eb02c7e976dd599186dbc2582`.
The five-member journal reports two changed members (`ledger`, `oracles`) and
three byte-identical members (`manifest`, `acceptance`, `oracle_schema`).

## Validation result

- `pytest`: 38 passed, 0 skipped.
- compiler `--check`: passed.
- `ruff check`: passed.
- predecessor package and canonical selector/descriptor hashes: unchanged and
  equal to their exact preservation locks.

No runtime execution, network access, Docker access, warehouse sample data,
model execution, live-file mutation, selector mutation, or descriptor mutation
was used for this compilation and validation.
