# Thor NVStreamer and live VSS acceptance — October 8, 2026

The native NVIDIA NVStreamer sidecar loops an owned H.264 fixture into the
current Thor VSS candidate. Recording, CUDA detection, semantic search,
appearance search, live visual questions, alerts and retained report playback
passed the checks below. This qualifies the tested single-camera workload for
a bounded run; it does not qualify unlimited ingestion, additional cameras,
other codecs or overlapping heavy Cosmos jobs. The 48 GiB diagnostic reserve
remains mandatory.

## Running source

- Host: Jetson AGX Thor, current JetPack 7.2.1/L4T R39.2 candidate.
- NVStreamer base: NVIDIA ARM64 VSS 3.2.1, pinned by digest in
  `tools/thor/nvstreamer.py`; native service version `2.1.0-26.05.4`.
- Fixture: `thor-ai-walk-single-slice.mp4`, 1280×720, 10 FPS, single-slice H.264,
  9.6096 seconds, no audio. A person walks beside a brick wall and trees.
- Generated upstream URL:
  `rtsp://10.88.9.76:31554/nvstream/home/vst/vst_release/streamer_videos/thor-ai-walk-single-slice.mp4`.
- VSS source: `thor-nvstreamer-mock`, ID
  `17e03964-ba65-4eb0-9207-d6abfa951242`, warehouse CUDA detector profile.
- VSS live proxy: `rtsp://10.88.9.76:30556/live/17e03964-ba65-4eb0-9207-d6abfa951242`.
- VSS UI: `http://10.88.9.76:3001`; NVStreamer: `http://10.88.9.76:31000`.

The sidecar uses separate private media/state, a 4 GiB memory ceiling and no
automatic restart. It belongs to the guarded `vss-thor` project. Startup checks
the guard and reserves the complete sidecar ceiling above 48 GiB. Image staging
requires AI stopped, 90 GiB available and 200 GiB free disk. Start NVStreamer
before VIOS support during cold recovery so the existing sensor comes online.

## Failure found and corrected

The first appearance gallery opened concurrent native GPU snapshot decoders.
Available memory reached **47.858 GiB at 22:02:33 UTC**. The guard stopped the
project; the host did not reboot. The trip and stop results are preserved in
`artifacts/thor-nvstreamer-2026-10-08/initial-*.json`.

Recorded thumbnails now use the evidence service's CPU reader with one decoder,
a bounded 8 MiB/32-entry cache and no native GPU retry. Appearance results also
contained unescaped ISO `+00:00` offsets; the proxy now preserves them without
losing microseconds. VIOS epoch-PTS MKVs have unreliable seek indexes, so the
reader decodes to the requested instant instead of returning a later frame.
Six distinct requested frames passed a real-media regression. An 18-image
appearance gallery returned 18 real JPEGs, not placeholder successes, in 55.66
seconds with six HTTP workers. Serial decoding makes large galleries slower.

The evidence Python source is now mounted read-only, matching the existing
development workflow. Its CPU container was restarted to apply the fix.

History acceptance also found that Node fetch's separate five-minute header
timeout expired while a 22-caption local graph build was still progressing.
The backend completed at 22:45:38 UTC after the UI had already reported
`fetch failed`. Long history requests now use a bounded Node HTTP transport
that honors the full configured deadline and caps responses at 4 MiB. Thor's
default live graph window is five recent minutes; other platforms retain their
existing default, and explicit window configuration is respected. This reduces
graph rebuild work without removing the retained recordings or caption data.
The initial failed record is preserved as `initial-history-failure.json`.
Formatting during the repeat test reloaded the route and exposed another
issue: its module-local job map caused recovery polling to start a duplicate
graph build. Job ownership now survives source hot reload. A module-reload
regression verifies that the still-running build is not resubmitted.

## Runtime and browser checks

The successful soak ran **22:24:27–22:34:34 UTC**, including cleanup:

- 118 fresh embedding chunks, 4,174 detector frames, 19 caption chunks.
- Five fresh owned ROI incidents; native CV remained near 10 FPS.
- 603 one-second guard telemetry samples: minimum **51.372 GiB available**,
  maximum thermal telemetry age 1.0 second, unchanged boot ID
  `652c4102-7adf-4a68-98dd-4cdf6cb8bde5`.
- The owned ROI rule and caption lane were stopped afterward; capture, native
  detection and semantic indexing continued.

A separate continuous visual rule produced two model matches with a
30-second/four-frame/128-token profile while detection and embeddings remained
active. Minimum sampled memory was 51.674 GiB. Only the owned rule was removed.
No caption build or visual question overlapped that rule.

The Codex in-app browser exercised actual UI controls and verified:

- Native NVStreamer dashboard, generated RTSP URL and live WebRTC at 1280×720.
- Recent scene search, camera/time filters, sorting and playable fresh evidence.
- Native object selection followed by appearance search; pagination 6→12→18.
- Ten-second live visual answer, saving the answer with review notes, opening
  the report and replaying its locally retained ten-second video.
- Events showing native ROI incidents and continuous visual model matches.
- Live source history ready over 22:42:11–22:47:11 UTC, followed by an answer
  correctly describing the paved sidewalk, low brick wall and green trees.
  Its cited footage decodes at 1280×720. Natural-language ISO ranges using
  `between … and …` initially became two point clips; the parser now preserves
  the full range, with a regression check. The complete cited clip plays at
  1280×720, ready state 4, duration 52.512 seconds (requested 52.542 seconds).
  The extended history/playback checks retained 49.773 GiB minimum available
  across 1,122 one-second samples, with fresh thermal telemetry and no reboot.

Saved report ID: `779f1b24-40c1-469f-86a9-30b525f2f573`.

**Observed AI limit:** a three-second answer incorrectly described a walking
person as standing. A ten-second answer correctly described walking and the red
shirt, with some imprecise scene phrasing. Review footage before relying on an
answer. The caption-derived history summary also inferred clothing variations
that did not occur in this fixed loop; the tested scene question was accurate.
Model matching is not human verification. Multi-slice H.264 performance
and additional concurrent sources remain unqualified.

## Scoped code checks

- NVStreamer helper: 4 admission/isolation checks passed.
- Thor deployment renderer: 25 checks passed.
- CPU evidence service: 32 checks passed, including real FFmpeg integration in
  a networkless CPU container.
- Image proxy: 8 checks passed, including raw ISO offsets and no GPU retry.
- History API and real HTTP transport: 14 checks passed, including delayed
  headers, an enforced total deadline, response size limits and a bounded Thor
  window and preserved build ownership across a route reload.
- UI TypeScript check and `git diff --check` passed.

Machine-readable receipts are under `artifacts/thor-nvstreamer-2026-10-08/`.
Recording was left on for continued user testing. The source is a looped test
fixture; longer recording and storage growth require their own monitoring.
Temporary rules are deleted and the caption lane is stopped to leave Cosmos
available for interactive questions; native detection and embeddings stay active.
