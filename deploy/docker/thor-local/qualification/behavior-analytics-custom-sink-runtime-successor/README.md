# Behavior Analytics custom Sink runtime successor

This package qualifies exact Metadata500 capability index 210, `customization.behavior.sink-extension`, against the released VSS 3.2.1 arm64 Behavior Analytics image on Thor.

`JsonlFileSink` is a minimal concrete subclass of NVIDIA's documented `Sink` interface. It implements batch `write`, single-message `write_msg`, and idempotent `close`; routes records by destination key; and preserves opaque bytes, extracted keys, string/binary headers, JSON serialization, and protobuf serialization without a network dependency.

The probe mounts the implementation read-only into the released image and exercises it there. It produced three event records and one `nv.Incident` record across two local destinations. The disposable container exited zero without OOM/restart, was removed, and both normal Behavior Analytics containers remained running.

This is a qualified extension implementation, not a claim that `file` is an NVIDIA built-in `sinkType`. An application can construct `JsonlFileSink` directly or add an explicit branch to `get_sink`; the tracked upstream factory remains limited to Kafka, Redis Stream, and MQTT.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-custom-sink-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/behavior-analytics-custom-sink-runtime-successor/tests/test_receipt.py
```
