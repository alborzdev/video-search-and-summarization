# RT-CV 2D core runtime qualification

This package is the retained Thor proof for four VSS 3.2.1 RT-CV 2D
capabilities:

- official row 375: file and stream detection/tracking;
- official row 380: dynamic stream lifecycle;
- official row 381: health and metrics; and
- official row 382: Thor VPI tracker tuning.

The executor uses the cached VSS 3.2.1 RT-CV image, cached Warehouse RT-DETR
and SigLIP2 artifacts, and the small checked-in `services/alert/warmup/test.mp4`
fixture. It does not download or use the excluded Warehouse sample bundle.

## Run

Plan mode is read-only:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-2d-core-runtime-successor/executor.py plan
```

Runtime mode requires the exact acknowledgement and writes the schema-validated
receipt only after cleanup succeeds:

```bash
python3 deploy/docker/thor-local/qualification/rt-cv-2d-core-runtime-successor/executor.py \
  execute \
  --ack I_ACK_ISOLATED_RT_CV_FILE_RTSP_LIFECYCLE_AND_EXACT_CLEANUP \
  --write-receipt
```

The executor creates only qualifier-owned resources: one isolated RT-CV
container, two short-lived protobuf consumers, one MediaMTX container, one
loopback FFmpeg publisher, one Kafka topic, and two consumer groups. It never
adds a stream to the main RT-CV or VIOS services. It verifies the main RT-CV
snapshot and the intentionally paused workloads before and after the run.

## Claim boundary

This package does not claim the adjacent RT-CV rows for Smart City/GDINO,
RADIO-CLIP, SigLIP2 occlusion/re-entry identity, or RT-CV on-demand image
embedding. Those require separate exact runtime oracles. The 1,152-dimensional
SigLIP2 vectors retained here are supporting evidence for the two detection
lanes, not promotion evidence for the occlusion/re-entry row.

No raw broker message, camera identity, stream URL, bounding box, confidence,
track identity, or embedding vector is retained. The receipt contains only
bounded aggregate counts, booleans, dimensions, metric family names, and
SHA-256 digests.
