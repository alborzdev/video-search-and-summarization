# Thor RT-VLM SSE runtime qualification

This package turns the current Thor RT-VLM deployment into retained,
oracle-bound evidence for six NVIDIA VSS 3.2.1 capabilities:

- the default Cosmos3 Nano BF16 model artifact and served identity;
- caption Server-Sent Events (SSE);
- generation-token, user-prompt, and system-prompt limits; and
- the `/v1/generate_captions` endpoint rename.

The executor is inert unless the exact lifecycle acknowledgement is supplied.
Its only mutation is one fixed, preflight-absent RT-VLM file UUID. It uploads the
tracked 2.6 MB ten-second clip, exercises the exact boundary pairs and caption
SSE vector, deletes that UUID, and requires the asset store and container state
to match pre-state. It never calls the VSS Agent, registers RTSP, changes VIOS,
pulls an image/model, restarts a service, uses the warehouse bundle, or reaches
an external network.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/execute.py plan

python3 deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/execute.py \
  execute \
  --ack I_ACK_RT_VLM_OWNED_FILE_UPLOAD_AND_EXACT_DELETE \
  --write

python3 deploy/docker/thor-local/qualification/rt-vlm-sse-runtime/verify.py
```

`execute --write` refuses to overwrite an existing receipt. The checked-in
receipt is immutable evidence; use a fresh worktree or explicitly archive a
prior receipt before a new qualification run.
