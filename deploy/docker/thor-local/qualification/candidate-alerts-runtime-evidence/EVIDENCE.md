# Candidate-alert collector evidence status

Status: implemented, statically verified, live run not executed, and
non-promoting.

No HTTP request, Alert Bridge mutation, VLM request, sink delivery, Docker
operation, service lifecycle action, model access, or evidence receipt was
performed while implementing this package.

Static evidence:

```text
collector.py plan   -> exact source/binding/bounds/schema checks; runtime_actions=0
test_collector.py   -> 40 passing fake-only cases
```

The fake suite covers default inertness, exact authorization, numeric-loopback
target and media admission, proxy/redirect policy, exact 8/8 budget use,
response closure, deterministic positive/adjacent semantics, preexisting-ID
refusal, ownership admission only after exact 201 plus unique-marker readback,
no-delete handling for ambiguous create, HTTP 409, malformed success,
redirects, and concurrent replacement, cleanup after a later semantic failure,
non-owned state drift, evidence redaction, and a standalone strict wrapper plus
nested evidence schema.

Even a future passing authorized receipt will only prove the synchronous API
admission and reversible configuration boundary described in `README.md`.
Because the endpoint returns before background processing, such a receipt must
remain `promotion_eligible=false` and cannot be used as final VLM-verdict or
end-to-end candidate-alert parity evidence.
