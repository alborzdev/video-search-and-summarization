# Behavior Analytics dynamic control runtime qualification

This package retains Thor runtime proof for the VSS 3.2.1 Behavior Analytics
dynamic-configuration and dynamic-calibration contracts. It ran NVIDIA's own
integration drivers against the released arm64 container on an isolated Kafka
topic, then added narrow probes for every calibration implementation, the
immutable existing-type boundary, and the 15-second disk-baseline fallback.

All 24 official dynamic-configuration scenarios and all seven official
dynamic-calibration scenarios passed. The real container exercised `upsert`,
`upsert-all`, `ack`, `request-config`, and `delete`; all three acknowledgement
statuses; filtered partial updates; invalid-message rejection; atomic file
landing and watchdog application; stale calibration rejection; and all three
calibration types. Every disposable container exited zero without OOM or
restart, and every qualification topic and container was removed afterward.
The two normal Behavior Analytics containers were never stopped.

Verify the source-locked receipt without changing runtime state:

```bash
python3 deploy/docker/thor-local/qualification/behavior-analytics-dynamic-control-runtime-successor/verifier.py check
pytest -q deploy/docker/thor-local/qualification/behavior-analytics-dynamic-control-runtime-successor/tests
```

The wrapper changes only log-query reliability: it appends the missing UTC `Z`
to the upstream driver's `docker logs --since` timestamp and bounds the same
container log. Scenario assertions remain NVIDIA's. The 143-message topic
summary contains deliberate replays from validation attempts and is retained as
transport corroboration, not as a count of the 31 official scenarios.

This proof is Kafka-only. It does not claim Redis/MQTT control parity, output
sink parity, multi-replica fan-out, disk-full injection, or the full multi-stage
Behavior Analytics pipeline capability.
