# LVS semantic runtime closure successor

This additive package closes the LVS semantic observations that can be proven
through current local production APIs without starting or stopping services.
It supplements, and does not replace, the 34-action NAT Agent session
successor. The Warehouse sample is excluded.

The default `plan` command is static and inert. A live run requires a reviewed
manifest, numeric-loopback Agent/LVS/RT-VLM/VST/Elasticsearch/media origins, and the
exact acknowledgement. Environment proxies and redirects are disabled. The
executor performs at most 24 HTTP requests in 1,800 seconds, reserving the
final 300 seconds exclusively for stop/quiescence/deletion cleanup, and never reads
credentials, scans ports, downloads external data, or changes service
lifecycle state. It stops only the attested owned caption stream and deletes
only documents from that stream's proven-empty dedicated Elasticsearch index.

## Newly concrete semantics

An authorized passing run proves:

1. The running NAT `WorkflowBuilder` resolves the exact five advertised LVS
   tools. The new read-only Agent endpoint returns only their fixed public names
   and availability; it does not expose configuration, prompts, schemas, URLs,
   credentials, or arbitrary tool names.
2. The two preprovisioned VST fixtures have the exact timeline durations,
   stored byte counts, and SHA-256 identities declared by the manifest. The
   media URLs must be response-derived and match an explicitly allowed numeric
   loopback origin.
3. LVS is ready and exposes the exact expected build and local model identity.
4. The owned live stream's dedicated `default_<uuid>` Elasticsearch index is
   empty before generation. LVS then accepts caption generation, the exact
   owned collection becomes populated through the Kafka/Logstash path, and
   `/v1/stream_summarize` returns a nonempty CA-RAG result for the exact stream
   and model with no obvious empty-result phrase. Content grounding is not
   claimed by this observation.
5. The complete VST timeline document is digest-identical before and after the
   observations. The owned VST and RT-VLM stream registration is preserved.
6. A `finally` path sends the exact RT-VLM stop request with stream affinity,
   waits for two stable collection counts, deletes all raw, structured, and
   aggregate documents from the pre-empty owned collection, and requires two
   zero-count observations separated by a bounded delay. This cleanup also
   runs after an ambiguous start response or any later oracle failure.

The ownership attestations are important: the stream UUID must be unique to
the run, must equal the contract's UUIDv5 derivation from `run_id`, and must be
preprovisioned exclusively for this run. The manifest explicitly attests that
no concurrent foreign writer owns the dedicated collection, and the collection
must be empty before captioning, so cleanup cannot silently inherit history.

## Remaining honest boundary

Six items remain externally unprovable with the current APIs:

- Semantic correlation of the CA-RAG answer to the delivered event, object,
  and scenario. Exact stream/model affinity and nonempty retrieval are proven,
  but a count-only Elasticsearch observation cannot exclude prompt echo.
- Exact disconnect cancellation/quiescence receipt. The server does exact
  cancel → quiesce → cleanup, but intentionally removes the request before a
  second observer can fetch a terminal receipt.
- Preexisting absence of future report objects. Their exact keys include a
  server-selected completion timestamp, and `/static` has no listing API.
- A complete unrelated NAT Agent state fingerprint. Behavioral session
  isolation is proven by the predecessor, but checkpoints and the two internal
  LVS state stores are not externally enumerable.
- Exact Kafka and Logstash process/image digests. The pre-empty Elasticsearch
  transition proves the live running delivery path, not its container digest.
- The canonical 14-action bound. It cannot contain the predecessor's honest 34
  Agent actions plus this independent 24-request supplement.

Accordingly this package remains nonpromoting:
`executor_ready=false`, `promotion_eligible=false`, and
`canonical_state_advanced=false`.

## Commands

Safe, inert validation:

```bash
python3 deploy/docker/thor-local/qualification/lvs-semantic-runtime-closure-successor/executor.py plan
pytest -q deploy/docker/thor-local/qualification/lvs-semantic-runtime-closure-successor/tests/test_executor.py
```

Future authorized execution:

```bash
python3 deploy/docker/thor-local/qualification/lvs-semantic-runtime-closure-successor/executor.py execute-closure \
  --manifest /absolute/reviewed/lvs-closure-manifest.json \
  --acknowledgement I_ACK_LVS_CLOSURE_RUNTIME_AND_LIVE_CAPTION_GENERATION
```

No live execution was performed while building this package.
