# Safe Merge Plan

This candidate must not be copied wholesale into the live ledger. The live
ledger, manifest, acceptance inventory, and oracle catalog form a cross-linked
contract and must move together in a later reviewed change.

## Preconditions

1. Run `validate_candidate.py --report` and the focused tests.
2. Confirm the live target still points at VSS 3.2.1 GA commit
   `7640d91728a1a78b4664a7b336947f80bfa78d59` and reviewed main commit
   `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`.
3. Re-check that no proposed new ID has entered the live ledger and all nine
   enrichment targets still exist.
4. Preserve unrelated user changes in the dirty worktree.

## Ordered merge

1. Add or deduplicate the 26 source records in `official-capabilities.json`.
   If a source already exists under another ID, reuse the existing ID and
   rewrite candidate source references before recomputing hashes.
2. For each new capability, copy the candidate `status` members to the live
   top-level fields `acceptance_class`, `thor_state`, and `runtime_state`.
3. Add each exact capability title to its feature family's `advertised` list,
   and add its ID to `official_capability_ids`.
4. Deep-merge the nine enrichment contracts into their existing claims. Do not
   replace existing evidence, statuses, or source claims; deduplicate arrays.
5. Translate the 14 discrepancy/boundary records into the live discrepancy
   representation. Preserve locator detail in evidence or resolution text if
   the live schema still accepts only `source_ids` and `resolution`.
6. Recompute every affected live source `claim_set_sha256` using the live
   ledger canonicalization, not the candidate canonicalization.
7. Keep all candidate `expected_manifest_binding.semantic_coverage=false`.
   Existing Agent, RT-Embed, Alerts, and Video Analytics manifests cover API
   operations only.
8. Add semantic oracles before advancing any `runtime_state`. Static source,
   config, artifact, or route evidence must not become `passed_current`.
9. Recompute feature-family aggregate acceptance, Thor, and runtime states.
10. Update acceptance feature crosslinks only where the existing scenarios do
    not already cover the candidate scenario IDs.

## Required merge-time semantic work

- Agent: config schema, MCP resolution, profile-specific reports, report
  persistence, and Phoenix span hierarchy.
- Evaluation: actual `nat eval` runs and all five output files.
- RT-Embed: exact model identity, dimensions, reindex behavior, and custom model
  source integration. The 448p base default and 448p anomaly search default
  remain scoped.
- Model customization: artifact/class-map/anchor compatibility and downstream
  semantic checks.
- Auto Calibration: keep
  `must_not_claim_official_thor_support=true`; runtime remains blocked until the
  backend exists and a custom-data project completes.
- Warehouse: use operator-provided custom video/models/calibration. Do not add
  the excluded sample bundle as a parity prerequisite.
- Security: preserve `must_not_claim_remediated=true` even after network-boundary
  tests pass.

## Final validation after a future merge

Run the live ledger validator, capability-oracle validator/tests, acceptance
planner/tests, parity manifest suite, static milestone wrapper, Ruff, and
`git diff --check`. Exact live counts must be intentionally updated in their
tests; no count should be weakened to a lower bound.
