# Future evidence requirements

## Non-negotiable boundary

Evidence must be produced by an authorized operator outside this package. Never
put a password, API key, access key, session token, bearer value, cookie, signed
URL, or full authorization header in the document. The plan and validator do
not read credential stores or environment variables and make no network calls.

Source code, configuration, a unit-test mock, an HTTP stub, or a local emulator
shows only that a path exists. None is proof of Slack delivery, AWS/GCS object
validation, Enterprise RAG report generation, or FRAG retrieval.

The evidence document must validate against `evidence.schema.json`, contain the
four attestations in plan order, and bind `plan_sha256` to the canonical SHA-256
of the current plan JSON. Generate that digest without writing a file:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import hashlib
import json
import importlib.util
from pathlib import Path

path = Path("deploy/docker/thor-local/qualification/external-entry-attestations/plan.py")
spec = importlib.util.spec_from_file_location("external_entry_plan", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raw = json.dumps(module.compile_plan(), sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(raw.encode()).hexdigest())
PY
```

## Fields common to every attestation

Record only sanitized identities and hashes:

- provider HTTPS endpoint hostname and port, successful TLS verification, a
  SHA-256 of the path, and a SHA-256 of the provider
  account/workspace/collection scope;
- the matching TLS authority hostname, provider kind, TLS peer-certificate
  SHA-256, and SHA-256 of the authenticated provider-identity probe receipt;
- an operator-created test artifact ID, kind, byte size, and content SHA-256;
- operation, request timestamp, correlation ID, payload SHA-256, sanitized
  header-set SHA-256, and the statement that authorization succeeded without
  recording the credential;
- response timestamp, 2xx status, response-body SHA-256, provider request-ID
  SHA-256, and the same correlation ID;
- deletion of only the operator-owned test artifact, or a stated retention
  policy with a future expiry. Bind the cleanup record to the exact artifact ID
  and content SHA-256 and to a provider cleanup/retention receipt SHA-256. Slack
  may instead record provider message retention.

All timestamps must include a timezone. Cleanup must occur after the response;
a retention expiry must be later than the cleanup timestamp.

## Provider-specific proof

### Slack notification — `external_optional`

Use a user-managed Slack destination through exactly `slack.com` or
`api.slack.com`. Correlate the exact incident SHA-256 to the payload, successful
response body, provider request ID, hashed channel identity, hashed Slack
message timestamp, and real destination receipt. A mocked Slack API response or
the shipped notifier source is not delivery proof.

### AWS/GCS validation — `alternate_local_lane`

Upload an operator-owned test object, read it back, run the advertised
validation, and correlate the object content SHA-256 across the request and
readback. Include hashed object-key and cleanup/retention receipt identities.

The provider must be actual AWS S3, GCS through its supported interface, or an
operator-supplied globally routable endpoint that verified TLS and an
authenticated provider probe identify as an actual AWS/GCS service. Record both
the endpoint mode and actual provider kind. `local_emulator_used` and
`claimed_local_equivalence` must both be false. Loopback, private, local, generic
unverified S3-compatible, and emulated endpoints are rejected.

### RAG report generation — `external_optional`

Use a user-managed Enterprise RAG service whose verified TLS identity is bound
to an authenticated provider probe. Correlate the exact test-document SHA-256
with ingestion, the request payload with the query, and the response body with
the retrieval response. Bind the retrieved excerpt to the citation and to the
report source, and bind that citation to the report. Independent report
generation without real document retrieval is insufficient.

### FRAG retrieval integration — `external_optional`

Use a user-managed Enterprise RAG endpoint with the same verified TLS and
authenticated provider-probe identity requirements. Correlate the exact test
document with ingestion, request payload with query, response body with the
non-empty retrieval response, and retrieved excerpt with the citation. The
shipped FRAG adapter, configuration, or a mocked response is not retrieval
proof.

## Validation is not promotion

The validator rejects unknown fields, duplicate JSON keys, credential markers,
wrong entry order or acceptance classes, plan drift, insecure or inconsistent
provider identities, local/private/emulated endpoints, replayed correlation or
provider request IDs, uncorrelated digests/IDs, reversed timestamps, and cleanup
that is not bound to the exact artifact and provider receipt. It emits only a
sanitized validation summary. It never updates the shared README, wrapper,
qualification ledgers, or official feature state.
