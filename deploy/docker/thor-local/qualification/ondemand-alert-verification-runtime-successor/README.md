# Thor multi-category and on-demand alert-verification runtime evidence

This package qualifies official capability rows 324 and 325, `multi-category classification` and `on-demand verification`, against the running Thor-local Alert Bridge, local Cosmos 3 VLM, and local Elasticsearch sink. It serves only the bundled 10-second warehouse fixture on numeric loopback, creates two uniquely owned verifier configs, and submits two positive jobs. Both mappings—including a case-normalized input alias—produce distinct persisted output categories with deterministic `completed / verified / confirmed` results, reasoning, and `OK` parse status. The run also proves pre-publish cancellation for an independent job, rejects an unknown category, removes uniquely tagged backend publications produced by the local RT-VLM, and restores every externally observable pre-state projection exactly.

Run from the repository root:

```bash
python3 deploy/docker/thor-local/qualification/ondemand-alert-verification-runtime-successor/harness.py \
  --contract deploy/docker/thor-local/qualification/ondemand-alert-verification-runtime-successor/contract.json \
  --acknowledgement I_AUTHORIZE_OWNED_ONDEMAND_ALERT_VERIFICATION \
  --run-id thor-ondemand-YYYYMMDDa \
  --output deploy/docker/thor-local/qualification/ondemand-alert-verification-runtime-successor/runtime-receipt.json
```

The run never calls VSS Agent `/generate`, never uses the warehouse sample bundle or external network, and refuses to delete anything that lacks either the exact event/sensor ownership tuple or the unique prompt token plus RT-VLM source identity. It waits for both backend publications to become observable before cleanup, preventing a cancelled inference from publishing after the final snapshot. Completed/cancelled HTTP job receipts are process-local and remain bounded by Alert Bridge's one-hour TTL because the released API has no terminal-receipt purge route; all configs, sink documents, streams, rules, and container state are restored exactly.

Verify retained evidence with `python3 deploy/docker/thor-local/qualification/ondemand-alert-verification-runtime-successor/verify.py`.
