# Base semantic exact-report cleanup successor

This additive, Warehouse-free successor fixes the concrete cleanup defect in
the frozen `base-semantic-runtime-evidence` candidate without rewriting it.
The deployed static API is file-granular: `GET` and `DELETE`
`/static/{file_path:path}` address one object-store key.  Thor's filesystem
backend checks `path.is_file()` and calls `path.unlink()`; it has no list or
recursive-directory delete operation.

The production report layout is also not `/static/<run-id>/...`:

- `report_gen` writes a top-level `agent_report_YYYYMMDD_HHMMSS.md`;
- `video_report_gen` writes a top-level
  `vss_report_<safe-sensor>_YYYYMMDD_HHMMSS.md` and matching `.pdf`;
- `template_report_gen` writes a matching `agent_report_*.md/.pdf` pair,
  optionally below one sensor-ID component.

Consequently, deleting `/static/<run-id>` and observing 404 at that same path
does not enumerate or remove any generated report.  This successor never makes
that claim.  Its authorized collector performs one reviewed
`POST /generate/stream`, extracts exactly one same-stem Markdown/PDF pair from
the direct response, reads each exact key, deletes each exact key, and requires
an individual 404 readback for each key.  It emits only path/content digests.
An assertion failure after the generation response still runs the same bounded
exact cleanup before returning the primary failure.

The default command is inert:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor/executor.py plan
```

After reviewing a closed manifest, an already-running numeric-loopback agent
can be exercised explicitly:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor/executor.py \
  execute-http --manifest /absolute/reviewed.json --run-id RUN \
  --origin http://127.0.0.1:8000 \
  --acknowledgement I_ACK_BASE_EXACT_REPORT_CLEANUP
```

The manifest must list every report-base origin that the deployed agent may
place in its response.  Those origins are used only to admit returned static
paths; all cleanup requests remain confined to the selected numeric-loopback
origin.  Proxies and redirects are disabled, all paths are exact allowlisted,
and the complete successful transaction is seven requests/actions: generation,
two reads, two deletes, and two 404 postconditions.

## Deliberate non-promotion boundary

The authoritative selected metadata is the schema-v2, 500-row artifact at
`live-metadata-500-migration/post-state-capability-oracles.json`.  Its Base
rows retain frozen full-workflow envelopes of 8 requests for
`tiny-agent-media` and 11 for `hitl-state-transcript`.  Exhaustive exact cleanup
adds per-artifact requests and therefore cannot honestly fit those envelopes.
The mechanically derived successful successor envelopes are 11 for
`tiny-agent-media` (five semantic requests + two artifact reads + two deletes +
two 404 checks) and 12 for `hitl-state-transcript` (six non-render semantic
requests + two exact render reads + two deletes + two 404 checks). The focused
generation/cleanup collector in this package is seven requests: one generation
plus the same six per-artifact operations.
This package does not bind to, change, or supersede those canonical rows.  It
remains non-promoting until a reviewed successor updates the full semantic
workflow envelopes and runtime execution produces a valid receipt.

The receipt also records `preexisting_absence_proven: false`: the existing
timestamped report generators use object-store upsert and do not expose the
future key before generation.  The direct generation response strongly binds
the finite output set and this package proves exact removal of that set, but it
does not invent a pre-creation absence observation or claim canonical
qualification.

Run the static and fake-only tests:

```bash
pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/base-semantic-exact-cleanup-successor/tests
```
