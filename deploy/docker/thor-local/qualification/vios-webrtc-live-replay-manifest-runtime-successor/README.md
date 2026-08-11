# VIOS live/replay WebRTC manifest qualification

This package binds fresh, real Chromium/Playwright live and replay WebRTC runs
to official VSS 3.2.1 row 417. Live WebRTC decoded current frames and reported
PLAYING. Replay WebRTC decoded a recorded interval, continued after UI and API
seek-forward operations, and correctly rejected an unsupported action without
stopping playback.

The two source receipts retain separate `/live/` and `/replay/` WebSocket/API
routes, timing semantics, session lifecycles, and cleanup proofs. Peer IDs,
media-session IDs, SDP, and ICE candidates remain intentionally ephemeral.

Compile or verify the sanitized combined receipt without product actions:

```bash
python3 deploy/docker/thor-local/qualification/vios-webrtc-live-replay-manifest-runtime-successor/compiler.py plan
python3 deploy/docker/thor-local/qualification/vios-webrtc-live-replay-manifest-runtime-successor/compiler.py check
```

The underlying browser refresh runs use the exact acknowledgements documented
in the two source qualification packages. Neither calls the VSS Agent, changes
main VIOS configuration, mutates RT-CV, or uses the Warehouse sample.
