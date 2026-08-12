# Live-stream VLM rule runtime successor

This package qualifies official VSS 3.2.1 row 328, `live-stream VLM rules`, on Thor. It applies one natural-language rule to nine consecutive four-second inference windows covering a complete deterministic 36-second RTSP cycle: full-frame blue, green, then red, with each phase lasting twelve seconds.

RTSP readers can join a looping stream at an arbitrary phase. The oracle therefore requires the phase-invariant result: exactly three cyclically contiguous `Yes` windows for the single green phase and exactly six `No` windows for the blue/red phases. The retained run also requires raw `incidentDetected` flags and Elasticsearch incidents on exactly those three matching chunk identities, with rule/request/stream/sensor/category correlation.

Cleanup deletes the owned rule, its three incidents, the UUID-derived raw-events index, and the publisher. Public rules, persisted rules, RT-VLM streams, pre-existing incidents, and the exact 38-container running set must match their before-state digests. No external endpoint, Warehouse sample, or VSS Agent `/generate` request is used.

Run only when no realtime rules or RT-VLM streams are active:

```bash
python3 deploy/docker/thor-local/qualification/realtime-alert-live-stream-rule-runtime-successor/harness.py \
  --ack I_AUTHORIZE_OWNED_LIVE_STREAM_VLM_RULE \
  --contract deploy/docker/thor-local/qualification/realtime-alert-live-stream-rule-runtime-successor/contract.json \
  --output deploy/docker/thor-local/qualification/realtime-alert-live-stream-rule-runtime-successor/runtime-receipt.json \
  --run-id local-rerun
```

Verify retained evidence with `python3 deploy/docker/thor-local/qualification/realtime-alert-live-stream-rule-runtime-successor/verify.py`.
