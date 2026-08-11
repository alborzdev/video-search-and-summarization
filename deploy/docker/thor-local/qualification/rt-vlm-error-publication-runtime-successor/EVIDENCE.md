# Evidence

The retained Thor run passed in 10.810167 seconds with zero HTTP, model, Agent,
asset, and stream requests. The exact live RT-VLM source used its bounded sender
thread and production publication method to emit one schema-valid Kafka error
record with the required `message_type=error` header. The same method, with the
supported Redis backend switch enabled, emitted one equivalent schema-valid
Redis Pub/Sub message through Thor's private Docker host gateway.

RT-VLM, Kafka, and Redis retained their exact pinned image identities, remained
healthy, and reported zero restarts and no OOM events. Cleanup proved the owned
Kafka topic absent, the ephemeral Redis channel had no persistent key or
subscriber, and both sender threads stopped.

No generated topic or channel name, raw payload, credential, prompt, session,
request identifier, semantic output, Warehouse sample data, or VSS Agent call is
retained.
