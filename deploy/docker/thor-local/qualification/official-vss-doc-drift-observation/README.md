# Official VSS 3.2.1 documentation drift observation

This isolated, offline package records the already-reviewed 2026-08-01
aggregate observation against the immutable 2026-07-31 documentation source
lock. It does not fetch documentation and does not replace, mutate, or relabel
the July lock.

The bound denominator is the checked-in set of 172 VSS 3.2.1 documentation
URLs and its checked-in 26,449-edge directed crawl graph. The reviewed August
observation says that all 172 raw response-body hashes changed while every
per-page byte count, the URL set, and the directed topology stayed identical.

Exact August per-page hashes and response bodies are not available in the
workspace. Consequently this package records aggregate metadata and a future
review plan; its validator independently re-proves only the checked-in July
baseline. Raw-byte drift does not prove semantic change, and identical byte
counts/topology do not prove semantic equality. Semantic equality is explicitly
`unproven`.

Run the offline validator and tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 deploy/docker/thor-local/qualification/official-vss-doc-drift-observation/validate_observation.py
PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider deploy/docker/thor-local/qualification/official-vss-doc-drift-observation/tests
```

The only result is
`documentation_raw_drift_observed_semantics_unproven_non_advancing`. It supplies
no runtime or feature evidence and has no effect on official capabilities,
acceptance, oracles, or any source lock.
