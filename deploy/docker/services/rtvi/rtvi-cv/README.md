# Perception Module

Shared DeepStream perception stack used across all blueprints: the published `vss-rt-cv` image plus a repo-local unified entrypoint (`ds-start.sh`, bind-mounted) supporting warehouse RT-DETR, RT-DETR+GDINO, and Sparse4D model families.

## Running Standalone

Blueprint compose files still expect `VSS_APPS_DIR` to be the **`deployments` root** (so paths like `$VSS_APPS_DIR/developer-profiles/...` resolve). The `rtvi/rtvi-cv/compose.yaml` bind mount for `ds-start.sh` is **`./ds-start.sh`** relative to that file, so it does not use `VSS_APPS_DIR` and cannot double up when your env points at `.../rtvi/rtvi-cv`.

Standalone smoke test:

```bash
cd deploy/docker/services/rtvi/rtvi-cv
docker compose -f compose.yaml up
# With SDR: docker compose -f compose.yaml --profile sdr up
```

## Configuration

| Variable            | Default                                 | Description                                                                                                                |
|---------------------|-----------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `DS_MODEL_FAMILY`   | `rtdetr-warehouse`                      | Model family: `rtdetr-warehouse` (aliases `cnn`), `rtdetr-gdino` (alias `rtdetr`), `sparse4d-warehouse` (alias `sparse4d`) |
| `DS_MODE_FLAG`      | `1`                                     | DeepStream `-m` parameter                                                                                                  |
| `DS_MESSAGE_RATE`   | `1`                                     | `--message-rate` parameter                                                                                                 |
| `DS_TRACKER_REID`   | `false`                                 | `true` stages/enables tracker ReID; `false` sets `reidType: 0` and avoids an unrelated ReID engine build                  |
| `DS_SHOW_SENSOR_ID` | `false`                                 | Enable `--show-sensor-id`                                                                                                  |
| `DS_CONFIG_FILE`    | `run_config-api-rtdetr-protobuf700.txt` | Config file (RT-DETR+GDINO path)                                                                                           |
| `MODEL_TYPE`        | `cnn`                                   | Model type for the perception app                                                                                          |
| `STREAM_TYPE`       | `kafka`                                 | Message broker: `kafka` or `redis`                                                                                         |
| `NUM_SENSORS`       | `30`                                    | Batch size (RT-DETR/GDINO)                                                                                                 |
| `MODEL_NAME_2D`     | —                                       | Set to `GDINO` for GDINO model                                                                                             |

### Thor RT-DETR engine cache

TensorRT 10 may reject the legacy explicit FP16 builder flag for the Smart
City FP16 ONNX and retry in strongly typed mode. On `AGX-THOR`, that fallback
serializes the generated engine beside the ONNX model. The entrypoint therefore
sets `model-engine-file` to
`/opt/storage/rtdetr-its/model_epoch_035.fp16.onnx_b<NUM_SENSORS>_gpu0_fp16.engine`.
Mount `/opt/storage/rtdetr-its` read-write to retain the first build; keeping
only `/opt/engines` writable is insufficient for this model on Thor.

The HTTP service can report ready before a first engine build has completed,
and the pipeline instance that performed the build may not accept a useful
finite source afterward. For deterministic first deployment, use one isolated
instance to trigger the engine build, wait for the cache file, then replace it
with a fresh instance before adding production streams. Removing an
already-ended source is not idempotent and returns a pipeline error.
Subsequent launches reuse the cache and do not need this build phase.

## Blueprint Integration

Blueprints use `extends` on `compose.yaml` and add blueprint-specific volumes and environment (configs and models are bind-mounted into the image):

```yaml
services:
  perception-2d:
    extends:
      file: $VSS_APPS_DIR/rtvi/rtvi-cv/compose.yaml
      service: perception
    profiles: ["my_profile"]
    container_name: vss-rtvi-cv
    volumes:
      - $VSS_APPS_DIR/my-blueprint/deepstream/configs/ds-main-config.txt:/opt/.../ds-main-config.txt
    environment:
      DS_MODEL_FAMILY: rtdetr-warehouse
```

SDR services extend `perception-sdr` from the same `compose.yaml` and override only the WDM env vars that differ.

## Files

```
deploy/docker/services/rtvi/rtvi-cv/
├── ds-start.sh          # Unified entrypoint
├── compose.yaml         # Base services for `extends` + standalone
└── README.md
```
