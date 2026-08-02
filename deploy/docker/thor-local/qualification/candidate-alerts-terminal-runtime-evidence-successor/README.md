# Candidate Alerts terminal runtime-evidence successor

This additive successor removes the predecessor collector's stale assumption that the caller-selected incident `id` is also the on-demand job correlation ID. It accepts only the server-generated `correlationId` and exact `statusUrl` returned by `POST /api/v1/verification/ondemand`, then dynamically admits that one literal loopback job path.

An authorized candidate run creates and read-binds one exact run-owned verification config, submits one positive job, polls `GET /ondemand/{correlationId}` to a `completed` terminal state, and requires a verified processing result plus an acknowledged Elastic or Kafka sink receipt with transport-specific identity. It then submits a second valid job, immediately calls `DELETE` using its independently server-generated ID, requires `cancellationAccepted=true`, and observes the job twice as terminal `cancelled` with no result or error. This is the public runtime proof corresponding to the source-locked atomic pre-publish gate.

The adjacent unknown-category rejection remains. Cleanup deletes only the exact identity-bound config and requires the full unrelated config projection to match its pre-state. On-demand terminal records have no deletion endpoint and remain in the process-local bounded store until TTL expiry or restart; the receipt states this explicitly.

The default command is inert. All origins and media URLs must be explicit numeric loopback HTTP; proxies and redirects are disabled. Requests, polls, duration, response sizes, and cleanup reserve are bounded. Receipts contain only hashes, counts, state labels, and sanitized sink classifications. Warehouse is excluded.

```bash
python3 collector.py plan
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_collector.py
```
