# Explicit native preview qualification

`native_preview.py` is source-only until the parent owns the GPU lease and runs it. The helper starts one actual native worker using the two recorded files, with a 480-observation limit and 90-second process timeout. It uses private ephemeral local HTTP consumers; it does not contact or change the canonical gateway, site, Agent or RTSP publishers.

Inside the prepared GPU container, with the saved available-memory guard active and no other GPU workload running inference, preserve NVIDIA's compatibility setup for the Python helper and its child worker:

```sh
/opt/nvidia/nvidia_entrypoint.sh \
  python3 /opt/city/tests/native_preview.py --allow-gpu \
  --config-dir /opt/city/configs \
  --model-revision YOUR_ACTUAL_ENGINE_MODEL_REVISION \
  --state-dir /state/native-preview-qualification-NEW
```

For Medium, replace the config directory with the already-generated Medium profile (576 input). The helper does not build an engine or change model selection. It requires at least the saved available-memory reserve, never below20GiB; raise its argument if the actual saved reserve is higher. Use a new output directory per run. The runtime must mount both `/media/traffic-sample.mp4` and `/media/pedestrian-sample.mp4`. Root owns image preparation, GPU launch and runtime activation.

When creating a temporary Docker qualification container, use `--entrypoint /opt/nvidia/nvidia_entrypoint.sh` and pass `python3 /opt/city/tests/native_preview.py ...` as its command, with the existing qualified GPU/resource/mount arguments. **Do not use `--entrypoint python3`**: that bypasses NVIDIA's host/driver and CUDA forward-compatibility setup. Likewise, an already-running container's `docker exec` process should invoke the NVIDIA entrypoint explicitly rather than assume that it inherits process-local environment changes from PID1.

The first bounded preview run bypassed this entrypoint and emitted480 empty-object observations despite a loaded engine and no reported inference error;285 JPEG identities/geometries still matched. The run correctly failed the unchanged positive-detection and outage gates. A subsequent preview-off80-frame control through the normal entrypoint produced76 positive frames and638 tracked objects. That isolates a launch-environment difference as a concrete candidate; it does not yet qualify preview-on behavior or prove which library/env change caused the empty outputs. The normal startup explicitly reports CUDA13.2 forward compatibility with userspace595.58 over kernel driver580.142 on this host.

The observation receiver records all480 observations, their receipt times and per-source ordered sequences. A separate preview receiver independently matches source/session/sequence/source-time/model headers to the exact already-received observation (bounded250ms metadata-race wait), checks original declared dimensions and parses JPEG SOF dimensions. It always saves the first accepted JPEG and matched observation per source as `first-SOURCE.jpg/json`, even if no objects were detected. Separately it saves one `positive-SOURCE.jpg/json` pair with positive detections per available source for visual inspection; it retains hashes for all accepted previews. First-image capture does not satisfy the positive gate. Positive detection association does not by itself prove the model's semantic accuracy or that every pixel/box is correct.

After at least240 observations, eight accepted previews and one positive match, the helper **closes the preview listener socket**. Subsequent JPEG requests encounter an unavailable endpoint. The observation server stays running. A passing receipt requires all480 complete, ordered metadata observations, at least40 after socket closure, and visible native preview HTTP failure counters. It also checks the32-identity/source and two-pending-JPEG bounds and requires valid preview images from both original source geometries. This controls a network-consumer outage, not a codec/converter plugin failure.

Inspect `receipt.json`, `worker.log`, `preview-stats.json`, received-observation/preview NDJSON and the saved positive JPEGs. If preview conversion or demux fails, the receipt should fail and expose native error/missing-image counters; do not call the browser path qualified. This helper does not establish final-city calibration, MV3DT, long-run resource stability, browser rendering, physical-clock alignment or zero performance impact. Compare sustained metadata/source-clock throughput in the separately controlled live run.

Pure helper controls do not launch inference:

```sh
python3 -m unittest discover -s /opt/city/tests -p test_native_preview_helpers.py -v
```
