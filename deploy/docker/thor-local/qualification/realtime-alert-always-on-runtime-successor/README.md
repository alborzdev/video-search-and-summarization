# Realtime alert always-on runtime successor

This package qualifies official VSS 3.2.1 capability row 331, `always-on lifecycle`, on the deployed Thor-local stack. It uses the small bundled alert fixture and a uniquely owned local RTSP path; the excluded warehouse sample is not used.

The harness registers one owned RT-VLM camera, posts `camera_streaming`, proves a repeated event is idempotent, restarts only Alert Bridge, and posts the event again. Direct RT-VLM worker logs prove restart recovery stops the surviving caption worker before creating one replacement. A second duplicate remains inert, and `camera_remove` removes the declared rule, worker, and stream. Exact unrelated state and the running-container set are restored.

Run only when no realtime rules are active:

```bash
python3 deploy/docker/thor-local/qualification/realtime-alert-always-on-runtime-successor/harness.py \
  --ack I_AUTHORIZE_OWNED_REALTIME_ALWAYS_ON_AND_ALERT_BRIDGE_RESTART \
  --contract deploy/docker/thor-local/qualification/realtime-alert-always-on-runtime-successor/contract.json \
  --fixture services/alert/warmup/test.mp4 \
  --output deploy/docker/thor-local/qualification/realtime-alert-always-on-runtime-successor/runtime-receipt.json \
  --run-id local-rerun
```

Verify retained evidence with `python3 deploy/docker/thor-local/qualification/realtime-alert-always-on-runtime-successor/verify.py`.
