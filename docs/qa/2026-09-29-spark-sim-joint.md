# Spark and Isaac Sim joint trial — September 29, 2026

The user authorized stopping Moondream and disabling its automatic startup.
VSS then completed cache-only startup alongside the active Isaac Sim renderer,
with the user-authorized **24 GiB Spark reserve**. Live preview, embedding/indexing,
a fresh recent-window answer and its exact inspected clip pass. Durable report
retention and live incident generation exposed separate application bugs during
this trial; the repair results are recorded below. Sustained ingestion and
repeatable scene accuracy remain unqualified.

Times below use UTC on September 30 where specified; the local trial began on
September 29 EDT. The earlier [intake receipt](2026-09-29-spark-sim-intake.md)
preserves observations before Moondream was stopped.

## Moondream startup policy

- Container `moondream-photon-dgx-spark` is stopped and its effective Docker
  restart policy is `no`. Its previous policy was `unless-stopped`.
- `/home/spark/moondream-photon-dgx-spark/docker-compose.yml` now persists
  `restart: "no"`; Compose configuration validation passes.
- In the separate `/home/spark/isaac-sim6-stack` checkout, the Scout launcher now
  defaults `START_MOONDREAM=0`, with explicit `--moondream` opt-in. The integration
  Compose file also uses `restart: "no"`; README/workflow instructions match.
  Shell syntax/help, scoped whitespace and Compose checks pass. These four edits
  remain uncommitted beside that checkout's existing unrelated work.
- Both the inherited Docker policy and the launcher's old default could start
  Moondream without an explicit current request. The original launch event was
  not established. No matching inspected system/user unit, desktop autostart or
  Spark user crontab entry was found; root crontab was not accessible.
- Available host memory after stopping Moondream was 103.143 GiB. Sim's native
  renderer and RTSP worker, and `isaacsim-mcp`, remained running.

## Joint startup and memory

- Attempt 11 completes in **609.196 seconds**, exit 0, with all configured health
  probes passing. The startup sampler's minimum is **41.814 GiB**. Cache-only
  mode, Nemotron fraction 0.11 / batch 1 / 32768 context, and existing models are
  preserved. Cosmos video/text warmup passes.
- The checkpoint-scoped pre-warmup advice retains all four safetensors
  (17,534,339,368 bytes) and raises MemFree from 14.540 to 30.865 GiB; available
  memory is 48.687 → 48.683 GiB. No global cache flush runs.
- A fresh direct visual request returns in **2.156 seconds**, describing a
  hospital room with a bed, monitor and medical equipment. It matches the broad
  scene but does not establish cart localization or temporal accuracy.
- A 900.140-second startup/transport observation takes 4493 samples at 200 ms:
  minimum **40.686 GiB**, unchanged boot ID and no new guard trip.
- A separate 900.041-second live-analysis observation takes 4492 samples at
  200 ms: minimum **39.176 GiB**, unchanged boot ID and no new guard trip. It
  covers preview, recent-window inspection, report save and the beginning of the
  first rule trial. It ends before rule cleanup; do not combine these observations
  into an uninterrupted full-trial minimum.
- A third 900.165-second repair/retry observation takes 4493 samples at 200 ms:
  minimum **39.534 GiB**, unchanged boot ID and no new trip. It covers the
  targeted application rebuilds, rule retry/cleanup and retained report playback.
- Boot ID remains `6b100cd0-2daa-4ef5-8db5-2b4c0bee5201`. The user guard is active
  at 24 GiB. The earlier 21:06:47 EDT trip predates the current Sim renderer's
  21:29:33 EDT start; its cause remains unknown.

Private receipts live under `.spark/attempt-11/` and `.spark/sim-probe/`, including
`startup-transport-joint-memory-result.json` and
`live-analysis-joint-memory-result.json`, plus
`repair-retry-joint-memory-result.json`. These files and media are ignored.

## Live source and TCP repair

Source **Spark Hospital Corridor**, ID
`3688c328-7e71-493c-a1c7-011ad2fb3893`, uses the user-supplied
`rtsp://10.88.9.91:8554/digital-twin`. It was added with analysis paused and
recording off. The earlier recorded conveyor source/history is preserved.

The local MediaMTX publisher accepts TCP only. The inherited VST configuration
used UDP: WebRTC ICE connected, but upstream RTSP PLAY returned 454 and VST
received zero RTP packets. A temporary TCP proxy proves reception; the persistent
fix generates private `.spark/vst-config.json` with
`network.rtsp_streaming_over_tcp=true` and mounts it into the Spark VST roles.
The Thor base configuration is unchanged. Recreating only streamprocessing
restores the original primary proxy (30554), clears the diagnostic duplicate and
receives 9829 packets at average 29.598 fps with zero packet loss/errors in a
29-second QoS observation. This packet rate does not establish fresh Sim viewport
frame rate; raw CPU decoding still shows sparse delivery and repeated frames.

All six bootstrap tests pass, including real Compose rendering, the private TCP
mount, unchanged Thor config and preservation of the saved reserve/cache mode.

## Browser journey

- Live preview renders **1280×720**, video readyState 4, no video error and no
  console warning/error. Proof: private `live-preview.png`.
- Recording becomes `alwaysOn`. Explicit source resume enables live embeddings
  and indexing; detection stays off. No history-captioning job is configured.
- The recent-window question asks where wheeled monitor carts are and whether
  a person is nearby. The answer places one cart on the right, another farther
  back near the center, and reports no visible people. Manual exact-clip review
  supports these observations.
- Inspected interval: **02:39:51.469Z → 02:40:16.469Z**, exactly 25 seconds.
  Agent/tool logs show approximately **12 seconds** from visual-tool start through
  clip preparation and completed inference. The later browser observation is an
  upper bound including automation delay, not measured user response latency.
- The exact inspected clip plays to its 25-second end at 1280×720, readyState 4
  and no error. Proof: private `inspected-clip.png`.

## Retention and incident repairs

The initial saved report `3c3c0ba6-bcb5-4318-ac32-54752b080b3e` preserves its answer
and timestamps, but explicitly reports `source_retention`. The exporter rejects
its generated clip because it does not cover the requested duration. The source
MKV covers the entire interval; bounded CPU reproduction gives 25.767 seconds
with stream copy and 24.233 seconds with the old transcode fallback. The strict
coverage check is correct and is not relaxed. Native VST exact-clip playback works.

The first custom rule runs from 02:47:00.867Z until deletion around 02:56:49Z.
It receives frames and performs repeated inference, but emits generic captions
instead of the explicit condition verdict expected by the existing trigger parser.
No incidents are produced. This is a functional failure, despite healthy services.

Cleanup removes only the test-owned rule and local monitoring configuration,
pauses embeddings/indexing, verifies Cosmos inference inactive and stops recording.
The first pause request returns 502 because it attempts to contact omitted detector
workers. Actual analysis is paused, but that response is a real control-flow bug.
Spark now clears those inherited endpoints rather than treating absent workers as
services that must be stopped. Source history and report records are preserved.

### Verified repairs and bounded retry

- The exporter now first retains the same native VST MP4 route used by exact
  playback. Downloads stay on the configured VST origin, allow only storage MP4
  paths, reject redirects/traversal, enforce time/size bounds and check start
  metadata plus the unchanged duration limit. Existing local-media fallback is
  preserved. All **15 exporter tests** pass, including real CPU FFmpeg/ffprobe
  retention of a 25-second file and rejection of shorter coverage. Only the
  exporter image/container is refreshed; models stay loaded.
- Resaving through the supported report API creates report
  `15a70ea5-e70a-4dbb-8d4d-404b67ef6c3d` with `media_status=retained` in 0.137
  seconds, using the already generated native VST clip. The old failed report is
  preserved. FFprobe verifies **25.000 seconds**, H.264, **1280×720** and
  14,885,072 bytes. This fast cached save is not a cold export latency measurement.
  Browser replay subsequently reaches 25.000 seconds / ended true / readyState 4
  with no video or console error after recording is off. Private proof:
  `retained-live-report-playback.png` and `retained-live-evidence.png`.
- Alert Bridge wraps only alert requests with a visible-evidence
  `TRUE`/`FALSE`/`UNKNOWN` contract. Original saved conditions and ordinary
  caption requests remain unchanged; the incident parser is not loosened.
  Its scoped suite passes **137 tests / 12 skips**, including parser agreement,
  condition preservation and non-alert passthrough. Only Alert Bridge is rebuilt
  and recreated.
- A follow-up incident-response formatter removes only the exact generated
  wrapper from the displayed condition, preserving model prompts and stored
  Elasticsearch documents. Its Alert Bridge tests pass **160 / 12 skips**.
  The UI reads incidents through the source-mounted VA MCP service instead of
  this bridge endpoint; the matching agent formatter passes **42 tests**,
  including agreement with the actual Alert Bridge wrapper and preservation of
  model provenance. Only VA MCP is restarted to apply that source-mounted fix.
  A fresh browser incident view now shows the original condition after rule
  deletion; exact model prompts remain available in the incident response.
  The removed rule's display name falls back to `semantic` / “Rule record
  unavailable”, while its source, timestamps and condition remain readable.
  Scoped Ruff/format checks pass. Raw Mypy reports an existing duplicate-variable
  declaration in `video_analytics/utils.py`; with that existing `no-redef` error
  excluded, the affected helper's typecheck passes.
  The historical event report created before this formatting fix retains its
  original recorded prompt. No report record is rewritten.
- The second browser-authored rule is
  `b9ba723d-9f80-41bd-8a3e-fd50ab467cb2`, created **03:08:01.057Z**, named
  **Monitor cart visibility — verdict retry**. It uses the same cart condition,
  four fixed frames per 30-second window, 2-second overlap, 512×512 input,
  max 128 tokens, reasoning/audio off and informational severity. Cleanup starts
  at 120 seconds and completes **127.768 seconds** after creation.
- **Three incidents** carry explicit `TRUE` model responses and the matching
  source/rule/request IDs. The first response is logged **03:08:33.937Z**,
  approximately **32.88 seconds** after rule creation. This is first inference
  completion, not measured event-to-UI latency. Its recorded window is
  **03:08:10.729Z → 03:08:33.262Z**, with frame IDs `0:0` and `0:3`; later
  windows start 03:08:40.729Z and 03:09:10.729Z.
- Events & reports visibly lists all three model matches. The first incident's
  exact **22.534-second** footage shows the cart on the right and plays fully:
  readyState 4, ended true, no video error. It is manually reviewed, then saved
  through **Save event report**. Report `ce0ba556-738a-42da-b8e0-d922bdaf05ff`
  retains the clip and replays fully after recording is off, with no console
  warning/error. This event report preserves the model match and review notes;
  saving it does not run new inference.
- The Spark agent config clears the omitted warehouse detector endpoint, and
  bootstrap clears the omitted traffic endpoint. After only the agent is
  recreated, a real pause returns **200 / paused**, replacing the earlier false
  partial response. All six bootstrap tests and Python/whitespace checks pass.

Final cleanup verifies no active live rules, paused source analysis,
embedding/indexing off, Cosmos inference inactive and recording `off`.
VSS remains up with Sim running and Moondream stopped. Source history, all report
records and incident records remain available. The guard and budgets are retained.
Private evidence includes `retry-incidents.json`, `retry-duration.json`,
`cleanup.json`, `retained-live-report.json`, `retained-event-report.json` and
`retry-incident-playback.png`.
`retry-incident-original-condition.png` captures the corrected display.

Scoped validation commands (from the repository root):

```sh
python3 tools/spark/test_bootstrap.py
docker run --rm --runtime runc --network none --cpus 2 --memory 512m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/deploy/docker/thor-local/evidence-clip:/tests:ro" -w /tests \
  --entrypoint python3 vss-spark-evidence-clip:source -m unittest test_server -v
PYTHONPATH=services/alert /home/spark/.local/bin/uv run --offline \
  --with pytest --with pytest-asyncio --with httpx --with pyyaml --with pydantic \
  python -m pytest services/alert/test/api/test_incident_service.py \
  services/alert/test/api/test_realtime_service.py -q
PYTHONPATH=services/agent/src /home/spark/.local/bin/uv run --offline \
  --with pytest python -m pytest \
  services/agent/tests/unit_test/video_analytics/test_utils.py -q
```

## Remaining qualification

No controlled scene reset or independently scored negative interval has been
provided. A static cart-positive check cannot establish alert accuracy. Multiple
streams, sustained recording/ingestion, Sim motion freshness, detector profiles,
concurrent heavy summarization and a timed presenter rehearsal remain open.
Historical Thor/Jetson labels and Spark GPU telemetry also remain limitations.
