# Sparse4D advertised-entry oracles

This isolated package plans and validates future candidate evidence for exactly two advertised Sparse4D entries:

1. Sparse4D multi-camera 3D detection and tracking;
2. shared RT-CV lifecycle, health, and metrics.

It does not deploy Warehouse or Sparse4D. The default command only verifies digest-locked repository inputs and prints an inert plan:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/sparse4d-entry-oracles/executor.py
```

The package reuses, but never invokes, `validate-warehouse-sparse4d-input.py` and the `plan`, `prepare`, `preflight`, and `qualify` stages of `thor-warehouse-sparse4d.sh`. It has no subprocess, Docker, network, lifecycle, model-load, download, credential, or write path. The NVIDIA Warehouse sample bundle is explicitly excluded.

## Admission and evidence boundary

A future receipt must bind an operator-owned custom dataset with exactly `Camera`, `Camera_01`, `Camera_02`, and `Camera_03`, matching calibration, RT-DETR, the exact Sparse4D v2.2 ONNX, and the finite `(900, 11)` anchor. It must also prove:

- the 50 GiB memory, 30 GiB disk, local ARM64 image, idle-port, and idle-GPU preflight gates;
- distinct, time-ordered loaded-before-used events for the admitted RT-DETR and Sparse4D identities;
- nonempty per-camera detections, fused 3D/BEV tracks tied to those detections, and cross-camera correlation covering all four cameras;
- healthy state for every required service, throughput whose frames/duration agree with FPS within 5% or one frame, ordered latency percentiles, resource measurements, and `mdx-bev`/`mdx-behavior` stream observations;
- removal of exactly run-owned stream and output resources without touching preexisting resources.

No passing receipt is checked in. External candidate receipts can be checked read-only:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/sparse4d-entry-oracles/executor.py \
  validate-evidence --receipt /absolute/outside-repo/sparse4d-candidate.json
```

A passing result remains `observed_not_admitted`; this tool never edits any live ledger.

## Current blockers

- Sparse4D v2.2 ONNX and its `(900, 11)` anchor are not staged locally.
- Matching operator-owned four-camera media/calibration are not admitted.
- The reused validator does not independently admit the requested RT-DETR identity.
- Preflight has not passed for a prepared private lane.
- No authorized runtime semantic, health, latency, resource, or exact-cleanup receipt exists.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/sparse4d-entry-oracles/tests
```

Tests use synthetic in-memory or temporary documents only. They are not runtime evidence and do not start any service.
