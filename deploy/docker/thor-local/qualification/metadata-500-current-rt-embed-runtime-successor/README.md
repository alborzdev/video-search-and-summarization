# Current 500-row RT-Embed runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including current capability-oracle-bound RT-Embed model, RFC 2397,
duplicate-ID, and complete 24-operation API evidence—with the unchanged 211
reviewed planning candidates from the prior official-Edge-model-qualified
500-row view. Candidate IDs, order, planning-only states, and evidence-empty
status remain unchanged.

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-rt-embed-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-rt-embed-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, or product API
operation. Explicit write mode changes its four generated post-state documents,
the immutable 289- and 500-row descriptors, and the metadata-set selector.
