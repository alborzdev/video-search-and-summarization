# RT-VLM file upload and dense captions runtime successor

This bounded qualifier closes two advertised VSS 3.2.1 behaviors against the local Thor RT-VLM service: `file upload` and `dense captions`.

One deterministic nine-second MP4 contains three planted moving-square phases. The executor rejects corrupt bytes without catalog allocation, uploads the valid file, verifies metadata and byte-for-byte content digest readback, then uses that exact asset for three ordered timestamped dense-caption chunks. A `chunk_duration=0` control must return one full-file chunk rather than a false multi-chunk result. It exact-deletes the owned file and restores the pre-existing catalog and model set.

The package uses direct loopback RT-VLM APIs and the live OpenAPI. It never calls VSS Agent `/generate`, mutates a stream, restarts a service, or uses the Warehouse sample. The receipt retains no prompt, caption text, or raw identifier.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-file-dense-captions-runtime-successor/execute.py plan
pytest -q deploy/docker/thor-local/qualification/rt-vlm-file-dense-captions-runtime-successor/tests/test_execute.py
python3 deploy/docker/thor-local/qualification/rt-vlm-file-dense-captions-runtime-successor/execute.py execute \
  --ack I_AUTHORIZE_BOUNDED_RT_VLM_FILE_DENSE_CAPTIONS_RUNTIME
```
