# RT-VLM local-media runtime successor

This bounded current-Thor qualifier proves the exact VSS 3.2.1 advertised rows for allowlisted `file://` video input and inline `data:` video input through the direct loopback RT-VLM API.

The positive cases use the deterministic nine-second blue/green/red fixture and require ordered semantic recognition. The adjacent-negative cases require structured rejection for a symlink escape, a traversal escape, a non-allowlisted absolute path, a mismatched inline MIME type, and malformed base64. The executor also proves exact catalog, asset-statistics, model-inventory, cache-inventory, fixture, and owned-path cleanup.

The executor is inert by default. Acknowledged execution is limited to 13 loopback HTTP requests, two model calls, and 11 bounded commands against the named RT-VLM container. It does not call VSS Agent `/generate`, mutate streams, restart services, access the Warehouse sample, or retain prompts, generated text, raw resource IDs, or container IDs.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-local-media-runtime-successor/execute.py plan
pytest -q deploy/docker/thor-local/qualification/rt-vlm-local-media-runtime-successor/tests/test_execute.py
python3 deploy/docker/thor-local/qualification/rt-vlm-local-media-runtime-successor/execute.py execute \
  --ack I_AUTHORIZE_BOUNDED_RT_VLM_LOCAL_MEDIA_RUNTIME
```
