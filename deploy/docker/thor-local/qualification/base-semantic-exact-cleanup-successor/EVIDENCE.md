# Evidence boundary

## Source-proven behavior

The contract byte-locks the frozen predecessor, the selected Agent OpenAPI
inventory, the Thor filesystem object store, all three report generators, and
the report-agent output formatter.  Static validation proves:

- the Agent declares `POST /generate/stream` and exact-key `GET`/`DELETE`
  `/static/{file_path:path}`;
- filesystem deletion checks for a file and unlinks that exact path;
- report artifacts use finite timestamped Markdown/PDF filenames rather than a
  run-ID directory;
- a success receipt can contain only two response-derived path digests, two
  successful readbacks, two exact successful deletes, and two per-key 404
  postconditions;
- namespace deletion and recursive deletion claims are schema-forbidden.

## Not runtime evidence

No checked-in receipt exists.  The plan and tests use no network, Docker,
service lifecycle, model, GPU, downloads, or host mutation.  Fake transports
verify control flow and failure cleanup only.  They do not prove an Agent is
deployed or that a Thor-local report was generated.

This package does not prove pre-creation absence because current report writers
use timestamp-derived keys with `upsert_object`.  It does not advance the
schema-v2 500-row canonical metadata, alter the frozen 8/11 Base envelopes,
promote either Base oracle, or claim complete Base/HITL semantic qualification.
The reviewed accounting identifies 11/12 as the required successful full-lane
envelopes once exact two-file cleanup replaces the false namespace probe and
cleanup; those numbers are analysis here, not a canonical metadata mutation.
Warehouse and the Warehouse sample bundle remain excluded.
