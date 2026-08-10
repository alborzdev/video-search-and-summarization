# Current 500-row LVS formats runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the oracle-bound MP4, AVI, MOV, MKV, and WebM LVS runtime
qualification—with the unchanged 211 reviewed planning candidates from the
prior RT-VLM-qualified 500-row view. Candidate IDs, order, planning-only
states, and evidence-empty status remain unchanged.

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-lvs-formats-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-lvs-formats-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, or product API
operation. Explicit write mode changes its four generated post-state documents,
the immutable 289- and 500-row descriptors, and the metadata-set selector.
