# Behavior Analytics three-broker dynamic-control qualification

This package retains current-Thor runtime proof for the VSS 3.2.1 advertised
Kafka, Redis Streams, and MQTT dynamic-configuration and dynamic-calibration
capability. Each backend used its own isolated six-channel namespace and a
disposable released Behavior Analytics container.

For every backend the harness observed the startup `request-config`, returned
the namespaced bootstrap snapshot, sent a direct update that changed
`behaviorMaxPoints` from 200 to 3, received a successful acknowledgement, and
waited until main plus both workers applied the atomic checkpoint. It then sent
a versioned Cartesian calibration update and waited for all three live
calibration instances to reload it. Finally it published 300 frames from
NVIDIA's compact repository fixture. Every backend returned enhanced frames and
behaviors across all three cameras; every enhanced frame contained FOV and ROI
metrics, and the maximum behavior trajectory length was exactly three. This
proves the revisions affected subsequent processing rather than merely being
acknowledged.

Verify the retained evidence without changing runtime state:

```bash
PYTHONPATH=services/analytics/behavior-analytics/src python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-broker-control-runtime-successor/verifier.py check
pytest -q deploy/docker/thor-local/qualification/behavior-analytics-broker-control-runtime-successor/tests
```

The harness deletes only its explicit Kafka topics and Redis streams. MQTT uses
a disposable no-persistence broker and non-retained messages. All disposable
containers exited zero and were removed; the two normal Behavior Analytics
services were never stopped. This proof does not claim every output family on
all three sink backends, 3D/MV3DT modes, multi-replica fan-out, or disk-full
injection.
