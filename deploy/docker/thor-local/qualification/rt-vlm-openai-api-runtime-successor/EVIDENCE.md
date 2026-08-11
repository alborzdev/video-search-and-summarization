# Evidence

- Exact candidate rows: official indices 347, 348, 349, 350, 353, and 354.
- Runtime surface: direct local RT-VLM OpenAPI and REST API on loopback port 8018.
- Text oracle: one deterministic non-stream response and token SSE reconstruction.
- Multimodal oracle: ordered blue/green/red evidence plus a prior-turn-dependent green follow-up.
- File API: exact create/list/get/content/delete and post-delete unavailability.
- Operations: live/ready, metadata, version, manifest, model inventory, and Prometheus metrics.
- Cleanup/policy: exact catalog and asset-stat restoration; no Agent, stream, lifecycle, Warehouse, prompt, semantic text, or raw ID retention.

The schema-valid sanitized live result is retained as `runtime-receipt.json` after acknowledged execution.
