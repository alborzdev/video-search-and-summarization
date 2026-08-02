# LVS semantic HTTP runtime successor

This additive package supplies a concrete, authorization-gated HTTP candidate
for the frozen `lvs-semantic-runtime-evidence` semantic core. It does not edit
that predecessor and does not claim that the full LVS Agent oracle is
executor-ready.

The selected schema-v2 500-row metadata set is source-locked. Its LVS row must
remain `open_unexecuted`, evidence-empty, executor/collector-null, and bounded
at 14 requests/actions. The production LVS OpenAPI, server routes, file models,
Agent tools, LVS/Thor-full configs, and local generated environment are also
locked.

## Concrete boundary

An authorized successful run performs exactly 14 HTTP requests against one
explicit numeric-loopback LVS origin:

1. Capture the complete `/files?purpose=vision` pre-state.
2. Require `/v1/ready` HTTP 200 and require the manifest model in `/models`.
3. Upload two distinct, digest-pinned, at-most-32 MiB local fixture files with
   client-selected run-derived UUIDs; validate each upload and GET readback.
4. Call `/v1/summarize` for the first owned file and require a correlated,
   non-empty backend summary. This is not mislabeled as an Agent-generated
   `video_report_gen` artifact.
5. DELETE only the two registered UUIDs in reverse upload order. After each
   deletion, list files and require that UUID absent.
6. Require the unrelated post-state projection byte-equal to the pre-state and
   recheck readiness.

The executor writes nothing. It prints a sanitized candidate receipt with
response sizes and digests, hashed origin/run/model identities, fixture
digests, coverage classifications, and cleanup facts. It omits URLs, raw
payloads, file paths, prompts, raw resource IDs, and credentials. It never
starts/stops services, scans ports, reads credentials, downloads data, or uses
the Warehouse sample.

## Honest residual boundary

Only fixture setup is complete at the full predecessor-action level. Five
actions are concretely but partially observed: file-list pre-state,
LVS/model readiness, one-file backend summary, exact file/dependent-collection
cleanup, and file-list restoration. Those do not overclaim Agent report,
stream, prompt, artifact-identity, disconnect, cancellation, quiescence, or
separate dependency readiness evidence.

Eight actions remain adapter-required, so `executor_ready=false` and
`promotion_eligible=false`:

- deployed discovery of the five-tool catalog through the NAT Agent transport;
- multi-video report orchestration (the current server handler selects
  `id_list[0]`; `video_report_gen` owns the Agent-level multi-video path);
- live-caption start and retrieval with an independently owned stream plus
  Kafka, Logstash, and CA-RAG observations;
- first/latest shared prompt writes and cross-Agent isolation through two NAT
  Agent sessions;
- disconnect, exact server-side cancellation, and quiescence proof (the public
  LVS file API exposes no request-status collector).

## Safe commands

The default command is inert, and focused tests are mock-only:

```bash
python3 deploy/docker/thor-local/qualification/lvs-semantic-runtime-http-successor/executor.py plan
pytest -q deploy/docker/thor-local/qualification/lvs-semantic-runtime-http-successor/tests/test_executor.py
```

Runtime requires prior operator review and the exact acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/lvs-semantic-runtime-http-successor/executor.py execute-http \
  --manifest /absolute/reviewed/lvs-http-manifest.json \
  --acknowledgement I_ACK_LVS_HTTP_RUNTIME_AND_EXACT_TWO_FILE_CLEANUP
```

The manifest supplies the explicit `http://127.0.0.1:PORT` origin, run ID,
advertised model, scenario/events, and exactly two distinct absolute fixture
paths with SHA-256 identities. Hostnames, HTTPS, non-loopback addresses,
credentials in URLs, proxies, redirects, symlinked paths, oversized files, and
digest drift fail before network activity.
