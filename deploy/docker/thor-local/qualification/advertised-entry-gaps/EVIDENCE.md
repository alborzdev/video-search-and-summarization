# Advertised entry gap evidence

This artifact is planning evidence, not runtime evidence.

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
| spatial-ai-utils | 8 | seven local offline tools plus one external boundary |
| synthetic-data-tools | 4 | local offline tools |
| enterprise-rag | 2 | user-managed external boundary |
| **Total** | **86** | **all plan entries open** |

Classification totals:

- required local: 55
- alternate local: 26
- external optional: 5
- runtime evidence: 0
- canonical entry-level capabilities: 1 (`CPU multimedia support`)
- runtime-qualified entry-level capabilities: 0

The two source families already marked `passed_current` are
`spatial-ai-utils` and `synthetic-data-tools`. Their 12 advertised entries are
still open because no entry-level official capability IDs or literal semantic
oracles exist. `vios-codecs-audio` is the separate partial family: CPU
multimedia now has an exact canonical capability/oracle, remains
`not_qualified`, and its other five advertised semantics remain open here.

Digest locks:

- manifest raw SHA-256:
  `879d683f9ad22ace194f5c818361418bc9027d7011cb4fa9d6f9a4af738cacba`
- manifest canonical SHA-256:
  `9b955d9f68fdf5f413e48b92653861b0d56933b1803e84d145e1eafff93f7e6c`
- official capability ledger raw SHA-256:
  `65241b3ad56f5d9bb817ba040c06abdbfe034701be645c845d94e4f065514f0e`
- classification rules raw SHA-256:
  `8b32b2fcfa8e669d1b45408c7a8e04c238e54c590be2b5bc24b3506ae1449314`
- classification rules canonical SHA-256:
  `631cccf7d20b68f82bdb384f36b2c409e26abe26fe4c1425b740bad1f2ba77d6`
- compiled plan payload SHA-256:
  `a50231e6de3b97cd551a46c32a317e83c71cff2ca27eb22a0363d92e756587d4`
- compiled plan raw SHA-256:
  `9ea23d0e84c22f913024035b92633c173e46bce61e7b80ddc6af376d0e389239`

The five external boundaries are Slack notification, a remote
OpenAI-compatible model endpoint, AWS/GCS validation, Enterprise RAG report
generation, and FRAG retrieval integration. They cannot be promoted using
local mocks or without user authorization.
