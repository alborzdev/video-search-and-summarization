# Continue the demo on DGX Spark

## Status and purpose

**October 1 pre-rehearsal audit:** The launcher now recovers late RTSP
publication even with capture off, retries discovery outages, preserves warm
sessions on UI/readiness failures, and finishes capture independently of a
failed monitoring pause. The UI discovers cameras registered after an empty
startup catalog and discards stale endpoint responses. Index fact requests have
five-second deadlines. Event review and the all-camera overview include detector
rule events, retain healthy feeds during a partial outage, and show incomplete
coverage explicitly. Rule resume rechecks source capabilities; competing
proximity rules cannot falsely appear active. Offline asset preflight passes,
as do 94 UI/API regressions, 46 Spark tooling tests and strict app typechecking.
The browser verified a fresh three-second forklift answer, a retained question
draft through background polling, and the detector event feed. Launcher tests
now isolate their state so shutdown checks cannot pause the real source.
The active source is recording and indexing again, the test alert is paused,
and Sim/models/reserve are unchanged. A disconnected reboot after these latest
edits still needs the next rehearsal.

**October 1 desktop entrypoints:** **Start VSS** and **Stop VSS** are installed on
the Spark Desktop and in Applications. Start the Sim first, then Start VSS. The
launcher verifies cached assets, starts guarded services, restores the current
source-mounted app, and verifies fresh recording/indexing with detection and
tracking. Cold startup and a repeat start pass; source identity and historical
recording intervals are preserved. The current app entrypoint is
`http://127.0.0.1:7777/?workspace=guided`, replacing the changing LAN address for
on-device use. Internal container URLs use the Docker gateway `172.17.0.1` and
the Sim is ingested through host loopback. Startup has no image pulls, model
downloads, npm installs, or VST package installation. See
[staff instructions](spark-desktop-startup.md) and
[verification receipt](qa/2026-10-01-spark-desktop-launcher.md). At this checkpoint
VSS is running with recording and source analysis on, visual rules paused,
reserve 24 GiB, Sim unchanged and Moondream stopped. Historical checkpoint
states below are superseded by this entry. A full disconnected show-duration
rehearsal and the warehouse scene's accuracy remain unqualified.

Updated September 30, 2026. This checkout contains the demo UI redesign, backend
fixes, research, presenter runbook, tests, and an independent **Spark candidate**
bootstrap. It is ready to hand to Codex on the Spark for deployment and continued
work. The Spark target has since passed first downloads/GB10 engine compilation
and a real recorded-fixture upload → search → playback → fresh answer → saved
report → retained replay journey. Cache-only restart and a fresh visual request
also pass. After a later 24 GiB guard trip, attempt 10 verifies recovery with a
smaller language-model allocation and the Cosmos pre-warmup cache fix: video/text
warmup, fresh visual requests and retained-report playback pass. The 180-second
post-request observation also passes, with a 27.818 GiB minimum and no new trip.
See [target evidence](qa/2026-09-29-spark-startup.md). The bounded joint Sim trial
is recorded below; sustained live ingestion remains unqualified.

Current target state: the user authorized stopping Moondream and disabling its
automatic startup. Moondream is stopped with Docker restart `no`; the Sim Scout
launcher now starts it only with explicit `--moondream`. Attempt 11 completes
cache-only VSS startup alongside the active Sim renderer in 609.196 seconds,
with a 41.814 GiB startup minimum. A separate 15-minute live-analysis observation
stays above 39.176 GiB with no trip or reboot. Live preview, embeddings/indexing,
a fresh cart-location answer and exact 25-second playback pass. Spark's VST now
uses TCP for the user's TCP-only MediaMTX publisher. Durable report retention
and the alert verdict contract are repaired. The bounded retry produces three
incidents and retained event playback passes; see the current
[joint trial receipt](qa/2026-09-29-spark-sim-joint.md) for repair outcomes and
post-trial state. Sustained ingestion and repeatable scene accuracy remain open.
The joint trial left hospital source analysis paused, recording off and no active
live rule. Sim remains running; Moondream stays stopped. The current UI trial
state is recorded below.

The tradeshow UI now opens a live Sim desk: scene preview, source-scoped
questions, explicit recording controls, inspected-interval replay, saved reports,
and source-scoped search/alert entry points. The new desk is running through
`python3 tools/spark/ui.py dev`, with source hot reload and a 4 GiB UI ceiling.
Only the UI was recreated; model budgets and Sim were preserved. The September 30
empty-scene rehearsal passes capture → question → replay → durable report →
playback after capture stops. Its bounded 555.337-second observation stays above
36.792 GiB available, with the 24 GiB guard active and no reboot. See the
[tradeshow UI receipt](qa/2026-09-30-spark-tradeshow-ui.md) and current
[presenter runbook](demo-presenter-runbook.md). Source analysis remains paused,
recording is currently **on**, and no live rule is active. The built-image fallback still has
the previous screen until deliberately packaged. The next rehearsal needs a
repeatable avatar entrance/hold/exit sequence from the user; avatar accuracy and
sustained tradeshow duration remain unqualified.

Live cameras now uses a full 16:9 frame, questions and answers below the video,
a compact recording/indexing rail, optional processing details, and a separate
camera/recording browser. Opening either workspace never starts recording or
analysis. The primary catalog camera uses a live preview; VST's stored-picture
endpoint still returns damaged frames on this target, so remaining static
previews and disconnected fallbacks can inherit that limitation. Capture gating
is shared with the demo desk, and source changes cancel old questions and reset
playback/history context. Same-camera preview navigation now waits for VST
session teardown, with a decoded-frame deadline and explicit retry. The
presentation layout also fills the display without retaining a sidebar column. The
September 30 live camera check passes a fresh
question, exact 25.001-second replay and locally retained report. Its bounded
898.133-second observation records 33.825 GiB minimum available, unchanged boot
ID and no new 24 GiB guard trip. The affected 72 tests and strict app typecheck
pass. At that checkpoint the source remained recording on, analysis paused, detectors off,
with no live rules; model budgets, Sim and Moondream's explicit opt-in are unchanged.

The subsequent user-requested detection/tracking stage is now active. Spark has
one `vss-rtvi-cv` SBSA worker using RT-DETR Warehouse and CUDA NvDCF, with ReID
disabled. Hospital source analysis is resumed with `warehouse-safety`; recording,
detection, tracking and semantic indexing are on. Fresh metadata, downstream
tracks, index progress and a concurrent question/replay pass. The bounded run
has a 29.422 GiB overall memory minimum, with no new guard trip or reboot;
active ingestion stays above 33.090 GiB. Startup now admits the worker only with
the saved reserve plus 6 GiB, based on its measured first engine-build peak.
The reserve remains 24 GiB. The opt-in detector flag is saved; Docker restart
remains `no` and the agent's cold-start source gate remains in place. No live
rule or continuous caption job was activated. Industrial mislabels appear in
the hospital scene, so this qualifies the data path, not avatar accuracy or
occupancy totals. See the [detector receipt](qa/2026-09-30-spark-detection-tracking.md)
for model staging, restart instructions and remaining rehearsal gates.

The user's target is **Isaac Sim and VSS running together on the same Spark**,
with a live RTSP stream from Sim. Do not stop or reconfigure Sim without discussing
it with the user. Start with one stream. The fresh-checkout default reserve is
48 GiB; on September 29 the user explicitly authorized a **24 GiB Spark trial
reserve**. Preserve the saved setting on this target and measure joint operation.
The Spark guard stops only
this VSS Compose project; it cannot prevent every driver/GPU hang.

## Get the exact working branch

```sh
git clone --branch agent/vss-3.2.1-thor-parity https://github.com/alborzdev/video-search-and-summarization.git
cd video-search-and-summarization
git lfs install
git lfs pull
python3 tools/spark/test_bootstrap.py
```

For an existing checkout, fetch and switch to that branch, preserving any local
work, then `git pull --ff-only`. Do not use the upstream NVIDIA default branch:
it does not include our demo changes. Use the pushed commit supplied in the handoff
message to confirm `git rev-parse HEAD`.

Give Codex on Spark this prompt:

> Read AGENTS.md and docs/spark-handoff.md. Deploy this custom video intelligence
> demo locally on this DGX Spark alongside the existing Isaac Sim workload. Use
> tools/spark/bootstrap.py, preserve the reserve and existing Sim data/processes,
> and diagnose any first-run failures. Keep all inference local. Download the
> required images/models and build the checked-out UI. Connect the user's Sim RTSP
> source after core validation. Test upload, playable search results, fresh visual
> answers, saved reports and one bounded live rule in the Codex integrated browser.
> Record actual latency/memory and every remaining limitation in the progress log.
> Do not claim readiness from container health alone. Continue improving the
> tradeshow demo using docs/demo-presenter-runbook.md and the progress ledger.

## Host prerequisites

Use NVIDIA's [VSS prerequisites](https://docs.nvidia.com/vss/3.2.0/prerequisites.html)
and [Spark deployment guidance](https://build.nvidia.com/spark/vss/instructions)
for current supported versions. At preparation time the documentation specifies
DGX OS 7.4.0, driver 580.95.05, NVIDIA Container Toolkit 1.17.8+, Docker 28.3.3+
(and below 29.5.0), Compose 2.39.1+, and NGC CLI 4.10+ when using NGC CLI workflows.
The helper uses Docker/model-service downloads rather than requiring NGC CLI.
Python 3, Git LFS (`git-lfs` package), and working Docker/NVIDIA runtime access are required. Git LFS is needed to fetch the bundled video fixtures, rather than pointer files. The helper refuses
runtime changes on anything other than an aarch64 GB10 host.

Budget at least 200 GiB free on the Docker storage filesystem for image/build/model
staging, plus video retention capacity. The helper checks checkout free space;
Codex must also check `docker info --format '{{.DockerRootDir}}'` if Docker lives
on another filesystem. Initial downloads and engine compilation can take a long
time; the demo's answer latency target applies after warm-up.

Elasticsearch requires `vm.max_map_count >= 262144`. If needed, configure this
persistently using the host's sysctl configuration. The provisioning step uses
`sudo -n install` only for missing data directories; it never recursively changes
existing service-owned data. If sudo needs a password, perform that host setup
interactively. Do not weaken directory permissions to work around it.

NGC access/license acceptance is required for NVIDIA registry images/models.
Enter the key locally, never in chat or Git:

```sh
read -rsp 'NGC API key: ' NGC_API_KEY; echo
export NGC_API_KEY
```

`stage` logs Docker into nvcr.io through password-stdin. First model startup uses
the key from the invoking environment. It is not saved in the rendered files,
but Docker/NIM container metadata may retain it. After successful caching, unset
it and recreate the model containers in a controlled staged restart; prove they
start from cache before calling the installation offline-ready. Never commit
Docker credentials, generated environments, or `.spark/`.

After the first successful model download, render again with the existing
host/gateway/data-directory/registry arguments and `--cached-models`. This mode
pins local model paths, enables HF/RTVI offline mode, disables NIM model downloads,
and removes NGC download keys from the rendered model services. Unset download
credentials in the invoking shell and perform a controlled staged restart of the
model services and their consumers. `render` alone does not recreate containers;
verify readiness and a fresh real visual request after `up`. The mode is saved
across later renders; use `--no-cached-models` when intentionally downloading a
new model. This is cache-only startup, not proof of network-isolated operation.

## Render, download/build, and start

Substitute Spark's LAN IPv4 and its actual `docker0` address (`ip -4 addr show
docker0`). Use a persistent data directory with enough space. Render is safe on
another host for inspection; all runtime-changing stages require Spark.

```sh
python3 tools/spark/bootstrap.py doctor
python3 tools/spark/bootstrap.py render --host-ip SPARK_LAN_IP --gateway DOCKER0_IP
python3 tools/spark/bootstrap.py stage
python3 tools/spark/bootstrap.py install-guard
python3 tools/spark/bootstrap.py up
python3 tools/spark/bootstrap.py verify
```

Open `http://SPARK_LAN_IP:7777/` in the Codex integrated browser. Credentials, the
generated Compose graph, health receipts and new runtime data live under ignored
`.spark/`. `--data-dir /absolute/persistent/path` changes the data root at render
time. Do not change it accidentally on a later render. Keep a backup of
`.spark/graph-password` with any Neo4j database backup.

If the host cannot establish TLS to `registry.npmjs.org`, `render` accepts
`--npm-registry https://registry.yarnpkg.com` to build from Yarn's npm mirror.
Preserve the existing host/gateway/data-directory arguments when rendering again.
The build still uses `npm ci` with the checked-in versions and integrity hashes;
registry overrides must be HTTPS URLs without embedded credentials.

`stage` verifies the bundled Logstash plugin archive, downloads the checksum-locked
VIOS MCP wheelhouse, pulls released services, and builds source derivatives,
including the current UI. It refuses to build while this candidate stack runs.
Keep Sim idle during large image builds if unified-memory pressure is high; the
helper cannot qualify someone else's GPU workload. It does not prune caches.

`up` provisions missing data roots, requires the guard, starts dependencies and
models serially, and waits for readiness before continuing. A one-shot initializer
sets the empty Nemotron cache volume to the image's service user (1000:1000);
the model itself continues to run as that non-root user. Model admission requires
the saved runtime reserve plus an initial peak estimate: 24 GiB for Nemotron,
20 GiB for embeddings, and 24 GiB for Cosmos. With the target's 24 GiB reserve,
these checks require 48, 44 and 48 GiB available respectively. These are startup
estimates to validate on Spark, not measured joint-workload guarantees. A failed
admission is a real capacity constraint to investigate with Sim, not permission
to automatically lower the reserve. The guard remains a user systemd service;
ensure the operator's user session remains active, or configure user lingering
when unattended operation is desired. Services deliberately do not auto-restart.

After each model becomes ready, startup advises away large files only within its
candidate cache mounts using `POSIX_FADV_DONTNEED`. Files are retained and no
privileged/global cache flush runs. This addresses observed GB10 CUDA allocation
failure while host MemAvailable still included substantial file cache; inspect
the before/after memory log and a real visual request, because RTVI can suppress
a warmup error and still report healthy. The Spark gateway targets the loopback
agent through `VSS_AGENT_BACKEND_HOST`; other profiles retain the host-IP default.

Spark also sets `VLM_RECLAIM_MODEL_FILE_CACHE=true` and the explicit
`VLM_FILE_CACHE_RECLAIM_ROOT` for checkpoint-scoped advice immediately after
Cosmos engine initialization, before the wrapper's first CUDA allocation.
This source hook defaults off for other profiles. The Spark Nemotron allocation
fraction is now 0.11, with one sequence and 32768 context; a 0.13 run crossed the
24 GiB operating reserve after a successful short question. That historical
23.985 GiB sample triggered 30 clean candidate-container stops, without reboot or
stopping the pre-existing workloads. Attempt 10 completes recovery in 640.224
seconds with a 28.445 GiB startup minimum, no trip and unchanged boot ID. The
pre-warmup hook raises MemFree from 7.087 to 23.421 GiB while retaining all four
Cosmos safetensors; video and text warmup both pass. Fresh movement/end-location
answers return correctly in 1.423/0.942 seconds, and the saved report's retained
video replays fully with no console warnings or errors. The 180.620-second
post-request observation records 902 samples at 200 ms cadence, a 27.818 GiB
minimum, no new guard trip and unchanged boot ID. Keep the guard; these bounded
checks alone do not establish joint or sustained capacity; the later bounded Sim
trial is documented separately.

The target reserve is saved in ignored `.spark/settings.json`; subsequent renders
preserve it when `--reserve-gib` is omitted. To change it explicitly, render with
the existing host/gateway/data-directory/registry arguments plus `--reserve-gib 24`,
then run `systemctl --user restart vss-spark-guard.service`. Confirm `floor_gib`
in `.spark/guard-status.json` before starting models. Thor's guard is separate
and retains its existing settings.

Stop only this candidate graph with:

```sh
python3 tools/spark/bootstrap.py stop
```

Use `docker compose -p vss-spark -f .spark/compose.json logs --tail 100 SERVICE`
for diagnosis. Rendered config contains a generated database password; do not
paste the whole file or `docker inspect` environment output into chat/logs.

Spark generates a private VST config with RTSP-over-TCP enabled; the Thor base
config is preserved. Detector workers are omitted, so Spark also clears their
inherited control endpoints. A paused source must remain paused after explicit
startup; do not infer live qualification from health alone.

## What is portable and what changes on Spark

**October 1, second offline/full-day audit:** startup now applies an idempotent
overlay to the existing cached graph, adding missing Docker file-log rotation and
the patched Kafka source bind for both analytics services. It preserves model
configuration, budgets, addresses and unrelated mounts. Only the two CPU analytics
workers were recreated for this audit; fresh processing was observed, all loaded
model container IDs were unchanged, and the restarted memory guard reported its
existing 24 GiB floor. The guard tolerates status-write/Docker failures and retries
stops while memory remains below that floor. Private settings/status writes are
atomic, and launcher Docker readiness operations have deadlines.

The UI cancels obsolete preview/replay responses, avoids late object-URL leaks,
and retries failed previews on reconnect/background resume. Cosmos reservations
now have cancellation, a maximum of three waiting requests and a 30-second queue
deadline. Verification passed 52 Spark tooling tests, 46 affected UI/API tests,
seven candidate-state regressions, the deployed Kafka reconnect regression, the
strict app typecheck and the offline cache preflight. A browser question returned
a real answer for a recorded three-second warehouse interval.

Eleven read-only samples over 300.9 seconds showed continuously fresh semantic
coverage and 36.63–36.83 GiB available memory. Video grew by 307,136,192 bytes,
projecting to 29.4 GB for eight hours at this rate; measured total disk growth
projects to 33.4 GB. About 1.27 TB remained free. Samples are saved privately at
`.spark/desktop-logs/20261001-eight-hour-audit-samples.jsonl`. An actual eight-hour
offline rehearsal with representative simulator activity remains unverified.
The analytics workers have no processing heartbeat endpoint, and their Kafka
configuration does not acknowledge offsets after successful batch processing;
health alone cannot prove output, and automatic replay of detector events missed
during a worker outage is not guaranteed. These are remaining qualification and
recovery limits, not evidence of a successful full-day soak. See
[desktop startup](spark-desktop-startup.md) for the operator flow.

**Further October 1 fresh-boot triage:** the launcher tolerates a bounded Docker
reboot delay, clears a partial model session before cold admission, derives init
jobs from completion dependencies, reports dead/removing containers promptly,
and preserves the original failure if shutdown cleanup also fails. Its local
Sim probe now gates capture/indexing even when discovery has a stale online
flag. The unavailable-publisher branch was exercised read-only against the live
runtime; it returns an actionable message and preserves loaded model containers.

VLM rule Resume validates the actual job and recreates only definitive missing
jobs; failed/stopped jobs require Pause before Resume. Pause/Delete handle
missing jobs idempotently and release persisted visual ownership. Cold startup
also clears Sim-source orphaned ownership before source analysis, preventing a
stale reservation from disabling questions after reboot. UI health polling no
longer switches the selected camera or destroys drafts/workflow chapters, empty
background catalogs retain desks with unknown health, and Connected requires
actual playing live frames. Fresh recording can still permit questions while
preview is unavailable. No service/model/Sim restart or reserve change was made
in this pass. Offline assets/cache and isolated regression checks passed; the
physical offline cold boot and eight-hour workload rehearsal remain unverified.
The final scoped run passed 60 Spark tooling tests and 52 affected UI/API tests
(112 total), plus the strict app typecheck and offline cache preflight. The real
unavailable-publisher check returned after 46.4 seconds with unchanged model
container IDs and the existing 24 GiB reserve.

| Component | Spark candidate |
|---|---|
| UI / Agent / VIOS MCP / evidence support | Current source; independent new data roots |
| Vision model | Cosmos3 reasoner inside source-built RT-VLM 3.2.1 SBSA |
| Language model | Supported Spark Nemotron Nano 9B NIM variant; different from Thor Edge 4B |
| Search embeddings | Cosmos Embed1 448p on RT-Embed 3.2.1 SBSA; downloads weights and compiles a fresh GB10 TensorRT cache |
| Summaries / graph Q&A | Source-patched LVS SBSA, local model endpoints, 768-dimension embeddings |
| Video | Released ARM64 VIOS; Spark uses its codec installer, not Thor's Tegra codec bundle |
| Safety / startup | Saved target reserve (24 GiB authorized trial; 48 GiB fresh default), serial admission, saved sources and always-on rules paused |
| Detectors | Omitted initially, matching the current Thor core runtime; enable/qualify separately |
| Telemetry | Shared CPU/service monitoring; Thor tegrastats omitted; Spark GPU monitoring needs target verification |

No Thor TensorRT engines, bare local image IDs, fixed Thor paths/IPs, external
Docker volumes or existing containers are needed by the Spark graph. Existing
Thor scripts and historical artifacts remain for recovery, not Spark startup.
Do not run `artifacts/thor-memory-2026-09-09/manage.py` or `tools/dev/ui.py` on Spark:
those intentionally operate the Thor candidate. A Spark hot-reload workflow is
still to be qualified; the initial bootstrap builds the UI from source.

Use the SBSA embedding image from the first engine build. If a previous attempt
used the Jetson base, retain its generated TensorRT plans outside the active
model filenames and rebuild them under SBSA. Plans from the Jetson 10.13 runtime
were incompatible with the SBSA 10.14 runtime on this target; retaining weights
and ONNX exports avoids repeating model downloads.

The entire application source is transferred through Git. **Existing runtime
content is not**: long recordings, indexed databases, uploaded media, saved user
reports/rules, model weights, caches, credentials and machine configuration are
not application source. This installs an empty library. A few bounded simulation
fixtures are in `artifacts/demo-boundary-probe-2026-09-28/clips/`; upload them for
initial testing, then onboard Sim's RTSP stream through the UI. If old recordings
and reports are needed, transfer a consistent data backup separately, preserve
ownership, and migrate source URLs; do not copy live database directories blindly.
Large raw captured tensors and rolling telemetry are retained only on Thor;
reviewable screenshots, summaries, scripts and bounded capture metadata are in Git.

## Required target acceptance before calling it ready

1. Record OS/driver, GPU, free disk, boot ID and idle memory with Sim running.
2. Confirm image pulls, source builds, model identities, weights, fresh engine
   compilation, API health, and a successful cached restart without download keys.
3. Upload a small fixture. Verify ingestion actually indexes embeddings; perform
   a natural-language search, play the match, ask a fresh question, save a report,
   and replay its evidence. Health alone does not prove any of these.
4. Connect one user-provided Sim RTSP URL. Confirm the live preview/retained video,
   recent-window question, and a bounded simple visible-condition rule. Keep
   recording retention within measured disk capacity. Pause collection afterward.
5. Measure first/warm answer latency and minimum available memory while Sim is
   active. Inspect actual answers against the frames. Do not market package damage,
   partial-edge detection, temporal comparisons or sustained monitoring as proven:
   they were not fully qualified on Thor either.
6. Record target fixes and evidence in `docs/demo-transformation-progress.md` and
   a new dated Spark QA receipt, commit and push so both devices can continue.

Preparation tests and the Git/fresh-checkout receipt are recorded in
[the migration receipt](qa/2026-09-29-spark-handoff.md).
