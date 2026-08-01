# Evidence boundary

The package binds the three canonical planning requirements to their exact capabilities and runtime oracles. It fails closed unless every planning row remains unmaterialized/non-executor-ready, every capability remains `partial`/`not_qualified`, every oracle remains `open_unexecuted` with no evidence, and all twelve canonical/product/test source locks match.

## Positive offline observations

- The real Search compatibility route is registered as deprecated and accepts exact `video/mp4` and `video/x-matroska` values. The fake downstream sees the async body and exact forwarded headers; no real transport is opened.
- The real Search route rejects a missing type, missing/invalid/zero length, an unsupported type, and a parameterized media type before the fake upload boundary.
- The exact production `RequestInfo` class begins both bounded requests as `queued`; the exact production `_trigger_query` method changes each to `processing` before entering the fake RTVI generator.
- The checked-in UI validator admits MP4/MKV by default, and the checked-in Agent documentation preserves the proprietary-codec opt-in boundary.

## Mismatches and limits

- Unsupported Search media yields `415`, contradicting the canonical `missing_or_unsupported_status: 400`. The executor records the mismatch and never normalizes it.
- Two in-process `_trigger_query` calls can overlap at the fake pipeline boundary. This disproves serialization in that isolated handler layer, but it does not prove that a deployed RTVI service fails to queue. End-to-end queue behavior remains unqualified.
- The UI's narrow format surface is not proof that LVS cannot decode AVI/MOV/WebM through another API path. The five-format capability therefore remains unproven, not marked failed.
- No media is decoded, no VLM runs, and no Thor service is contacted. Format-by-format local inference and live two-request queue behavior remain required.
- Zero-call confinement counters are assertions from exact locked-source review and replaced transport boundaries, not general-purpose runtime instrumentation of transitive dependencies.

`runtime_evidence` is always empty, `official_capability_effect` is always `none_candidate_only`, and the Warehouse sample bundle is excluded.
