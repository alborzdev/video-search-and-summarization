# SpatialAI utilities staged runtime authority

This directory is a non-promoting successor package for
`manifest-entry.spatial-ai-utils.00` through `.06`. It is intentionally not a
canonical parity-state change.

Current Thor development evidence:

- focused package suite: `43 passed`;
- `01` 3D/2D geometry: pass, 2 positives + 5 adjacent cases, 9 literal product
  calls;
- `04` HOTA/CLEAR/Identity/Count: pass, 2 positives + 5 adjacent cases, 16
  literal product calls;
- `05` NVSchema conversion: pass, 2 positives + 5 adjacent cases, 9 literal
  product calls;
- `00`, `02`, `03`, and `06`: capability-local dependency/ABI preflight
  blockers on the current default Python; their workloads are staged but no
  runtime success is claimed;
- `07` AWS/GCS: excluded, unchanged, and not contacted.

The all-row development run returns `partial` while preserving the three
independent passing rows. Instrumented fail-closed guards report zero network,
Docker, service, model, download, Warehouse, product-subprocess, and filesystem
escape attempts. The receipt is development evidence only because the checkout
is dirty and current canonical oracles have not yet been projected to
executor-ready bindings.

The closed result schema and semantic validator reject forged bindings,
promotion candidates, environment claims, determinism and cleanup claims,
row/aggregate counters, action IDs, function-call maps, and observations.
Regression tests also prove that zero-product-call adapters cannot pass,
sibling writes are denied and cleaned up, and non-target platform/Python
runtimes fail before workload execution. A combined bypass regression uses
`mkfifo` plus prebound `posix_spawn` and `SocketType` aliases; all attempts are
denied, the FIFO path is absent after cleanup, and no false pass can validate.

No Warehouse sample, cloud provider, model, VSS deployment, container, stream,
index, or service was used or changed.
