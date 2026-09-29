# RTSP replay transport stage

September 28, 2026. Goal: qualify transport before browser playback or analysis.
Used the VIOS/NvStreamer API workflow and existing local configuration; no
deployment, image pull, detector or live analysis job was started.

## Findings

- VIOS is reachable at port 30888 and reports version 2.1.0-26.05.4.
- Existing configured RTSP sources retain old Thor proxy addresses
  (`10.88.8.175`). VIOS sensor status reports CameraNotFoundError for their
  active streams. Four Isaac Sim catalog records name upstream host
  `10.88.8.191`; its current identity and scene remain unconfirmed.
- The local replay publisher was stopped by the earlier guard trip. Its mounted
  configuration uses HTTP 31000 and RTSP server instances starting at 31554,
  with a 4 GiB container cap and host networking.

## Bounded action and result

Started only the existing `vss-vios-nvstreamer` container. A startup check would
stop it if available memory fell below 49 GiB, above the unchanged guard floor
of 48 GiB. It returned type streamer/version 2.1.0-26.05.4 with 50.203 GiB
available. Advertised RTSP URLs now use current Thor address `10.88.9.12`.

Inspected `/sensor/streams`, retained as `nvstreamer-replay-streams.json`.
Decoded one frame from the returned conveyor RTSP URL with TCP transport,
software ffmpeg decoding, one-frame output and a 12-second external timeout.
Process exited 0; the frame visibly shows the expected simulated conveyor.
Evidence: `conveyor-rtsp-frame.jpg`. Post-decode memory: 50.090 GiB available.

## Scope and next stage

Publisher remains running, with no new VIOS camera or continuous-analysis job
registered. Existing desired-analysis states remain unchanged. This proves a
bounded RTSP replay decode, not live browser playback, fresh indexing, alerts
or connection to a running Isaac Sim scene.

Source inspection: Agent's `/api/v1/rtsp-streams/add` currently registers the
sensor and starts the chosen analysis profile. It has no preview-only option.
Do not assume adding through that endpoint is a transport-only action. Next
provide an explicit preview-only connection path with persisted paused analysis,
then qualify VIOS/WebRTC against this labeled recorded simulation before
enabling any bounded analysis workload. Preserve old source records for recovery.
