# RT-VLM absolute timestamp runtime successor

This package closes `manifest-entry.rt-vlm-performance-observability.07-absolute-timestamp-metadata` against the current Thor-local RT-VLM service.

It generates one deterministic eight-second timestamp-burned MP4 and uploads it with a fixed UTC source time. A bounded 2–6 second request must return timestamp-mode `media_info`, two exact absolute chunk windows aligned to the fixture clock, nonempty inference, frame counts, and per-chunk latency metrics. The adjacent negative submits a malformed noncanonical absolute source timestamp and requires structured HTTP 422 before any asset is created.

The executor calls direct loopback RT-VLM APIs only. It never calls VSS Agent `/generate`, adds a stream, restarts a service, or uses the Warehouse sample. It exact-deletes its one owned asset, restores the complete pre-existing RT-VLM file catalog, and retains no prompt, caption text, or raw resource identifier.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-absolute-timestamps-runtime-successor/execute.py plan
pytest -q deploy/docker/thor-local/qualification/rt-vlm-absolute-timestamps-runtime-successor/tests/test_execute.py
python3 deploy/docker/thor-local/qualification/rt-vlm-absolute-timestamps-runtime-successor/execute.py execute \
  --ack I_AUTHORIZE_BOUNDED_RT_VLM_ABSOLUTE_TIMESTAMP_RUNTIME
```
