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

- `00`: parse and apply a two-camera reassignment, recompute group origin and
  dimensions, then reject malformed/empty moves and unknown strict targets.
- `01`: generate 9-DoF corners and project visible/offscreen boxes, then cover
  legacy shape, calibration, scalar, and transform negatives.
- `02`: render two camera panels plus BEV twice, assert exact dimensions,
  pixels, and input immutability, then exercise five transform/image/shape
  negatives.
- `03`: execute the JSONL loader, production evaluator, and save path for a
  perfect fixture, normalize only nondeterministic evaluation time, and cover
  missing/malformed/timestamp/legacy-shape inputs.
- `04`: execute HOTA, CLEAR, Identity, and Count on a perfect two-frame track
  twice; the five adjacent cases include identity switch, empty tracker, empty
  ground truth, malformed similarities, and missing counts.
- `05`: convert a tiny Sparse4D result with the product's timezone-aware
  `base_timestamp`, byte-compare the two outputs, and load the emitted
  NVSchema 4.0 JSONL. Negatives cover class, envelope, coordinates, output
  format, and frame token.
- `06`: generate four colored PNG frames, verify numeric ordering, encode a
  downsampled MP4, decode it with frame-skip semantics, validate decoded
  pixels, and cover five empty/missing/invalid media cases.

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

This package is staged only. It verifies the current canonical rows and source
locks. Rows `01`, `04`, and `05` are canonically `executor_ready`; rows `00`,
`02`, `03`, and `06` remain `planning_index_only`, and every row remains
`open_unexecuted` with no evidence. Therefore its output always records
`receipt_is_runtime_evidence=false` and
`aggregate_is_promotable=false`, performs no ledger/oracle/manifest mutation,
and lists only successful rows as non-promoting `individual_receipt_candidates`.
A later clean receipt capture, executor-ready projection for the remaining
rows, and canonical promotion step must bind and validate any official
receipts.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/spatial-ai-utils-runtime-evidence-successor/tests
```
