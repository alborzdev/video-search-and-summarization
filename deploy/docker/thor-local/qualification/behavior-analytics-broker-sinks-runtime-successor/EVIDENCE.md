# Evidence

- Released runtime image: `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1`, exact arm64 image ID retained.
- Sink factory results: `SinkKafka`, `SinkRedisStream`, and `SinkMQTT`.
- Output families per sink: frames, behaviors, events, incidents, anomalies, cluster, and space-utilization.
- Route coverage: 21 of 21, with exactly one observed record per route.
- Payload evidence: exact byte count and SHA-256 plus successful protobuf decode and semantic identity for every family.
- Transport evidence: exact destination, extracted message key, and family/backend headers for every route.
- Brokers: healthy local Kafka 8.2.0, healthy local Redis 8.6.2, and disposable Mosquitto 2.0; exact image IDs retained.
- Exit integrity: all three released-image probes and Mosquitto exited zero without OOM or restart.
- Cleanup: namespaced Kafka topics and Redis streams are absent; the disposable MQTT broker and all probe containers are absent.
- Preservation: both normal Behavior Analytics containers remained running with zero restarts and no OOM.

The protobuf messages are deterministic schema-real representatives of each
advertised output family. This proves the built-in sink matrix and delivery
contract. Generation/quality of anomalies, clusters, and space metrics is
qualified by separate feature evidence where applicable and is not inferred
from this transport probe. No VSS Agent generation, external request, VIOS or
RT-CV mutation, image download, or 100 GB Warehouse sample occurred.
