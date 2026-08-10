# Current 500-row official Edge model runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including current semantic qualification of the exact local Nemotron
3 Nano 4B FP8 and Cosmos3 Nano Edge model identities—with the unchanged 211
reviewed planning candidates from the prior LVS custom-model-qualified 500-row
view. Candidate IDs, order, planning-only states, and evidence-empty status
remain unchanged.

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-official-edge-model-identities-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-official-edge-model-identities-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, or product API
operation. Explicit write mode changes its four generated post-state documents,
the immutable 289- and 500-row descriptors, and the metadata-set selector.
