# Wave 8 Evidence Boundary

## Accounted denominator

The executor digest-locks the exact sets it recomputes from the live ledgers:

- 110 total planning requirements;
- 26 materialized and 84 live-open;
- 56 predecessor selections (26 materialized, 30 still open);
- 54 live-open requirements audited before this wave;
- 6 selected here and 48 left unselected.

## Selected static negative contracts

| Planning requirement | Capability | Static evidence only |
|---|---|---|
| `systems-lvs-empty-caption` | `behavior.lvs.live-caption-empty-window` | The documented empty-window/no-captions known limitation remains present. |
| `systems-lvs-shared-prompt` | `behavior.lvs.shared-caption-prompt` | The documented shared-backend last-writer limitation remains present. |
| `systems-lvs-spurious-index` | `behavior.lvs.caption-spurious-index` | The documented spurious epoch-dated incident-index limitation remains present. |
| `systems-cr2-recovery` | `behavior.base.cr2-nim-recovery` | The CR2/NIM full-stack redeployment boundary remains consistently documented. |
| `systems-search-known-issues` | `behavior.search.retention-indexing-quality` | Retention, asynchronous indexing, and quality limitations remain grouped in the negative contract. |
| `systems-rt-cv-ended-stream` | `behavior.rt-cv.delete-ended-stream` | The ended-stream deletion limitation remains documented. |

## What a pass means

A pass means every raw file digest, canonical ledger binding, exact set digest,
and required source token matched the reviewed repository state. These are
negative-contract preservation checks only. A pass does not demonstrate any
advertised runtime behavior on Thor and does not independently reproduce any
known limitation or recovery procedure.

The executor binds each selected capability to its current oracle and requires
`current_state == "open_unexecuted"` and `evidence == []`. That check prevents
this static package from being mistaken for runtime evidence. The executor does
not edit acceptance, capability, oracle, or manifest ledgers.
