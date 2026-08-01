# Candidate-alert runtime evidence collector

This is the first authorization-gated collector built on
`runtime-evidence-common`. It binds planning requirement `candidate-alerts` to
capability `runtime.workflow.alert-verification` and the Alert Bridge REST
surface. The default command is an inert plan and performs no HTTP request.

The collector is deliberately non-promoting. It observes Alert Bridge health,
configuration identity, positive HTTP 202 admission, adjacent unknown-category
HTTP 400 rejection, exact config cleanup, and restoration of the non-owned
configuration digest. The on-demand endpoint schedules VLM and sink work in the
background; this bounded collector does not observe final VLM completion,
verdict correctness, Kafka/Elasticsearch delivery, fixture-server identity, or
the media payload digest. Its evidence therefore cannot close the capability
by itself.

## Inert validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-alerts-runtime-evidence/collector.py \
  plan

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/candidate-alerts-runtime-evidence/test_collector.py
```

The plan validates all source locks, the deterministic accepted/rejected
fixture pair, required Alert Bridge OpenAPI operations, the exact canonical
8-request/8-action bounds, the canonical capability/oracle IDs, and strict
contract/plan schemas. Cleanup ownership is not registered until POST returns
an exact HTTP 201 and a separate GET proves the complete persisted config plus
a unique marker derived from the authorized run identity. Ambiguous responses,
redirects, malformed success, HTTP 409, and a concurrent creator therefore
fail closed without DELETE. Tests inject only an in-memory fake Alert Bridge
and never call the live opener.

## Authorized runtime command

Do not run this command until the operator has reviewed whether the configured
Alert Bridge VLM and sinks are local or external and has explicitly authorized
the config mutation plus background VLM task:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/candidate-alerts-runtime-evidence/collector.py \
  execute \
  --run-id '<unique-plain-run-id>' \
  --acknowledgement I_ACK_CANDIDATE_ALERTS_CONFIG_MUTATION_AND_BACKGROUND_VLM \
  --origin http://127.0.0.1:9080 \
  --media-url http://127.0.0.1:<fixture-port>/tiny-identity.mp4
```

Both origins require numeric loopback literals and explicit ports. The media
URL must be canonical HTTP with an exact MP4 or MKV path and no credentials,
query, fragment, traversal, or percent encoding. The collector does not start
the fixture server or any VSS service.

The live CLI constructs an explicitly empty-proxy urllib opener with redirects
disabled, then injects it into `BoundedHTTPTransport`. It emits sanitized JSON
to stdout and writes no receipt. It never records raw URLs, request payloads,
prompts, sensor IDs, config names, exception text, or authorization material.

## Exact bounded workflow

| Request/action | Operation | Oracle |
| --- | --- | --- |
| 1 | `GET /health` | Alert Bridge reports `status=ok` |
| 2 | `GET /api/v1/verification/config` | exact run-owned config is absent; capture non-owned state |
| 3 | `POST /api/v1/verification/config` | exact run-marked config receives an unambiguous 201 |
| 4 | `GET /api/v1/verification/config/{alert_type}` | complete config and unique run-owned marker match; only now register cleanup |
| 5 | `POST /api/v1/verification/ondemand` | accepted fixture request returns 202 and exact correlation ID |
| 6 | `POST /api/v1/verification/ondemand` | adjacent unknown category returns 400 |
| 7 | exact `DELETE` cleanup | only the ledger-owned config may be removed |
| 8 | config-list postcondition | owned config is absent and non-owned digest matches pre-state |

Cleanup and its postcondition reserve the final two action slots atomically
before deletion. Any semantic failure after ownership registration still
attempts this exact cleanup. A create ambiguity or ownership-readback mismatch
cannot enter the cleanup ledger and therefore cannot delete concurrent or
external state. Redirects, proxy-enabled openers, response drift, preexisting
owned IDs, budget exhaustion, or non-owned state drift fail closed.

`evidence.schema.json` is standalone and self-contained. It rejects unknown
wrapper or nested fields, raw URLs, arbitrary runtime-evidence objects, budget
drift, action-sequence drift, missing cleanup, and comparison-shape drift
without requiring caller-side schema substitution.
