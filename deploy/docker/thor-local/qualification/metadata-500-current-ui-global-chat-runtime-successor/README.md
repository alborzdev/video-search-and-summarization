# Current 500-row Global Chat runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the oracle-bound Global Chat sidebar runtime qualification—
with the unchanged 211 reviewed planning candidates from the prior Agent
WebSocket-qualified 500-row view. Candidate IDs, order, planning-only states,
and evidence-empty status remain unchanged.

Regenerate atomically and verify:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-ui-global-chat-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-ui-global-chat-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, browser, or
product API operation. Its explicit write mode changes only the four post-state
documents, two descriptors, and the selected-set pointer. It does not use the
Warehouse sample bundle.
