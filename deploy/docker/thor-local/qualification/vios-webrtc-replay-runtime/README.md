# VIOS WebRTC replay Thor qualifier

This package qualifies `protocol.vios.webrtc-replay` against the native VIOS
Recorded Streams UI and the replay control API. It uses the retained local
`pit-POV` file sensor, a real Chromium `RTCPeerConnection`, and the shipped VIOS
UI. SDP, ICE candidates, peer IDs, and media-session IDs remain ephemeral and
are never written to the retained receipt.

Run the static and evidence checks:

```bash
pytest -q deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/tests
python3 deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/verify.py
```

Preview the bounded runtime transaction:

```bash
python3 deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/execute.py
```

Execute it only with the explicit acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/execute.py \
  --execute \
  --ack I_ACK_VIOS_WEBRTC_REPLAY_EPHEMERAL_RUNTIME \
  --run-id official \
  --output deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/runtime-receipt.json
```

The transaction is numeric-loopback-only and does not restart Docker, alter
service configuration, add a VIOS or RT-CV sensor, call the VSS Agent generate
endpoint, download assets, or use the excluded Warehouse sample bundle. It
must explicitly stop the replay peer and prove exact fixture, container, and
running-set restoration.
