# Current 500-row NvStreamer runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the evidence-bound NvStreamer file-to-stream workflow—with
the unchanged 211 reviewed planning candidates from the prior 500-row view.
Candidate IDs, order, and planning-only states remain unchanged.

The projector reuses the reviewed predecessor implementation with a new,
explicit source/output lock set. It registers a new immutable 289/500 pair and
selects the 500-row view. Historical descriptors and predecessor post-state
files remain untouched.

Regenerate atomically and verify:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-nvstreamer-file-workflow-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-nvstreamer-file-workflow-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, or product API
operation. Its explicit write mode changes only the four post-state documents,
two new descriptors, and the selected-set pointer.
