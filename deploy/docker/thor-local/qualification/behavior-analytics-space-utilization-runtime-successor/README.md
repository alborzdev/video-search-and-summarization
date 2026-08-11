# Behavior Analytics space-utilization runtime successor

This package qualifies exact Metadata500 capability index 209, `runtime.behavior.space-utilization`, against the released VSS 3.2.1 arm64 Behavior Analytics image on Thor. It runs the real three-worker `Analytics3DApp` with Cartesian calibration and sends 90 Kafka `nv.Frame` protobufs from NVIDIA's tracked 36 MB integration fixture.

The original fixture contains no pallet/box targets, so the probe deterministically relabels and positions one existing 3D object per non-empty frame at a known in-zone pallet coordinate already present in NVIDIA's tracked sample data. This creates a bounded scene in `buffer_zone_3` without modifying source assets. It also explicitly translates the fixture's legacy singular `bbox3d.embedding` JSON key to the released schema's `embeddings` key in memory.

Nine outputs covered all three calibrated buffer zones. Runtime evidence includes positive occupied, free, total, utilization ratio, extra-pallet capacity, and utilizable-free-space values; populated free/utilizable layouts; and arithmetic consistency within two-decimal output rounding.

The 100 GB Warehouse sample bundle was not downloaded or referenced. This package does not claim a physical multi-camera scene, a 3D detector/MV3DT runtime, or a performance envelope.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-space-utilization-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/behavior-analytics-space-utilization-runtime-successor/tests/test_receipt.py
```
