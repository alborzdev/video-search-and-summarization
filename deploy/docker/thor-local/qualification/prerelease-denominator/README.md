# VSS exact prerelease diff denominator

This package is the exhaustive **static Git-metadata denominator** for the
divergence rooted at VSS 3.2.1 commit
`7640d917047cf7b0fd3085eefb8282754b56bc94`:

- stable `main`: `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`;
- `develop`: `a34c6b0406bcadd380e4c4dac6ff7e830deb27e5` (the last
  `nightly-20260801` remains `708dac2ff071c76971d5cc8cab24f3879e6aac63`);
- 499 commits reachable from the prerelease tip but not the merge base;
- 109,058 develop-side path/status records covering 59,917 unique paths;
- two commits reachable from stable `main` but not the merge base, preserved as
  explicit divergence exceptions; and
- every commit classified into one or more of the existing fourteen candidate
  families or seven explicit non-feature/watchlist categories.

It replaces the curated watchlist's previously unavailable denominator. It
does not replace that watchlist's reviewed feature descriptions, and it does
not turn prerelease content into a stable, implemented, local, or runtime-
qualified capability.

## Files and evidence ceiling

- `denominator.json` enumerates all 499 prerelease commits and both main-only
  exceptions with tree, parent, timestamp, subject, classification trace,
  path/status count, and per-commit digest.
- `head-delta.json` and its schema record the exact one-commit delta after
  `nightly-20260801`: the develop-only NemoClaw Hermes agent runtime addition.
  The validator content-locks and binds that bounded semantic record to the
  latest denominator row without promoting it into the stable 3.2.1 capability
  inventory.
- `path-status.jsonl.gz` contains every path/status record. Its uncompressed
  canonical JSON Lines stream is 25,040,081 bytes; deterministic gzip is
  789,448 bytes. The validator checks both byte counts and both SHA-256s.
- `classification-rules.json` is the deterministic, ordered classification
  contract. The fourteen family IDs must exactly match the adjacent curated
  watchlist. The Warehouse sample rule intentionally matches zero commits in
  this locked range; that does not bring the optional sample bundle into scope.
- `validator.py` replays all record counts, digests, ordering, path safety, and
  classifications offline. It never invokes Git, the network, Docker, model
  services, or credentials.
- `generate.py` is the separately invoked reproducibility tool. It invokes only
  local Git commands, forces `GIT_NO_LAZY_FETCH=1`, and fails unless all three
  locked commits and trees are already available.

The evidence ceiling is `commit_tree_and_path_status_metadata_only`. Renames
are represented deterministically as delete/add pairs by using
`--no-renames`; no blob similarity heuristic or file blob is needed. A family
classification means only “this commit was considered in this candidate
family.” Runtime parity remains false, runtime evidence remains empty, and
official promotions remain zero.

## Offline validation

From the repository root:

```bash
python3 deploy/docker/thor-local/qualification/prerelease-denominator/validator.py
pytest -q deploy/docker/thor-local/qualification/prerelease-denominator/tests
```

The compact result is available with `validator.py --json`.

## Deterministic regeneration

Only the materialization step below is connected. It fetches commit/tree
metadata with `blob:none`; the generator itself is local-only and refuses a
promisor fetch:

```bash
VSS_DENOM_GIT_DIR=$(mktemp -d /tmp/vss-prerelease-metadata.XXXXXX)
git -C "$VSS_DENOM_GIT_DIR" init --bare
git -C "$VSS_DENOM_GIT_DIR" remote add upstream \
  https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git
git -C "$VSS_DENOM_GIT_DIR" fetch --filter=blob:none --no-tags upstream \
  refs/heads/develop:refs/heads/develop \
  refs/heads/main:refs/heads/main \
  refs/tags/v3.2.1:refs/tags/v3.2.1
GIT_NO_LAZY_FETCH=1 python3 \
  deploy/docker/thor-local/qualification/prerelease-denominator/generate.py \
  --git-dir "$VSS_DENOM_GIT_DIR"
python3 deploy/docker/thor-local/qualification/prerelease-denominator/validator.py
```

Regeneration intentionally overwrites only `denominator.json` and
`path-status.jsonl.gz` in this package. Review both outputs and update their
fail-closed schema/constants only after independently confirming a deliberate
source-lock change.

The exact acquisition and workspace measurements from this materialization are
recorded in `EVIDENCE.md`.
