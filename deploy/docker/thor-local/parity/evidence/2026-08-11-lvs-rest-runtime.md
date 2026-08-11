# Thor complete LVS REST runtime qualification

The canonical capability ledger now classifies `api.core.lvs-17` as
`passed_current`, backed by the sealed current-runtime package at:

- `deploy/docker/thor-local/qualification/lvs-rest-current-runtime-successor/runtime-receipt.json`
- `deploy/docker/thor-local/qualification/lvs-rest-current-runtime-successor/verify.py`
- `deploy/docker/thor-local/qualification/lvs-rest-current-runtime-successor/official-runtime-evidence.json`
- `deploy/docker/thor-local/qualification/lvs-rest-current-runtime-successor/canonical-runtime-evidence.json`

The target-bound transaction discovered exactly 18 deployed OpenAPI
operations: all 17 operations documented for VSS 3.2.1 plus Thor's explicit
`GET /files/{file_id}` compatibility extension. Every operation returned the
expected success contract, and six reviewed adjacent-negative contracts also
passed.

The semantic run exercised a generated recorded clip through upload, metadata
readback, VLM caption generation, both summary aliases, authenticated
loopback Neo4j graph ingestion, graph-backed visual Q&A, and deletion. It also
published a private synthetic RTSP stream, observed local RT-VLM caption
delivery through Kafka/Logstash/Elasticsearch, and completed live-stream
summarization.

Cleanup restored the complete file catalog and warm graph counts, proved the
owned graph asset absent, and removed the exact owned camera, caption request,
live index, relay, publisher, and fixture. The six involved runtime identities,
health states, start times, restart counts, and network modes remained exact.

The OpenAPI bearer declaration is retained, but the local LVS application does
not enforce bearer credentials on trusted loopback. External access remains a
host firewall/reverse-proxy responsibility. No VSS Agent `/generate` request,
VIOS/RT-CV sample-stream mutation, Warehouse sample action, raw prompt, raw
semantic output, or credential is retained by this evidence.
