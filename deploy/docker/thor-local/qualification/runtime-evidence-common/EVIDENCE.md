# Runtime evidence common evidence status

Status: package-only, inert, and non-promoting.

This directory supplies reusable safety primitives for future runtime evidence.
It does not contain or claim live Thor evidence, service readiness, feature
parity, or closure of an advertised requirement. The package does not alter the
canonical capability or oracle documents.

The strict contract fixes these invariants:

- execution is disabled by default and no live CLI command exists;
- only explicit-port numeric loopback HTTP(S) origins and exact admitted paths
  may reach an injected opener;
- injected openers must declare proxy and redirect handling disabled;
- request bytes, response bytes, requests, and all semantic/cleanup actions are
  bounded; exact cleanup and its absence postcondition are charged separately
  but reserved atomically before the cleanup callback;
- run and authorization identities are exact and raw approval material is not
  evidence;
- only exact run-owned resources enter the LIFO ledger;
- cleanup requires an exact-target action and a passing absence postcondition;
- pre/post state is represented by canonical SHA-256 comparisons; and
- evidence stores payload and target digests, not raw sensitive material.

Static validation evidence:

```text
common.py check       -> static package/schema validation only
common.py self-test   -> injected fake opener and in-memory fake resource only
test_common.py        -> 57 passing fake-only cases
```

The tests include negative cases for DNS and remote origins, implicit ports,
decorated origins, path traversal, ambiguous encodings, missing opener policy
markers, redirects, final-URL drift, oversize requests and responses, request
and action exhaustion, response closure on error, identity mismatch, duplicate
or foreign resource ownership, LIFO order, cleanup recovery, failed absence
postconditions, raw-payload redaction, and strict-schema extra properties.

Any later executor that uses these primitives still needs its own explicit
approval bundle, source locks, fixtures, semantic oracle, cleanup allowlist,
postconditions, and authorized live run. This package alone must never be cited
as runtime or parity evidence.
