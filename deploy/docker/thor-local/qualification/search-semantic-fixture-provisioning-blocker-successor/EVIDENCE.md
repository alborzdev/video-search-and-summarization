# Evidence boundary

This package records reviewed source evidence, not deployed runtime evidence.

## Proven by locked production sources

- The universal upload flow obtains an upload URL, lets VST return its own
  `sensorId`, and calls `/complete` with that allocated identity.
- RT-Embed completion is synchronous and reports
  `usage.total_chunks_processed`.
- RTVI-CV registration is not fail-closed: connection and timeout failures are
  logged and skipped.
- `SearchInput` is `extra="forbid"`, contains selected-object metadata, and
  has no explicit embedding-vector field.
- Embed and attribute tools generate query embeddings internally and search
  configured Elasticsearch indices.
- Attribute append-mode enrichment depends on VST stream resolution and skips
  failed results.
- Search and Thor-full profiles bind behavior/raw searches to fixed
  `mdx-*-2025-01-01` indices.
- Elasticsearch templates provide the expected wildcard families and dense
  vector mappings; this makes exact tuple setup possible but does not create
  VST/CV/model identity.
- Video deletion is an explicitly best-effort multi-system flow with partial
  and failure outcomes and field-based Elasticsearch `delete_by_query`.
- The selected Metadata-500 Search oracle is still evidence-empty,
  `open_unexecuted`, 14/14, and executor/collector-null.

## Not proven

- No full fixture was created.
- No Search, VST, RTVI-CV, RT-Embed, or Elasticsearch request was sent.
- No model ran and no media was uploaded.
- No cross-system exact cleanup receipt exists.
- No predecessor receipt is validated by this package.
- No canonical row is bound, promoted, or advanced.

The eight blocker IDs in `contract.json` are therefore negative evidence
against claiming the preprovisioned-fixture gap closed. They are not evidence
that the underlying advertised Search feature is absent.
