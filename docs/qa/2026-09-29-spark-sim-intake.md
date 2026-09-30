# Spark Sim RTSP intake — September 29, 2026

Status at intake: the user-supplied stream responds and CPU video decoding works.
This receipt preserves the period when VSS was stopped and the Moondream decision
was pending. The user subsequently authorized stopping Moondream and disabling
its automatic startup. VSS now runs alongside Sim; live preview, a fresh answer
and exact playback pass after a Spark VST TCP configuration repair. See the
[joint trial receipt](2026-09-29-spark-sim-joint.md) for current results and state.
The user-authorized Spark reserve remains **24 GiB**.

## Later guard trip and actual Sim workload

- At **21:06:47 EDT** (September 30, 01:06:47 UTC), a later guard sample reaches
  **23.8978958 GiB** available. All 30 running VSS containers stop; each stop
  command exits 0. The earlier successful 180-second observation does not cover
  this later operating interval.
- Boot ID remains `6b100cd0-2daa-4ef5-8db5-2b4c0bee5201`. The trip receipt is
  retained under ignored `.spark/guard-trip-after-attempt-10.json`.
- The current native Isaac Sim renderer, PID 1681651, starts at **21:29:33 EDT**.
  Its RTSP worker, PID 1682838, starts at **21:30:31 EDT**. These processes start
  after the trip; the trip's cause is not established.
- GPU process observations show renderer 4097 MiB, RTSP worker 212 MiB, and
  Moondream Python PID 3642 at 23423 MiB. These are process observations, not
  complete workload memory or simultaneous peak measurements.
- `isaacsim-mcp` and `moondream-photon-dgx-spark` remain running. No Sim or
  Moondream configuration/process has been changed during this intake.
- The user `vss-spark-guard.service` is active with `floor_gib=24`. Saved settings
  retain `reserve_gib=24` and `cached_models=true`. Available host memory is
  approximately 77.9 GiB with VSS stopped and the other workloads running.

## Stream evidence

- URL: `rtsp://10.88.9.91:8554/digital-twin`, supplied by the user.
- TCP RTSP DESCRIBE succeeds with HTTP-style status 200 and an H.264 SDP track.
  The local MediaMTX path API also reports the path ready with an H264 track.
- FFprobe reports H.264 at **1280×720**. Its nominal rate fields do not establish
  delivered frame rate. The publisher source targets 30 pushes per second, with
  a latest-frame slot and leaky queues; a push can repeat the held viewport frame.
- A decoded JPEG shows a hospital corridor with wheeled monitor carts. This is
  a different scene from the earlier recorded conveyor fixture. No person is
  visible in that reviewed frame.
- An extended CPU capture produces an **8.000-second**, **1,901,868-byte** H.264
  MP4 with **480 output frames**. Offline decoding processes all 480 frames with
  no warnings/errors. The re-encoder duplicates frames, so this proves a readable
  clip and does not establish a 60 fps source or smooth live delivery. Earlier
  shorter attempts produced empty output; receiver delay/timing needs checking.
- A CPU-only local ARM64 Ubuntu/FFmpeg image supports the probes. No host package
  or GPU inference runtime is changed. Media, detailed logs and metadata remain
  private under ignored `.spark/sim-probe/`.

## Passthrough timing probe

One **60.269-second** TCP receiver probe decodes to a null sink with `showinfo`
and `-fps_mode passthrough`, without encoding, a rate filter or output frame
duplication. Host monotonic timestamps record arrival of each decoded frame.
The timeout ends the deliberately bounded run (exit 124); it is not counted as
an unexpected process failure.

| Measurement | Observed |
| --- | ---: |
| First decoded frame from probe launch | 32.932 s |
| Decoded frames | 56 |
| PTS span of decoded frames | 26.966 s |
| Host arrival span of decoded frames | 26.999 s |
| PTS gap median / p95 / maximum | 0.0357 / 1.0016 / 1.0022 s |
| Arrival gap median / p95 / maximum | 0.0666 / 1.0029 / 1.0038 s |
| Unique decoded frame checksums | 51 |

The observed count is about two decoded frames per second over that post-start
span. More specifically, 30 frames arrive in roughly one second, followed by
26 frames at approximately one-second intervals; the median gap obscures this
slower phase. Matching PTS and arrival gaps suggest sparse upstream delivery,
but the source of that behavior is not established. This is a receiver result,
not a complete measurement of fresh viewport rendering or the cause of sparse
delivery. It explains why the short capture attempts were insufficient and
prevents claiming smooth 30 fps delivery. Detailed evidence is retained locally
as `.spark/sim-probe/passthrough-decode.json` and `passthrough-decode.log`.

No decoder errors appear. The first decode is an I-frame. Delayed keyframe
availability is plausible because the publisher's `gop-size=30` counts encoded
frames, but this is a hypothesis. Follow-up should compare fresh viewport
captures, worker pushes, actual encoder output/keyframes and leaky-queue drops.

## Gates recorded at intake (superseded by joint trial receipt)

1. Resolve the pending Moondream decision before full VSS startup. Do not infer
   permission from the supplied RTSP URL. Preserve the 24 GiB guard and active Sim.
2. Investigate the demonstrated first-frame delay and sparse delivery with the
   Sim publisher owner before accepting live preview. Do not infer the cause
   from advertised rate fields or the publisher's push counter.
3. Once memory is available, use the saved cache-only staged bootstrap. Record
   actual model warmup, minimum memory, boot ID and fresh visual answers with Sim
   active; container health alone is insufficient.
4. Add one initially paused semantic-search source, then perform a bounded live
   preview/recent-window question and visible-condition rule in the browser.
   Correlate the source, rule, incident, trigger frames and playable evidence.
5. Obtain scene/reset controls for repeatable negative/positive trials. The
   visible hospital carts can inform a first prompt but do not establish accuracy.
6. Remove only test-owned rules, pause analysis/captioning and stop recording
   afterward. Preserve source history and retained evidence. Sustained monitoring
   remains unqualified.
