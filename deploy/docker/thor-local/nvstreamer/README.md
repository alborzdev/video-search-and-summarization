# NVStreamer on Thor

## Current October candidate

When `.thor/settings.json` exists, use the guarded sidecar helper:

```bash
python3 tools/thor/nvstreamer.py start
python3 tools/thor/nvstreamer.py upload /absolute/path/to/video.mp4
python3 tools/thor/nvstreamer.py list
python3 tools/thor/nvstreamer.py status
python3 tools/thor/nvstreamer.py stop
```

The native ARM64 image is staged once with `python3 tools/thor/nvstreamer.py stage`.
Stop AI services before staging; it requires the active 48 GiB guard, 90 GiB
available memory, and 200 GiB free disk. It pins the NVIDIA 3.2.1 ARM64 base,
uses the reviewed October codec lock in a networkless build, and fixes the
vendor CUDA driver lookup for JetPack. Restore the models in the documented
[Thor startup order](../../../../tools/thor/README.md).

For a cold recovery with an existing mock source, start NVStreamer before the
VIOS support stage. VIOS can retain an offline sensor status when the upstream
is absent at startup. Keep analysis paused during model restoration, then check
the camera's connection and enable capture explicitly.

The optional sidecar joins project `vss-thor` so the existing guard covers it.
Start requires its full 4 GiB ceiling above the 48 GiB diagnostic reserve.
Its private media and state are under `.thor/data/nvstreamer/`; it does not
reuse VIOS recordings. Stop affects only this service. It does not restart
automatically after reboot. WebRTC uses its own `32001-32100` port pool and
external STUN is disabled for this local mock-camera server.

Open `http://<Thor-LAN-IP>:31000` to upload media or copy the generated RTSP
URL. Add that exact URL in VSS **Live cameras**, then explicitly enable capture
and the desired analysis profile. Uploading into NVStreamer alone does not
start VSS recording or AI. The tested fixture is single-slice H.264, 720p,
10 FPS; other encodings require their own runtime checks.

## Historical standalone wrapper

This wrapper runs NVIDIA NVStreamer as a persistent, local MP4/MKV-to-RTSP
service alongside the Thor VSS deployment. It uses the already-built
Thor-compatible image and NVIDIA's VSS 3.2.1 NvStreamer configuration.

## Start and stop

```bash
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh start
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh status
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh stop
```

The container uses `restart: "no"`, so a host reboot leaves media sources
stopped until an operator explicitly starts them after runtime safety checks.

## Create a stream

Open `http://<THOR-IP>:31000` from Thor or another device on the LAN. Upload an
H.264/H.265 MP4 or MKV with no spaces in its filename. NVStreamer loops the
file and displays the generated RTSP URL after processing it.

Uploaded media persists under the ignored runtime directory:

```text
deploy/docker/data-dir/videos/nvstreamer/
```

List generated streams from the terminal with:

```bash
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh list
```

Use the exact URL returned by NVStreamer; RTSP ports are assigned dynamically
from the configured `31554-31561` pool.
