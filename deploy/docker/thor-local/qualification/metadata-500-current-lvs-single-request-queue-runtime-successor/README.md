# Current 500-row LVS one-video runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the corrected and runtime-qualified LVS one-video-at-a-time
processing boundary—with the unchanged 211 reviewed planning candidates from
the prior LVS-format-qualified 500-row view. Candidate IDs, order,
planning-only states, and evidence-empty status remain unchanged.

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-lvs-single-request-queue-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-lvs-single-request-queue-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, or product API
operation. Explicit write mode changes its four generated post-state
documents, the immutable 289- and 500-row descriptors, and the metadata-set
selector.
