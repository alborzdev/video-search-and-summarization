# Advertised-entry executor 74-row successor

This package rebases the historical Waves 1–7 advertised-entry executor
inventory from its former 87-row denominator onto the current 74-row gap plan.
It contains the deterministic Phase 1 inventory compiler and the Phase 2
guarded dispatcher for all 71 retained candidates.

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

## Phase 2 dispatch

Every candidate row has:

```text
executor: direct_historical_adapter
dispatch_status: implemented_phase_2
runtime_evidence: []
can_mark_passed_current: false
```

The dispatcher calls the retained adapter directly: Wave 1 with no arguments,
Wave 2 with the advertised literal, Wave 3 with the locked historical case,
Waves 4–5 with no arguments and a three-value return, Wave 6 with no arguments
and a four-value return, and Wave 7 through `_observe_case`. It never calls a
historical executor's `execute()` or `main()`.

Every selected case runs twice. The checked receipt records identical canonical
output hashes, source locks before and after each call, and effect traces. The
default selection is the exact 71-row candidate set. Empty, duplicate, blocker,
migrated, and unknown selections fail before historical modules are loaded.

Historical Wave 1–7 inventories and executors are digest-locked inputs and are
not rewritten. This avoids invalidating Wave 8 and later qualification packages
that retain those historical hashes.

## Validate

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor/executor.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor/tests
```

The compiler rejects duplicate JSON keys, non-finite JSON numbers, unsafe or
symlinked repository and package paths, oversized or changing files,
source-lock drift, schema drift, denominator drift, any current-plan pointer
whose locked manifest literal differs, migration identity drift, and any live
promotion of a current gap identity.

## Integrity boundary

This is an in-process integrity guard, not an operating-system sandbox. Module
source is read once through descriptor-anchored `openat` traversal with
`O_NOFOLLOW`, identity checks, size bounds, and exact SHA-256 locks. Historical
modules use an explicit builtins allowlist, preloaded exact imports, and an
unregistered namespace. Nested compilation is limited to exact source paths,
source digests, AST-shape digests, and registered code objects. Legacy readers
are replaced with a selected-case capability reader.

During adapter calls, general file opens and mutations, temporary files,
subprocess/fork/exec/spawn, threads, DNS/network/server APIs, and direct sockets
are denied. The only socket exception is the thread-local AF_UNIX stream
socketpair used by Python's asyncio event-loop bootstrap; the checked full run
records three such bootstraps and zero forbidden-effect attempts. This package
does not claim OS-level credential or host confinement. It performs no
Warehouse sample-bundle action and does not promote any current gap row.
