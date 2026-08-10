# Thor RT-CV search-profile runtime — 2026-08-10

This receipt retains the local, no-stream recovery and readiness evidence for
the VSS 3.2.1 `perception-2d-fusion` service on NVIDIA Thor. The observation
was captured at `2026-08-10T06:40:22Z` from source revision
`69ac3e4abb520bd1cd2f7232af03e257609ce255` plus the reviewed changes in this
milestone.

## Root cause and repair

The search profile's `[primary-gie]` configuration runs with `batch-size=16`,
but `ds-pgie-config.yml` pointed at an `_b8_gpu0_fp16.engine` filename. A valid
batch-16 engine had already been generated on this Thor. On the first recovery
start, DeepStream could not open the nonexistent batch-8 path, retried the
strongly typed FP16 ONNX without an explicit FP16 builder flag, and remained in
`startup=NO` while rebuilding. The container was not OOM-killed
(`OOMKilled=false`).

The engine path now matches the effective batch size:

```text
/opt/storage/rtdetr_warehouse_v1.0.2.fp16.onnx_b16_gpu0_fp16.engine
```

After the targeted container restart, DeepStream logged successful
deserialization at `0:00:06.401459211` and `startup=YES` was observed at
`2026-08-10T06:36:13Z`. No engine rebuild was required. The Thor official-edge
overlay also sets this service to `restart: unless-stopped`; the live Docker
policy was read back as `unless-stopped` so an ordinary host reboot restores
the service while a deliberate operator stop remains respected.

## Exact runtime identity

- Image: `nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1`
- Image/config digest:
  `sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458`
- Architecture: `arm64`
- RT-DETR ONNX SHA-256:
  `0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267`
- Thor batch-16 TensorRT engine SHA-256:
  `13bd7a67da81b1a9d59a7a1b5cd577d8208ef1a77b5568f5b02f00590d484e69`
- Container: `vss-rtvi-cv`, `running`, Docker health `healthy`
- Container start: `2026-08-10T06:35:56.499465893Z`

The decisive DeepStream log record was:

```text
NvDsInferContext[UID 1]: ... deserialized trt engine from :/opt/storage/rtdetr_warehouse_v1.0.2.fp16.onnx_b16_gpu0_fp16.engine
```

## Read-only REST observations

All requests returned HTTP 200 from numeric loopback port 9000:

| Endpoint | Required observation | Observed |
|---|---|---|
| `/api/v1/live` | DeepStream liveness | `ds-liveness=YES` |
| `/api/v1/ready` | Pipeline readiness | `ds-ready=YES` |
| `/api/v1/startup` | Initialization complete | `ds-startup=YES` |
| `/api/v1/health/get-dsready-state` | Compose health contract | `ds-ready=YES` |
| `/api/v1/metrics` | Metrics schema and system counters | HTTP 200, GPU and CPU utilization present |
| `/api/v1/stream/get-stream-info` | No unapproved resource mutation | `stream-count=0` |

At capture time the host had `31,971,766,272` bytes of available memory and
`30,828,290,048` bytes free on `/`. The system cache cleaner remained active;
no second cleaner was started.

## Test evidence and boundary

The official-edge suite passed `47/47`, including exact service-set
fail-closure, resolved Compose restart policy, and a regression check binding
the engine filename suffix to the effective primary-GIE batch size. The Thor
Smart City static/runtime-contract script also passed, including its offline
GraphML behavior-analytics check.

This receipt proves RT-CV container recovery, exact local model/engine
identity, no-rebuild initialization, REST liveness/readiness/startup/metrics,
zero-stream prestate, and reboot policy. It intentionally does **not** qualify
stream add/remove, detection output, tracking output, search embeddings, or UI
ingestion. Those require a separately acknowledged, owned temporary stream
run and cleanup evidence.
