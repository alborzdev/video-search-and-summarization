# Evidence boundary

## Mechanically established

`compile_plan()` validates every schema and source lock, including:

- the exact full-envelope predecessor;
- the advertised Base VQA and report semantics in the candidate adapter;
- the Thor bind mount from `${VSS_DATA_DIR}/agent-reports` to
  `/vss-agent/agent_reports`;
- the Thor Agent's filesystem object-store configuration and exact-file
  deletion implementation;
- the production VQA/report implementation surfaces; and
- the exact tracked 2,617,799-byte MP4 fixture and SHA-256.

The authorization-gated executor additionally requires a reviewed regular
Matroska file and SHA-256, request binding to both exact media identities,
absence of expected answer/event text from the requests, an empty bounded
report-object prestate, exact response-derived report ownership, report
section/event semantics, absent-event exclusion, no report delta around each
negative request and its two-second quiescence window, and exact restoration
of the prestate after per-object cleanup.

Receipts contain fixture and content hashes, counts, booleans, and fixed step
IDs. They do not contain report paths, report contents, raw prompts, media
paths, or object-store filenames. Their schema fixes non-promotion and rejects
forged pre-absence, cleanup, semantic, or snapshot-equality claims.

Fourteen fake-only tests cover both Base cases, exact pre-absence, cancellation and
invalid-request no-delta behavior, pixel/distractor/follow-up semantics,
required report headings and events, answer-leakage rejection, fixture digest
failure, authorization-before-file-read, cleanup restoration, and receipt
forgery rejection.

## Not established

No live HTTP request, Docker operation, service lifecycle action, credential
use, download, model inference, or real report-store write occurs during
planning or tests. There is no checked-in runtime receipt. The primary MP4 is
materialized and byte-locked, while the exact MKV remux remains a
manifest-time operator input. Agent media IDs are request-bound, but the
public Agent/VST response does not prove their stored bytes match the reviewed
digests. The two-second negative quiescence check is bounded rather than an
indefinite absence claim. The selected Metadata-500 rows remain unchanged and
unpromoted. Warehouse and its sample bundle remain excluded.
