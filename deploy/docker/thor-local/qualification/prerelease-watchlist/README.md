# VSS curated prerelease candidate watchlist

This package records a curated prerelease candidate watchlist selected from
observed differences between official VSS `main` at
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57` and the divergent `develop` /
`nightly-20260801` tree at
`708dac2ff071c76971d5cc8cab24f3879e6aac63`. The prerelease tree declares
version `3.3.0`; it is not the stable VSS 3.2.1 baseline.

The manifest records fourteen selected candidate families and forty selected
source pointers. It has no authoritative full-diff denominator, so its coverage
fraction is not computable. It cannot prove, and must never be described as,
complete, comprehensive, or exhaustive coverage of `develop`. Every selected
family is eligible only for candidate-static analysis and remains a runtime
watchlist item. The adjacent `prerelease-denominator/` package now exhaustively
accounts for commits and path/status records, but deliberately does not upgrade
this watchlist to feature-semantic completeness. This package cannot:

- edit stable acceptance, capability-oracle, planning, or runtime-lane ledgers;
- add runtime evidence or promote an official capability;
- emit or authorize a `passed_current` result;
- use a network, require a local `develop` checkout, run subprocesses, inspect
  credentials, or call Docker; or
- make the optional approximately 100 GB Warehouse sample bundle mandatory.

## Evidence ceiling

`manifest.json` contains exact upstream repository, branch, tag, merge-base,
commit, comparison, source-path, source-URL, and introducing-commit locks. Its
source witnesses are deliberately labelled `locked_remote_pointer_only`.
Offline validation proves that those reviewed pointers and dispositions have
not drifted; it does **not** prove the remote file content, implementation,
deployment, runtime behavior, or the absence of other prerelease changes. A
separately reviewed sibling now supplies an authoritative Git commit/path
denominator. It does not supply file-content or runtime proof, so this package's
evidence ceiling remains `locked_remote_pointers_only` and its own coverage
fraction remains `not_computable`.

The manifest preserves two exceptions:

- `deprecated-thor-edge-4b` is a conflict. The prerelease Build Vision Agent
  edge reference still names an obsolete Thor Edge 4B fallback. Thor's locked
  official Nemotron-3-Nano-4B-FP8 plus Cosmos3 contract takes precedence.
- `warehouse-sample-bundle` is excluded. Custom, operator-owned Warehouse data
  remains within the associated candidate family.

Graph RAG, Kubernetes, SOP, NemoClaw, and other infrastructure-bearing
families remain watchlisted at runtime until their local prerequisites and
lifecycle are explicitly authorized. The stable 3.2.1 qualification counts
remain unchanged.

Run the offline validator and adversarial tests from the repository root:

```bash
python3 deploy/docker/thor-local/qualification/prerelease-watchlist/validator.py
pytest -q deploy/docker/thor-local/qualification/prerelease-watchlist/tests
```

`validator.py --json` emits a strict-schema result containing fourteen selected
`pointer_locked_candidate` rows, fourteen `watchlist_not_executed` runtime
states, an explicit unavailable denominator, empty runtime evidence, and zero
official promotions.
