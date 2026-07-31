# Thor VIOS full-UI audit — 2026-07-31

The ordinary VIOS full UI is already part of the unified Thor profile; it is
separate from the main VSS UI's smaller Video Management tab.

- `bp_developer_thor_full_2d` selects `vst-ingress`.
- Resolved Compose selects the local Linux/ARM64
  `nvcr.io/nvidia/vss-core/vss-vios-ingress:3.2.1` image at digest
  `sha256:ecee4b30ab5e76fa5d342ba4c7ade5b3f176dbb2543ccad03d07759fea2a5e47`.
- The image embeds the production `/vst-ui` SPA assets. Reviewed bundle labels
  cover the dashboard, sensor management, recording, media, live/replay,
  video wall, QoS/statistics, debug, and playback-automation surfaces.
- VIOS Nginx serves the SPA and proxies its API/WebSocket/storage routes.
- Thor HAProxy routes `/vst` and `/vst/*` to VIOS on port 30888.

The unified browser URL is `http://127.0.0.1:7777/vst/#/dashboard`; the direct
isolated URL is `http://127.0.0.1:30888/vst/#/dashboard`.

Thor overlays `deploy/docker/thor-local/vios/vst_config.json` read-only into
both the sensor and stream processor. It is byte-for-byte equivalent to the
released VIOS contract after replacing the two public Google STUN servers with
the loopback-only `127.0.0.1:3478` target. A nonempty loopback target is
intentional: an empty list activates VST's compiled Google-STUN fallback. The
focused static test also guards the two mounts, full-profile selection, VIOS
Nginx UI/API/storage routes, and unified HAProxy route.

The remaining gap is current runtime browser evidence. Qualification must
cover every navigation surface, live WebRTC over host ICE candidates, replay,
video wall, schedules, downloads, stats/debug panels, exact cleanup, absence
of external network attempts, and a pull-free restart.

The source-only `CalibrationWorkflow.tsx` is unreachable and depends on an
absent auxiliary backend on port 8003, which also conflicts with Thor's VLM
port. Calibration is therefore not counted as a VIOS UI capability here; it is
tracked by the dedicated `auto-calibration` family instead.
