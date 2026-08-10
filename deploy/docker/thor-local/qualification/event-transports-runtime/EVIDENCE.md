# Retained evidence

- Target: NVIDIA VSS 3.2.1 on arm64 Thor.
- Captured: 2026-08-10 through local host-network Kafka and Redis brokers.
- Receipt SHA-256: `d941aa26df52b5f4e0c3a5505ef92ef319785d060d19267db54fdd221c3000d7`.
- Fixture contract SHA-256: `2229e2ff89a22fe0454bab8028d5d3764d5d21908fc2e9c742e6e208a29ef043`.
- Kafka official evidence SHA-256: `c17aa7a3747f60498e3f5ede7897fae415ddabec2fe1cfa377c1e572cb41f192`.
- Redis official evidence SHA-256: `ddd6ee935c5a8da3d231d226d9695091ba90d28e9e094335e82137ced124a2e6`.

Kafka used `AlertSubmissionService.submit_nvschema_alert_protobuf` and
`KafkaMessageBroker.get_producer` from the mounted NVIDIA source. One owned
`nv.Behavior` record round-tripped with the exact key and semantic fields. The
invalid protobuf adjacent negative returned `invalid_payload`/400 and emitted
no record.

Redis used the mounted NVIDIA `SinkRedisStream` and `SourceRedisStream` classes.
The valid envelope preserved key, value, headers, and entry-ID timestamp and
was acknowledged. The malformed-header adjacent negative raised
`JSONDecodeError` before acknowledgement and was retained pending until exact
cleanup.

The run validated the distinct advertised 18-topic Kafka and 16-stream Redis
tables. Its exact topic/group/stream/container resources were absent afterward,
the non-owned Kafka topic and Redis key name sets matched pre-state, and both
brokers remained healthy. No credentials, message payloads, external requests,
Warehouse data, VSS Agent calls, or VIOS/RT-CV mutations are retained.
