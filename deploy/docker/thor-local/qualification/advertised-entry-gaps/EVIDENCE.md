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
  `bd181bea21b053407da4df7767e73496c4defab100d109e4ee0a3e113e42f35a`
- manifest canonical SHA-256:
  `e9ce811975db681a57a22663259462d212adf0af6afddce7b15dc2f94c1696b1`
- classification rules raw SHA-256:
  `8b32b2fcfa8e669d1b45408c7a8e04c238e54c590be2b5bc24b3506ae1449314`
- classification rules canonical SHA-256:
  `631cccf7d20b68f82bdb384f36b2c409e26abe26fe4c1425b740bad1f2ba77d6`
- compiled plan payload SHA-256:
  `21dfd759455866923a12c9595422d2dc7a52af4ff6421a85ecde41f792bba5f5`
- compiled plan raw SHA-256:
  `e57f5fca4cc14b4b37a059823b23a191036ecfda1374791d6f9afde27047b4ec`

The five external boundaries are Slack notification, a remote
OpenAI-compatible model endpoint, AWS/GCS validation, Enterprise RAG report
generation, and FRAG retrieval integration. They cannot be promoted using
local mocks or without user authorization.
