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
| vios-codecs-audio | 6 | local codec/audio matrix |
| audio-understanding | 3 | alternate local audio workflow |
| vios-ui | 7 | browser/backend correlation |
| agent-and-mcp-apis | 8 | local API/MCP operations |
| spatial-ai-utils | 8 | seven local offline tools plus one external boundary |
| synthetic-data-tools | 4 | local offline tools |
| enterprise-rag | 2 | user-managed external boundary |
| **Total** | **87** | **all open** |

Classification totals:

- required local: 56
- alternate local: 26
- external optional: 5
- runtime evidence: 0
- passed entry-level capabilities: 0

The two source families already marked `passed_current` are
`spatial-ai-utils` and `synthetic-data-tools`. Their 12 advertised entries are
still open because no entry-level official capability IDs or literal semantic
oracles exist.

Digest locks:

- manifest raw SHA-256:
  `6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127`
- manifest canonical SHA-256:
  `172a6ff8c33cd7d3e1378bf6cb643e4c56fd70f5d4c2e117166a640932f7c411`
- classification rules raw SHA-256:
  `8b32b2fcfa8e669d1b45408c7a8e04c238e54c590be2b5bc24b3506ae1449314`
- classification rules canonical SHA-256:
  `631cccf7d20b68f82bdb384f36b2c409e26abe26fe4c1425b740bad1f2ba77d6`
- compiled plan payload SHA-256:
  `97cb92ffb83d05388759f7428324344f91ec294116e5d24721c1ba21d994ab7d`
- compiled plan raw SHA-256:
  `dd3c8cbbcae859137e73da4a8d4d9227f535dd674979b5d9e8f5cf25b885d122`

The five external boundaries are Slack notification, a remote
OpenAI-compatible model endpoint, AWS/GCS validation, Enterprise RAG report
generation, and FRAG retrieval integration. They cannot be promoted using
local mocks or without user authorization.
