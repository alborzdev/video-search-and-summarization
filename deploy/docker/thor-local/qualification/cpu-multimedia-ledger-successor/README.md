# CPU multimedia ledger successor

This package preserves Advertised-entry Executor Waves 1–8 as immutable
historical candidate snapshots while verifying the current 87-to-86 gap-ledger
transition. It does not rewrite the old wave inventories, denominators, source
locks, or evidence wording.

The verifier reads the exact predecessor commit
`0c9a0a388900e1012b9fba68c6f2b17d6abb3c06` from the already configured local
Git object database. It verifies that commit's four core ledgers, all eight wave
package tree OIDs, all eight inventory byte hashes, the complete predecessor
chain, and every repository source lock reachable from those inventories. It
then reads four checked-in current core files and proves:

- the current 86 gap IDs equal the historical 87 IDs minus only
  `manifest-gap.vios-codecs-audio.05-cpu-multimedia-support`;
- the historical 83 candidate IDs become 82 still-open candidates plus that
  one retired gap ID;
- the same four external-attestation blocker IDs remain open;
- the CPU entry now has one canonical `required_local` capability and one
  canonical oracle, with `wired` / `not_qualified` / `open_unexecuted` state
  and empty evidence;
- the current capability/oracle denominators are both 277.

The same predecessor commit also freezes 17 additional current-bound packages:

- Wave 3 `agent-smartcity`, `systems`, `calibration-warehouse`, and `bundle`;
- `lvs-mcp-static-adapter-integration` and
  `calibration-schema-static-integration`;
- the candidate-only `offline-mv3dt-tools` package and its immutable execution
  receipt;
- Planning-requirement Executor Waves 5 through 12.
- the parity `source-lock` and Wave 3 `recursive-coverage` validators.

For these packages the verifier checks exact package tree OIDs, 22 key
candidate/inventory/receipt byte hashes, 245 structurally valid embedded source
locks, and the presence of every declared source path in the predecessor tree.
Each is reported separately as `identity_verified_not_reexecuted`.

Run from the repository root:

```bash
python deploy/docker/thor-local/qualification/cpu-multimedia-ledger-successor/executor.py
python -m pytest -q \
  deploy/docker/thor-local/qualification/cpu-multimedia-ledger-successor/tests
```

The only subprocess calls are bounded, shell-free, read-only local `git
rev-parse`, `git cat-file`, and `git show` object reads. The package performs no
network, Docker, download, service, media, model, runtime, or file-write action.

## Wrapper substitution boundary

The old Wave 1–8 direct suites intentionally dereference mutable current paths
that were locked to their 87-entry snapshot. They therefore must not be run as
current-ledger validators after the canonical CPU entry was added. A current
static wrapper can run this successor package instead: it proves exact
predecessor identity for the advertised waves and the 17 frozen candidate,
integration, planning, source-lock, and coverage packages, plus the complete
current set transition.

This verifier does not export a detached worktree and does not re-execute the
historical Python test processes. If re-execution is required for forensic
purposes, it must happen separately in an isolated export of the exact
predecessor commit. Some embedded source digests intentionally describe an
earlier snapshot within a frozen artifact; they remain bound by that artifact's
byte identity and are not rebased to the predecessor tip. Identity/partition
verification is also not runtime qualification of CPU multimedia support.
