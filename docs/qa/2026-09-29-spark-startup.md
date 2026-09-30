# Spark target preparation — September 29, 2026

Status: complete Spark startup and the recorded-fixture browser journey pass:
upload, indexed search, playable evidence, fresh visual answer, saved report and
retained evidence replay. Attempt 10 passes cache-only recovery with the Cosmos
pre-warmup cache fix, successful video/text warmup and fresh visual requests.
The 180-second post-request memory observation also passes, with a 27.818 GiB
minimum and no new guard trip. Later bounded joint Sim results are linked below;
sustained ingestion remains unqualified. The active Spark
reserve is 24 GiB by explicit user instruction; earlier entries below retain
their original 48 GiB setting.

Later current-state update: after the user authorized stopping Moondream and
turning off its automatic startup, attempt 11 passes full cache-only startup
with the active Sim renderer: 609.196 seconds, startup minimum 41.814 GiB.
Live preview, semantic indexing, a fresh recent-window answer and exact playback
pass. A separate 15-minute observation records a 39.176 GiB minimum, no new trip
and unchanged boot ID. Durable live retention and alert verdict bugs are repaired; the bounded retry
produces three incidents and retained event replay passes. See the [joint trial receipt](2026-09-29-spark-sim-joint.md)
for fixes, actual bounded results and current cleanup state. The earlier trip at
21:06:47 EDT predates the current renderer's start and remains unexplained.

## Host and checkout

- DGX Spark / aarch64 / NVIDIA GB10, driver 580.142.
- Ubuntu 24.04.4 LTS; DGX OTA version 7.5.0 (base build reports 7.3.1).
- Docker client/server 29.2.1; Compose 5.0.2; NVIDIA Container Toolkit 1.19.0.
- `vm.max_map_count`: 1048576. Docker storage is `/var/lib/docker` on the
  checkout's filesystem, with approximately 1.4 TiB free.
- Branch `agent/vss-3.2.1-thor-parity`, starting commit
  `c465e198b2729d45644d851250c2ca1ce94e9417`.
- Starting boot ID: `6b100cd0-2daa-4ef5-8db5-2b4c0bee5201`.
- Approximately 89 GiB host memory available before preparation.
- Pre-existing containers: `isaacsim-mcp` and `moondream-photon-dgx-spark`.
  Both were left running. The GPU process listing showed one Python process
  using 23423 MiB; this alone does not establish an active simulator scene.

Compared host versions with the current
[NVIDIA VSS prerequisites](https://docs.nvidia.com/vss/3.2.0/prerequisites.html).
Newer host OS/driver versions and a rendered Compose graph are not proof that
the complete custom local Spark configuration works.

## Completed preparation

- Spark `doctor` passes; all three bootstrap tests pass on the target.
- Installed Ubuntu's ARM64 Git LFS 3.4.1 package binary into
  `~/.local/bin/git-lfs` without requiring a privileged package installation.
  Repository-local filters use its absolute path; the existing pre-push hook
  was preserved. `git lfs pull` and `git lfs fsck` pass. All ten bounded MP4
  fixtures under the boundary-probe artifact contain video payloads.
- An apparent modification to `libwebrtc.a` disappeared after restoring the
  LFS filter. Its pre-install contents were backed up in ignored local state;
  no source file was intentionally replaced.
- Rendered the independent 35-service candidate for `10.88.9.91`, gateway
  `172.17.0.1`, using ignored `.spark/data` as its fresh data root.
- Installed and enabled the user `vss-spark-guard.service`, preserving the
  48 GiB diagnostic floor. User lingering was already enabled. No Thor
  runtime tooling or reserve was changed.
- Verified the pinned Logstash archive and staged all 31 checksum-locked
  CPython 3.12 Linux/AArch64 VIOS MCP wheels.
- Prepared a local credential/data setup script. It prompts for the NGC key
  locally, stores it with mode 600 in ignored `.spark/`, and uses sudo to create
  only missing data directories with the bootstrap's required ownership/mode.
  Passwordless sudo and NVIDIA registry credentials were unavailable initially.
- The user completed the local setup: all 21 required data roots now exist,
  and the NGC key has mode 600. NVIDIA registry login passed and released
  service images are downloading.
- All 12 distinct public service images have downloaded successfully.
- All eight public source derivatives build: UI, VIOS MCP, evidence clip,
  broker health, Elasticsearch, Elasticsearch init, Kibana init, and Logstash.
  The sampled build-memory minimum is 85.893 GiB; this includes the initial
  failed UI attempt and successful retry, and is not an inference measurement.
- The Spark Nemotron NIM and released Cosmos embedding base image have downloaded.
  All remaining NVIDIA bases/service images subsequently downloaded successfully.
- The complete `bootstrap.py stage` pass succeeds, including all source
  derivatives. Duration: 61.03 seconds; measured minimum available memory:
  86.195 GiB. The boot ID is unchanged. Staged startup has now begun; model
  weights, fresh engine compilation and inference are still unqualified.
- First actual startup found a fresh-data dependency bug: the broker topic
  check ran before `kafka-topic-init-container`, then waited for all 21 missing
  topics. Kafka itself was healthy. Stopped only that candidate check; the
  attempt exited after 129.06 seconds, minimum available memory 87.612 GiB,
  boot ID unchanged, and no model had started.
- Added the topic initializer's successful completion as a broker-check
  dependency. The actual-Compose ordering regression failed before the fix
  (`topic init` position 10 versus `broker check` position 1), then all three
  bootstrap tests, Python compilation and whitespace checks passed.
  Re-rendered with the same data root/registry and resumed staged startup.
- Verified the ordering fix on the target: topic initialization and broker
  validation both exit successfully; database/search/graph/monitoring services
  become healthy. Checked every bind input; none is missing.
- Second startup exposed renderer double-escaping of shell dollars. Logstash
  serves HTTP 200 and its Kafka consumers run, but its installed health command
  contains `$${status}` rather than `${status}`. The extra dollar pair turns
  the comparison into a PID-containing literal, producing silent health failures.
  The source graph stored `$$$${status}` after escaping Compose's already escaped
  output again. No models had been admitted.
- Changed rendering to preserve existing dollar pairs and escape only singleton
  dollars, while retaining deferred NGC credentials. The health-command regression
  fails on the old renderer and all three tests pass after the correction.
  Stopped only candidate Logstash and resumed with the same data root; second
  attempt minimum memory was 84.492 GiB, boot unchanged. Actual corrected health
  is the next check, not assumed from the source test.
- The third startup confirms corrected Logstash health and brings up the early
  infrastructure/video services. Nemotron then exits with a cache permission
  error: the empty Docker named volume is root-owned, while this image's `nvs`
  user is 1000:1000. No model inference ran. Attempt duration: 144.06 seconds;
  minimum available memory: 82.721 GiB; boot unchanged and no reserve trip.
- Added a one-shot Nemotron cache initializer that changes only its volume
  root's ownership/mode before model startup, preserving non-root inference.
  The graph now contains 36 services. All three bootstrap tests, Python
  compilation and whitespace checks pass. The fourth startup confirms initializer
  exit 0 and begins successful NGC model downloads, without the permission error.
- Inspected this exact NIM image's `/opt/nim/inference.py`: the 0.25 GPU fraction
  is supported, but the supplied `MAX_NUM_SEQS` and `NIM_KVCACHE_PERCENT` do not
  control its vLLM engine. It uses `NIM_MAX_BATCH_SIZE` (default 8) and
  `NIM_MAX_MODEL_LEN` (default 131072). After consulting the Thor memory record,
  stopped only this candidate model during download and set the supported knobs
  to one sequence and 32768 context, consistent with the bounded language-model
  context in that record. The GPU fraction and reserve remain unchanged.
  Fourth attempt duration: 121.04 seconds; minimum 81.465 GiB; boot unchanged.
  The fifth serial startup is active; all three bootstrap tests pass.
- Nine boundary-fixture SHA-256 hashes match their manifest. The chosen
  conveyor fixture is H.264, 1920×1080, approximately 29.97 fps and 7.535 seconds;
  CPU decoding and manual review of its middle frame show a box on the conveyor.
  An ignored copy has a readable recorded-simulation filename for later upload.
- Diagnosed the initial UI build failure: npm reported `Exit handler never
  called`, while its cached debug log recorded repeated registry `ECONNRESET`
  errors. Host curl and both bridged/host-network Node reproduced TLS failure
  to `registry.npmjs.org`; `registry.yarnpkg.com` returned metadata and tarballs
  successfully. Added `render --npm-registry` and selected Yarn's documented
  mirror, preserving the existing data root, lockfile and integrity validation.
  Retried `npm ci` successfully; both the complete source UI image and VIOS MCP
  image now build on ARM64. The VSS UI production build passes lint/typechecking
  with one pre-existing `OperationsWorkspace` effect-dependency warning. The three
  bootstrap tests and Python compilation pass after this renderer change.

## Model startup and target fixes

- Fifth startup completes NGC weights and fresh Nemotron GB10 compilation.
  API identity is `nvidia/nemotron-nano-9b-v2`, distinct from the image name;
  corrected application configuration to use that identity. Engine logs confirm
  32768 context, 7.338 GiB weights, 1.13 GiB peak activation, 3.14 GiB non-torch
  memory and approximately 18.82 GiB cache at the original 0.25 GPU fraction.
  The API becomes healthy; generation requests return HTTP 200. The initial
  `detailed thinking off` probe does not disable this model's reasoning; its
  cached template requires `/no_think`. These are request-generation checks,
  not visual-answer or agent workflow acceptance.
- Fifth attempt then refuses embedding admission at 51.6 GiB available versus
  the old 63 GiB check. Duration: 413.14 seconds; minimum available memory:
  50.230 GiB; boot unchanged, no guard trip. Existing workloads remain running.
- Prepared a smaller Nemotron GPU fraction (0.13) for the single-sequence/32K
  workload after reviewing its actual cache allocation. HF assets are already
  persisted under the NIM volume; the vLLM compile cache is now persisted there
  as well. The new fraction still requires target startup/request validation.
- The user paused startup to discuss the thresholds, then explicitly instructed:
  "go for it lets do 24giB reserve". Added a saved Spark reserve setting, preserved
  across renders, and per-model startup peak estimates (24/20/24 GiB for language,
  embedding and vision). The active guard confirms 24 GiB. Five tests pass,
  including exact-boundary/recovery behavior, project-only stops, saved reserve
  persistence and invalid-setting rejection. Python compilation/whitespace pass.
  The sixth startup is active with admission thresholds 48/44/48 GiB. These are
  initial estimates, not measured joint-Sim qualification; Thor tooling is unchanged.
- Confirmed the exact model's `/no_think` control with a real completion:
  `ready` in 0.155 seconds / three generated tokens. Found that the agent's
  reasoning helper recognized `nvidia/nvidia...` names but missed this NIM's
  canonical `nvidia/nemotron...` API name. Extended that recognition while
  preserving Nemotron 3's template control. All 32 reasoning test methods pass
  via a direct assertion runner (host pytest is absent). The agent already
  mounts checked-out Python source, so the fix requires no image build.
- The 0.13 Nemotron engine initializes successfully with 32768 context,
  approximately 4.14 GiB cache and a 15.82 GiB total GPU allocation target.
  Available host memory recovers to approximately 64.6 GiB (versus 51.6 GiB
  before), with both pre-existing workloads untouched. API warmup/readiness
  and embedding startup are the next checks.
- Reduced-cache Nemotron becomes healthy and answers the `/no_think` probe
  correctly in 0.209 seconds. Embedding builds fresh GB10 batch-2 TensorRT engines:
  video engine 2107 MiB / 46.38 seconds; text engine 213 MiB / 10.44 seconds.
  Decoder initialization then exits because the inherited Jetson ARM image's
  `pyds` cannot resolve `libnvbufsurface.so.1.0.0` on this host. Sixth attempt:
  430.14 seconds, minimum 51.096 GiB (including its old large-cache baseline),
  boot unchanged, no 24 GiB reserve trip.
- NVIDIA's [Spark embedding instructions](https://docs.nvidia.com/vss/3.2.1/real-time-embedding.html)
  explicitly require `3.2.1-sbsa`. Corrected the bootstrap's embedding base/tag
  and added an actual-Compose SBSA assertion; all five tests pass. Paused only
  candidate Nemotron for the affected source-image rebuild. Existing Moondream
  and Isaac Sim MCP remain running, with downloaded models/engine files retained.
- The released SBSA base downloads (digest
  `sha256:c84ab86eeeca72c93c82ee309ec04507889cbbd3f5ca961624423c24ab175053`),
  passes a real `import pyds` check with the NVIDIA runtime on Spark, and the
  affected source derivative builds successfully. Available memory returns to
  approximately 82 GiB with candidate Nemotron paused. Seventh staged startup
  has begun with the same caches, data root and approved 24 GiB reserve.
- Seventh startup exposes an incompatible engine cache: the Jetson base built
  TensorRT 10.13.2 plans, while the SBSA base uses 10.14.1.48. A direct Triton
  load with error logging confirms both plan files fail version compatibility.
  Attempt duration: 178.06 seconds; minimum available memory: 62.098 GiB;
  boot unchanged, no reserve trip. Retained both old plans with `.bak` suffixes
  in the candidate cache and resumed serial startup to rebuild them in SBSA.
  Model weights and ONNX files are retained; no global cache was deleted.
- The eighth attempt compiles fresh SBSA TensorRT 10.14.1 engines. Video:
  2108.42 MiB, generation 38.65 seconds; text: 212.446 MiB, generation 10.47
  seconds. Triton starts successfully, decoder warmup completes, and embedding
  becomes healthy. Approximately 56 GiB remains available when Cosmos starts
  its first model download. This establishes initialization/decoder warmup;
  fixture indexing and playback still require end-to-end acceptance.
- Cosmos downloads all 34 files (16.34 GB, 6m45s), loads 16.7105 GiB of
  model memory, and initializes its 4 GiB KV cache (29,120 tokens) with 16K
  context. Its first tiny visual warmup reports a CUDA allocation error, although
  host available memory remains approximately 35 GiB. The service suppresses
  that warmup failure and later reports healthy; health is insufficient proof.
- The eighth serial startup completes all health probes: 820.23 seconds,
  minimum available memory 27.585 GiB, boot unchanged, no 24 GiB reserve trip.
  Existing Moondream and Isaac Sim MCP remain running. No Sim renderer workload
  has yet been demonstrated.
- A post-start probe shows only approximately 1 GiB immediately free and about
  28 GiB available, with most reclaimable memory in file cache. Used unprivileged
  `POSIX_FADV_DONTNEED` on only the four newly loaded Cosmos safetensor files:
  free memory rises from 1.281 to 12.646 GiB, cached memory falls from 25.518 to
  14.149 GiB, and available memory stays approximately 28.08 GiB. Files are
  retained. This is a targeted diagnostic, not a global cache flush or a reserve
  change. NVIDIA documents related UMA reporting/cache behavior in the
  [Spark known issues](https://docs.nvidia.com/dgx/dgx-spark/known-issues.html).
- Direct RTVI file upload and a fresh eight-frame conveyor movement question
  return HTTP 200 in 6.022 seconds. Cosmos answers, "The box moves along the
  conveyor belt and exits the frame." Thirteen generated tokens, no reasoning
  trace. Frame comparison and the complete indexed browser workflow remain open.
- Browser source setup exposes a gateway mismatch: the Spark agent binds to
  loopback, while HAProxy connects through the host LAN address. The direct agent
  and UI-server proxy work, but public `/api/v1/analysis-profiles` returns 503,
  blocking upload. Added an agent-backend host setting with the existing host-IP
  default; Spark selects loopback. Five tests pass, Python compilation and
  whitespace checks pass. Recreated only HAProxy; the actual public profile
  endpoint now returns 200. The browser upload subsequently passes.

## Recorded-fixture browser acceptance

Used the Codex integrated browser against the real Spark gateway. Uploaded
`Conveyor-Recorded-Simulation.mp4` through the file chooser with the ready
semantic-search profile. The 7.535-second fixture produces two indexed semantic
segments; the natural query "A box moving along a conveyor belt" returns both,
and the UI merges the adjacent evidence into one clip. The selected video plays
to completion: native video `readyState=4`, `error=null`, `ended=true`.

Asked "How does the box move during this clip, and where is it at the end?"
The fresh Cosmos inspection takes 7501.3 ms and describes the curved conveyor
movement and the box exiting the frame. Manual review of the recorded clip agrees.
This uses the application's single-clip answer path, with synthesis reported as
0 ms; it does not prove a multi-clip Nemotron synthesis workflow.

Saved **Conveyor movement — recorded simulation**, with notes identifying the
prerecorded fixture and pending live RTSP qualification. Opened it through Events
& reports and replayed its retained local evidence to completion (`readyState=4`,
`error=null`, `ended=true`, duration 7.535 seconds). The report and indexed source
are in the independent Spark data root, not migrated Thor data.

- Source ID: `98ccb733-4326-4c9b-bdce-39334558932f`.
- Report ID: `f0ee5179-0260-492e-a247-002c7430c7c8`.
- [Saved report screenshot](spark-2026-09-29/saved-report.jpg).
- Host available memory observed during this browser journey: approximately
  26.2–26.6 GiB. This is a set of observations, not a continuously sampled
  workflow minimum. The startup minimum above describes startup only.

Added post-readiness `POSIX_FADV_DONTNEED` advice for large files under each
candidate model's cache roots. The helper uses read-only file descriptors, skips
symlinks escaping the roots, retains model files, and never globally drops caches.
Six bootstrap tests pass, including cache-boundary/file-retention assertions,
24 GiB guard boundaries, saved settings and actual Compose integration. All 32
reasoning test methods pass via a direct assertion runner; host pytest is absent.
Python compilation and whitespace checks pass.

## Cache-only restart and fresh inference

The ninth attempt recreates all three model containers using the saved
`cached_models=true` mode. NGC/HF/NVIDIA download credentials are absent; RTVI's
`NOAPIKEYSET` value is a literal placeholder, not a credential. HF offline is set
for all three, RTVI offline for both visual services, and NIM downloads are
disabled with a pinned local snapshot. Embedding reuses both TensorRT engines
and its decoder warmup passes. No network isolation claim is made.

All health probes pass in 465.157 seconds. Continuously sampled startup minimum:
25.286 GiB; unchanged boot ID and no reserve trip. Targeted cache advice raises
MemFree from 42.320 to 49.627 GiB after Nemotron, 40.555 to 49.319 GiB after
embedding, and 4.455 to 20.642 GiB after Cosmos. The Cosmos wrapper still reports
a CUDA allocation failure before its video warmup; its process catches the error
and reports ready. Post-readiness cache advice alone therefore does not fix this
initialization gap.

Freshly uploaded the fixture again after restart and received HTTP 200 with
the correct box-moving-and-exiting answer in 5.678 seconds. Nemotron's separate
`/no_think` request returns `Ready.` in 0.171 seconds. Memory sampled every 200 ms
around these sequential requests reaches a minimum of **24.349 GiB**, with no
guard trip or boot change. This is close to the authorized floor and does not
establish capacity for an additional active Sim renderer.

Parallel GPT-6.1 Sol review found no actionable issue in reserve/cached settings,
cache-file safety, HAProxy integration or reasoning handling. Investigation
confirms Cosmos's tiny `.cuda()` allocation occurs before its warmup's try block;
`ProcessBase` suppresses that exception. This finding led to the Spark-only
opt-in cache advice hook verified in attempt 10 below.

## Post-start reserve trip and recovery

At 21:03:46 UTC, after the bounded inference receipt above, a later guard sample
reaches **23.985 GiB**. The guard stops all 30 running candidate containers; all
stop commands exit 0, the boot ID is unchanged, and the pre-existing Moondream
and Isaac Sim MCP containers continue running. The receipt is retained locally
as `.spark/guard-trip-after-attempt-9.json`. The bounded request minimum above
is not the minimum for the later operating interval.

Keep the user-authorized 24 GiB floor. Lower Nemotron's GPU allocation fraction
from 0.13 to **0.11**, preserving 32768 context and batch 1. The pinned NIM exposes
this fraction but no fixed KV-budget environment variable. Its hybrid vLLM cache
logic allocates Mamba state once per request; the reported raw KV-token count
does not directly establish maximum context. The previous 8.03× 32K concurrency
estimate supports this smaller single-request trial, and initialization validates
actual minimum cache capacity before admitting the model. Expected allocation
savings are approximately 2.43 GiB; attempt 10 below records the measured recovery.

The new source derivative includes a default-off checkpoint cache helper called
after engine initialization and before the wrapper's first CUDA frame allocation.
Spark explicitly enables it with its candidate cache root; Thor does not. Only
the active checkpoint's safetensors are advised, with escaping symlinks rejected
and inodes deduplicated. Four stdlib tests pass with actual file-cache advice and
file-content retention checks; six bootstrap tests also pass. The affected
RT-VLM image builds successfully without re-downloading its base.

## Attempt 10 — cache-only recovery and warmup fix verified

Full staged startup completes in **640.224 seconds**, with a continuously sampled
minimum MemAvailable of **28.445 GiB**, no reserve trip and the unchanged boot ID.
The pre-existing Moondream and Isaac Sim MCP containers remain running. All three
models use persisted caches, with download credentials absent, HF offline mode
enabled, and RTVI offline mode enabled for both visual services. This proves the
tested cache-only startup, not network isolation.

Nemotron initializes successfully with allocation fraction **0.11**, 32768
context and batch 1. Its desired allocation is 13.39 GiB; the measured KV
allocation is approximately 1.21 GiB after the NIM's other memory accounting.
The smaller allocation retains the tested single-request configuration without
lowering the user-authorized 24 GiB guard.

The Cosmos source hook advises only its four active checkpoint safetensors,
**17,534,339,368 bytes**, after engine initialization and before wrapper warmup.
MemFree rises from **7.087 to 23.421 GiB**, while MemAvailable stays effectively
unchanged (**35.198 to 35.202 GiB**). The files remain intact. Both video and
text-only warmup complete. The full startup log has zero `Error during warmup`,
`CUDA out of memory`, or `No frames found` occurrences; decoder warmup also
completes without those errors. This closes the previously suppressed wrapper
allocation failure for the tested startup.

A new RTVI fixture upload and fresh movement question return HTTP 200 in
**1.423 seconds**, correctly describing the box moving along the conveyor and
exiting the frame. A second question about its final location returns HTTP 200
in **0.942 seconds**, correctly answering that it is out of frame. Nemotron's
separate readiness question returns `Ready.` in **0.168 seconds**. These are
sequential direct-model requests, not concurrent Sim or multi-clip synthesis
measurements.

After recovery, the browser reloads the saved report and replays its retained
7.535-second evidence to completion: `readyState=4`, `ended=true`, `error=null`.
The browser records no console warnings or errors during this recheck. The prior
indexed upload/search/report journey remains recorded above; this recovery check
adds retained-report playback.

The post-request memory observation completes in **180.620 seconds**, with
**902 samples at 200 ms cadence**. Minimum MemAvailable is **27.818 GiB**;
the first sample is 28.249 GiB and the last is 27.978 GiB. No new guard trip occurs,
and the boot ID is unchanged. The historical attempt 9 trip receipt remains
retained. This bounded observation does not establish sustained or joint-workload
capacity.

Six bootstrap tests, four stdlib cache-helper tests and all 32 reasoning test
methods pass; the reasoning checks use the direct assertion runner because host
pytest is absent. The affected source image rebuild takes 0.802 seconds, reusing
the existing base image and model cache.

## Remaining qualification

- Image staging/source builds are complete. Independent public-build admission
  preserved 63 GiB available memory; the complete bootstrap staging pass also
  remained well above that threshold.
- Measure joint and concurrent workloads before expanding capacity claims.
  Retain the 24 GiB runtime guard.
- Preserve existing non-VSS workloads. Stop or reconfigure them only with user
  direction if measured capacity requires it.
- The user-provided Sim RTSP URL is now available, and an actual renderer is
  running. A scene-reset procedure and joint-test memory decision remain needed
  for repeatable live-condition and workload measurements. See the
  [Sim intake receipt](2026-09-29-spark-sim-intake.md).
- Detector profiles are omitted, matching core scope. Spark GPU metrics are not
  implemented by the omitted Thor tegrastats exporter. Aggregate app readiness
  therefore has a warning even though the configured core services pass.
- UI/report copy still includes Thor/Jetson labels. Source-mounted Spark UI
  development, multi-clip synthesis, additional sources and sustained monitoring
  remain separate acceptance work.

Machine-generated environments, credentials, build logs, telemetry and data stay
under ignored `.spark/`. No production-ready, offline-ready or sustained-live
claim is made from these preparation checks.
