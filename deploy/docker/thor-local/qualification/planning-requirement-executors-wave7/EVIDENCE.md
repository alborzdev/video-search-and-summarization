# Wave 7 Evidence Boundary

## Accounted denominator

The executor digest-locks the exact sets it recomputes from the live ledgers:

- 110 total planning requirements;
- 27 materialized and 83 live-open;
- 50 predecessor selections (26 materialized, 24 still open);
- 59 live-open requirements audited before this wave;
- 6 selected here and 53 left unselected.

`calibration-schema-static` is now materialized by its canonical static
integration. It is outside this live-open audit and does not alter the six
historical Wave 7 candidate selections.

## Selected static subsets

| Planning requirement | Capability | Static evidence only |
|---|---|---|
| `ui-negative-oracle` | `behavior.ui.known-issues` | Seven limitations and the non-remediation boundary remain documented. |
| `nemoclaw-env-matrix` | `configuration.nemoclaw.model-surface-boundary` | Independent VSS/NemoClaw surfaces and local provider rendering are present in locked source. |
| `nemoclaw-recovery-oracle` | `behavior.nemoclaw.recovery-and-destructive-boundaries` | Recovery constants and explicit destructive-action gates remain present. |
| `agent-known-issues-oracle` | `behavior.agent.known-issues` | Scoped negative contract plus recursion/empty-chart source branches remain present. |
| `systems-nvstreamer-sync` | `configuration.nvstreamer.sync` | Config parsing and synchronized-start gating are present; compatibility is not proven. |
| `systems-nvschema-json` | `protocol.nvschema.json-frame` | Locked JSON-line consumers cover an illustrative field/alias subset, not a complete validator. |

## What a pass means

A pass means every raw file digest, canonical ledger binding, exact set digest, and required source token matched the reviewed repository state. It does not mean the advertised runtime behavior passed on Thor.

The executor also binds each selected capability to its current oracle and requires `current_state == "open_unexecuted"` and `evidence == []`. That check prevents this static package from being mistaken for runtime evidence. The executor does not edit acceptance, capability, oracle, or manifest ledgers.
