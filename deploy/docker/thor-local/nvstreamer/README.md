# NVStreamer on Thor

This wrapper runs NVIDIA NVStreamer as a persistent, local MP4/MKV-to-RTSP
service alongside the Thor VSS deployment. It uses the already-built
Thor-compatible image and NVIDIA's VSS 3.2.1 NvStreamer configuration.

## Start and stop

```bash
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh start
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh status
./deploy/docker/thor-local/nvstreamer/nvstreamer.sh stop
```

The container uses `restart: unless-stopped`, so it returns after a host reboot.

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

