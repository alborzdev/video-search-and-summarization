# Wave-four evidence boundary

## Exact accounting

- Gap-plan entries: 87
- Previously selected candidates: 52 (8 + 21 + 23)
- Entries open before this wave: 35
- Selected here: 5
- Entries left without a candidate executor: 30

The selected literals are `live captions`, `live stream summaries`, `stream
reports`, `caption-backed Q&A`, and `Elasticsearch caption storage`.

## What is observed

The executor verifies exact cross-layer source graphs for:

- explicit agent stream configuration, LVS caption kickoff, sticky RT-VLM
  routing, and RT-VLM Kafka publication;
- timeline-bound stream-summary requests, CA-RAG `summarization_online`, and
  structured/aggregate publication;
- RTSP report routing through LVS and markdown/PDF artifact orchestration;
- CA-RAG-gated, UUID-bound retriever Q&A and answer shaping; and
- RT-VLM stream/chunk identity through Logstash's deterministic
  `default_<streamId>` Elasticsearch mapping and the UUID-based summary read.

Python evidence comes from parsed AST definitions and call/attribute graphs.
The checked YAML is parsed with a loader restricted to its existing `!ENV`
scalar tags. The checked Logstash file is parsed only for eight unique,
digest-locked stream identity/index assignments.

## What is not observed

No service is contacted or started. No caption is inferred, Kafka message is
delivered, Elasticsearch document is indexed/read, summary is generated,
question is answered, or report file is written. Therefore all five source
plan entries remain `open_unexecuted`; none may be promoted in the acceptance,
official-capability, oracle, or runtime-lane ledgers.

The remaining 30 entries include runtime media, browser, scale, 3D/custom-data,
audio/model, offline-metric dependency, and external-system claims. The
Warehouse sample remains excluded while custom-data 3D capability remains in
scope for later runtime qualification.
