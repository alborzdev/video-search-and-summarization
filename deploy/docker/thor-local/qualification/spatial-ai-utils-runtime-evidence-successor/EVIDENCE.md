# SpatialAI utilities staged runtime authority

This directory is a runtime-evidence producer for
`manifest-entry.spatial-ai-utils.00` through `.06`. The producer performs no
canonical parity-state change; only an exact clean all-seven pass is marked
eligible for a separate reviewed metadata integration.

Current Thor development evidence:

- focused package suite: `89 passed` after adding fail-closed mode/authority
  discrimination, exact-byte selected-metadata and ancestry bindings, semantic
  root/selected row alignment, and publication TOCTOU defenses;
- `00` calibration/grouping: pass in the cache-only locked ephemeral
  environment, 2 positives + 5 adjacent cases, 17 literal product calls;
- `01` 3D/2D geometry: pass, 2 positives + 5 adjacent cases, 15 literal product
  calls;
- `04` HOTA/CLEAR/Identity/Count: pass, 2 positives + 5 adjacent cases, 16
  literal product calls;
- `05` NVSchema conversion: pass, 2 positives + 5 adjacent cases, 9 literal
  product calls, with a non-identity quaternion producing the expected nonzero
  Euler yaw and an exact strict-loader flattened semantic record;
- `03` detection mAP: pass in the cache-only locked ephemeral environment,
  2 positives + 5 adjacent cases, 37 literal direct/per-BEV product calls,
  including two counted sensor-split calls and exact confidence filtering;
- `02` multiview visualization: pass, 2 positives + 5 adjacent cases, 11
  literal product calls;
- `06` video/frame tools: pass, 2 positives + 5 adjacent cases, 17 literal
  product calls; `frame_skip=2` output equals source indices 0 and 2 from a
  full decode, decoded dimensions prove the 2x downsample, codec-tolerant BGR
  means/dominant channels match the source colors, and the committed lazy
  visualization package boundary removes both rows' former unrelated Shapely
  preflight dependency;
- `07` AWS/GCS: excluded, unchanged, and not contacted.

The seven provider-free rows account for 122 literal product calls per
all-capability run. The current default Python still blocks `00` and `03` on
missing optional dependencies; the checked offline environment supplies the
locked complete dependency set used for their passing executions.

Rows `01`, `04`, and `05` are now bound to their current canonical
`executor_ready` oracle rows; all seven canonical rows remain
`open_unexecuted` with empty evidence. The producer is fail-closed and never
performs promotion itself: a clean, non-development all-seven pass is runtime
evidence eligible for separate review, while plan, partial, subset, blocked,
and dirty-development results are non-evidence with empty eligibility. No
canonical mutation may occur before an eligible receipt is captured,
independently validated, and reviewed.
The default-Python all-row development replay returns `partial` with exact
passes `01`, `02`, `04`, `05`, and `06`, plus exact capability-local blockers
`00` and `03`. Instrumented guards report zero network, Docker, service, model,
download, Warehouse, product-subprocess, and filesystem-escape attempts.

The closed result schema and semantic validator reject forged checkout
head/tree/status, canonical and selected metadata document hashes, selected
target commit/version, target ancestry, promotion eligibility, environment
claims, determinism and cleanup claims, row/aggregate counters, action IDs,
function-call maps, and observations.
Regression tests also prove that zero-product-call adapters cannot pass,
sibling writes are denied and cleaned up, and non-target platform/Python
runtimes fail before workload execution. A combined bypass regression uses
`mkfifo` plus prebound `posix_spawn` and `SocketType` aliases; all attempts are
denied, the FIFO path is absent after cleanup, and no false pass can validate.

The schema now has disjoint plan/runtime shapes with exact capability identity
and order. An authority envelope additionally requires seven ready preflights
and complete per-row action, function-call, negative, determinism, binding, and
cleanup proof. Publication refuses every repository or `.git` destination and
every symlinked output parent, and deletes an exclusively-created receipt if
the post-write checkout/metadata revalidation differs.

No Warehouse sample, cloud provider, model, VSS deployment, container, stream,
index, or service was used or changed.
