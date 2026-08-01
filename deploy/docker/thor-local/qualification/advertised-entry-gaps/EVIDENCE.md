# Advertised entry gap evidence

This artifact is planning evidence, not runtime evidence.

The table covers the 74 entries selected from empty or partial capability
families. It does not include the 413 additional advertised strings that still
have family-only planning bindings; all 487 non-canonical entries remain global
literal-completeness blockers.

| Family | Entries | Required lane |
|---|---:|---|
| video-summarization-live | 6 | local runtime workflow |
| search-scale | 2 | Thor scale benchmark |
| alert-notifications-slack | 1 | user-managed external boundary |
| rt-vlm-media | 11 | local media matrix |
| rt-vlm-api | 8 | local API operations |
| rt-vlm-models | 5 | four local model lanes plus one external boundary |
| rt-vlm-performance-observability | 8 | local telemetry/behavior |
| rt-cv-3d-sparse4d | 2 | custom-data multiview runtime |
| rt-cv-3d-mv3dt | 6 | custom-data multiview runtime |
| vios-codecs-audio | 5 | local codec/audio matrix; CPU entry is canonical but runtime-open |
| audio-understanding | 3 | alternate local audio workflow |
| vios-ui | 7 | browser/backend correlation |
| agent-and-mcp-apis | 8 | local API/MCP operations |
| enterprise-rag | 2 | user-managed external boundary |
| **Total** | **74** | **all plan entries open** |

Classification totals:

- required local: 55
- alternate local: 15
- external optional: 4
- runtime evidence: 0
- canonical entry-level capabilities: 13 (CPU multimedia plus 12 tooling entries)
- runtime-qualified entry-level capabilities: 0

The eight `spatial-ai-utils` and four `synthetic-data-tools` advertised entries
now have exact entry-level capabilities and literal semantic oracles, so they
are no longer missing-entry gaps. All twelve remain runtime-unqualified and
evidence-empty; the AWS/GCS entry is an external-optional boundary. Their prior
family-level static evidence did not qualify the individual entries.
`vios-codecs-audio` is the separate partial family: CPU
multimedia now has an exact canonical capability/oracle, remains
`not_qualified`, and its other five advertised semantics remain open here.

Digest locks:

- manifest raw SHA-256:
  `1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce`
- manifest canonical SHA-256:
  `cbf65ddc55b3518763bf8ee57f58f24619956473035aeca98a274a7b1bc959f2`
- official capability ledger raw SHA-256:
  `cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0`
- classification rules raw SHA-256:
  `9938db401c3012d8ab39887291b0f013ae0b3c54ee94dabe25ec6f8bfed923ac`
- classification rules canonical SHA-256:
  `a3a1f938b777beb8d12a927f447bad0540f32e4b8e8401f1f3fee3a450671496`
- compiled plan payload SHA-256:
  `7a50b418c783de5e7a484616924e42bff884d3d4ef6b16b311b3e85a8a0a7d26`
- compiled plan raw SHA-256:
  `a1affc03163488d7027c4780bb85a69a2ab1fdd9a97ac466ccfbeeb093a1aada`

The four remaining external gaps are Slack notification, a remote
OpenAI-compatible model endpoint, Enterprise RAG report
generation, and FRAG retrieval integration. They cannot be promoted using
local mocks or without user authorization.
