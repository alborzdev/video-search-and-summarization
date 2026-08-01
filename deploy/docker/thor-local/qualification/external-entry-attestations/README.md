# External-entry attestation plan

This isolated package describes the remaining four Wave 7 external blockers and
validates a future, operator-produced, sanitized evidence document. It does not
contact a provider, inspect credentials or environment variables, start a
service, write evidence, or change any qualification state.

The exact denominator is:

| Advertised entry | Acceptance class | Current state |
| --- | --- | --- |
| Slack notification | `external_optional` | blocked pending real delivery evidence |
| AWS/GCS validation | `alternate_local_lane` | blocked pending actual AWS/GCS evidence |
| RAG report generation | `external_optional` | blocked pending Enterprise RAG evidence |
| FRAG retrieval integration | `external_optional` | blocked pending Enterprise RAG evidence |

`alternate_local_lane` does not make an emulator equivalent to AWS or GCS. An
operator-supplied endpoint is admissible only when the evidence identifies and
verifies an actual AWS or GCS service. MinIO, a generic S3-compatible endpoint,
or a local mock cannot satisfy this advertised claim.

Every admissible endpoint uses HTTPS with verified TLS. Slack is restricted to
the exact `slack.com` or `api.slack.com` API authority. Other endpoints must be
fully qualified and globally routable; loopback, private, link-local and local
names are rejected. Sanitized service-identity evidence binds the endpoint
authority and TLS certificate to an authenticated provider-probe receipt. For an
operator-supplied cloud endpoint, the evidence also declares and binds the
actual AWS S3 or GCS provider kind.

Run the inert plan from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/external-entry-attestations/plan.py
```

Validate a separately collected sanitized evidence document:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/external-entry-attestations/plan.py validate --evidence /absolute/path/to/sanitized-evidence.json
```

Run the package tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/external-entry-attestations/tests
```

The validator opens the supplied evidence with `O_NOFOLLOW`, checks the opened
descriptor is a bounded regular file, and reads from that same pinned descriptor.
A successful
validation means the document satisfies this package's strict future-evidence
contract; it does not promote an entry, modify a ledger, or prove that this
package itself observed the external event. Promotion remains a separate human
review and integration action. Accordingly, the validation summary reports four
contract-valid documents but zero qualified entries and
`promotion_eligible: false`.

See [EVIDENCE.md](EVIDENCE.md) for collection and sanitization requirements.
