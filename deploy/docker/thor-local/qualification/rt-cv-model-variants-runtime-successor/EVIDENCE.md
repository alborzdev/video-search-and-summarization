# RT-CV detector-model variants evidence

Official VSS 3.2.1 capability row 376 is runtime-qualified on this Thor by
`runtime-receipt.json` (SHA-256
`db43ea19a539ae5f060dd82edc48220d65d5a1b21cdc03786d299f02f89b135b`).
The receipt validates against `receipt.schema.json` and is bound to contract
SHA-256 `ac080b146981a0456216a9dd1f2a176ffe91d57199cb72e3f6673ae5e55fe187`.

## Runtime result

The final cached run completed in 84.31 seconds using the exact VSS 3.2.1
arm64 RT-CV and behavior-analytics images. It issued 79 bounded Docker commands
and 57 bounded HTTP requests while preserving 23,182,381,056 free bytes.

| Detector identity | Runtime backend | Engine | Observed result |
| --- | --- | --- | --- |
| Warehouse RT-DETR | inherited source-locked core proof | `13bd7a67...` | 8 file frames and 8 RTSP frames with Person/Pallet detections and tracking |
| Smart City RT-DETR | `nvinfer`, mode 7 | 95,010,612 bytes, `b31731f5...` | 21 objects across 8 frames; `car` and `person`; 3 repeated track IDs |
| Smart City Grounding DINO | Triton, mode 4, exact `person` prompt at 0.5 | 375,220,204 bytes, `3b9d6359...` | 8 `person` objects across 8 frames; one persistent track ID |

Both Smart City lanes proved a real dynamic REST stream add, positive frame and
FPS metrics, finite latency, eight decoded protobuf broker messages, finite
boxes/confidences, exact sensor correlation, successful stream removal, zero
container restarts, and no OOM kill.

## Thor corrections proved

- Smart City RT-DETR uses its writable ONNX-adjacent TensorRT cache on Thor.
- Tracker ReID is explicitly disabled without disabling NvDCF tracking.
- The deployable alerts profile disables simulation-only SEI time extraction
  and backward-SEI dropping, matching NVIDIA's checked-in Smart City reference
  configs so ordinary customer H.264 video reaches inference.
- The isolated loopback RTSP fixture uses host networking and unique
  loopback-only RTSP/RTP/RTCP ports because dynamically added sources select
  UDP after application startup.

## Safety and cleanup

No Warehouse sample bundle was downloaded. The proof made zero VSS Agent
calls and zero mutations to the main RT-CV or VIOS stream sets. Its MediaMTX,
RT-CV, consumer, Kafka topic/group, temporary files, and publisher were removed
exactly. The main healthy RT-CV container remained unchanged with zero streams,
and the three intentionally paused unrelated workloads retained their state.
Only the two reusable Smart City TensorRT engines remain.

## Regression command

```bash
python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/rt-cv-model-variants-runtime-successor/tests \
  -v
```

Result: 8 tests passed.
