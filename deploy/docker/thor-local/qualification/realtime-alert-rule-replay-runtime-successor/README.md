# Thor realtime alert rule replay runtime successor

This package qualifies official capability row 330,
`manifest-entry.realtime-alerts.02-rule-replay`, against the deployed
Thor-local Alert Bridge, Elasticsearch persistence, and RT-VLM services.

The acknowledgement-gated harness publishes the checked-in 2.5 MB H.264
fixture to local MediaMTX and requires an empty realtime-rule inventory before
it mutates anything. It creates one namespaced rule, verifies the public and
durable records, invokes replay twice, and checks after each invocation that
the generated rule identity, creation time, immutable configuration, and
RT-VLM stream identity are unchanged. Each inventory must contain exactly one
owned rule/document/stream. RT-VLM worker logs must additionally show the
create/remove sequence `1/0`, `2/1`, `3/2`, then `3/3` after cleanup, proving
there is exactly one live caption worker rather than merely one stream asset.

Cleanup deletes the rule, confirms a repeated delete returns explicit
not-found, stops the publisher, removes any uniquely owned VLM incidents, and
requires exact before/after digests for public rules, persisted rules, and all
unrelated RT-VLM streams. HTTP requests are restricted to numeric loopback,
the VSS Agent `/generate` endpoint is never used, and the retained receipt has
no UUID or stream URL.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/realtime-alert-rule-replay-runtime-successor/verify.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/realtime-alert-rule-replay-runtime-successor/tests
```

This evidence is intentionally limited to replay. It does not claim the
separate rule-CRUD row because the deployed OpenAPI has no update operation,
and it does not claim incident retrieval because that API has no rule-ID
filter.
