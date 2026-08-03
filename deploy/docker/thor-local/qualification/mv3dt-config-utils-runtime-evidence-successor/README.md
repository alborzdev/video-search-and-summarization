# MV3DT config-utils runtime evidence successor

This isolated package produces current-Thor evidence for exactly two
non-Compose repository tools:

- `tool.mv3dt.cam-info-generator`
- `tool.mv3dt.pub-sub-generator`

It does not deploy MV3DT or any Warehouse profile. It imports the two locked
Python sources directly and uses one tiny checked-in two-camera calibration.
There is no network, Docker, service, model, credential, download, or NVIDIA
Warehouse-sample path.

The default action is an inert plan:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/mv3dt-config-utils-runtime-evidence-successor/executor.py
```

A dirty-checkout development execution is always non-promoting and deliberately
omits the exact official receipts:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/mv3dt-config-utils-runtime-evidence-successor/executor.py \
  --execute \
  --allow-dirty-development \
  --oracle-document deploy/docker/thor-local/qualification/metadata-500-current-mv3dt-config-utils-successor/post-state-capability-oracles.json \
  --acknowledge I_ACKNOWLEDGE_OFFLINE_MV3DT_CONFIG_UTILS_RUNTIME_EVIDENCE \
  --output /tmp/mv3dt-config-utils-development.json
```

## Exact workload

Each capability has seven target actions/requests: two independent positive
runs and five named adjacent negatives. The pub/sub adapter also performs three
bounded camInfo fixture-generation supporting actions. The aggregate therefore
has 14 target actions/requests, three supporting actions, and 17 total actions
with no product subprocess. Six additional `_parse_model_args` helper calls
support those actions, so the literal imported source-function invocation count
is 23 (10 camInfo-lane invocations and 13 pub/sub-lane invocations).
The executor wraps all three imported entry points and checks the observed
by-function totals: seven parser, nine camInfo-generator, and seven pub/sub-
generator invocations. The seventh parser call is itself the duplicate-class
target case; the other six are helpers. A hard `SIGALRM` deadline enforces each
oracle's 900-second product-execution ceiling.
Both positive outputs must be byte-identical and match the checked output
digests.

The camInfo lane verifies two finite flattened 3x4 projections and two
per-class height/radius records. Its negatives cover unsafe and duplicate
sensor IDs, an invalid matrix, a duplicate class ID, and a symlinked output.

The pub/sub lane verifies the exact `localhost:1883` publications, two-camera
FOV-neighbor graph, and absence of self-subscriptions. Its negatives cover an
invalid broker, threshold, ROI, empty camera directory, and symlinked output.

Cleanup removes exactly the two oracle-owned namespaces, one at a time, after
capturing their absent pre-state. An adjacent sentinel and the complete Git
porcelain status are compared before and after execution.

## Promotable receipt boundary

A promotable run requires this producer and the executor-ready oracle
projection to be committed, the checkout to be completely clean, an absent
output path outside the repository, and the explicit acknowledgement. Only
then does each aggregate row contain an exact official receipt validated by
the canonical official-capability verifier. Because that canonical receipt
protocol has an exact field set, a separate exact outer
`runtime_evidence_binding` binds the row to capture time, executor, contract,
oracle document/row, action/request counts, deterministic run/output digests,
adjacent-negative digest, and the complete capability-evidence digest. The
aggregate itself never edits a ledger, oracle, manifest, selector, or acceptance
document.

Only the canonical checked-in `contract.json` can execute; alternate or mutated
contracts are rejected before attribution. Receipt publication walks every
parent directory from `/` using `openat` with `O_NOFOLLOW`, then creates the leaf
once with `O_EXCL`, verifies it is regular, writes mode `0600`, and fsyncs it.

## Dependency caveat

The current Thor environment runs the exact semantics, but its installed
packages differ from `requirements.txt`: NumPy 2.5.1, imported OpenCV 4.13.0,
PyYAML 6.0.3, and tqdm 4.68.4 are observed. The upstream declarations are
NumPy 2.2.6, OpenCV 4.12.x, PyYAML 6.0.2, and tqdm 4.67.1. The receipt records
this mismatch and is normative only for observed current-Thor behavior; it does
not claim dependency-pin parity.

## Post-promotion boundary

This producer is immutable evidence authority for the clean staging commit
recorded in the aggregate receipt. After canonical promotion changes the two
current ledger/oracle rows, its pre-state binding intentionally fails closed
with `current oracle row drift`; do not rewrite the producer or its contract to
make a second receipt appear current. Post-promotion verification runs through
the aggregate-aware canonical verifier and the deterministic metadata promotion
compiler instead. The focused producer suite is reproducible at the captured
staging commit recorded by the receipt.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/mv3dt-config-utils-runtime-evidence-successor/tests
```
