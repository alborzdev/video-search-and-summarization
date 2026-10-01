# Spark desktop startup verification — October 1, 2026

The new Desktop and Applications entries are **Start VSS** and **Stop VSS**.
Staff instructions are in [spark-desktop-startup.md](../spark-desktop-startup.md).
The simulator remains a separate application under its existing shortcut.

## Verified behavior

| Check | Result |
| --- | --- |
| Installed desktop entries | Executable, trusted, and accepted by `desktop-file-validate`; absolute script/icon paths; no terminal required |
| Local assets | Image inspection and cache check pass; model shards, tokenizer/config files, compiled GB10 engines and detector files present |
| Offline cache inspection | Runs with `--pull never --network none`; validates tensor offsets against file length |
| Real stop | VSS Compose services stopped; simulator container remained running; no volume or recording deletion |
| Cold start | Started cached services, restored source-mounted UI, recording and warehouse-safety analysis; fresh semantic coverage verified |
| Repeated start | Language, embedding, visual, detector and simulator process start timestamps unchanged; monitoring settings preserved |
| Actual desktop launch | `gio launch` of installed Start VSS completed the GUI path and produced a fresh ready receipt |
| Browser entry | `http://127.0.0.1:7777/?workspace=guided`, title Vision Intelligence; meaningful workflow and local AI online |
| Live preview | Decoded 1280×720 frames, `readyState=4`, video playing; current searchable coverage advances |
| Question | Submitted “Describe the visible scene and activity. Do not infer movement that is not visible.”; received a local visual answer with a 25-second inspected interval |
| Replay | Inspected clip opened and played decoded 1280×720 video with no media error |
| Browser errors | No errors or warnings in the checked tab |
| Historical media | Same sensor/stream UUID; every pre-migration recording interval retained |
| Memory | Existing 24 GiB reserve and active Spark guard retained; roughly 35–37 GiB available at ready/repeat/browser checkpoints |

The first cold-start log ran from 00:03:02 to 00:13:18 local time, including
one-time address migration. Give staff about 10 minutes before visitors arrive;
this is an observed run, not a guaranteed startup deadline. Latest healthy
desktop launch completed in about two seconds.

The current scene is still the original static hospital corridor. The answer
described that scene and reported no visible people. This verifies the local
question/replay path, not warehouse object accuracy, avatar activity or alert
accuracy. Warehouse safety is the selected analysis profile, not a claim that
the current video is a warehouse.

## Offline implementation

- Browser access uses host loopback. Backend/public service URLs use the stable
  Docker bridge gateway `172.17.0.1`, independent of venue DHCP.
- The simulator input is `rtsp://127.0.0.1:8554/digital-twin`. VST proxy/replay
  URLs use the Docker gateway so bridge-networked model containers can reach them.
- Only the existing simulator sensor/stream address fields were migrated in a
  guarded transaction with a private backup. Sensor and stream IDs, recording
  tables and historical attribution were preserved.
- Ingress binds loopback and the Docker gateway. The launcher does not expose
  the app on new venue network interfaces.
- Model services have offline flags, local model paths and empty download keys.
  Compose uses `--no-build --pull never`; UI dependencies are verified, never
  installed by the shortcut.
- The VIOS image already includes its required GStreamer packages. Its stock
  entrypoint called an unconditional apt installer; cached rendering now launches
  VST directly. The video service was recreated with this entrypoint during the
  cold-start test and is healthy.
- GUI output goes to private logs, so a desktop launch does not depend on a
  terminal output pipe. Progress and completion/error dialogs are used.
- Start checks the whole service graph as well as model probes. An incomplete
  session with ready models is stopped before a guarded cold recovery. Failed or
  interrupted startups stop the partial VSS stack. Stop still stops Compose if
  graceful API responses are unavailable or malformed.
- Operation locking prevents simultaneous starts. Stop can interrupt Start,
  verifies the target PID/script before signaling it, and waits for cleanup.
- There is no VSS/Moondream login autostart. The existing guard stays active.

## Scoped checks

`test_desktop.py`: 14 passing checks for offline configuration, credential
filtering, locking/cancellation, closed GUI output pipes, graceful-stop failure,
partial preparation cleanup, whole-stack readiness, strict source migration and
truncated cache detection. `test_bootstrap.py`: 6 passing checks, including the
cache-only video entrypoint. `test_ui.py`: 6 passing helper checks. Python
compilation, desktop entry validation and `git diff --check` pass.

Private operational evidence is in `.spark/desktop-logs/`,
`.spark/desktop-ready.json`, `.spark/desktop-network-before.json`,
`.spark/desktop-source-before.json` and `.spark/desktop-timelines-before.json`.
Browser screenshot:
`/home/spark/.codex/visualizations/2026/10/01/vss-desktop-startup/ready.png`.

## Remaining rehearsal

The host's WAN was not physically disconnected during the cold start. Cache
inspection was network-isolated and startup used local cached assets with
download/installer paths disabled. Rehearse with venue Internet absent before
the show, including the simulator's own independent offline startup. This run
does not qualify sustained show-day duration, multi-camera capacity, warehouse
recognition, appearance search, or positive/negative warehouse alert sequences.

Final state: VSS running in source-mounted mode; capture, semantic indexing,
detection and tracking active; visual monitoring paused; simulator unchanged;
Moondream stopped. Saved evidence and the 24 GiB guard are retained.

## Afternoon startup recovery

The 12:41:12 desktop start failed before model loading: both Logstash pipelines
reported a JRuby `TypeError` while requiring `logstash-core`. The saved failure
log is `.spark/desktop-logs/20261001-124112-start-1790872872652641138.log`.
The guard did not trip. The simulator and Frame Generation settings were left
unchanged.

Both protobuf codecs mutate a shared Ruby load path during registration. A
concurrent initialization race is a plausible explanation, not a conclusively
reproduced root cause. The cached Logstash bootstrap now loads that exact shared
protobuf directory and core dependency before the two pipeline workers start.
The local bootstrap differs from the cached official 9.3.3 source only by this
preload. Network-isolated configuration and two-pipeline startup probes passed;
the real cold start then initialized both `mdx-kafka` and `mdx-lvs` successfully.

The Kafka topic initializer also had an unconditional jq download. It now uses
the SHA-pinned local `.spark/offline-tools/jq` mount, refuses downloads in offline
mode and propagates parser/topic creation failures. Three network-isolated
probes covered missing parser, cached parser success and topic command failure.
The real recreated initialization container completed successfully with the
read-only cached parser and offline flag.

The full desktop retry ran from **12:51:42 to 13:03:25 local time (11m43s)**.
It restored the source-mounted app, opened Chromium in the existing session,
verified fresh semantic coverage and resumed recording, detection and tracking.
Fresh raw observations included tracked Forklift and Pallet boxes. The 24 GiB
reserve and guard remained active; no model images were rebuilt or downloaded.
The source still uses its historical camera name but now shows warehouse footage.

The user confirmed that Internet had been reconnected for this retry. This
proves recovery and the isolated cache/dependency paths, **not an entirely
disconnected reboot**. That rehearsal remains required. Latest scoped checks:
18 desktop tests and 6 bootstrap tests passed.

The browser's Live view submitted **Describe the scene.** using the default
3-second window (13:06:08–13:06:11 local). The local model described the shelving,
yellow markings, pallets and a forklift carrying boxes, and reported no visible
people. The answer displayed the exact 3-second recorded interval and opened
its evidence replay. This is a functional smoke check, not an accuracy study.
Screenshot: `/home/spark/.codex/visualizations/2026/10/01/vss-offline-start-recovery/scene-question.png`.
