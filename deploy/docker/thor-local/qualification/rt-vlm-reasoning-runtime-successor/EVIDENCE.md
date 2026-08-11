# Evidence

- Capability: `manifest-entry.rt-vlm-media.09-reasoning`.
- Runtime boundary: exact loopback endpoint `127.0.0.1:8018`; VSS Agent `/generate` is never called.
- Model oracle: the pre/post `/v1/models` set and both completion response model fields must identify the frozen local Cosmos reasoner without substitution.
- Semantic oracle: two digest-pinned mirrored clips receive one identical temporal comparison question with reasoning enabled and must return opposite correct conclusions.
- Leakage oracle: `<think>` content or the separate reasoning field is accepted only as a signal; reasoning is stripped before final-answer comparison and neither text is retained.
- Budget: exactly four HTTP requests, including two model requests, with no service lifecycle or persistent-resource action.
- Cleanup: generated clips exist only under one temporary executor-owned directory, which must be absent before a passing receipt is emitted.
- Warehouse sample bundle: excluded.
