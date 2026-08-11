# Current 500-row Search Content-Type runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the current-qualified Search backend, rendered Search UI, and
live Search upload Content-Type boundary—with the unchanged 211 reviewed
planning candidates from the prior Search-qualified 500-row view. Candidate
IDs, order, planning-only states, and evidence-empty status remain unchanged.

The Content-Type row proves both documented accepted media types through real
Agent/VST/RT-Embed ingestion, both documented HTTP 400 negative boundaries,
and exact cleanup. The `semantic-search` family remains runtime-unqualified
only for its explicit follow-up Q&A and broader file/RTSP archive-management
advertised boundaries.

Regenerate atomically and verify:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-search-content-type-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-search-content-type-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, browser, or
product API operation. Its explicit write mode changes only the four post-state
documents, two descriptors, and the selected-set pointer. It excludes the
Warehouse sample bundle.
