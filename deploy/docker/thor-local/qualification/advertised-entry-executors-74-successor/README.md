# Advertised-entry executor 74-row successor

This package rebases the historical Waves 1–7 advertised-entry executor
inventory from its former 87-row denominator onto the current 74-row gap plan.
It is a deterministic, read-only Phase 1 inventory compiler. It does not yet
dispatch any candidate adapter.

## Exact partition

The checked inventory contains exactly:

- 71 retained candidate rows, with per-wave counts `1, 18, 23, 5, 5, 8, 11`;
- 3 user-managed external-attestation blockers;
- 74 unique entry IDs and 74 unique manifest pointers; and
- 182 retained source-lock references over 88 unique repository paths.

The migration map separately accounts for all 13 identities removed from the
former denominator. Those identities now have exact live-predecessor capability
and oracle rows. Migration into that metadata predecessor is not runtime
qualification: 12 remain `not_qualified/open_unexecuted`, while AWS/GCS remains
`not_applicable/external_boundary_unexecuted`.

The three current blockers are Slack notification, Enterprise RAG report
generation, and FRAG retrieval integration. Their inventory rows have no
executor, no runtime evidence, and no promotion authority. The remote
OpenAI-compatible endpoint remains a Wave 3 source candidate; its source
observation is not an external-system attestation.

## Phase boundary

Every candidate row currently has:

```text
executor: null
dispatch_status: pending_phase_2
runtime_evidence: []
can_mark_passed_current: false
```

Consequently this package does not claim that any of the 71 candidate cases are
runnable through a consolidated CLI. A later phase must add and independently
verify bounded dispatch before changing that contract.

Historical Wave 1–7 inventories and executors are digest-locked inputs and are
not rewritten. This avoids invalidating Wave 8 and later qualification packages
that retain those historical hashes.

## Validate

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor/tests/test_compiler.py
```

The compiler rejects duplicate JSON keys, non-finite JSON numbers, unsafe or
symlinked repository and package paths, oversized or changing files,
source-lock drift, schema drift, denominator drift, any current-plan pointer
whose locked manifest literal differs, migration identity drift, and any live
promotion of a current gap identity.

## Safety

Validation performs no Docker, network, subprocess, credential, download,
service-lifecycle, model, host-inspection, or Warehouse sample operation. It
does not modify the manifest, capability ledger, oracle registry, acceptance
state, historical wave packages, or outer qualification wrapper.
