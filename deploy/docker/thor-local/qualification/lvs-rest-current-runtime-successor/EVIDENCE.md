# Sealed LVS REST evidence

- Date: 2026-08-11
- Target: NVIDIA VSS 3.2.1 Thor-local branch
- Capability: `api.core.lvs-17`
- Result: `passed_current`
- Exact deployed operation count: 18 (17 documented plus one Thor extension)
- Positive operation results: 18/18
- Adjacent negatives: 6/6
- Bounded requests/actions: 41/4 (limits 69/69)
- Runtime duration: 58.737 seconds (limit 900)
- Warehouse sample: excluded
- VSS Agent `/generate` calls: zero
- VIOS/RT-CV stream mutations: zero

Runtime observations:

- Recorded-video upload, exact info readback, VLM captions, `/v1/summarize`,
  `/summarize`, graph-backed `/v1/chat/completions`, and deletion passed.
- Q&A changed the warm authenticated Neo4j state from 4 nodes/0
  relationships to 14 nodes/15 relationships, with 10 asset-owned nodes, then
  exact deletion restored 4/0 and proved the asset graph absent.
- A private synthetic RTSP stream produced one or more caption documents in
  local Elasticsearch and `/v1/stream_summarize` returned a nonempty local
  summary.
- LVS, RT-VLM, Elasticsearch, Neo4j, Kafka, and Logstash retained exact
  container/image/start/health/restart identities across the transaction.
- File catalog, graph baseline, live index, camera, caption request, fixture,
  publisher, and relay were restored or removed exactly.

The canonical receipt is `runtime-receipt.json`; `verify.py` validates its
schema, source locks, bounds, exact operation set, cleanup, and retained-data
policy without contacting a runtime service.
