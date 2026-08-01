# MV3DT advertised-entry oracles

This isolated package supplies the missing admission and candidate-evidence validation layer for exactly four advertised MV3DT entries:

1. per-camera RT-DETR;
2. MV3DT BEV fusion;
3. BodyPose3DNet;
4. four-camera calibrated multiview tracking.

It does not deploy MV3DT and does not duplicate `thor-warehouse-mv3dt.sh`. The default action only verifies digest-locked repository contracts and prints an inert plan:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/mv3dt-entry-oracles/executor.py
```

That plan admits exactly `Camera`, `Camera_01`, `Camera_02`, and `Camera_03` from a custom operator dataset. The NVIDIA Warehouse sample dataset remains excluded. The plan reuses and raw-locks:

- `validate-warehouse-mv3dt-input.py` for custom media, calibration, model, synchronization, camInfo, and top-view admission;
- `thor-warehouse-mv3dt.sh` for the existing Thor preparation/preflight/qualification boundary;
- `generate_cam_info_configs.py` and `generate_pub_sub_configs.py` for offline camInfo and FOV-neighbor topology generation.

The package invokes none of them. It has no subprocess, Docker, network, lifecycle, model-load, download, credential, or write path.

## Candidate evidence validation

`evidence.schema.json` is the strict receipt contract for a separately authorized future run. It requires all four oracle records in fixed order and binds them to one exact-four admission and one cleanup receipt. The semantic validator additionally requires:

- nonempty `mdx-raw` detections from every admitted camera;
- `mdx-bev` fused tracks tied back to observed per-camera track IDs, with aggregate coverage of all four cameras;
- distinct, time-ordered BodyPose3DNet model-loaded and inference-used captures bound to the admitted ONNX hash;
- ordered cross-camera continuity transitions tied to fused global IDs, admitted directed topology edges, and all four cameras;
- one connected, self-subscription-free offline topology;
- globally unique, in-run capture artifacts;
- cleanup of exactly the namespace-owned streams and outputs, without touching preexisting resources.

No passing receipt is checked in. To validate an external candidate receipt read-only:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/mv3dt-entry-oracles/executor.py \
  validate-evidence --receipt /absolute/outside-repo/mv3dt-candidate-receipt.json
```

Structural and semantic validation returns `observed_not_admitted`. It never edits the official manifest, capabilities, advertised-entry plan, or runtime evidence.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  -p no:cacheprovider \
  deploy/docker/thor-local/qualification/mv3dt-entry-oracles/tests
```

The tests use only synthetic in-memory or temporary schema documents. They do not represent runtime receipts and do not start MV3DT.
