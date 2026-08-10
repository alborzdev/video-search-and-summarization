# Current 500-row VIOS WebRTC live runtime successor

This deterministic successor combines the current 289-row canonical Thor
ledger—including the oracle-bound native VIOS WebRTC live qualification—with
the unchanged 211 reviewed planning candidates from the prior replay-qualified
500-row view. Candidate IDs, order, planning-only states, and evidence-empty
status remain unchanged.

The projector reuses the reviewed metadata implementation with a new explicit
source/output set. It registers a new immutable 289/500 pair and selects the
500-row view. Historical descriptors and predecessor post-state files remain
untouched.

Regenerate atomically and verify:

```bash
python3 deploy/docker/thor-local/qualification/metadata-500-current-vios-webrtc-live-runtime-successor/project.py --write
python3 deploy/docker/thor-local/qualification/metadata-500-current-vios-webrtc-live-runtime-successor/project.py
python3 deploy/docker/thor-local/parity/verify_metadata_set.py --json
```

The projector performs no Docker, network, service, GPU, model, or product API
operation. Its explicit write mode changes only the four post-state documents,
two new descriptors, and the selected-set pointer.
