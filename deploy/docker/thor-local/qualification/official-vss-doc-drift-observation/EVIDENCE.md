# Evidence boundary

The validator re-hashes and parses these immutable 2026-07-31 artifacts:

- the 172-record official documentation byte source lock;
- the exact sorted 172-URL recursive target set;
- the exact 26,449-edge crawl graph.

It recomputes the URL-set hash, total July byte count, canonical July record-set
hash, edge count, self-edge count, and canonical URL-pair edge-set hash. No
network, download, Docker, service, credential, runtime, or canonical mutation
surface is used.

The 2026-08-01 comparison is deliberately classified as
`already_reviewed_2026_08_01_aggregate_observation`: 172 of 172 raw hashes were
reported changed, 172 of 172 per-page byte counts were reported unchanged, and
the URL set and graph topology were reported unchanged. The exact August hashes
and response bodies are not checked in, so the validator does not claim to
reproduce that external observation or materialize an August source lock.

Semantic comparison of normalized text, DOM, and capability claim locators was
not performed. Semantic equality remains unproven. A future exact August capture
must be a separate artifact, followed by semantic review, before any ledger
change could be proposed.
