# Realtime alert immutable rule CRUD runtime successor

This package qualifies official VSS 3.2.1 capability row 329, `rule CRUD`, on the deployed Thor-local stack. NVIDIA's documented update operation is replacement: create the new immutable rule, verify it, and then delete the superseded rule. The package uses that contract rather than inventing an unsupported PATCH endpoint.

The harness rejects an empty prompt and a non-RTSP source without mutation, rejects PATCH on an unknown rule without implicit creation, and then creates two UUID-identified subscriptions for one owned local RTSP stream. It reads and lists both rules, proves their public identities/configurations are immutable, and proves the internal RT-VLM request identifiers are distinct while the underlying stream is shared. It deletes the old rule, requires explicit 404 on repeated delete, and waits for the replacement to produce a genuine request-correlated incident after the old request has been canceled.

Cleanup removes only the two owned rules, their incidents, their UUID-derived raw-events index, and the local publisher. Exact unrelated rule, stream, incident, and running-container digests must be restored. The excluded Warehouse sample and VSS Agent `/generate` endpoint are not used.

Run only when no realtime rules or RT-VLM streams are active:

```bash
python3 deploy/docker/thor-local/qualification/realtime-alert-rule-crud-runtime-successor/harness.py \
  --ack I_AUTHORIZE_OWNED_REALTIME_RULE_CRUD \
  --contract deploy/docker/thor-local/qualification/realtime-alert-rule-crud-runtime-successor/contract.json \
  --fixture services/alert/warmup/test.mp4 \
  --output deploy/docker/thor-local/qualification/realtime-alert-rule-crud-runtime-successor/runtime-receipt.json \
  --run-id local-rerun
```

Verify retained evidence with `python3 deploy/docker/thor-local/qualification/realtime-alert-rule-crud-runtime-successor/verify.py`.
