# Thor VIOS WebRTC replay runtime qualification — 2026-08-10

This note retains the native VIOS Recorded Streams runtime evidence collected
from the local VSS 3.2.1 stack on AGX Thor. The run used numeric loopback
endpoints and the existing retained `pit-POV` file sensor. It did not add,
remove, or modify a sensor, stream, recording, or video file.

## Thor replay corrections

The released VIOS UI initially failed before signaling for two independent
reasons:

- It concatenated an endpoint ending in `/` with the `/vst` proxy pathname,
  producing `ws://127.0.0.1:7777//vst/api/v1/replay/ws`.
- It mounted the player after confirming that a sensor had a timeline, but did
  not carry that timeline into the player. The player therefore started before
  its second asynchronous timeline request completed and used the Unix epoch
  fallback instead of the recording start.

The Thor derivative now normalizes the WebSocket path through `URL.pathname`
and carries resolved recording intervals on each replay-capable sensor. The
backend subsequently logged the correct replay URI start time,
`2025-01-01T00:00:00.000Z`, for the retained 19.205-second clip.

The production UI is built reproducibly in a two-stage image. Both the Node
builder and NVIDIA VSS 3.2.1 ingress base are content-addressed, dependencies
are installed from the checked-in locks, and the final image contains only the
compiled UI layered over NVIDIA's ingress. The deployed image is
`sha256:ea2b5c14d12753d1f319d0e808f95d6be3127edcea9674b96c3a9b759bdf1ea4`;
only `vss-vios-ingress` was recreated and it returned to `healthy`.

## Browser qualification

The final guarded Chromium run ended at `2026-08-10T08:17:31Z`, took 11.68
seconds, and passed every assertion at
`http://127.0.0.1:7777/vst/#/recorded-streams`:

1. Select the exact existing `pit-POV` replay sensor.
2. Open the normalized `/vst/api/v1/replay/ws` WebSocket.
3. Observe configuration and loopback-only ICE-server exchange.
4. Send `stream/start` with the retained recording start time.
5. Complete `setAnswer` and bidirectional ICE-candidate signaling.
6. Receive and decode advancing WebRTC video in the native VIOS player.
7. Close the replay card, send `stream/stop`, and remove the player.
8. Confirm that the canonical pre/post replay sensor inventories are equal.

The selected video reached ready state 4 with a live, unmuted video track, no
media error, and 1280x720 dimensions. Over the retained four-second sample,
browser playback advanced from 0.036 to 4.040 seconds and decoded frames rose
from 3 to 178. The visible player reported approximately 10.5 Mbps. The
browser observed configuration, ICE-server, start, answer, ICE-candidate,
status, ping, and stop messages, followed by a clean WebSocket close. No HTTP
mutation was issued, no browser page error occurred, and backend teardown
destroyed the executor-owned decoder/WebRTC pipeline after `stream/stop`.

The UI still reports two non-fatal optional-integration diagnostics:

- Streambridge version probing returns HTTP 404 because this Thor profile does
  not deploy the separate Streambridge service.
- The uncalibrated single-camera `pit-POV` sensor has no 3D homography, so the
  optional analytics-overlay calibration fetch is empty.

Neither diagnostic affects replay, and both match explicit profile/physical
calibration boundaries rather than a failed core service.

Final screenshot retained outside the repository:

- `/tmp/vss-vios-webrtc-replay-runtime.png`: 373,629 bytes, SHA-256
  `7b818f4f062b75f1854be77b030536e0b03df0142db49fdf80eb652fe52db7ca`.

Visual inspection confirms a usable native VIOS Recorded Streams view showing
the decoded NASCAR pit-stop frame, timeline, playback controls, bitrate, and
selected `pit-POV` sensor rather than a black or placeholder video surface.

## Code verification and boundary

- The VIOS WebRTC streaming library production build passed.
- VIOS UI Prettier verification, zero-warning ESLint, TypeScript compilation,
  and the Vite production build passed.
- A clean multi-stage Docker build repeated both lockfile installs and both
  production builds successfully.
- `test-thor-vios-ui.sh` passed the ingress, offline-ICE, normalized-WebSocket,
  timeline-handoff, and reproducible-image static contracts.

This evidence qualifies the native VIOS Recorded Streams UI and
`protocol.vios.webrtc-replay` on Thor. It does not claim RTSP sensor lifecycle,
physical multi-camera calibration, 3D overlays, or the separately deployed
Streambridge service.
