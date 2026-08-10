# Thor RT-Embed current-runtime qualification

This package proves four NVIDIA VSS 3.2.1 RT-Embed contracts against the
already-running local Thor service:

- exact `Cosmos-Embed1-448p-anomaly-detection` model and generated fp16 Triton
  repository;
- RFC 2397 `data:` video embedding;
- duplicate camera and stream ID conflict behavior; and
- the complete documented 22-path, 24-operation REST surface.

The acknowledgement-gated executor verifies both multi-gigabyte artifact
trees directly from their existing Docker volumes, checks immutable runtime
identity and safe offline environment, and exercises text, uploaded-file,
data-URL, and live-RTSP embeddings. The RTSP source is an isolated MediaMTX
helper bound only to the RT-Embed Docker bridge gateway and fed by the tracked
10-second H.264 fixture.

The executor uses fixed oracle-owned UUIDs and namespaces. It captures complete
file, batch-stream, single-stream, asset-statistics, container, helper, and
operator-paused-workload pre-state. On every exit it attempts exact cleanup;
the retained passing receipt proves all inventories and runtime identity match
pre-state, the RTSP path is gone, and every publisher/helper is absent.

It does not pull or build images, stage models, restart services, use external
network endpoints, mutate VIOS, add an RT-CV sample stream, call the VSS Agent,
or use the Warehouse sample bundle. The negative `file://` test proves only the
unset-allowlist fail-closed branch; it intentionally does not promote the full
positive/traversal allowlist capability.

```bash
python3 deploy/docker/thor-local/qualification/rt-embed-current-runtime/execute.py

python3 deploy/docker/thor-local/qualification/rt-embed-current-runtime/execute.py \
  --ack I_ACK_RT_EMBED_CURRENT_RUNTIME_AND_EXACT_REVERSIBLE_CLEANUP

python3 deploy/docker/thor-local/qualification/rt-embed-current-runtime/verify.py
```

The first command is inert and fails with `acknowledgement_required`. The live
run is bounded to 900 seconds, 50 total HTTP requests, four semantic actions,
three disposable helper containers, numeric loopback HTTP, and private local
Docker-bridge RTSP. It requires at least 10 GiB free disk but does not duplicate
the model artifacts.

Retained JSON contains hashes, sizes, counts, fixed public model identities,
status codes, booleans, and durations. It excludes credentials, request/session
IDs, raw prompts, raw vectors, response bodies, RTSP URLs, SDP/ICE, and absolute
home paths.
