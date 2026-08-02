# Thor metadata-set selector

This directory adds a static, backward-compatible selection layer without
changing the current parity files or their validators. `selector.json` chooses
one registered immutable descriptor. The checked descriptor binds the complete
current metadata plane: manifest, official ledger and schema, capability-oracle
registry and schema, and acceptance inventory. The selected set remains the
existing 289-capability predecessor.

The staged `thor-vss-3.2.1-metadata-500-staged` set is also registered with the
`validation_only` lifecycle and can be resolved explicitly. It binds the
isolated 500-capability post-state, but it cannot be the selector's default:
default resolution accepts only a `live_ready` descriptor. The staged set
therefore cannot alter live behavior until a reviewed activation receipt,
descriptor lifecycle change, and selector switch are made. The additive v2
oracle validator and authoritative bundle dispatcher already validate it
explicitly without changing that lifecycle.

`resolver.py` validates the selector, descriptor, and every member before it
returns any document. Reads are bounded and file-descriptor-relative with
`O_NOFOLLOW`; duplicate keys, non-finite JSON, unsafe paths, symlinks,
non-regular files, raw-hash drift, schema drift, mixed target/count/ID sets,
oracle/ledger binding drift, policy-derived family aggregate drift, incomplete
or unknown acceptance scenarios, unknown sets, and observable read-time changes
fail closed. Returned documents are deep copies of one fully validated
in-memory snapshot.

To add a future version, add a new `validation_only` immutable descriptor and
its regular files, then add one hash-bound registry row. After its validator and
activation receipt are reviewed, change its lifecycle to `live_ready`, re-lock
the descriptor, and change `selected_set` in the same transaction. The resolver
semantics do not depend on the set ID or the count 289. Do not rewrite
historical descriptors or use symlinks as metadata members.

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/parity/metadata_sets/resolver.py --json

PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/parity/metadata_sets/resolver.py \
  --set thor-vss-3.2.1-metadata-500-staged --json

PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/parity/metadata_sets/tests/test_resolver.py

ruff check \
  deploy/docker/thor-local/parity/metadata_sets/resolver.py \
  deploy/docker/thor-local/parity/metadata_sets/tests/test_resolver.py
```

The resolver performs no network, service, Docker, host, model, GPU, runtime,
or Warehouse actions.
