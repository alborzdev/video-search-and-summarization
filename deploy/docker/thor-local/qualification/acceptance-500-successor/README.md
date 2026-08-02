# Acceptance 500 successor

This package is an isolated static projection of the Thor-local acceptance
inventory for the 500-capability ledger successor. It changes exactly eight
existing feature coverage records by appending one already-defined scenario ID
to each `scenario_ids` array. It does not modify the live acceptance inventory,
manifest, capability ledger, oracle registry, verifier, wrapper, or runtime.

The exact additions are:

- `rt-cv-2d` → `official-capability-contracts`;
- `video-summarization-live` → `mcp-tool-operation-matrix`;
- `search-scale` → `official-capability-contracts`;
- `alert-notifications-slack` → `openclaw-workflows`;
- `rt-vlm-media` → `rest-api-operation-matrix`;
- `rt-vlm-models` → `official-capability-contracts`;
- `rt-vlm-performance-observability` → `official-capability-contracts`; and
- `audio-understanding` → `core-agent-workflows`.

No scenario, blocker, record, executor, policy, API surface, skill coverage,
disposition, count, digest, or ordering is added or changed. Each new ID is
appended to preserve existing order. The compiler mirrors the two relevant
locked verifier contracts: feature coverage must include the union of all
capability scenario IDs, and every feature coverage record must retain valid
scenario/blocker assignments and exact advertised-item counts and fingerprints.

## Results and boundary

The live inventory has exactly eight coverage gaps against the 500-row ledger.
The projection has zero. The nine family status aggregate differences recorded
by the Ledger-500 proof remain separate and unchanged, so `live_merge_ready`
remains false. This artifact removes only the acceptance coverage category; it
does not claim that any capability passed or that family aggregate fields are
ready to merge.

Runtime execution remains disabled. The projection adds no evidence, runtime
state, activation, network action, cloud inference, model operation, Docker
operation, host inspection, or Warehouse sample dependency. Existing custom
data Warehouse planning records are preserved byte-for-byte in their sections.

The projected inventory and both schemas are deterministic. The inventory
schema fixes every unchanged section and all 55 feature records exactly. The
proof binds all inputs, verifier sources, the final 500-row ledger projection,
the eight JSON pointers, preservation hashes, zero remaining acceptance gaps,
and the separate nine-row family blocker list.

## Check

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/acceptance-500-successor/compiler.py \
  --check

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/acceptance-500-successor/tests/test_compiler.py

ruff check \
  deploy/docker/thor-local/qualification/acceptance-500-successor/compiler.py \
  deploy/docker/thor-local/qualification/acceptance-500-successor/tests/test_compiler.py
```

The compiler performs bounded, raw-hash-locked, non-symlink repository reads
only. `--write` replaces only the four generated files in this package through
same-directory regular temporary files.
