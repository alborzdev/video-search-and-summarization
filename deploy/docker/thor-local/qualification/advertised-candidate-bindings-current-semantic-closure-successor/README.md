# Current semantic-closure advertised candidate bindings

This additive, inert crosswalk connects the same ten exact advertised-entry
rows covered by Wave 3 to the strongest current Base, LVS, Search, and UI
candidate packages. It does not edit the authoritative candidate mapping.

The result deliberately separates three concepts:

- `implementation_state=concrete` means candidate code directly exercises the
  advertised behavior. It does **not** mean the code ran or passed on Thor.
- `implementation_state=partial` means a semantic gap or missing composition
  adapter remains even before a live run.
- `executor_ready=false` means the package is not eligible for canonical
  execution/admission. This remains false for every row.

The exact split is three concrete implementations (the two Base rows and the
UI row), seven partial implementations (two LVS and five Search rows), and
zero executor-ready, admitted, executable, evidenced, or promoted rows. Base
still lacks stored Agent-media digest readback. UI still lacks the canonical
bound review. LVS retains advertised per-source event attribution and exact
focus negatives. Four Search semantic executors still need a concrete adapter
from the new dynamic fixture handoff, while Search archive management still
lacks RTSP lifecycle coverage.

Every direct classification input is byte-locked. The compiler also verifies
the nested source/implementation locks declared by all six source packages,
so a transitive implementation change fails closed. Warehouse remains
excluded.

The authoritative mapping also remains exact-zero for required cloud
inference and Warehouse-sample dependencies across all ten rows. This is a
static mapping property, not a substitute for later local model/runtime
evidence.

Run the inert checks from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-candidate-bindings-current-semantic-closure-successor/compiler.py \
  check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/advertised-candidate-bindings-current-semantic-closure-successor/tests
```

`compile` writes deterministic JSON only to stdout. There is no network,
Docker, browser, service, credential, download, mutation, or live execution
mode.
