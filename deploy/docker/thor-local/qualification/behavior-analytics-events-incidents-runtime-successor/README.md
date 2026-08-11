# Behavior Analytics events-and-incidents runtime successor

This package qualifies exact Metadata500 capability index 206, `runtime.behavior.events-incidents`, against the released VSS 3.2.1 arm64 Behavior Analytics image on Thor.

The evidence is deliberately composite because NVIDIA's tracked 2D fixture exercises three violation families but does not enable FOV-count incidents by default. The source-locked base 2D run provides 121 decoded ROI/tripwire events in all four directional forms and 24,924 decoded proximity, restricted-area, and confined-area incidents. A supplemental isolated `Analytics2DApp` run enables FOV-count detection on the same tracked fixture, publishes 300 Kafka `nv.Frame` protobufs, and decodes 18 `FOV Count Violation` incidents with sensor IDs, contributing object IDs, and valid time bounds.

The FOV incidents were active when captured, so this package claims detection and incident aggregation but does not claim that their expiry/completion lifecycle was observed. The disposable container exited zero without OOM or restart; its qualification topics were removed; and both normal Behavior Analytics containers stayed running. The 100 GB Warehouse sample bundle was not downloaded or referenced.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-events-incidents-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/behavior-analytics-events-incidents-runtime-successor/tests/test_receipt.py
```
