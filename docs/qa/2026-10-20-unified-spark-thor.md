# Shared Spark/Thor branch and fresh GB10 acceptance — October 20

## Outcome

This receipt describes the initial unified-branch acceptance with the 3.2.1
inference runtimes, before the subsequent VSS 3.3 integration. Current 3.3
qualification is recorded in [the separate upgrade receipt](2026-10-20-vss33-spark.md).

At this checkpoint the Spark installation was running from
`codex/unified-spark-thor`, the fork's default branch. All 38 service roles
were accounted for: 32 containers
running and six initialization jobs completed successfully. The UI reports
seven of seven runtime services ready. The operator explicitly selected a
**20 GiB** reserve; saved settings, the active systemd guard and fresh UI
capacity observations agree. Model and container budgets were preserved.

The bundled conveyor workflow passed: upload, warehouse-profile registration,
two indexed chunks, semantic retrieval, native playback, a fresh visual answer,
report creation and playback of its retained media. RTSP was explicitly deferred
by the operator and has not been tested on this installation.

## One branch, device-specific runtime

The shared branch starts from the latest Thor tip
`4be283bd8a56bcaf9767f3f79b844fd2cc34333b`, which contains the entire Spark tip
`d12b6a89129361c3e627267773c02c4c363cc514` plus ten commits. No selective
cherry-picks are needed. Old branches and `main` remain available.

Common bootstrap, desktop and UI entry points inspect the actual GPU, select
Spark or Thor, and reject unsupported or ambiguous hosts. Application changes
are shared. Models, TensorRT engines, data and saved reserve settings remain
local to each device. See [setup and updates](../device-setup.md).

## Fresh-install repairs

- Provision missing data roots through a bounded CPU helper; preserve existing
  contents, traversable host-owned parents and runtime-owned application roots.
- Stage the checksum-locked agent OpenCV wheel and ARM64 Kafka parser.
- Build source services sequentially; Compose's parallel limit alone did not
  serialize independent BuildKit targets.
- Move global guided/story shell styles into the global stylesheet, repairing
  the production UI build. The running app uses the current source with HMR.
- Bind monitoring locally and use Grafana port 14000. Container-facing URLs use
  the Docker gateway, while local app ingress binds both gateway and loopback.
- Permit recorded-video startup without a registered simulator; preserve the
  guarded migration and startup behavior of existing local Sim installations.
- Stage the published RT-DETR warehouse ONNX by checksum and build the GB10
  engine locally. Detector readiness requires `ds-ready: YES`.
- Accept the operator's 20 GiB reserve in host and UI capacity checks, retaining
  startup headroom and the extra eight GiB required for bounded history builds.
- Keep capacity polling independent of serialized recording queries. Compare
  Python's precise timestamps at JavaScript's millisecond resolution, avoiding
  false future-sample failures on fast loopback responses. Twelve paired live
  health requests all returned a fresh active 20 GiB guard after the repair.
- Reuse Thor's reviewed ARM64 VST codec image. The released image omits codec
  bytes; online installation into a temporary container was lost on cached
  recreation. Spark now includes the locked codecs in its cached image and
  checks libav loading with networking disabled. No runtime package install.
- Recover superseded Ubuntu packages from the official October 7 snapshot only
  when the live URL fails; retain the exact reviewed sizes, hashes, inventory
  and package identities. All 63 archives verified; the lock is unchanged.
- Use device-neutral wording in the shared upload dialog. Source hot reload
  preserved the in-progress upload configuration.
- Establish the history test's Thor environment before importing its route.
- Pin the NIM API alias for future renders; the observed cached API already
  exposed `nvidia/nemotron-nano-9b-v2`. Health verification checks that identity.

## Real workflow evidence

Target: NVIDIA GB10, aarch64, Ubuntu 24.04.4, kernel 6.17.0-1014-nvidia,
driver 580.142, CUDA driver API 13.0, Docker 29.2.1, Container Toolkit 1.19.0.
Docker GPU access and Git LFS integrity checks passed.

The fixture `artifacts/demo-boundary-probe-2026-09-28/clips/0.mp4` was uploaded
through the real Sources dialog as `spark-setup-conveyor.mp4`, with the
`warehouse-safety` profile. VST accepted 2,611,191 bytes; the agent returned HTTP
200 with two processed chunks. The detector registered and finished that file;
this does not establish detection accuracy or live tracking capacity.

A fresh search for “a curved conveyor belt with blue supports” returned both
adjacent intervals, grouped into one playable result. The original and retained
report video both decoded in Chromium, with a 7.534-second duration. The
retained player advanced past one second without a media error.

A fresh selected-footage question asked: “Describe the shape of the conveyor
and the color of its supports.” The answer was “The conveyor has a curved shape
with blue supports.” It matches the inspected fixture. Local analysis took
5.5 seconds. This is one grounded check, not a model-accuracy benchmark.

The UI saved `Spark setup conveyor validation` with HTTP 201, report ID
`3f227dab-84cd-41ea-98e1-8924a634736a`, notes and retained evidence. The report
opened and its local video played. No alert rule was created.

Nemotron returned `READY` after the key-free restart in 3.303 seconds. Before
that restart, Cosmos Embed returned finite 768-dimensional text/video vectors
in 0.010/0.491 seconds. Query-video embedding used `publish_results=false` and
left all eight Kafka partition offsets unchanged, checking the shared Thor
repair that prevents query footage from being indexed.

## Startup and browser checks

The desktop asset preflight passed with networking disabled. All three model
containers completed a cold cached start with empty NGC key environments.
After the VST codec repair, that service was recreated from the new cached image
and the complete clip workflow passed. A final key-free warm desktop start also
passed and preserved the running source UI.

Browser plugin not available: used the repository's Playwright with cached
Chromium at 1440×900 and 390×844. Page identity, meaningful content, absence of
framework error overlays, source hot reload, real interaction and console
checks passed. The narrow view had a 390-pixel document width and no horizontal
overflow. The old seven-tab e2e script predates the current eight-tab navigation;
acceptance used the actual rendered controls and real services.

Since selecting 20 GiB, 1,929 one-second samples covered 1,928.6 seconds of
installation, cached restart and browser checks. Minimum available memory was
41.433 GiB. No guard trip or reboot occurred. This includes idle/restart time
and is not a sustained ingestion qualification.

## Scoped validation and limits

- Spark tooling: 80 checks across bootstrap, desktop, detector, metadata and UI
  helpers (the latest subsets include 21 bootstrap, 41 desktop and five metadata
  checks).
- Thor tooling: 54 existing checks plus the new immutable archive-recovery test.
- Shared runtime and guard: 15 checks.
- Focused UI/API regressions: 49 plus 15 admission/adapter checks; strict app
  TypeScript check passed after the final source edits.
- Production image staging passed; current UI validation uses source mode.
  The built UI fallback predates the final wording/capacity edits and needs an
  intentional rebuild if that fallback is selected.

No new Thor hardware run, RTSP/live ingestion, detection accuracy, camera
calibration, experimental audio or disconnected eight-hour rehearsal is claimed.
Those device/workload qualification gates remain intact. The user will supply
an RTSP URL later.
