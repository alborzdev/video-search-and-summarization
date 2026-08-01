# Candidate-alert completion scaffold

This package is an offline-only design and validation scaffold for the evidence
that the existing `candidate-alerts-runtime-evidence` admission collector does
not observe. It has no `execute` command, opens no socket, contacts no service,
and is always `promotion_eligible=false`.

The intended primary lane starts with the released Kafka-backed upstream
candidate ingress, `POST /api/v1/incidents`, rather than the direct
`/verification/ondemand` shortcut. A future authorized collector would submit
one positive and one negative candidate, then query the Elasticsearch-backed
`GET /api/v1/realtime/incidents` surface until it observes exact terminal
documents. The optional Kafka sink is a separate lane because Alert Bridge
selects one enhanced sink and exposes no Kafka result-read API.

## Offline validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-alerts/collector.py plan

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-alerts/test_collector.py
```

Only `plan` exists. The plan validates strict schemas, descriptor locks, the
confirmed/rejected pair, exact bound arithmetic, all active blockers, and the
non-promoting contract.

## Proposed bounded Elasticsearch lane

The hard maximum is 53 requests and 56 actions:

| Phase | Requests | Actions |
| --- | ---: | ---: |
| health, config pre/create/readback, result baseline, two candidate triggers | 7 | 7 |
| bounded terminal-result polling | 40 | 40 |
| exact config DELETE and absence/state postcondition | 2 | 2 |
| two exact sink-document DELETEs and two absence postconditions | 4 | 4 |
| collector-owned fixture-server start | 0 | 1 |
| fixture-server stop and closed-socket postcondition | 0 | 2 |
| **maximum** | **53** | **56** |

Six requests and eight actions are reserved before cleanup. Ownership is
registered in this order only after exact proof:

1. collector-owned fixture server after an exact numeric-loopback bind and
   identity manifest;
2. alert config after HTTP 201 plus exact readback of the run marker;
3. positive Elasticsearch document after a terminal receipt and exact
   `_index`, `_id`, correlation, fixture, media, and run-marker readback;
4. negative document under the same gate.

Cleanup is strict LIFO. Each resource consumes one exact cleanup transition
and one independent postcondition transition. A failed or ambiguous ownership
gate cannot enter the ledger.

## Two-fixture identity

`fixtures/positive.json` and `fixtures/negative.json` are digest-locked semantic
descriptors. They specify the opposite expected verdicts and distinct visible
identity tokens. They are not media files, deliberately: `materialized_media`
is false and remains a promotion blocker.

The pure `FixtureIdentity` model binds future media bytes to:

- the exact descriptor digest and complete pair identity;
- the authorized run ID;
- an exact media SHA-256 and byte count;
- one fixture-server identity digest;
- a unique, unguessable capability path; and
- the visible token the VLM result must echo.

A future fixture server must record every exact GET/Range response, bytes
served, the served artifact digest, and a canonical request-log digest. A URL
hash alone is insufficient.

## Terminal and sink receipt

`terminal-result.schema.json` is standalone and rejects unknown fields. A
successful receipt binds the correlation ID, fixture descriptor, media bytes,
visible identity, fixture server, fetch log, final confirmed/rejected verdict,
and one delivery receipt:

- Elasticsearch: exact index/document digests plus created/updated result;
- Kafka: exact topic, partition, offset, key, and payload digests.

Failed/cancelled terminal results must carry `verification-failed` and an
explicit `backend=none`, `delivered=false` receipt with a bounded failure code.
The schema is a required product contract, not evidence that the current API
already emits it.

## Query boundary

`canonical_incident_query()` accepts only scalar `sensor_id`, `category`, an
exact UTC timestamp, `limit<=100`, and `offset=0`. It emits one fixed-order,
percent-encoded path. Control characters, path syntax, injected query keys,
nonzero offsets, and oversized limits fail closed.

The shared runtime transport currently rejects all query strings, so this
builder remains intentionally disconnected from I/O. Connecting it requires a
separately reviewed bounded-query transport change.

## Remaining blockers

Static Thor source candidates now propagate per-category VLM parameters,
effective response-format/JSON parsing, enable direct-media verdicts, and copy
the audited modules into the derivative image. Those changes are not runtime
proof.

Promotion remains blocked because:

- the two semantic media artifacts and byte digests are not materialized;
- Alert Bridge has no terminal background-job status/cancel API;
- a task can publish after collector cleanup;
- sinks do not return durable success/failure delivery receipts;
- confirmed/rejected output and running-image identity are not live-proven;
- the strict query builder is not connected to a bounded transport; and
- Kafka still needs its own bounded Protobuf consumer and immutable-record
  policy, preferably against a dedicated oracle topic.

Without terminal/cancellation plus exact sink cleanup, a timeout cannot prove
that a late document or Kafka record will not appear. `reversibility_assessment`
therefore emits blocker `late-publication-not-reversible`; it never converts
this scaffold into promotion evidence.
