# Thor Alert non-blocking multithreaded runtime qualification

This package qualifies official capability row 327, `non-blocking
multithreaded execution`, against the current Thor-local VSS 3.2.1 Alert
Bridge image.

The harness starts one isolated Alert Bridge container on loopback ports and
uses uniquely owned Kafka topics, Redis prompt keys, and Elasticsearch
indices. Six protobuf incidents are published to a one-worker ingestion
configuration with async dispatch enabled and three dispatch threads. A
bounded local OpenAI-compatible fixture deliberately holds candidate 0 for
four seconds while the other five calls take 0.8 seconds each.

Passing requires all six candidates to enter the async dispatch pipeline
before the slow call completes, at least three VLM calls to overlap, every
fast candidate to complete ahead of candidate 0, and every candidate to retain
its own media URL, category mapping, JSON-parser verdict/reasoning, persisted
document, and per-sensor terminal Prometheus observations. Inline fallback is
forbidden.

The fixture never leaves loopback and does not make a semantic model-quality
claim; model semantics are qualified by the separate real-Cosmos Alert
receipts. The 100 GB warehouse sample and VSS Agent `/generate` are not used.

Run the live qualification:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 harness.py \
  --acknowledgement I_AUTHORIZE_OWNED_ALERT_CONCURRENCY_QUALIFICATION \
  --run-id <unique-run-id> \
  --output runtime-receipt.json
```

Verify retained evidence without changing runtime state:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 verify.py
```
