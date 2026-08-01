# Evidence boundary

Status: **static successor mapping verified; non-advancing**.

The deterministic result binds:

| Boundary | Exact observation |
|---|---|
| Predecessor commit | `0c9a0a388900e1012b9fba68c6f2b17d6abb3c06` |
| Historical gaps | 87 |
| Historical wave candidates | 83 |
| Historical external blockers | 4 |
| Current gaps | 86 |
| Current mapped historical candidates | 82 |
| Removed gap | `manifest-gap.vios-codecs-audio.05-cpu-multimedia-support` |
| Added gaps | none |
| Current capabilities / oracles | 277 / 277 |
| CPU capability | `required_local`, `wired`, `not_qualified` |
| CPU oracle | `open_unexecuted`, empty evidence |

All eight historical package tree identities and inventory byte identities are
read from the exact local Git commit. The verifier additionally rehashes every
unique repository source referenced by those inventories at that commit; the
current observed count is 125.

Four Wave 3 candidates, two checked static integrations, and Planning
Requirement Waves 5–12, the parity source lock, and recursive coverage are
frozen separately with the candidate-only `offline-mv3dt-tools` observation:
17 package trees, 22 key candidate/inventory/receipt artifacts, and 245
embedded source locks. Their
declared source paths are present in the predecessor tree. Every package result
is `identity_verified_not_reexecuted`; historical source digests remain bound
to the exact frozen artifact rather than being relabeled against a later tree.

No runtime evidence is collected or inferred. The result carries
`official_capability_effect: none_candidate_only` and explicitly records that
historical executors were not re-run from an exported worktree.
