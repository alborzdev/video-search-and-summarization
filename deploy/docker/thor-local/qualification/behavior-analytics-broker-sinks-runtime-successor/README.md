# Behavior Analytics broker-sink matrix qualification

This package retains current-Thor runtime proof for Metadata500 index 208,
`protocol.behavior.broker-sinks`. The released VSS 3.2.1 Behavior Analytics
image instantiated its real `SinkKafka`, `SinkRedisStream`, and `SinkMQTT`
classes through `get_sink`. Each sink published one schema-real protobuf for
every advertised output family: frames, behaviors, events, incidents,
anomalies, cluster, and space-utilization. That is an exact 7 x 3 matrix of 21
observed broker routes.

The host harness subscribed before publication, decoded each broker payload
with the repository protobuf classes, and checked its destination, message key,
payload hash, family/backend headers, and semantic identity. Kafka used the
existing healthy local broker, Redis Streams used the existing healthy local
Redis, and MQTT used an already-present disposable Mosquitto image. No image
was pulled or built.

Verify the retained evidence without changing runtime state:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-broker-sinks-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/behavior-analytics-broker-sinks-runtime-successor/tests
```

The live probes can be replayed individually with `run_sink_probe.py` and one
of `kafka`, `redisStream`, or `mqtt`. They create only namespaced destinations
and disposable containers, then remove them. The proof covers sink delivery,
not production throughput/HA or the semantic quality of upstream anomaly and
cluster generation. It does not use the excluded Warehouse sample bundle.
