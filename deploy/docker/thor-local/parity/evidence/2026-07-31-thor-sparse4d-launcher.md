# Thor custom-data Sparse4D lane evidence — 2026-07-31

## Scope and decision

The warehouse sample bundle was explicitly excluded. This milestone adds a
sample-free operator-data path for the upstream VSS 3.2.1 Sparse4D feature,
without container lifecycle actions or network downloads.

Authoritative source contracts inspected:

- `warehouse-3d-app/warehouse-3d-app.yml`: Sparse4D perception, v2.2 ONNX and
  kmeans anchor mounts, calibration, Configurator, behavior analytics, and
  optional extended services.
- `blueprint-configurator/blueprint_config.yml`: `AGX-THOR` inherits the
  single-GPU Thor profile and has a seven-stream 3D ceiling.
- `warehouse-3d-app/deepstream/configs/config.yaml`: 900 anchors, synchronized
  multi-sensor preprocessing, v2.2 paths, and calibration/BEV semantics.
- The 3D deployment skill and its warehouse-profile reference: Sparse4D routes
  to `MODE=3d`, Redis/Kafka only, no warehouse agent/LLM/VLM stack.

The lane follows the published four-synchronized-camera use case even though
the hardware ceiling is seven. This avoids claiming an unverified arbitrary
camera-count model contract.

## Implemented evidence

- `scripts/thor-warehouse-sparse4d.sh`
  - read-only default `plan`
  - private snapshot `prepare`
  - exact minimal/extended allowlists
  - image/architecture/port/memory/idleness `preflight`
  - nonexecuting `launch-command` with `--no-build --pull never`
  - read-only runtime `qualify`
- `validate-warehouse-sparse4d-input.py`
  - no source symlinks or excluded sample slug
  - valid self-contained ONNX graph
  - finite `(900, 11)` float NPY anchor
  - four exact synchronized H.264/H.265 videos
  - matching finite 3D calibration matrices, BEV group, correspondences, and
    media attributes
  - required plan-view metadata and decoded PNG structure/content
  - a second full validation of the private copied assets before checksum
    freeze and atomic publication
- `warehouse-sparse4d.compose.yml`
  - Redis protected loopback contract
  - Thor VST codec derivatives and `LD_LIBRARY_PATH` repair
  - offline flags on `perception-3d`
  - offline Redis Logstash derivative with digest-pinned ARM64 base,
    checksum-pinned local gem, and build networking disabled
  - deterministic image names for Compose-build one-shots
  - explicit DCGM exclusion on Jetson
- private 3D VST configuration patch sets `stunurl_list` to the nonempty
  loopback sentinel; an empty list is not used because VST falls back to its
  compiled public STUN server.

## Verification

Run from the repository root:

```text
bash deploy/docker/test-scripts/test-thor-warehouse-sparse4d.sh
```

Result: all 19 focused static checks passed. They cover syntax, safe helper
surface, absence of lifecycle/privileged execution, offline overlay, private
copy preparation, exact 19/31 service graphs, pull/build-free printed command,
synchronization failure, malformed anchor, malformed ONNX, non-finite
calibration, malformed PNG rejection, post-copy revalidation under simulated
source drift, excluded sample slug, staging cleanup, and snapshot-drift
failure.

Additional checks:

```text
ruff check deploy/docker/thor-local/validate-warehouse-sparse4d-input.py \
  deploy/docker/thor-local/render-warehouse-sparse4d-env.py \
  deploy/docker/thor-local/patch-warehouse-sparse4d-offline.py
git diff --check
```

Result: passed.

No containers were started, stopped, pulled, built, or removed. No warehouse
sample data was downloaded.

## Honest qualification state

Static wiring is complete, but runtime state is `not_qualified`:

- `sparse4d_warehouse_v2.2.onnx` is not present locally.
- `_ov_kmeans900_v2.2.npy` is not present locally.
- No operator-owned aligned four-camera dataset and matching calibration was
  available for this run.
- Minimal/extended local image staging and 50 GiB free unified-memory gates
  have not passed together.

The existing exact ARM64 `vss-rt-cv:3.2.1` image is necessary but not
sufficient. The parity goal must not treat this feature as complete until
`preflight` and `qualify` pass on the real custom dataset.
