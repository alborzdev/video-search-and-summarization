> **October 28 operator-adjusted intersection cameras:** The active Isaac pair uses 1280 × 480 with the operator's saved camera positions. Camera poses, lenses and apertures are applied in the USD session layer. VSS and experimental MV3DT use live-exported calibration `isaac-live-98b2ae97b267da51`; the five existing rules were preserved and migrated. Independent tracking accuracy and sustained performance remain unqualified. Earlier camera and tracker receipts below are historical. Pre-change recovery inputs are under `isaacsim-6/outputs/user-camera-save-backup-20261028T115754`.

> October 28 operator update: Spark uses its saved **5 GiB** reserve, with no additional startup allowance. Historical reserve/startup values below are superseded.

# VSS Smart City: operator workflow

**Current tracker migration (October 26):** the active two-camera profile uses one native MV3DT tracker, with no separate NvDCF stage or single-camera 2D fallback. Shared native IDs and native world-foot map positions are supported for all six city classes. NVIDIA MV3DT retains its internal CUDA DCF module. The bounded motion test still shows weak cross-camera ID agreement; reliable all-class identity is not qualified. See [implementation, runtime evidence and limits](../../docs/smart-city-native-mv3dt-2026-10-26.md). Earlier staged-tracker receipts below are historical.

**Current source clock:** the pinned Isaac profile explicitly uses `sourceClockMode: source-native-sei`, with exact encoded-AU wall-handoff proof before both trackers and through the JSON/exact-preview proxy. Single-camera startup uses that clock before the full pair starts; generic cameras keep RTCP. It does not verify physical exposure/browser timing or relax map guards. Qualification helpers use `--expected-source-clock-basis source-native-sei`; `soak.py` additionally uses `--trust-native-sei-wall-utc` for handoff-age checks and `--require-processed-preview` for exact envelopes. Do not use RTCP trust flags or relabel native receipts as RTCP. [Clock contract](../../docs/smart-city-data-contracts.md).

**Intersection implementation delivered:** the hash-pinned `pedestrian-pocket-v3/smart_city_expo_pedestrian.usda` has its reviewed southwest setback/waiting strip. Current native-SEI cameras, exact previews and guarded map display have bounded live evidence; one actual Ask/inspected clip played successfully. The new native pedestrian episode completed/restored, but its camera completion is unqualified under the original observation-gap bound. Final health/artifact checks passed. The implementation is accepted as a bounded booth prototype with the stated limits. Earlier five-story passes retain their original receipts. Select **Run a scenario** for finite stories over normal traffic. Vehicle IDs/counts remain camera-local; shared-person markers are experimental. [Current as-built](../../docs/smart-city-as-built.md), [goal ledger](../../docs/smart-city-intersection-goal-2026-10-26.md).

**Current camera transport (October 26):** two Isaac views use NVIDIA native H.264 RTSP at **960×540**, requested ceiling 30 FPS. The final 29.9868 s native sample measured **9.403 handoffs/s each**; a separate 57.82 s browser sample rendered **9.011/9.132 FPS**. These are bounded throughput results, not physical capture-to-display latency. The packet relay, camera URLs and UUIDs remain. Default `isaac_demo.py start` preserves saved calibration, map, rules and tracker settings. Geometry/identity changes require reviewed migration, not routine `--refresh-calibration`. [Native sample](../../docs/qa/smart-city-2026-10-26/native-sei-final-native-performance.json), [browser](../../docs/qa/smart-city-2026-10-26/native-sei-final-browser-performance.json).

**Current mobility workspace:** Open **http://127.0.0.1:7782/?workspace=smart-city** → **Insights**. The [mobility guide](../../docs/smart-city-mobility-2026-10-23.md) covers movement counts, crossing access, queues, pedestrian waiting, curb occupancy/dwell/turnover, configuration and exports. The current intersection rebuild has bounded live scenario checks; earlier endurance results apply only to their recorded builds.

**Current UI deployment (October 26):** port 7782 serves package `20261026T102610382036Z`, image `sha256:1d94d0350f90c2e4f120f0295553e6ed06d6b71789579378bf532a634605fc0f`, source `d4aee494f102dc2a60782060735fc22a879b5313cf5f140ea79543868ed0e25f`. Ten tasks passed **2 m 4.333 s**. Layout/branding and the 1040×1120 actor-free map asset `c4d14670c7be4dea04b4d29f9bd3e252681c11ff00da92568456781c261e1a70` are retained. The repair adds only native proof/mode to the public source allowlist; actual browser views now pass exact-preview guards. Final installation changed the native worker/UI and left the CPU gateway/scene/publisher running. Shared 7777 remains separate. Canonical isolated config is `.spark/city/polish-ui-compose.json`; [build/repair evidence](../../docs/qa/smart-city-2026-10-26/native-capture-clock-proxy-ui-build.json), [restart/rollback](UI-PACKAGING.md).

**Current tracking/timing (October 26):** native image `4e6b73d1…` / profile `cadd8867c22388c78066d9f0dac4b35e240d5512bc84a6b5e36446957dd9a1dd` retains eight pins and explicit native SEI authority, diagnostics off, mux sync off and zero latency/NTP window. All **19 rules acknowledge 450**, mobility 6 and calibration `isaac-live-045c84fe5fda7a15` remain. First NvDCF owns local journeys; second MV3DT emits optional current-frame person hints. All 11 latest pairs met the unchanged 150 ms guard (median 0.501168 ms/max 123.68622 ms). Retained pairs supplied 83 conditional initial map-guard passes/45 same-counter pairs; separately [final dashboard pixels](../../docs/qa/smart-city-2026-10-26/native-sei-final-dashboard.jpg) and accessibility reported one shared person/2 views. This is guarded display evidence, not global counts or ID accuracy. The older shared-person screenshot showed 0 joined with later accessibility 1; preserve that distinction. `browserClockVerified` stays false. [Paired evidence](../../docs/qa/smart-city-2026-10-26/native-sei-qualified-shared-pair.json). The earlier 597 ms rejected cohort, proxy `77c066` failure and PTS-sync trial remain preserved historical evidence.

**Earlier bounded scenario evidence (October 26):** the following checks used UI image `6781e5ed…`, rules 434 and mobility 6 before the native clock cutover. They remain evidence for those exact runs, not automatic acceptance for the final native-SEI artifacts; the October 22 replay soak also remains historical.

| Operator action | Actual result and how to read it |
| --- | --- |
| Keep the crossing clear | Scene completed/restored in 34.299 s; camera alert active→cleared, 12.114 observed blocked seconds, one completed and zero unknown episodes. |
| Curb obstruction | Scene completed/restored in 42.040 s; actual camera stop/dwell, departure counter 2→3 and final observed occupancy zero. Dwell describes zone presence, not loading permission. |
| Observe normal demand | Completed/restored in 30.031 s with normal flow and no extra arrival requests. A short window need not contain every turn or class. |
| Return to normal traffic while held | Real UI cancel released the held car; subsequent native motion was sampled, 3.470 route metres farther at 4.158 m/s. Queue clearance is a separate camera result. |
| People wait, cross, and clear | Native episode completed/restored in 97.123 s with actual SUCCEEDED arrival and 0.03796 m endpoint error; independently, the East north→south camera counter advanced 0→1. |
| Queue control | Full hold/release/native departure/restoration completed in 36.014 s. Camera observed two objects and a 9.535 m lower-bound extent; later membership was incomplete, so no camera queue-clear claim. |

The held queue image separately showed two observed objects/11.2 m lower-bound extent without camera clearance. [Earlier scenario receipts](../../docs/qa/smart-city-2026-10-26/v3-bounded-scenarios-checkpoint.json). The current native pedestrian episode completed/restored 42.7099 s/error 0.03830 m, while camera completion stayed 0→0 and pre-existing incomplete 3 stayed 3. The same local ID had 1.137 s/1.871 s fresh-object observation gaps, beyond the unchanged 1 s bound; there is no qualified current camera completion. [Current native/camera receipt](../../docs/qa/smart-city-2026-10-26/native-sei-final-pedestrian.json). [Continuity audit](../../docs/qa/smart-city-2026-10-26/native-sei-pedestrian-camera-continuity.json) distinguishes target observation loss from camera-frame outage. One real Ask returned a 5.0304 s inspected clip played to completion, indexing inactive. [Ask](../../docs/qa/smart-city-2026-10-26/native-sei-final-ask-browser.json). [Final health](../../docs/qa/smart-city-2026-10-26/native-sei-final-health.json) passed, including HTTP map, recordings and all five stories available/restored. Select one story at a time and read native cleanup separately from camera evidence; bounded booth acceptance is complete with those limits.

**Historical timing failure:** the pre-repair v3 sample had 597.073 ms median/597.315 ms maximum latest-pair skew and 0 of 11 within 150 ms, so shared joins were rejected. The explicit native AU clock fixes the worker's bad RTCP reconstruction without offsets or weaker guards; current 11 of 11 pairs and actual guarded display have their separate receipts above. The older failure, intermediate `77c066` proxy omission and native hint-gate issue remain preserved. [Pre-repair cohort](../../docs/qa/smart-city-2026-10-26/v3-final-performance-summary.json). Physical exposure/browser latency and MV3DT accuracy remain unqualified.

**Current prepared Spark demo:** `python3 tools/smart-city/isaac_demo.py start`, `status` or `stop` operates the two live cameras. Default Start validates and reuses saved geometry and verifies enabled native/backend rule coverage and applied revision. Preserve the reviewed 19-rule configuration, physical East-crossing selection and all eight staged-tracker pins. Do not run preset `isaac_mobility.py --apply` or `start --refresh-calibration` as routine recovery: those are engineering configuration changes. For a geometry-identical scene-wrapper change, use the reviewed `isaac_identical_calibration.py` preparation and inspect its preservation checks before any activation. The [East pedestrian guide](../../docs/smart-city-east-pedestrian-story-2026-10-26.md) describes the selected rules and migration boundary. See the [Isaac operator guide](../../docs/smart-city-isaac-integration.md) before changing cameras. Do not run the recorded-video commands below over the active Isaac site.

The mobility preset now preserves saved rules outside its actual generated-ID set and refuses a PUT if a saved measurement would reference a missing rule. It still resets its own generated rules to preset geometry and sensitivity, so it is not an operator-state restore command. Its legacy `--add-east-crossing` option adds the **South crossing's east approach direction**; it does not create the physical `XW_E` story. `prepare_east_pedestrian_story.py` prepares that separate reviewed migration without contacting services.

For a booth walkthrough, open `http://127.0.0.1:7782/?workspace=smart-city` and
confirm both analyzed pictures are current before starting one scenario. Read
the **Scripted event** status as scene preparation; use camera boxes, Insights,
the map and retained evidence for the independent AI result. Let a story finish,
or select **Return to normal traffic**, then check actual clearance. A released
hold is not an AI clear event. Earlier v2 native normal-flow recovery passed a separate
180-second observation; final bounded booth acceptance is recorded above. The
[scenario operator handover](/home/sparkdev/isaac_city_sim/docs/tradeshow-operator-handover.md)
gives the five stories, preparation limits and recovery steps. The setup and
recorded-input commands below are engineering workflows, not a required reset
of the active Isaac demonstration.

This adds a Smart City workspace and source analysis profile to the existing VSS deployment. It keeps the base Agent, visual inspector, media services and other industry profiles. The generic service commands below do not start Isaac; the prepared `isaac_demo.py start` command does.

See [the implemented architecture and model decision](../../docs/smart-city-as-built.md), [current progress](../../docs/smart-city-implementation-progress.md), [MV3DT decision](../../docs/smart-city-mv3dt-decision.md), and [production UI packaging](UI-PACKAGING.md) for their respective evidence and limits.

Commands below run from repository root. The tested host is DGX Spark. Preserve the saved `.spark/settings.json` reserve and its existing memory guard; the implementation used a **20 GiB** reserve. Thor configuration can be rendered on Spark, but Thor build/start/analyze requires actual Thor hardware. Never copy a Spark TensorRT engine into the Thor deployment.

The user disabled the separate Isaac-specific 23 GiB available-memory stop on October 23. Its current policy value is `null`; this does not alter the VSS guard, process limits or disk checks.

## 1. Check the existing deployment

```bash
cd /home/sparkdev/vss
python3 tools/smart-city/manage.py doctor
python3 tools/smart-city/manage.py render
```

`doctor` reads actual memory and the existing guard. It does not change budgets or start a model. `render` writes only `.spark/city/compose.json`. The model image, engine and base VSS deployment must already be staged before running inference; model build/evaluation instructions are documented separately.

## 2. Start the analytics gateway

```bash
python3 tools/smart-city/manage.py start
python3 tools/smart-city/manage.py status
```

The gateway listens at `127.0.0.1:9184`, persists configuration/events/replay frames under `.spark/city/state`, and mounts only controlled media. Starting it generates no observations. `setupRequired: true` means no cameras are configured. Configured cameras without new frames report `awaiting-observations`; retained frame history can still be queried after a worker finishes or the gateway restarts.

Restart only this CPU service to load an updated source-mounted gateway:

```bash
docker compose -f .spark/city/compose.json restart city-analytics
curl --fail --silent --show-error http://127.0.0.1:9184/api/v1/city/health
```

Wait until an active detector pass is finished before restarting the gateway. A failed observation delivery is an explicit inference failure; do not silently discard its frames or treat a producer queue overflow as success.

## 3. Stage recorded test inputs and register media

The tested files are H.264 MP4:

| Controlled file | Provenance | Actual metadata |
| --- | --- | --- |
| `.spark/city/media/traffic-sample.mp4` | NVIDIA DeepStream `sample_1080p_h264.mp4` | 1920×1080, 30 FPS, 48.1 seconds; moving camera |
| `.spark/city/media/pedestrian-sample.mp4` | OpenCV `vtest.avi`, actually converted to H.264 MP4 | 768×576, 10 FPS, 79.5 seconds; fixed camera |

These are independent recordings, not two views of the same city. They qualify detection/playback integration; they do not qualify a shared ground map or cross-camera identity.

On this prepared host, verify the staged inputs:

```bash
test -s .spark/city/media/traffic-sample.mp4
test -s .spark/city/media/pedestrian-sample.mp4
```

For a new deployment, place real H.264 MP4 inputs into that controlled directory. For example, after obtaining the two source files:

```bash
mkdir -p .spark/city/media
cp /path/to/sample_1080p_h264.mp4 .spark/city/media/traffic-sample.mp4
cp /path/to/converted-vtest-h264.mp4 .spark/city/media/pedestrian-sample.mp4
```

An AVI rename is not a conversion. Use an actual H.264 encoder when preparing the second file. Keep original downloads and record their hashes/provenance.

Read the existing VIOS inventory before uploading. The repository's configured `vss vios add --type video` CLI is the preferred media-only wrapper when available. Its supported underlying request is shown here for this local deployment:

```bash
curl --fail --silent --show-error http://127.0.0.1:30888/vst/api/v1/sensor/list

curl --fail-with-body --silent --show-error --request PUT \
  --header 'Content-Type: application/octet-stream' \
  --data-binary @.spark/city/media/traffic-sample.mp4 \
  'http://127.0.0.1:30888/vst/api/v1/storage/file/traffic-sample.mp4?timestamp=2025-01-01T00%3A00%3A00.000Z'

curl --fail-with-body --silent --show-error --request PUT \
  --header 'Content-Type: application/octet-stream' \
  --data-binary @.spark/city/media/pedestrian-sample.mp4 \
  'http://127.0.0.1:30888/vst/api/v1/storage/file/pedestrian-sample.mp4?timestamp=2025-01-01T00%3A00%3A00.000Z'

curl --fail --silent --show-error http://127.0.0.1:30888/vst/api/v1/storage/timelines
```

Run those PUT requests only when the files are absent from VIOS. Read the actual `sensorId` and `streamId` from its response; never derive IDs from names. Successful local registrations are recorded in [the gateway README](../../services/analytics/behavior-analytics/apps/city/README.md). Calling Agent `/videos/{id}/complete` also invokes configured embedding hooks; it is not the media-only path.

## 4. Install the local host controller

The controller provides the RTVI-CV REST interface expected by the existing VSS source APIs. It runs as the host user and uses fixed Docker CLI commands. The HTTP analytics container has no Docker socket.

```bash
python3 tools/smart-city/manage.py controller-setup
python3 tools/smart-city/manage.py controller-service
systemctl --user daemon-reload
systemctl --user enable --now vss-city-controller-spark.service
python3 tools/smart-city/manage.py controller-status
```

The isolated runtime environment is `.spark/city/control-env`, installed from exact tested pins in `controller-requirements.txt`. The user unit has a 512 MiB ceiling and listens only on `127.0.0.1:9190`. `controller-status` can report a healthy HTTP service with `ready: false` when model artifacts or saved guard/headroom are unavailable. An old state file is not proof of a running worker.

For manual development without systemd:

```bash
python3 tools/smart-city/manage.py controller-start
python3 tools/smart-city/manage.py controller-status
python3 tools/smart-city/manage.py controller-stop
```

Stop a standalone controller before enabling the user unit. Stop the user unit with:

```bash
systemctl --user stop vss-city-controller-spark.service
```

Optional `.spark/city/controller.env` supports only these settings in the standalone launcher: `CITY_RTSP_ALLOWED_HOSTS`, `CITY_VSS_ORIGIN`, `CITY_GATEWAY_URL`. The unit reads the same environment file. For the explicitly labelled local RTSP replay fixture, this host uses:

```text
CITY_RTSP_ALLOWED_HOSTS=127.0.0.1,localhost,172.17.0.1
```

After changing it, restart only the controller when it owns no active detector, or deliberately pause its sources first:

```bash
systemctl --user restart vss-city-controller-spark.service
```

## 5. Enable the existing VSS source profile

```bash
python3 tools/smart-city/manage.py profile-enable
curl --fail --silent --show-error http://127.0.0.1:8100/api/v1/analysis-profiles
```

This writes an additive `.spark/city/agent-city-overlay.json` setting `VSS_CITY_RTVI_CV_URL=http://127.0.0.1:9190`, then recreates only `vss-agent` with `--no-deps`. It does not change model services, budgets, the base Compose file or other profile URLs. The catalog retains semantic, warehouse and legacy traffic profiles, and adds `smart-city` with six object classes, seven rule families and a two-source capacity.

Reapply `profile-enable` after a base Agent recreation or deployment render; otherwise that base configuration intentionally has no city controller URL. Before disabling the worker URL, pause every active Smart City source through the existing Agent controls shown below and confirm the controller inventory is empty. Disabling the URL alone does not stop a controller-owned detector. To disable the URL after pausing:

```bash
python3 tools/smart-city/manage.py profile-disable
```

## 6. Select and run real source analysis

Read actual VIOS IDs first. The following placeholders are intentional; use returned UUIDs, not invented IDs.

For an existing uploaded recording, select the profile through the Agent. This starts real GPU inference and skips embedding generation through the existing recorded-analysis endpoint:

```bash
python3 tools/smart-city/manage.py source-analysis \
  --kind recorded --source-id VIOS_UUID --profile smart-city
```

The controller verifies VIOS ownership, stages only controlled source exports if needed, probes actual dimensions in a bounded CPU subprocess, updates the canonical city site and starts the existing guarded native worker. Adding/removing the second source restarts the shared worker and creates new tracker sessions. A third source is rejected. Repeated add while a source is already running does not restart it.

For the prepared two-recording developer site, the direct bounded validation workflow is also available. This is a developer inference command; it does not assign the VSS source profile:

```bash
python3 tools/smart-city/manage.py recorded
python3 tools/smart-city/manage.py analyze --frames 3000
python3 tools/smart-city/verify_recorded_run.py --help
```

Use the source-profile route for ordinary VSS operation. Do not run the direct inference command at the same time as the controller owns a worker. `recorded` replaces the city site's configuration, so do not run it while live analysis is active.

## 7. RTSP previews, profile selection and pause/resume

The prepared RTSP publisher is a CPU-only loop of recorded files. Its camera names and UI must remain labelled recorded replay; it is not Isaac Sim or a real live city. It does not generate detections. Start its publisher using the dedicated helper after staging its documented prerequisites:

```bash
# Use the existing CPU PyAV export environment from the model tooling.
# Preserve the original; generate and fully verify all 795 frames of a
# separate single-slice, 10 FPS, no-B-frame pedestrian replay derivative.
.spark/city/export-env/bin/python tools/smart-city/prepare_replay_fixture.py
python3 tools/smart-city/rtsp_replay.py start
python3 tools/smart-city/rtsp_replay.py --help
```

The publisher verifies the derivative and original hashes against its provenance receipt. The original pedestrian recording exposed repeated decoded PTS in the current VIOS multi-slice RTSP proxy. The canonical encoding removes that behavior in this controlled test input; it does not repair or qualify arbitrary multi-slice cameras. The final Isaac Sim encoder must be tested through VIOS with the selected H.264 access-unit/slice settings. Pause owned analysis through the Agent before restarting publishers.

Register previews through the existing Agent with analysis explicitly paused:

```bash
python3 tools/smart-city/manage.py preview-register \
  --url rtsp://172.17.0.1:18554/city-traffic --name city-traffic-rtsp-replay
python3 tools/smart-city/manage.py preview-register \
  --url rtsp://172.17.0.1:18554/city-pedestrians --name city-pedestrian-rtsp-replay
```

If already registered, use the existing UUID instead of registering the same name again. These commands start neither detector nor embedding nor VLM analysis. VIOS may return a different source-specific proxy URL; the controller verifies it against `/sensor/{id}/streams` rather than trusting an arbitrary submitted RTSP URL. The hostname must also be explicitly allowed.

Configure then resume a paused camera through the existing Agent controls:

```bash
python3 tools/smart-city/manage.py source-analysis --kind live \
  --source-id VIOS_UUID --name city-traffic-rtsp-replay --profile smart-city
python3 tools/smart-city/manage.py source-analysis --kind live \
  --source-id VIOS_UUID --name city-traffic-rtsp-replay --action resume

# Pause without deleting the source or retained recordings.
python3 tools/smart-city/manage.py source-analysis --kind live \
  --source-id VIOS_UUID --name city-traffic-rtsp-replay --action pause
```

`configure` preserves a paused state. `resume` starts the existing configured VSS live analysis path, which may also restore semantic services; qualify that combined envelope. Live detector execution uses explicit `--live --frames 0` while retaining the saved guard and cancellation cleanup. Runtime controller tests must not overlap independent model builds/benchmarks on the same GPU.

The controller retains the canonical site/map when its final source is paused or removed. Per-source calibration and rule settings are archived under `.spark/city/controller-calibrations.json` and `controller-source-rules.json`, so incremental camera activation does not erase a temporarily absent camera's setup. UI rule deletions replace that source's archive; stale calibration-dependent rules are disabled for review. Current observations and event timers still reset on source-set changes.

The analyzed display path now also supports an exact native JPEG/metadata pair. The gateway retains at most two latest images for two seconds, matches their accepted source/session/sequence/time/model identity and original geometry, and never writes JPEGs into observation history or SQLite. Native display queues can drop preview frames while metadata continues independently. The [preview API and health contract](../../services/analytics/behavior-analytics/apps/city/PREVIEW.md) defines the binary envelope, limits and safe delivery counters. Native GPU checks, final production UI cutover/rendered image-overlay checks and the final two-hour combined Spark replay passed; see [the pinned package/browser receipt](../../docs/qa/smart-city-2026-10-22/ui-final-production.json) and [endurance summary](../../docs/qa/smart-city-2026-10-22/medium-final-all-ui-summary.json). Raw WebRTC remains a fallback with its separate clock guard.

## 8. Explicit geometry fixtures

Fixtures test the map, linked selection, rules and event transitions through the real ingestion API. All observations are synthetic and remain visibly labelled. Do not attach unrelated real video to these trajectories or report them as detection results.

The gateway image already includes the fixture generator:

```bash
# Explicitly replace the city site with the two-camera synthetic fixture and precompute one loop.
docker exec vss-city-analytics python -m apps.city.fixtures \
  --base-url http://127.0.0.1:9184 --fps 5 --no-realtime

curl --fail --silent --show-error \
  'http://127.0.0.1:9184/api/v1/city/snapshot?mediaTimeSeconds=9'
```

Use fixtures on a dedicated city gateway after stopping real source analysis. They never run automatically on startup. The fixture cameras have exact known homographies, six classes, two views, a vector street plan and all seven backend rule families. They do not qualify real inference, physical localization error or cross-camera tracking.

## 9. Clocks, map calibration and qualification

- Recorded playback alignment uses GStreamer segment stream time, including MP 4 edit-list/start offsets. The worker emits `mediaTimeBasis: gstreamer-segment-stream-time`; raw PTS is retained separately. Legacy records without that verified basis do not produce an aligned overlay.
- Raw WebRTC overlays require a verified source/browser capture-clock link. `arrival-pts-unsynchronized` is insufficient for that timestamp lookup, and the actual browser did not expose absolute capture time. The UI therefore hides unmatched raw-video boxes. The native paired-preview path instead supplies the exact image and accepted frame snapshot together; this proves source-frame identity without enabling `browserClockVerified`.
- A close timestamp match alone does not prove the video gateway preserved the same clock. Keep the native/browser clock mapping receipt and test end-to-end latency, reconnects and resets.
- Live source metadata separates `ingestAgeSeconds` from `sourceClockAgeSeconds` and a bounded `sourceClockProgressRatio`. `delayed-or-unsynchronized` warns when the source clock is old/ahead or advances too slowly, even when ingestion remains fresh. The October 26 same-buffer SDK/RTCP mapping passed its bounded check; physical exposure timing and the separate camera/browser clock link remain unqualified.
- The top-down map uses static camera calibration and bbox-bottom-centre projection. Missing/invalid/out-of-region geometry returns null positions, never pixel coordinates labelled as metres.
- The two public recordings have no shared calibration or overlap. Their ground map remains unavailable. The final Isaac Sim handoff needs static street geometry, source dimensions and calibrated transforms/homographies with independent landmark checks.
- First-stage native NvDCF IDs remain the camera/session-local analytics authority. Current optional MV3DT person-map hints have explicit second-stage provenance and existing guards; they do not create unique site-wide counts or qualified vehicle identity. The gateway does not silently deduplicate or invent global IDs.
- Source loss produces stale/unknown events. It does not prove a vehicle departed or clear an incident. Reports and snapshots are scoped to the current site; fixture events cannot appear as recorded results after a site switch.
- A timestamp-basis change retires the old tracking/timer epoch even when a producer mistakenly reuses its session ID. Old-basis late frames cannot restore those durations.
- The final Isaac Sim environment, physical map error, cross-camera fusion, full booth-day endurance, sustained visitor-rate questions and Thor deployment need their own qualification. The completed two-hour Spark replay does not establish those results.

Detailed schemas and guarantees: [gateway README](../../services/analytics/behavior-analytics/apps/city/README.md), [data contracts](../../docs/smart-city-data-contracts.md). Runtime receipts live under [docs/qa/smart-city-2026-10-22](../../docs/qa/smart-city-2026-10-22).

Historical October 22 recorded-input checks include:

| Check | Actual result and limit |
| --- | --- |
| [Native JPEG branch and endpoint outage](../../docs/qa/smart-city-2026-10-22/preview-native-480-outage.json) | All 480 metadata observations published; 136 JPEGs matched exact identity/geometry. Metadata continued for 239 observations after the preview endpoint closed. This tests connection failure isolation, not every possible converter fault. |
| [Medium paired preview, 300 seconds](../../docs/qa/smart-city-2026-10-22/medium-paired-preview-300s.json) | Both registered replay sources passed, with 57 validated envelope fetches each, no observation sequence gaps or clock rollbacks, maximum reported source age 0.340 seconds and minimum available memory 24.572 GiB. No scheduled Ask calls or browser latency measurement. |
| [Three Medium questions and 600-second monitor](../../docs/qa/smart-city-2026-10-22/medium-three-ask-600s.json) | Three distinct five-second evidence windows and one byte-identical repeat passed; no OOM/restart, minimum available memory 24.174 GiB. This earlier run predates the paired JPEG preview. |
| [Explicit five-second semantic check](../../docs/qa/smart-city-2026-10-22/medium-paired-five-second-semantic.json) | Answer returned in 9.37 seconds with a decoded 150-frame evidence clip. Limited visual review agreed broadly with movement; a fourth pedestrian near the end was omitted. This is not an exhaustive count or semantic benchmark. |
| [Final combined Spark replay, 7,200 seconds](../../docs/qa/smart-city-2026-10-22/medium-final-all-ui-7200s.json) | Passed with 1,359 samples, 215,896 traffic-source / 71,966 pedestrian-source frame observations and 1,359 matching binary-envelope fetches per source. No sequence gaps, clock rollbacks or source epoch changes. Seven sequential five-second questions at 15-minute intervals completed in 7.75–24.33 seconds; minimum available memory was 22.875 GiB. |

The [final resource/artifact summary](../../docs/qa/smart-city-2026-10-22/medium-final-all-ui-summary.json) records zero OOM events and zero restarts across all eight monitored containers. Highest reported source-clock ages were 0.390 / 0.232 seconds, not browser capture-to-display latency. VIOS stayed below its original 2 GiB ceiling, but its memory rose from about 1,322 MiB to 1,424 MiB during the run; retention/growth and a day-long plateau remain unresolved.

The one-frame question path remains unqualified after a real request described a purple image; its exact cause is unresolved. The Smart City request explicitly uses five seconds. The October 22 production UI and rendered camera/box/occupancy and Ask/evidence interaction checks passed, as did that two-hour combined replay. This tested one sequential Ask every 15 minutes, not continuous visitor-rate or concurrent questions or a full booth day. Manual review still found prose errors, so generated prose is not authoritative for counts or alerts. Those unrelated clips remain uncalibrated and map/rule fixtures remain separate. Their run had no active native MV3DT adapter. The current Isaac deployment has a separate two-stage adapter with guarded experimental person hints; promoted global fusion and vehicle accuracy remain unqualified. Current final-scene and Thor runtime claims need their own evidence.

## 10. Focused CPU tests

The implementation's already prepared CPU test environment is `/tmp/vss-city-backend-test-env`. To create a durable equivalent without changing system Python:

```bash
python3 -m venv .spark/city/test-env
.spark/city/test-env/bin/python -m pip install -r tools/smart-city/controller-requirements.txt \
  pytest==9.1.1 pytest-asyncio==1.4.0 httpx==0.28.1 ruff==0.17.1 mypy==2.4.0

.spark/city/test-env/bin/python -m pytest -q \
  tools/smart-city/test_manage.py tools/smart-city/test_controller.py \
  services/analytics/behavior-analytics/apps/city/tests

PYTHONPATH=services/agent/packages/vss_agents/src .spark/city/test-env/bin/python -m pytest -q \
  services/agent/packages/vss_agents/tests/unit_test/api/test_analysis_profiles.py \
  services/agent/packages/vss_agents/tests/unit_test/api/test_analysis_profile_capacity.py

.spark/city/test-env/bin/ruff check tools/smart-city/controller.py \
  tools/smart-city/test_controller.py tools/smart-city/test_manage.py \
  services/agent/packages/vss_agents/src/vss_agents/api/analysis_profiles.py \
  services/agent/packages/vss_agents/tests/unit_test/api/test_analysis_profiles.py

.spark/city/test-env/bin/ruff format --check tools/smart-city/controller.py \
  tools/smart-city/test_controller.py tools/smart-city/test_manage.py \
  services/agent/packages/vss_agents/src/vss_agents/api/analysis_profiles.py \
  services/agent/packages/vss_agents/tests/unit_test/api/test_analysis_profiles.py

cd services/agent
../../.spark/city/test-env/bin/mypy --follow-imports=silent \
  packages/vss_agents/src/vss_agents/api/analysis_profiles.py
```

These are pytest tests, not unittest-discover tests. The controller tests replace Docker/services with CPU mocks; they start no detector. Geometry fixtures explicitly test projection failures, directions, dwell/gaps, occupancy/queues, resets, durable history, frame matching, rule revisions, media ranges, site isolation and native acknowledgements. Separate runtime receipts prove actual inference and source lifecycle.

## 11. Models and device-local builds

The prepared Spark has both RF-DETR Small (512) and Medium (576), exported with `rfdetr==1.11.2`, opset 17, dynamic batch one/two, FP32 input/output and FP16 TensorRT internals. The [artifact lock](artifacts.lock.json) pins the original checkpoints, exported graphs and observed Spark engines. Both engines passed actual 100-image FP16 corpus checks at batch one and two. This is a class-stratified COCO validation proxy, not final-city accuracy.

| Model | FP16 batch-two road AP | Engine GPU compute p50 / p95 per two-image batch |
| --- | ---: | ---: |
| Small | 55.884 | 8.247 / 9.047 ms |
| Medium | 57.803 | 9.423 / 12.382 ms |

These benchmark values use the original detector postprocessing. The current October 23 worker keeps one supported city class per query; its paired cached-output rescore changed Medium's six-class AP50:95 to 57.681. See the [as-built model discussion](../../docs/smart-city-as-built.md#models-and-measurements) for the exact order of filtering, measured tradeoff and retained false-detection limits.

The timing excludes decoding, preprocessing, tracking, analytics, transport and display. Both were measured serially in the same operating state. Medium improves this proxy's aggregate and small-object AP, with a truck-class tradeoff. It subsequently passed the mixed-rate native checks, final rendered UI checks and two-hour combined Spark replay above. Small remains the tested lower-cost baseline. The generic selector defaults to Small only when no saved device-local selection exists; use `show` to inspect the actual selection. Full booth-day, final-scene and Thor qualification remain separate. Source clock, event and spatial accuracy remain independent gates. [Challenger investigation and full method](CHALLENGERS.md) lists the candidates actually run and the licensing/download/plugin barriers for the others.

Inspect or prepare a qualified model on this host without starting inference:

```bash
python3 tools/smart-city/model_profile.py show
python3 tools/smart-city/model_profile.py config --size medium
```

Selection is explicit and atomic. Pause the controller's sources before changing it; a selection does not modify an already running worker. The next launch uses generated 512/576 configs and a SHA256-bearing model revision:

```bash
python3 tools/smart-city/model_profile.py select medium
# Restore the smaller option when testing the alternative.
python3 tools/smart-city/model_profile.py select small
```

RF-DETR selection requires local artifact hashes and actual FP16 quality receipts, not a filename alone. Do not fabricate receipts or copy Spark qualification into Thor. The controller and launcher share the same selected-model contract.

### Experimental TrafficCamNet Transformer in the Isaac simulation

The explicit Spark selector `trafficcamnet-transformer` runs the tested NVIDIA TrafficCamNet Transformer Lite R18 engine with native MV3DT. It emits `person`, `car`, and `two-wheeler`; the last is NVIDIA's combined class and can include bicycles and motorcycles. It does not provide distinct bicycle, motorcycle, bus, truck, or road-sign output in this application. Its detection comparison and limitations are documented in the [October 26 report](../../docs/smart-city-nvidia-detector-comparison-2026-10-26.md); detection and shared-ID accuracy in the live simulation remain separately testable. This trial does not replace the RF-DETR qualification or qualify Thor.

On the prepared Spark host, the original evaluated model and target-device engine can be staged and selected without a network download or new build:

```bash
python3 tools/smart-city/stage_trafficcamnet_runtime.py
python3 tools/smart-city/model_profile.py config --size trafficcamnet-transformer
python3 tools/smart-city/model_profile.py select trafficcamnet-transformer
python3 tools/smart-city/model_profile.py show
```

Pause both controller-owned sources and verify the detector has exited before switching. Select the matching pinned MV3DT demo profile with class 6 geometry and the matching DeepStream image, restart the controller if it is still using the old model-profile code, then resume the existing sources through the Agent. Launch validates model and adapter hashes; the selected worker binds the three adapter files read-only. It does not rebuild an engine or change the saved memory reserve. The live worker must be relaunched for any model selection to take effect.

To roll back, pause the sources and wait for the worker to exit, then run `python3 tools/smart-city/model_profile.py select medium` and resume them. RF-DETR uses the original image binaries without the experimental adapter mounts. Preserve the calibrated tracker profile and keep source identities and recordings intact; model selection alone does not delete them. If the adapter is rebuilt, its receipt changes and TrafficCamNet must be explicitly reselected before launch.

For engineering rebuilds, stage each original checksum-verified checkpoint:

```bash
python3 tools/smart-city/model_assets.py small
python3 tools/smart-city/model_assets.py medium
```

`export_model.py` and `verify_export.py` run in an isolated PyTorch environment. This run used the existing `vss-rtvi-vlm:3.3-sbsa-codecs` image's PyTorch `2.11.0a0+a6c236b9fd.nv26.3.46836102`, TorchVision `0.25.0a0+b7d91027.nv26.3.46836102`, `rfdetr[onnx]==1.11.2`, ONNX 1.21.0 and Transformers 5.5.0. Do not install model packages into the live Agent, VLM or controller environments. The existing `vss-city-export` engineering container mounts `.spark/city` at `/work`; on this prepared host:

```bash
docker exec --user 1000:1000 vss-city-export /work/export-env/bin/python \
  /work/export_model.py --size medium --checkpoint /work/models/rf-detr-medium.pth \
  --output /work/models/rfdetr-medium --batch 2
docker exec --user 1000:1000 vss-city-export /work/export-env/bin/python \
  /work/verify_export.py --size medium --checkpoint /work/models/rf-detr-medium.pth \
  --onnx /work/models/rfdetr-medium/rfdetr-medium.onnx \
  --video /work/media/traffic-sample.mp4 --output /work/models/rfdetr-medium/validation
```

Those commands describe the prepared engineering container, not a fresh-host installer. Its script copies must match `tools/smart-city/` before rebuilding. Retain the export/parity receipt and re-run precision/quality checks for any changed dependency or graph.

Build the native image and a target-local engine under the saved guard, with existing inference stopped first so timing/build workloads do not overlap:

```bash
python3 tools/smart-city/manage.py build
python3 tools/smart-city/manage.py build --perception
python3 tools/smart-city/build_engine.py --size medium
```

The engine builder stops its own GPU container if guard telemetry fails, available memory crosses the saved reserve or its 20-minute bound expires. It records the graph/engine/image hashes and hardware. A successful build is not inference qualification. Use `benchmark_engines.py` for reference-set consistency and serial timing, then `evaluate_tensorrt_corpus.py` for the actual FP16 corpus. Its explicit `run --allow-gpu` stage needs the single GPU work slot; `prepare` and `score` remain CPU-only. Keep one-frame parity separate from dataset accuracy.

Complete recorded replay audit on the prepared inputs:

```bash
python3 tools/smart-city/manage.py recorded
python3 tools/smart-city/manage.py analyze --frames 3000
python3 tools/smart-city/verify_recorded_run.py \
  .spark/city/state/observations-ACTUAL_RUN_TIMESTAMP.ndjson \
  --output docs/qa/smart-city-2026-10-22/recorded-run-current.json
```

Use the actual generated observation filename. The auditor requires all 1,443 traffic and 795 pedestrian frames, increasing unique sequence values, bounded original-image boxes, string IDs and exact browser-time lookups. The two recordings remain uncalibrated independent scenes.

## 12. Thor preparation and final cameras

The [Thor requirements](../../deploy/docker/smart-city/thor-requirements.json) record the DeepStream 9.2 / JetPack 7.2.1 GA / L4T 39.2 candidate stack from [NVIDIA's installation guidance](https://docs.nvidia.com/deepstream/text/DS_Installation). Verify the actual Connect Tech BSP first. This workflow does not flash the Anvil-T5, change its guard or copy Spark binaries. `--device thor render` is safe preparation on Spark; build/start/analyze require actual Thor hardware and a matching local engine receipt.

On the actual target, preserve its initialized `.thor/settings.json` reserve, rebuild the native libraries and engine, then repeat decoder, CUDA preprocessing/tracking, negative controls, source lifecycle, temporal alignment and concurrent-memory qualification. The Spark image uses CUDA device RGBA surfaces; the target GPU conversion/copy path must supply the same validated linear input contract. A container tag alone does not prove that path works on the installed BSP.

For Isaac Sim cameras and map changes, use [the camera handoff](../../docs/smart-city-camera-handoff.md). The current two-camera Expo site has actual shared geometry; matrices, ground homographies and geometry must continue to describe the approved scene and decoded image sizes. Optional guarded person hints from the deployed native second stage do not qualify global identity, vehicle fusion or unique site counts. Keep production fusion disabled until its independent promotion criteria pass. A prepared Thor configuration does not establish target-device runtime.


## 13. Historical October 22 replay recovery

This section preserves the recovery procedure for the earlier recorded-input configuration and its exact UI package. It is **not the current Isaac demo recovery procedure**. Use the [Isaac operator guide](../../docs/smart-city-isaac-integration.md) for the active two-camera site and isolated port-7782 package. Do not apply the historical shared-UI command below as routine recovery for the current demo.

After a base VSS redeploy, first restore its ordinary healthy model/media services through the existing Spark workflow. Keep the saved 20-GiB guard active. Verify the existing city controller and the Agent's city profile URL; if either is missing, restore the controller/profile through sections 4–5 before requesting source pauses. Reuse the existing controller and do not start a standalone controller alongside its systemd unit. Then pause both owned Smart City sources through section 7 and confirm controller inventory is empty before recreating VIOS or changing native tuning. These recovery checks do not start source analysis or a model build. This section describes the measured Spark configuration; it is not a Thor startup recipe.

The worker reads `.spark/city/state/runtime-tuning.json`. The original mixed-rate replay used only `muxTimeoutUs: 10000`. The baseline two-camera Isaac profile used the following values before the current mux robustness trials; this example is not the final accepted mux configuration:

```json
{ "muxTimeoutUs": 10000, "previewFps": 30, "decoder": "cpu" }
```

`previewFps` accepts integers 1–30; the default is 15. `decoder` accepts `cpu` or `hardware`; Spark defaults to CPU and Thor keeps its existing hardware default. Recorded runs retain their existing behavior. Hardware decoding was exercised on Spark, but its short shared-GPU trial did not show a speed advantage. No inference interval option is supported: the preprocessed-tensor path bypasses nvinfer’s full-frame interval check. The mux now uses the actual source dimensions rather than the old 1080p default. See [performance evidence](../../docs/smart-city-performance-2026-10-23.md).

Preserve or restore that file while analysis is paused. `manage.py` deliberately falls back to the generic 40,000-microsecond native default when the file is absent; that default was too slow for the tested 30-FPS/10-FPS source mix. The selected Medium engine is recorded separately in `.spark/city/state/model-selection.json`; retain the pinned engine SHA256 in [the model receipt](../../docs/qa/smart-city-2026-10-22/rfdetr-medium-fp16-b2-coco100-run.json). Do not overwrite either file with unvalidated camera-specific tuning.

The measured VIOS process uses this additive `.spark/city/vios-memory-overlay.json`, with its original two-CPU/two-GiB limits inherited from the base:

```json
{ "services": { "streamprocessing-ms": { "environment": { "MALLOC_ARENA_MAX": "2" } } } }
```

With analysis paused and no active clip export, reapply only that service if a base redeploy removed the setting:

```bash
docker compose --project-name vss-spark \
  -f .spark/compose.json -f .spark/city/vios-memory-overlay.json \
  up -d --no-deps --force-recreate --no-build --pull never streamprocessing-ms
```

This allocator setting is part of the tested candidate, not a proven isolated fix or permission to raise VIOS limits. Wait for VIOS health and recheck the existing city controller/profile before proceeding.

The October 22 replay UI package was `.spark/smart-city-ui/20261022T150135382138Z`, image `sha256:dbf42268586b4979015a0ba15f2fc81cb41aec27a350c4b93785a9cfa3254a04`, source SHA256 `28474f847c0ce59c45641d6678cec1808a4fed8d6b181db0c76e481f2cb1e9ed`. It includes the decoded-bitmap ownership and canvas allocation fixes, with 158 UI tests and TypeScript passing. See [its package/browser receipt](../../docs/qa/smart-city-2026-10-22/polish-bitmap-ui.json) for the exact validation scope. The earlier `20261022T073106035307Z` package remains the historical two-hour-qualified baseline. A concurrent Defense task can have newer shared-shell source changes, so coordinate before replacing its development UI with this frozen package. Section 14 describes the isolated deployment used during parallel development. The following command replaces the shared UI; run it only when deliberately restoring this historical snapshot and no monitor is using the service:

```bash
docker compose --project-name vss-spark \
  -f .spark/compose.json \
  -f .spark/smart-city-ui/20261022T150135382138Z/compose-ui-production.json \
  up -d --no-deps --force-recreate --no-build --pull never vss-ui
```

The immutable package/image must still exist; otherwise prepare a fresh package using [UI-PACKAGING.md](UI-PACKAGING.md), rather than editing a saved snapshot. Its recorded source, artifact and image hashes are in [the polish package review](../../docs/qa/smart-city-2026-10-22/polish-ui-review.md); the earlier package receipt remains historical evidence. A future source edit needs a fresh build; production TSX is not hot-reloaded.

Verify HTTP root/site/health, resume the two actual registered source UUIDs sequentially, and verify both exact-frame camera previews and the active native rule acknowledgement. Source-set changes create a new tracker epoch. Managed live workers append to the bounded `.spark/city/state/live-observations.ndjson` family; finite qualification runs retain separate timestamped files. Confirm the actual worker arguments before following [the combined soak workflow](SOAK.md), including its explicit UI-container check. Open `http://127.0.0.1:7777/?workspace=smart-city`. Keep unrelated public recordings uncalibrated; use the separate labelled geometry-fixture workflow for map demonstrations.


## 14. Live storage bounds and parallel UI development

Managed live observations now rotate at 256 MiB per file with two previous files, at most 768 MiB of NDJSON in the named current/previous files, plus small manifest/lock metadata. A reader holding a retired inode open can temporarily retain its disk allocation beyond that visible-family cap. Rotation applies only to the stable live family, not historical test receipts or original media. The writer rejects partial records and inconsistent manifests instead of silently repairing evidence. Pause sources and preserve the entire failed family before explicitly starting a fresh family. The [native README](../../services/rtvi/rt-cv/smart-city/README.md) and [soak contract](SOAK.md) explain startup/recovery and reader checks. SQLite frame-history pruning now visits all sources; durable events remain independently scoped and preserved.

The isolated production UI runs in `vss-city-polish-ui` on loopback port 7781, behind `vss-city-polish-ingress` on loopback port 7782. This topology was introduced for the October 22 polish qualification and now hosts the October 26 package identified at the top of this guide. It uses the existing HAProxy routing template and existing backend/model services; it is not another detector or a copied event store. The private prepared-host compose file is `.spark/city/polish-ui-compose.json` and can contain inherited backend credentials; do not publish it. Open `http://127.0.0.1:7782/?workspace=smart-city` for the current isolated package. Shared port 7777 was not recreated for this package and is not its acceptance surface.

The [first shared-UI monitor attempt](../../docs/qa/smart-city-2026-10-22/polish-shared-ui-interrupted.json) failed after 214.06 seconds when the shared UI was recreated during authorized parallel development. Both requested source pauses completed; no scheduled Ask ran before the failure. Keep that failed receipt. The [production UI/browser receipt](../../docs/qa/smart-city-2026-10-22/polish-ui-production.json) records the immutable package, responsive views, exact-frame overlays and a separate manual five-second Ask/evidence check. Combined runtime qualification is recorded separately.

When qualifying the isolated snapshot, pass `--vss-origin http://127.0.0.1:7782 --container vss-city-polish-ui --container vss-city-polish-ingress` to `soak.py`. Port 7781 serves Next directly and lacks the complete media/inventory ingress routing. When qualifying the normal shared deployment, use port 7777 and explicitly include `vss-agent-ui`. Do not recreate a monitored service during a run; that correctly fails qualification. The saved 20 GiB reserve and active guard still apply with both UIs present.

The October 22 bitmap-cleanup snapshot passed its [twenty-minute combined qualification](../../docs/qa/smart-city-2026-10-22/polish-bitmap-runtime-summary.json): 47,916 frame observations, one live-log rotation, matched previews for both sources and one scheduled five-second question, with no container restarts or OOM events. That run's monitor and memory sampler completed. This qualifies that tested two-source replay, not the current Isaac package. Current combined acceptance remains active in the [October 26 goal ledger](../../docs/smart-city-intersection-goal-2026-10-26.md); Firefox after the bitmap fix and a full booth day remain separate checks.


### October 27 tracking quality comparison

The [native tracking quality audit](../../docs/smart-city-tracking-quality-2026-10-27.md) records the RF-DETR Large/MV3DT car–truck continuity repair, person-only pose comparison, rejected ReID/geometry/matching variants and deployment limits. `capture_tracking_reference.py` retains encoded footage with a separate read-only reference. `replay_tracking_trial.py` runs bounded isolated comparisons and restores the live detector. `evaluate_tracking_quality.py` scores completed trials using independent raw-image correspondences. The offline `--recorded-native-sei-clock` mode cannot publish to operational analytics or previews. `prepare_tracking_quality.py` creates a review bundle with model/configuration hashes and rollback; preparation does not activate it.

### Analyzed WebRTC display selection

On Spark, `runtime-tuning.json` can explicitly select `previewTransport` as
`jpeg` or `webrtc`. The latter requires an enabled, pinned native MV3DT profile
and the existing MediaMTX v1.21.2 binary whose SHA256 is checked by
`video_transport.py`. It renders/starts the separate `city-video` relay before
the worker. No relay binary is downloaded implicitly. The CPU relay has a
256 MiB limit and no GPU devices. RTSP publication, relay API and WHEP signaling
listen on loopback (18558, 9193, 9192); WebRTC ICE media uses UDP 8192 on the
local/LAN interfaces. The UI proxies signaling through the city analytics
service; clients do not supply arbitrary relay URLs.

The native image must contain the WebRTC worker changes, including the live
RECORD sink pacing repair. Merely setting this JSON field on an older image
cannot enable video. `previewFps` remains a cap (up to 30), and model/tracker
throughput must be measured separately. The legacy display is restored by
selecting `jpeg` with its previously measured 8 FPS ceiling and restarting only
detections. Model engines, camera calibration and memory reserves are independent
of this display setting. The volatile deployment receipt is
`.spark/city/state/video/deployment.json`; a short live trial does not qualify
multi-camera tracking accuracy or a sustained ingestion workload.

The source controller also handles the VIOS restart case where the per-sensor
stream route returns 404 while the aggregate stream inventory is valid. It
falls back only for that status and requires the exact registered sensor ID,
stream ID, URL and configured host policy. It does not treat a missing stream
as permission to accept an arbitrary RTSP address.

Live overlay metadata uses the shared ingress's `bk_city_events` backend with
`option http-no-delay`, scoped to the city SSE routes. Packet coalescing on the
general UI backend added up to 220 ms and made detections flash even though
their metadata was eventually delivered. Validate the HAProxy template in each
ingress before a graceful `SIGUSR2` reload. Existing SSE connections stay on the
old worker until the page reconnects; refresh already open viewers once. Native
video publication also has a bounded gateway-admission receipt, and status
serialization no longer holds up the metadata stream. The browser continues to
require an exact, current RTP/frame identity and clears invalid overlays.

### Wider intersection backdrop

The October 28 map capture covers 260 × 280 metres at 4160 × 4480 pixels,
four times the previous width and height with the same 16 pixels per metre.
`public/smart-city/isaac-intersection-a-map-wide.png` is an actor-free capture
of the current native city. Its registration and image hash live in the UI's
`smart-city/intersectionMapBackdrop.json`. The old PNG remains available.

The wider raster has separate bounds from the operational map. `mapPresentation`
selects it only for the matching site, original image URL and original focus
bounds. The default view and Reset remain focused on the existing intersection;
the minimum zoom becomes 0.25. Camera calibration, source geometry, valid ground
polygons, rules and tracking bounds are unchanged. No analytics site update is
needed to publish this presentation asset. The isolated source UI also needs the
new PNG in its `.spark/city/ui-public/smart-city` public mount.

The runtime's existing `capture_vss_map.py` accepts `MAP_EXTENT_SCALE=4` and a
distinct `MAP_CAPTURE_NAME`. It still requires detached camera products, an
inactive scenario and the native-stage guard, and restores its temporary
session layer and viewport. Stop analysis before capture and restore both
publishers and detection afterward. The GUI viewport's saved pixel resolution
is already scaled; restoration must divide by its saved scale before calling
`set_texture_resolution`, so capture does not shrink the presentation view.
