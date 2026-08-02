# Evidence

- Source locks cover the stale predecessor, server-generated job registration and routes, terminal state store, atomic publish gate, sanitized sink receipts, Elastic/Kafka acknowledgement behavior, and their production offline tests.
- Fake-only tests prove server IDs are not taken from request incident IDs, dynamic job paths cannot escape loopback admission, intermediate state transitions are bounded, positive completion requires an acknowledged sink identity, and accepted cancellation remains terminal with no delayed result.
- Exact config ownership and unrelated-state restoration retain the predecessor's fail-closed cleanup boundary.
- No Docker, network, background VLM, sink, download, or live action was run while building this successor. No runtime receipt is checked in or promoted.
- Honest gaps: runtime terminal records are process-local and disappear on restart/TTL; there is no public API to remove them immediately. An acknowledged sink receipt is not independently read back from Elasticsearch/Kafka by this collector. Media URL identity is hashed, but the Alert Bridge public API does not return a fetched-media digest. Live Thor/model/sink identity evidence remains pending separate authorization.
