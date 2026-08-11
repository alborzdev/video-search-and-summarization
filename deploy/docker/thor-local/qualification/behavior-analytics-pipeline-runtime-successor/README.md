# Complete Behavior Analytics pipeline runtime successor

This package qualifies exact Metadata500 capability index 203, `runtime.behavior.pipeline`, with one released-image `Analytics2DApp` run on Thor.

The probe published 600 Kafka `nv.Frame` protobufs containing 4,417 objects. Every object had a valid bounding box, non-empty tracking ID, high-confidence finite 4-D embedding, and the tracked fixture's spatial coordinate. During the same run it applied a live configuration update (`behaviorMaxPoints` 200 → 3), reloaded Cartesian calibration, transformed coordinates, evaluated ROIs, updated behavior state, and emitted ROI/FOV metrics.

All 600 enhanced frames returned with all 4,417 objects. The service emitted 971 behaviors across five tracked identities and three sensors; every behavior retained a finite 4-D embedding and transformed location, while the live point limit was reflected exactly. Positive ROI and FOV metrics were decoded.

The 4-D vectors are deterministic qualification inputs proving pipeline continuity, not a model-quality or production-dimension claim. The run does not claim 3D/MV3DT or throughput performance and does not use the 100 GB Warehouse sample bundle.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-pipeline-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/behavior-analytics-pipeline-runtime-successor/tests/test_receipt.py
```
