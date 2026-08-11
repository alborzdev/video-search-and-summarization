# Retained evidence

`runtime-receipt.json` is the schema-validated retained result for official
capability rows 370 and 372.

The passed receipt proves:

- the same 2,575,454-byte H.264 fixture completed through HTTP URL and inline
  base64 transports with two finite 768-dimensional chunks each;
- corresponding vectors met cosine >= 0.999999 and maximum absolute
  difference <= 1e-9, while trace attributes retained distinct `http` and
  `data` transport provenance;
- Kafka delivered two parseable `VisionLLM` protobuf embedding records with
  exact `vision_llm` headers and request/chunk-correlated record keys;
- Redis delivered one schema-exact, request-correlated error for an actual
  failed embedding API request without changing persistent key count;
- Kafka and Redis publication spans were children of their originating
  pipeline/API spans, carried correlated request attributes, recorded broker
  acknowledgement facts, and exported the configured Thor-local service name;
- all owned observers stopped, the service and peer container identities were
  preserved, operator-paused workloads remained stopped, and RT-Embed's file,
  asset, stream, model, health, restart, and OOM state returned exactly.

The receipt intentionally excludes raw embeddings, media payloads, URLs,
resource IDs, request IDs, trace/span IDs, Kafka offsets, Redis payloads, and
credentials.
