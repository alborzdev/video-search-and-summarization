# SpatialAI utilities runtime-evidence successor

This staged producer covers exactly the seven provider-free
`spatial-ai-utils` entries `00` through `06`. Entry `07`, AWS/GCS
validation, is deliberately excluded and is verified to remain
`external_optional/not_applicable` with an `external_boundary_unexecuted`
oracle. The producer never uses an NVIDIA Warehouse sample or any other
downloaded dataset.

The default command is an inert plan:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/executor.py
```

Execution is capability-local. `--select` accepts `00` through `06` or a full
capability ID and may be repeated. A missing or ABI-incompatible dependency
blocks only its own row; other selected rows continue and retain independent
results. Both planning and execution fail closed unless the runtime is Linux
on AArch64 with Python 3.12, matching the contract. The checked-in offline
environment supplies the complete dependency set for all seven provider-free
rows. For a default-environment development check, select only rows whose
dependencies are already present, for example:

```bash
output="$(mktemp -u /tmp/spatial-ai-runtime.XXXXXX.json)"
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/executor.py \
  --execute --select 01 --select 04 --select 05 \
  --allow-dirty-development \
  --acknowledge I_ACKNOWLEDGE_OFFLINE_SPATIAL_AI_UTILS_RUNTIME_EVIDENCE \
  --output "$output"
```

`mktemp -u` is shown only to choose an absent leaf in an existing safe
directory. The executor itself opens every parent with `openat` and
`O_NOFOLLOW`, creates the leaf once with `O_EXCL`, sets mode `0600`, and
fsyncs it. It refuses alternate contract files.

## Exact workloads

Every selected, ready row has seven target actions and seven requests: two
independent positive executions plus five named adjacent cases. Literal calls
from the executor into imported product functions are counted separately by
function name and bound into each result.

- `00`: parse and apply a three-camera reassignment, create two overlapping
  groups, create two capacity-bounded clusters, and run both in-memory and
  file-backed group-origin calculation. Both generated groups must contain
  exactly two cameras and cover all three source IDs; both clusters must be
  nonempty, capacity-bounded, and assign every source camera exactly once.
  Origins and dimensions must be finite, nonzero, and identical for every
  member of a group. Calls implemented by `core.cameras.bev` are recorded under
  exact `bev.*` product identities before five strict negatives.
- `01`: generate 9-DoF corners, directly project their points successfully,
  project visible/offscreen boxes, and run the NVSchema BEV-object wrapper on
  both boxes while proving that only the visible object survives and the input
  is immutable. The source-locked projection CLI `main()` is also executed
  in-process twice against owned JSONL/calibration files; no subprocess is
  spawned. Five legacy-shape, calibration, scalar, and transform negatives
  remain.
- `02`: directly execute the image and BEV renderers and the two-camera
  composite renderer twice, asserting exact dimensions, pixels, and input
  immutability before five transform/image/shape negatives.
- `03`: execute both the direct JSONL evaluator/save path and the production
  per-BEV-sensor orchestration for a perfect fixture. Calls to `accumulate`,
  `calc_ap`, `evaluate_detection`, the per-BEV wrapper, the loader, and the save
  path are counted explicitly. Direct and per-sensor output digests are stored
  separately after normalizing only nondeterministic evaluation time, and the
  locked CLI source proves its confidence-threshold binding. Each prediction
  input includes confidences `0.9` and `0.4`; both the direct loader and the
  counted sensor-split path must retain exactly the `0.9` object at threshold
  `0.5`.
- `04`: execute HOTA, CLEAR, Identity, and Count on a perfect two-frame track
  twice; the five adjacent cases include identity switch, empty tracker, empty
  ground truth, malformed similarities, and missing counts.
- `05`: convert a tiny Sparse4D result containing a non-identity 90-degree yaw
  quaternion with the product's timezone-aware `base_timestamp`, byte-compare
  the two outputs, assert the nonzero Euler rotation, and load the emitted
  NVSchema 4.0 JSONL through the strict `gt_json_aicity` semantic path. The
  flattened identity, type, confidence, location, scale, and rotation plus raw
  top-level/bbox confidence are exact assertions. Negatives cover class,
  envelope, coordinates, output format, and frame token.
- `06`: generate four colored PNG frames, verify numeric ordering, encode a
  downsampled MP4, and decode it both fully and with `frame_skip=2`. The kept
  pixel digests must equal source indices 0 and 2 from the full decode, proving
  nontrivial skip behavior. Decoded dimensions must equal source dimensions
  divided by two, and decoded mean/dominant BGR values must match all four
  source colors within a locked codec tolerance. Five empty/missing/invalid
  media cases remain.

The product-execution section has a hard 900-second `SIGALRM` deadline. An
install-once, active-execution-gated Python audit hook denies socket creation,
connection and resolution, process spawn/exec/fork events, model or Warehouse
reads, and filesystem mutations outside the active owned namespace—even
through aliases captured before execution. Explicit wrappers also cover socket
pairs, `SocketType`, every available `os` spawn/exec/fork entry point,
`os.system`/`os.popen`, `mkfifo`, and `mknod`; the latter APIs do not emit a
usable audit event on this target. Attempt counters are retained and any
nonzero count fails execution. There is no credential or cloud-provider path.

## Filesystem and cleanup

Product I/O is confined to one `mkdtemp` root under `/tmp`, with one absent
capability-owned namespace at a time. Each namespace is removed immediately
after its row completes. The complete temporary root is inventoried before and
after every row, including sibling names and file hashes. An adjacent sentinel
and the complete Git porcelain status are compared before and after execution;
the temporary root is removed in `finally`.

## Authority boundary

The producer never mutates the ledger, oracle, manifest, runtime producer, or
external-provider row. Its promotion envelope is derived rather than supplied
by a caller. `receipt_is_runtime_evidence=true` and
`aggregate_is_promotable=true` are emitted only when one execution passes the
exact ordered `00`--`06` set from a clean checkout, both before/after status
hashes are empty, the commit and commit-tree identities are bound, all 49
actions and 122 imported product calls are present, cleanup is exact, and every
external-activity counter is zero. That envelope identifies
`family_id=spatial-ai-utils`, lists exactly `00`--`06` in
`eligible_capability_ids`, records `development_smoke_only=false`, and requires
a separate reviewed metadata integration before canonical state can change.

Plan, partial, subset, blocked, or `--allow-dirty-development` output is always
non-evidence and nonpromotable with an empty eligibility list. The development
flag itself forces that result even if the checkout happens to be clean. The
closed schema encodes both envelopes and the semantic validator independently
re-derives the predicate while binding the live checkout head/tree/status and
current ledger/oracle document hashes. Runtime bindings also record the raw
active metadata selector, selected set and descriptor, resolved selected
ledger/oracle paths and hashes, the selected target commit/version, and proof
that the contract's upstream commit is the checkout's merge-base ancestor.
Selector, descriptor, ledger, and oracle digests are computed from the exact
bytes parsed for validation. The seven SpatialAI rows and the external-provider
boundary must be identical in root and selector-resolved metadata.

Execution receipts may be published only through exclusive mode-`0600`
creation outside the repository (including outside `.git`) through a
non-symlinked parent path. After the bytes are written and reread, the producer
repeats source locks, HEAD/tree/status, root metadata, selected metadata, and
ancestry validation. Any drift removes the new receipt instead of publishing
stale authority.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/tests
```
