# VIOS WebRTC live Thor qualifier

This package qualifies `protocol.vios.webrtc-live` against the shipped VIOS
Media Streams UI and live-stream API. It starts one isolated Thor-local
NvStreamer container, uploads a deterministic two-second H.264/AAC fixture
through the documented API, and negotiates a real Chromium
`RTCPeerConnection`. SDP, ICE candidates, peer IDs, and media-session IDs are
ephemeral and are never written to the retained receipt.

Run the static and retained-evidence checks:

```bash
pytest -q deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/tests
python3 deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/verify.py
```

Preview the bounded runtime transaction:

```bash
python3 deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/execute.py \
  --output deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/plan-receipt.json
```

Execute it only with the explicit acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/execute.py \
  --execute \
  --ack I_ACK_VIOS_WEBRTC_LIVE_EPHEMERAL_RUNTIME \
  --output deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/runtime-receipt.json
```

The transaction uses numeric loopback and one executor-owned Docker bridge. It
does not restart Docker, mutate service configuration, add a sensor to the
main VIOS or RT-CV deployments, call the VSS Agent generate endpoint, download
assets, or use the excluded Warehouse sample bundle. It explicitly stops the
live peer and proves exact Docker inventory, running-set, port, temporary-tree,
and main-VIOS restoration.
