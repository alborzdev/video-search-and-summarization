# Behavior Analytics 2D runtime qualification

This package retains the Thor runtime proof for the VSS 3.2.1 Behavior Analytics
2D pipeline. It uses NVIDIA's compact repository integration replay (29.7 MB),
not the excluded 100 GB Warehouse sample bundle.

The qualification ran the released `vss-behavior-analytics:3.2.1` arm64 image in
an isolated disposable consumer group and six qualification-only Kafka topics.
The replay published 20,000 frames containing 171,436 objects for three cameras.
`inspect_topics.py` decoded the real output protobufs and measured behavior,
enhanced-frame, event, and incident semantics. Both disposable containers exited
zero without OOM or restart; their topics and containers were then removed. The
two normal Behavior Analytics containers were never stopped and remain running.

Verify the retained, source-locked evidence without changing runtime state:

```bash
python3 deploy/docker/thor-local/qualification/behavior-analytics-2d-runtime-successor/verifier.py check
pytest -q deploy/docker/thor-local/qualification/behavior-analytics-2d-runtime-successor/tests
```

This proof is intentionally limited to Kafka-backed `warehouse_2d` behavior. It
does not claim 3D/MV3DT, Redis/MQTT, dynamic configuration/calibration, 3D space
utilization, or custom-sink coverage.
