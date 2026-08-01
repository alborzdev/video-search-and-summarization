# Tooling entry ledger successor

This package is the read-only successor for the exact published predecessor
commit `f638eb3421ec5620fe22609590c5e9d5872d33d0`. It proves the current core
transition from 277 capabilities, 277 oracles, and 86 advertised gaps to
289 capabilities, 289 oracles, and 74 gaps.

The 74-entry plan is the scoped empty/partial-family action set, while its
global denominator reports 487 advertised entries without an exact
entry-specific mapping and 413 family-only entries outside this plan.

The transition is exactly the eight `spatial-ai-utils` and four
`synthetic-data-tools` advertised entries. Their gap IDs are retired to full
canonical capability IDs and `oracle.{full capability id}` oracle IDs. The
eleven provider-free entries remain `wired/not_qualified` with
`open_unexecuted`, evidence-empty oracles. AWS/GCS is the sole new
`external_optional/not_applicable` boundary and remains
`external_boundary_unexecuted`.

The verifier also proves that all 277 predecessor capability records, all 277
predecessor oracle records, and all 74 surviving gap records are unchanged.
The two historical family-level `passed_current` labels are conservatively
retired to `not_qualified`; their evidence is retained only as historical
corroboration and is not promoted to any entry oracle. The Warehouse sample
bundle is excluded from the plan and all twelve new capability/oracle bounds.

## Historical package substitution

Twenty packages that directly embed the `f638…` core hashes are frozen by
exact predecessor tree OID and 30 directly dependent file SHA-256 locks. This
includes `cpu-multimedia-ledger-successor`,
`detection-map-static-executor`, and `external-entry-attestations`. They are
reported as `identity_verified_not_reexecuted`, allowing a unified wrapper to
run this successor instead of replaying those mutable-current validators
against the 289/74 core.

## Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/tooling-entry-ledger-successor/executor.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v \
  -s deploy/docker/thor-local/qualification/tooling-entry-ledger-successor/tests
```

The executor uses only bounded, shell-free local `git rev-parse`, `git
cat-file`, and `git show` reads plus regular reads of the four current core
files. It performs no writes, network access, Docker, downloads, service
lifecycle, model/media execution, external-provider calls, or runtime evidence
promotion.
