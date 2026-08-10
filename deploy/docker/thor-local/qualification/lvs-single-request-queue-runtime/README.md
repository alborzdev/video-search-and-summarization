# Thor LVS one-video-at-a-time runtime qualification

This package proves NVIDIA VSS 3.2.1 LVS's advertised GPU-utilization
boundary on Thor. The current FAQ says LVS processes one video at a time and
that batch processing requires an external queue system. It does **not**
advertise a built-in batch scheduler.

The acknowledgement-gated executor derives one tiny MP4 from the tracked
ten-second fixture, uploads two byte-identical copies under fixed
qualifier-owned IDs, and submits two summaries within a 50 ms start-skew
bound. It samples LVS outstanding-work metrics while the requests run and
requires a `2 -> 1 -> 0` transition. Separately, it binds the running
`cosmos-reason3` topology to one VLM server process, one GPU, batch size one,
and one in-flight model slot using exact environment, process flags, mounts,
source literals, byte sizes, and SHA-256 values.

The proof does not claim that the HTTP API, media decoding, or response
post-processing is globally serialized. Those stages can overlap. The
qualified contract is the one-video-at-a-time VLM processing boundary, while
batch scheduling remains external.

```bash
python3 deploy/docker/thor-local/qualification/lvs-single-request-queue-runtime/execute.py plan

python3 deploy/docker/thor-local/qualification/lvs-single-request-queue-runtime/execute.py \
  execute \
  --ack I_ACK_LVS_TWO_REQUEST_QUEUE_AND_EXACT_CLEANUP

python3 deploy/docker/thor-local/qualification/lvs-single-request-queue-runtime/verify.py
```

Execution uses numeric loopback only. It never calls the VSS Agent, registers
RTSP, changes service lifecycle, stages a model, or uses the Warehouse sample
bundle. Cleanup removes only owned files actually created by the run and
requires exact pre/post service and resource state.
