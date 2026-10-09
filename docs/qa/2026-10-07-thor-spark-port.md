# Latest Spark application port: fresh Thor candidate

Status: the Thor candidate passes actual three-model cache-only inference,
upload/playback, semantic search, visual evidence, saved reports, replay history,
playable history citations, live browser playback, and a five-minute combined
capture/detection/embedding/caption workload with actual detector-rule incidents.
Live visual questions and ten-second inspected-clip playback also pass. The continuous visual-rule path also passes two actual confirmed incidents and
clean shutdown. The code and bounded runtime acceptance are ready for review. Keep
the 48 GiB diagnostic reserve. Sustained ingestion, additional sources, other
camera encodings and concurrent heavy workloads remain unqualified.

The dated observations below preserve failed attempts and their corrections;
later acceptance paragraphs supersede earlier pending statements.

## October 7 late-evening functional checkpoint

This checkpoint supersedes pending-model statements in the earlier staging
observations below. All caches now pass exact membership and SHA-256 checks,
including the 17,545,910,496-byte Cosmos BF16 artifact. No model download is
running. The exact native ARM64 detector image is also staged.

The actual Nemotron FP8 checkpoint loads under vLLM 0.19.0 on Thor, using the
reviewed eager execution, 32k context, 2 GiB KV cache and single-sequence limits.
Real generation answers `17 + 25` with `42`; automatic tool choice returns the
requested `camera_metadata` call and exact sensor UUID.

The actual embedding checkpoint exports and builds native TensorRT engines
(batch maximum two, eight frames, 448-pixel input) and serves 768-dimensional,
finite, nonzero text, image and six-second video embeddings. Two three-second
conveyor windows pass Kafka → Logstash → Elasticsearch indexing. Native cosine
retrieval returns those fresh conveyor windows. Full Agent/UI search is still
pending.

These real requests exposed a client/API mismatch: the inherited image route
was absent and video query payloads used an older format. The Agent client now
uses the unified media API and reads `chunk_responses[].embeddings`. Media
queries request a single unchunked vector and disable result publication per
request; ordinary ingestion still publishes by default. This prevents a search
image from becoming its own indexed hit. Three runtime publication tests and
22 Agent embedding tests pass. The actual Python 3.13 Agent client returns
finite 768-dimensional text, image and video vectors against the rebuilt
service. After Logstash flush and Elasticsearch refresh, index count stays at
two and both owned query UUIDs have zero indexed documents. This completes the
client/API and query-publication check without claiming full UI search.

Ruff lint passes across Agent source. The full format check reports six files
and Mypy reports 108 errors in 16 files. Running both checks against a private
snapshot of Git HEAD reproduces the same findings (only the Mypy log timestamp
differs); this client change adds none. The full Agent unit suite completes
with 2,611 passes and seven failures. Five are missing test-harness OpenCV/`rm`;
the other two ingestion rollback expectations also fail against unchanged Git
HEAD. No tests are skipped or removed. Runtime-matched harness rechecks are
complete: all 12 scoped checks pass with offline OpenCV and a read-only `rm`
provided to the test container. Two baseline ingestion expectation failures
remain; the embedding-client tests pass.

Both models were stopped for the final Cosmos transfer and embedding rebuild,
then restarted in order. Configuration now removes model download credentials
and selects only verified local caches. Cache-only functional recreation,
Cosmos visual inference, Agent/LVS workflows, detector qualification and bounded
AI ingestion still require acceptance. The 48 GiB guard remains active.
Nemotron generation/tool calling and real Agent-client text/image/video queries
also pass after cache-only container recreation; inspection confirms model
download credentials are absent (the VLM has only `NOAPIKEYSET`).

Cosmos's first complete model startup fails its internal 600-second process
initialization deadline. A nonblocking Python stack snapshot shows it in
`torch.empty` while creating CUDA linear weights; checkpoint files had not yet
been read. During that initialization a six-second embedding ingestion request
exceeds its 120-second client deadline, then finishes both chunks immediately
after Cosmos stops (278 seconds total server processing). This is a failed
combined-startup check, not successful ingestion acceptance. All models are
stopped for bounded CUDA/MPS allocation diagnostics. Standalone direct CUDA
and MPS probes each allocate 1 GiB in about 0.1 seconds. The MPS probe
allocation succeeds but its explicit quit command times out; container teardown
stops that temporary daemon. Cosmos is now being tested alone to isolate
combined-service contention. The first visual inference
and full application tests remain pending; the diagnostic floor is unchanged.

The isolated Cosmos runtime loads the complete BF16 model (16.6871 GiB in
13.23 seconds), warms up and recognizes the actual conveyor/box frame in
3.6 seconds. The primary-color oracle initially fails: the answer correctly
names olive/teal/purple/lime because the resized GPU pixels are wrong. Raw
native-size decode preserves RGB primaries; GPU bilinear resize changes them to
`[127,127,0]`, `[0,127,127]`, `[127,0,127]` and `[127,255,127]`.
Changing the destination to RGBA does not fix it. GPU nearest-neighbor resize
preserves all four primaries at 608 × 320. A real native decode against the
modified source confirms this behavior. The Thor profile now explicitly selects
nearest-neighbor resizing in both RTVI services; their default remains bilinear
for existing deployments. Both source images rebuild successfully in serial with
all model services stopped. Cosmos's corrected color-oracle API check and the
combined startup correction remain pending.

## Baseline

Application base: `codex/spark-tradeshow-offline`, commit
`d12b6a89129361c3e627267773c02c4c363cc514`. Work branch:
`codex/thor-tradeshow-port`, checkout `/home/nvidia/video-search-and-summarization`.

The device identifies as **CTI Gauntlet + Thor AGX** (user's Anvil T5), Linux
AArch64 with 14 CPU cores and 122.862 GiB usable shared memory. Observed:

| Component | Installed |
| --- | --- |
| OS | Ubuntu 24.04.4 |
| Kernel | 6.8.12-1021-tegra |
| Jetson Linux | R39.2.0 |
| JetPack | 7.2.1-b49 |
| NVIDIA driver | 595.78 |
| CUDA runtime | 13.2.86 |
| TensorRT | 10.16.2.10 |
| Docker / Compose | 29.8.2 / 5.6.0 |
| NVIDIA Container Toolkit | 1.19.1 |

NVIDIA's [VSS 3.2.1 prerequisites](https://docs.nvidia.com/vss/3.2.1/prerequisites.html)
cover older Jetson BSP/Docker combinations. This newer host requires fresh
runtime validation. The [Jetson R39.2 documentation](https://docs.nvidia.com/jetson/archives/r39.2/DeveloperGuide/)
is the matching platform reference; no downgrade has been applied.

The reviewed cgroupfs host transaction was completed, preserving the registered
NVIDIA runtime. The required socket buffers and `vm.max_map_count` pass checks.
An explicit `--runtime=nvidia --gpus all` container successfully queried the GPU;
the generic GPU option alone did not select the needed Thor runtime.

A compiled CUDA 13.2 probe allocated 4 MiB, executed a kernel, synchronized,
copied and checked its result, then freed the allocation. It passed on the
host and in an explicit NVIDIA-runtime Ubuntu container. Device properties
report compute capability 11.0 and managed/pageable/concurrent managed memory
support. This establishes basic CUDA execution, not vLLM/TensorRT image
compatibility or inference acceptance.

## Candidate configuration

Independent `.thor/` state and `vss-thor` Compose project. The latest application
sources and shared Spark fixes are reused, with Thor-specific model images,
memory limits, caches and telemetry. The original profile templates and
official-edge launcher safety fuse are preserved.

The normal 36 GiB minimum has not been lowered. The current diagnostic guard
retains **48 GiB available**, checks fresh thermal telemetry and targets all
containers in this candidate's project. Guard logging failures cannot prevent
container stop attempts. Model startup retains the reviewed 90 GiB cold
baseline, 15 GiB additional per-model headroom and Nemotron → embedding → Cosmos
order. Detection remains omitted by default pending isolated runtime and
combined-memory tests. The optional warehouse worker uses one source, disabled
ReID, a separate Thor engine cache and the reviewed VPI CUDA tracker selection.
Its published ONNX checksum has passed; its ARM64 image is being staged.

The Nemotron 4B FP8 snapshot has finished staging: its reviewed Hugging Face
revision, exact membership and all 22 file hashes pass verification.
The Cosmos3 BF16 NGC listing matches all reviewed model file hashes and sizes.
Both downloads stage outside the final cache and verify before publication.
The 63-package VIOS ARM64 codec bundle passes exact membership, hashes and
package-control checks. Three unavailable Ubuntu patch versions were replaced
using signed APT metadata in a separate explicitly reviewed lock; the original
historical lock was not rewritten.

The small pinned Python image was staged as an OCI archive after verifying its
original registry index, ARM64 manifest, config and layer hashes, then imported
through Docker's platform-specific loader. Its repository digest remains the
original pin. This allowed dependency staging to progress while large image
pulls continued. Docker's [29.7 release notes](https://docs.docker.com/engine/release-notes/29/)
describe the daemon-wide concurrency limit that can queue other pulls.

## Checks completed

- Spark helper regression suite: 17 passing tests.
- Thor render/model integrity suite: 22 passing tests, including credential
  isolation, exact image/model selection, changed-file/symlink rejection,
  optional detector isolation, preservation of saved runtime/data settings and
  checksum-verified recovery of a fully downloaded but unpublished partial file,
  and rejection of image staging without an active guard.
- This BuildKit version traversed an unreadable `.thor` database directory
  during wildcard COPY processing despite exclusions. Alert and LVS now build
  from generated snapshots containing only their named source inputs. Context
  loading passes (about 637 KiB for Alert); snapshot checks reject symlinks,
  exclude private state and remove deleted source files on refresh. Runtime
  directories and Git metadata are also excluded from root build contexts.
- Cosmos staging now downloads its four independent shards in parallel, with
  separate partial files and an exclusive cache lease. Tests prove duplicate
  writers are rejected, resumed bytes are checksum-verified before publication,
  and credentials reach only the metadata API. The live serial transfer was
  deliberately replaced for throughput, preserving over 2.2 GB of its partial
  first shard. All four partial files advance; a 126-second observation window
  measured 2.782 MB/s aggregate transfer. Full cache verification and inference
  remain pending.
- Detector configuration: 3 passing tests. Spark retains its original CUDA
  tracker; Thor selects VPI CUDA backend 1 and conversion setting 2, with
  unchanged shared templates. Runtime detection is still pending.
- Runtime guard: 6 passing tests, including disk-full stop behavior.
- UI app TypeScript check and 6 source-resolution Jest tests pass.
- The source recovery button now refreshes both the catalog and recording
  timelines. Previously retry could recover a listed file while Play silently
  returned because its timeline remained stale. Nine video-management component
  tests and the app TypeScript check pass. In the browser, interrupted catalog
  and timeline requests were restored; Retry alone recovered both and the
  24-second clip played at 512 × 512 with no media error. Ordinary refreshed
  playback also passed with no framework errors. The VIOS thumbnail API returns
  the actual conveyor frame through its NVIDIA decoding pipeline.
- Redis startup and a real `PING` command pass.
- PostgreSQL startup and an actual `SELECT 1` query pass.
- Kafka starts, the topic initializer completes, and the built broker-check
  helper confirms required topic availability. Neo4j starts healthy and passes
  an authenticated `RETURN 1` query.
- Prometheus and Grafana start successfully. Prometheus scrapes the Thor
  exporter through Docker's private host gateway; a query returns an actual
  measured GPU-utilization sample. Node exporter also serves host-memory
  measurements and is successfully scraped. The checked host-memory metrics
  are available; some optional collectors yield no data. Unstarted backend
  targets remain down.
- VIOS MCP image builds from its verified offline wheelhouse and its dedicated
  HTTP health endpoint passes.
- The VIOS stream processor initially failed its hard-coded CUDA lookup and
  crashed during shutdown (exit 139, not OOM). This JetPack injects the driver
  under `/opt/nvidia/l4t-gpu-libs`, absent at the vendor's absolute path.
  The Thor build replaces that single ELF string with `libcuda.so.1`, keeping
  offsets and length intact and rejecting changed/ambiguous vendor binaries.
  The exact image resolves the driver, passes `cuInit` and finds one device.
  Sensor, stream processing, SDR and VIOS ingress now start healthy.
- A real 24-second clip upload creates an online file source and archive
  timeline. VIOS returns a replay MP4; FFmpeg decodes 144 frames over six
  seconds through the returned HTTP URL. This is upload/archive acceptance;
  inference and live GPU ingestion remain pending.
- Manual live capture passes through the current UI API: a registered source
  begins off, switches to user recording, establishes a retained lookback window
  and stops off. With the single-slice 24 FPS conveyor replay, the application's
  evidence URL decodes 144 frames over six seconds. The bounded recording test
  retains at least 103.803 GiB available, fresh thermal telemetry and the same
  boot ID; the temporary replay is stopped afterward. The candidate disables
  automatic recording of newly registered sources. This is recording/evidence
  acceptance, not AI ingestion or physical-camera qualification.
- The earlier eight-slice-per-frame replay records only about one frame per
  second in the released VIOS runtime; the single-slice variant records normally.
  Preserve this as a multi-slice input compatibility limitation, not a successful
  full-frame recording check. An attempted capture before source reconnection
  correctly reports failure; retry after connection settles passes.
- Elasticsearch initializes 15 green indices and Kibana starts healthy.
  The Kibana dashboard initializer completes successfully. The analytics
  consumers start and connect to their Kafka partitions.
  This prepares indexing storage; actual embedding/search remains pending.
- Logstash builds using the exact offline protobuf pack and starts healthy.
  Its `mdx-kafka` and `mdx-lvs` pipelines initialize without errors and acquire
  Kafka partitions. Their event counts are still zero; this does not establish
  real inference or indexing acceptance.
- Phoenix and the independent 512 MiB recording-history service start ready.
  The bounded, read-only host metadata bridge passes an authenticated SQL-backed
  snapshot returning the uploaded recording. No model inference is claimed by
  these checks.
- The ARM64 Alert and LVS source images finish building. The CPU Alert backend
  starts and returns HTTP 200 with `status: ok`; the Thor Compose profile now
  uses this HTTP probe for health. Read-only rule and verification-config APIs
  return their empty initial state, and alert-submission health reports its
  entity validator and event bridge ready. No alert verification or inference
  is claimed. The LVS image also passes its current server imports and CLI
  parsing in a 2 GiB CPU container with networking disabled, including the
  `--max-live-streams` argument. This probe supplies the log directory normally
  created by its entrypoint. LVS startup remains gated on the three model services.
- The source-mounted Video Analytics MCP service starts in the actual VSS Agent
  image. Its health endpoint, MCP initialization and discovery of all nine
  configured tools pass. Analytics queries still require the remaining backends.
- With container networking disabled, the actual Agent Python 3.13.13 runtime
  installs the staged ARM64 OpenCV wheel and decodes all 576 frames of the
  24-second replay at 512 × 512. This verifies offline agent video decoding,
  not inference or Video I/O ingestion.
- The exact Agent image, current source mounts and offline OpenCV wheel also
  pass `nat validate` with networking disabled. The latest inherited config
  registers the top-agent workflow, 24 functions and its function group.
  Configuration validation does not prove successful tool execution or inference.
- Evidence-clip image builds with the pinned Python base; its health endpoint
  passes and all 27 tests pass inside the image, including FFmpeg checks.
- Prepared a 24-second H.264 replay from the four captured conveyor frames.
  Its transport version has one-second keyframes, no B frames and baseline
  profile. A bounded private RTSP replay decoded 127 frames over its requested
  six-second window. Minimum available memory was 110.323 GiB, maximum thermal
  age was one second and the boot ID stayed unchanged. The temporary publisher
  and server were stopped. This qualifies the local test fixture, not VSS
  ingestion, physical-camera capture or model inference.
- The telemetry exporter runs in a bounded 256 MiB Python image and emits fresh
  host temperature, power and shared-memory measurements. Current `tegrastats`
  omits GPU utilization. An opt-in, two-second-bounded NVML CLI fallback supplies
  that measured value; unsupported values and failures remain unavailable.
  Fourteen exporter tests pass. The host-network UI uses the private host-gateway endpoint;
  browser checks now identify Jetson Thor and show real measurements.
- Browser: guided workspace loads, System navigation works, desktop 1440 × 1000
  and mobile 390 × 844 layouts render without a framework error overlay or
  horizontal mobile overflow. The System screen accurately reports unavailable
  backends while staging is incomplete. No successful inference is claimed.

The Browser plugin is absent in this environment, so QA used the installed
Playwright client and an isolated headless Chromium profile. QA scripts and
screenshots are outside the repository. Source-mounted Turbopack uses a 2 GiB
heap and 4 GiB container ceiling; no full UI image build was required.

At the staging checkpoint, available memory was approximately 111 GiB, thermal
telemetry was fresh and the boot ID remained
`652c4102-7adf-4a68-98dd-4cdf6cb8bde5`.

## Remaining acceptance

The exact ARM64 vLLM image (`b587dd56…65e8`) is now staged and passes a
network-disabled, 2 GiB container CUDA probe on the actual device. PyTorch
2.10.0 / CUDA 13.0 reports compute capability 11.0 and native `sm_110` support;
pointwise tensor operations and cuBLAS matrix multiplication produce the
expected values. Peak tensor allocation is 9,076,736 bytes. The probe exits
successfully in about three seconds, with at least 103.44 GiB available, fresh
thermal samples and the same boot ID. This proves this runtime's basic CUDA
execution; model loading, generation and tool calls still require acceptance.
The server CLI also imports its native vLLM extension successfully under the
NVIDIA runtime with networking disabled. Its help confirms support for the
reviewed explicit KV-cache size, eager mode, batch-token limit, automatic tool
choice and `qwen3_coder` parser. A CPU-only invocation hits the image's driver
placeholder; this GPU runtime must use the configured NVIDIA runtime.

The same exact vLLM runtime recognizes the locked Nemotron checkpoint as
`NemotronHForCausalLM`, BF16 compute dtype, `modelopt` quantization backend and
32,768-token context. The checkpoint declares FP8 quantization. This was a
network-disabled configuration check without model weights, so actual FP8
weight loading, generation and tool calls remain pending.
A separate network-disabled probe now selects and executes the actual
`FlashInferFP8ScaledMMLinearKernel` used by `ModelOptFp8LinearMethod` on Thor.
Synthetic FP8 weights with unit scales and BF16 inputs produce the expected
2 × 256 output with every value exactly 256. Peak tensor allocation is
33,623,552 bytes; the probe exits in 15.58 seconds with 103.76 GiB available
and the same boot ID. This uses the Nemotron image's configured default UID 0,
its actual quantization config and vLLM configuration context. It does not load
the checkpoint or test generation, recurrent attention or tool calling.
Preliminary harness errors (a different UID, missing engine context and missing
tensor-parallel initialization for parameter creation) are retained separately;
the completed probe supplies synthetic parameters directly and executes the
unmodified selected quantization method and kernel.

The first parallel Cosmos transfer ended with incomplete shard responses.
Partial files were preserved, and the next staging run resumes from those
offsets with eight bounded attempts per file and fresh signed URLs. Credentials
remain confined to the metadata API. Short responses and interrupted reads are
covered by tests; wrong resume ranges and complete checksum mismatches fail
without publication. The complete Cosmos
snapshot and actual inference are still pending.

Embedding staging now locks the same anomaly-detection model to Hugging Face
revision `3b1455ed97c7b1d5419c0c3129b7199ca4cd9382`: 25 files totaling
4,793,033,722 bytes. Small-file contents were checked against their Git blob
identities before recording SHA-256 hashes; weight hashes come from that
revision's LFS metadata. Staging is complete: all 25 file hashes verify, and
the index references all ten weight shards (820 tensors). The cache declares
768-dimensional embeddings, eight video frames, 448-pixel resolution, and no
FP8/Transformer Engine use. Model loading and inference remain pending.
The app stage now checks its model
prerequisites and reuses ready model dependencies instead of rejecting them or
recreating them. All 22 Thor bootstrap tests pass, including partial-download
publication, changed-cache rejection and this app startup boundary.
The embedding image is pinned to the exact `978ef47a…1438` index resolved by
the active source-overlay build. Registry inspection confirms its ARM64
manifest; future builds no longer select the mutable 3.2.1 tag.

The two overlapping RTVI image builds both ended with BuildKit's
`failed commit on ref ... lease does not exist` error for a shared base layer.
Their process and build-history handles confirm terminal failure. Serial recovery of both images completed from retained partial content; the
lease failure's root cause is not established. No Docker prune or cache-cleaner job was found
active at the failure checkpoint. Image staging now holds an exclusive lease
and builds each source image in a separate sequential Compose invocation;
tests reject duplicate staging and stop before the next build after failure.
This is explicit sequencing because [Bake targets run in parallel](https://docs.docker.com/reference/cli/docker/buildx/bake/).
Both source images are now built for ARM64: embedding image
`dc44cb74c6c4db4ad931067bbb6ec19cbba83a68c98dfb097b98a4182d3cd62d` and
VLM image `59c45f9a3fa978f13ac198b59e4a82a76e1081901d73b253b31ceda9ce36559d`.
No build-cache prune or daemon restart was used for recovery.

Both exact images pass network-disabled native CUDA checks as RTVI UID 1001,
with 2 GiB container limits. Their PyTorch 2.10.0 NVIDIA build reports CUDA
13.0, Thor compute capability 11.0 and compiled `sm_110` support. Pointwise
operations and cuBLAS multiplication pass with 9,322,496 bytes peak tensor
allocation. Embedding's installed Transformers 4.52.4 resolves the offline
configuration and tokenizer, imports the model and constructs all 1,198,007,162
parameters using its native empty-weight initialization contexts. Every
parameter stays on the meta device; checkpoint weights and inference were
not exercised. A preliminary global-meta probe failed on scalar extraction;
the actual Transformers initialization context works without installing
Accelerate or modifying the locked model.

Cosmos's installed Transformers 4.57.1 / vLLM 0.11.1 runtime recognizes
`Qwen3VLForConditionalGeneration`, BF16 with no quantization, and a 16,384-token
context. Its actual engine interface supports the explicit KV-cache byte
limit, eager execution, sequence/token batch limits and processor cache limit.
This check uses checksum-verified metadata copied from staging, with no
weight shards. Available host memory remained above 103.47 GiB and the boot
ID stayed unchanged. The exact embedding runtime also builds a 12,660-byte TensorRT 10.14.1
engine with a 64 MiB workspace limit, deserializes it and executes its CUDA
addition kernel correctly on Thor. This separate probe uses no AI checkpoint,
networking or downloaded engines; it finishes in 5.41 seconds with 103.60 GiB
available. An initial probe reached successful execution but its receipt code
called `len` on TensorRT host memory; the corrected buffer-size call yields a
complete successful receipt. Full model weight loading, embedding engine
export/build and inference still need acceptance.

The locked embedding model's QFormer constructor also requests
`BertConfig.from_pretrained('bert-base-uncased')`. The new candidate HF cache
was empty. A checked-in auxiliary bundle now supplies the 570-byte BERT
configuration and its Apache license from [revision `86b5e093…3594`](https://huggingface.co/google-bert/bert-base-uncased/tree/86b5e0934494bd15c9632b12f734a8a67f723594),
verified against Git blob identities and SHA-256 hashes. Read-only mounts expose
the exact snapshot and newline-free `refs/main` required by HF's cache lookup.
The embedding service is always offline, with current and legacy HF/Transformers
cache variables pointing at that cache; it no longer receives an NGC key.
A network-disabled probe in the staged Transformers 4.57.3 runtime resolves the
configuration and checks its hidden size, attention heads and vocabulary size.
The recovered embedding image also resolves this configuration and constructs
the complete model with empty weights offline as UID 1001. Actual checkpoint
loading and inference remain pending.

The fresh HF and Triton volume roots were also root-owned and unwritable by
RTVI UID 1001. Provisioning now changes only inactive candidate cache-volume
roots, preserving active mounts and rejecting other projects' volume names.
Real create/delete checks pass in both volumes as UID 1001. Tests cover altered
auxiliary config, malformed cache references and this ownership boundary.

Finish the remaining image/model staging,
start and validate support and models in order, then verify real upload,
playback, indexing, search and visual questions. Validate cache-only recreation
before claiming offline operation. Detection and a bounded live-source probe
need separate memory/progress/thermal evidence. Sustained multi-source ingestion
and concurrent heavy summarization remain outside the historical qualification.

The remaining combined-startup hypothesis is contention between private MPS
servers; it is not yet established as the cause. NVIDIA's
[MPS system constraints](https://docs.nvidia.com/deploy/mps/595/when-to-use-mps.html)
recommend a single arbitration point. A private diagnostic Cosmos launcher
with its MPS daemon disabled is prepared, preserving all reviewed model budgets
and guard settings. It has not been applied or accepted. No permanent MPS
configuration change has been made.

The rebuilt Cosmos API now passes the exact four-color oracle and actual
conveyor-frame recognition in 7.61 seconds. Direct inspection of the fixture
shows a tan paper bag with dark printed markings; the earlier box-only assertion
was incorrect and is recorded separately. The model correctly identifies the
bag and curved conveyor after the resize correction. This proves isolated
BF16 visual inference, not combined service acceptance. Normal Nemotron →
embedding order is being restored for the private no-MPS Cosmos experiment.

The first combined diagnostic stopped before applying its Cosmos override:
the isolated run had created `model-init.lock` and a small `vllm-cache` directory
inside the checkpoint, so exact membership verification rejected startup.
Those two runtime artifacts were quarantined without modifying model files;
all checkpoint hashes and membership subsequently passed. Cached RTVI mounts
are now read-only, and Cosmos's existing `VLM_RUNTIME_STATE_DIR` setting directs
writable state to its HF volume. The 22 Thor bootstrap checks pass, including
the immutable mount and runtime state configuration. A fresh guarded combined
startup is testing the private no-MPS override; its result remains pending.

That combined experiment passed actual Nemotron generation and tool calling,
embedding text/image vectors, exact Cosmos color recognition and paper-bag
conveyor recognition with all three models loaded. Cosmos weights loaded in
11.01 seconds and engine profiling/warmup took 96.55 seconds. The six-second
video ingestion request produced two 768-dimensional chunks in 0.89 seconds;
normal Kafka publication remained enabled. Across 457 fresh telemetry samples,
the minimum available memory was 56.216 GiB, maximum thermal age was one second,
and the boot ID stayed unchanged. This is bounded combined model acceptance,
not application or sustained live qualification.

The isolated Agent probe initially omitted `RTVI_EMBED_MODEL` and selected its
legacy default alias; supplying the application's existing configured alias
resolved that harness error. Actual text/image/video Agent queries then passed
in 4.13 seconds, with normalized vectors and unchanged index count (two owned
query IDs produced zero indexed records). A checked-in Thor wrapper now
verifies the vendor script before applying the same MPS adjustment, preserving
the shared Kafka gate. Its normal-path restart and inference are being tested
before app startup. No model or memory budget changed.

On October 8, the checked-in launcher passed normal gated Cosmos restart and
actual visual inference (7.89 seconds), followed by embedding inference (0.56
seconds), with 56.79 GiB available. App-stage startup then passed all health
probes at 55.16 GiB. A fresh browser upload of `thor-oct8-ui-conveyor` completed
its full Agent processing path and used the application's January 1 media
timeline; the earlier October-dated diagnostic source is outside that uploaded
search index convention. The fresh source returned Agent semantic matches and
one merged UI search clip. Its full 24-second, 512×512 replay played in the
browser without errors. Exact keyword checks for two new query IDs confirmed
zero query documents and unchanged total embedding count (seven).

Actual Agent → LVS → Cosmos replay inspection correctly answered that the
conveyor has blue supports and is curved. A broader description incorrectly
called the tan paper bag cardboard boxes. CPU-decoded frames at 0, 7 and 14
seconds confirm the paper bag, and the failed material-identification receipt
is preserved. Single-frame material recognition passed earlier; full-video
object/material accuracy is a model limitation, not a passing accuracy claim.
UI evidence synthesis, history, detection and bounded live AI ingestion still
need separate acceptance.


The rendered selected-evidence question passed with an E1 citation, and the
saved “Thor replay geometry QA · October 8” report exported its title, answer
and citation in HTML. Replay history initially failed because numeric
file-relative event intervals were validated against absolute recording
chunk times. Full-file validation now subtracts only a matching explicit,
timezone-aware creation origin; persisted NTP metadata, partial requests and
live requests are unchanged. All 45 aggregation guard tests pass. The same
24-second source then built history in 60 seconds and correctly answered the
blue/curved geometry question. Its answer quoted Unix seconds, so the UI now
recognizes Unix ranges strictly inside the retained source timeline. Eleven
history API tests and the scoped UI typecheck pass. Actual browser history
question → citation → ten-second video playback passed without page errors.
Detection and bounded live AI ingestion remain pending.


The detector's first native engine build was container-OOM-killed at its
6 GiB limit, with more than 96 GiB host memory available and unchanged boot.
An isolated 8 GiB retry built the 93,821,524-byte native engine and reached
actual `ds-ready: YES`; minimum host availability was 94.674 GiB. Restarting
from that engine under the normal 6 GiB limit passed and cleared build-time
allocations. The new `build-detector-engine` command requires all GPU services
stopped and at least 90 GiB available, uses the temporary 8 GiB limit, then
stops its builder and removes the override. Normal detector startup requires
an existing engine. Twenty-five bootstrap tests plus three launcher tests pass.

The first real-camera test registered successfully but produced no frames:
the inherited simulator SEI clock settings discarded ordinary inputs. Thor
now disables those two simulator settings while preserving system NTP time,
CUDA tracking, normal budgets, and Spark defaults. Frame flow returned at
approximately 30 FPS and native Person detections reached Elasticsearch.
The raw Kafka observer was unsuitable for the detector's binary payload and
assumed UUID sensor IDs; the real 2D converter uses the REST camera name.
The corrected qualification observes the actual decoded/indexed records with
an exact unique name and fresh time window. It accepts DeepStream's documented
-0.1 confidence sentinel for tracker-only frames, while requiring an actual
Person detection with a positive inference confidence. See
[NVIDIA object metadata contract](https://docs.nvidia.com/metropolis/deepstream/9.0/sdk-api/struct__NvDsObjectMeta.html).
The five-minute output test remains in progress.

The explainer now reads the configured health profile rather than hard-coding
Spark; twelve component tests and actual Thor browser rendering pass.
Appearance crop embeddings also explicitly disable publication, matching the
main Agent media query client. Seven appearance tests pass. Required Agent
lint passes, and its 108 Mypy errors / six formatting files match HEAD apart
from line-number shifts. The final full unit run passed 2,616 tests; one
missing sibling Alert Bridge mount was corrected and its test passed on
recheck. The two previously reproduced ingestion assertion failures remain.

### Native CUDA detector acceptance (October 8, 01:14 EDT)

The corrected five-minute isolated detector test passed. The native person-walking
sample produced 6,837 fresh decoded detector records through Kafka, Logstash and
Elasticsearch, with actual positive Person detections, finite ordered bounding
boxes, fresh thermal telemetry, unchanged boot ID and at least 101.633 GiB
available. Tracker-only confidence `-0.1` is an explicit DeepStream sentinel;
the positive oracle required inference confidence of at least 0.5. No empty
indexed frame was observed, so this receipt does not certify a negative-scene
accuracy check. The source registration and owned replay publisher were removed
or stopped at completion. Recording and Agent ingestion were off during this
isolated test. Receipt: `.thor/qa/detector-five-minute-acceptance.json`.

The checked-in `build-detector-engine` command was then exercised against the
cached native engine with the three AI models and CV stopped. It verified the
ONNX, required the 90 GiB baseline, waited for actual pipeline readiness, stopped
its temporary 8 GiB container and removed `.thor/compose-detector-build.json`.
Normal startup recreated the healthy detector with exactly 6,442,450,944 bytes
of container memory. Logs: `detector-builder-cached-command.log` and
`detector-normal-six-gib-restoration.log`. This confirms the command's cached
runtime path and cleanup; the earlier eight-minute native engine compilation
receipt establishes the first-build path separately. The general `verify`
command now checks the detector's `ds-ready: YES` body as well as HTTP status.
Combined live capture/detection/embedding/caption acceptance remains pending.

### Combined live workload acceptance (October 8, 01:34 EDT)

One owned 1280 × 720, 10 FPS, single-slice H.264 replay camera passed a
five-minute diagnostic with manual recording, the normal 6 GiB CUDA detector,
live embeddings and the existing 30-second/four-frame Cosmos caption profile
running together. The stored outputs reached 59 embedding chunks, 2,084 detector
frames and nine caption documents. Available memory stayed at or above
52.084 GiB, thermal telemetry remained fresh and the boot ID did not change.
The final analysis status proved indexing active, and the retained recording
window was ready for questions. No model, decoder, KV or reserve budget changed.

The temporary person-entry polygon produced actual Restricted Area Violation
incidents through the analytics backend. The rendered Events & reports view
showed the correct rule and source without browser errors. Live browser video
also decoded at 1280 × 720 and advanced to 2.527 seconds, with readyState 4 and
no player/page errors. Receipts: `full-live-rule-events-ui.json` and
`full-live-player-ui-probe.json` under `.thor/qa/`.

The original combined-test receipt reports a cleanup observer failure: its
JSON parser incorrectly expected a body from successful native caption DELETE.
A separate recheck received HTTP 200 with zero bytes and confirmed the owned
VLM resource has `inference_active: false`. Rule deletion, Agent pause, capture
stop and owned publisher/server stops all completed. The original failed
observer receipt is preserved; `full-live-workload-and-cleanup-acceptance.json`
combines the completed workload checks with
`full-live-caption-cleanup-recheck.json`. The observer now accepts empty success
bodies. Earlier attempts are also preserved: initial capture reconnect race,
then the correct one-source capacity rejection caused by the older QA upload's
legacy warehouse assignment. Re-profiling that owned recording to semantic-only
through the supported API removed zero detector records and preserved its media
and search index. No capacity limit was bypassed.

This qualifies the bounded single-source workload on this boot. It does not
qualify sustained operation, additional sources, multi-slice camera recording,
concurrent heavy questions or model answer accuracy for all object/material
classes. The 48 GiB diagnostic reserve and CUDA tracker remain mandatory.


### Live question, search and evidence acceptance (October 8, 01:39 EDT)

With continuous ingestion/captioning paused, manual capture from the owned
single-slice source was re-enabled for a bounded visual question. The actual
rendered UI submitted a ten-second recent-footage request and received a grounded
answer in 10.115 seconds, identifying the paved path, low brick wall and dense
green trees/bushes. The answer carried the verified observed interval
05:38:55.694–05:39:05.694 UTC. The UI's Play inspected clip action decoded exactly
ten seconds at 1280 × 720 and advanced beyond 0.5 seconds with no player or page
errors. Live source-filtered fusion search returned ten clips, all with the exact
owned sensor UUID. Available memory stayed above 52.001 GiB. Capture and the
owned publisher/server were stopped after the requests. Receipts:
`.thor/qa/live-visual-and-search-acceptance.json`, `live-visual-question-ui.json`
and `live-inspected-clip-ui.json`. The earlier browser harness tried the visible
button text rather than its Send question accessible label and sent no request;
that failure is preserved in `live-visual-button-harness-failure.json`.

The final read-only platform dispatcher selects Thor on the actual host. All four
GPU services have their pinned native/source image identities and no model
download credentials. `bootstrap.py verify` passes every health probe, including
actual detector readiness and Elasticsearch primary-shard health. These health
checks supplement the functional receipts above. The full non-ignored-file
secret scan checked 28,371 files. Its sole private-key signature was the unchanged
vendor fake RTC certificate test fixture already in Git HEAD; an exact-byte/HEAD
comparison records that narrow baseline exemption. No new credential or actual
NGC key was found. The initial scanner finding and reviewed receipt are retained.


### Continuous visual-rule acceptance (October 8, 01:46 EDT)

The actual UI coordinator and native Alert Bridge created a temporary visual
rule for the owned camera using the existing 30-second, four-frame, 512-pixel,
128-token profile. The condition checked an outdoor paved path and green trees,
which are visible throughout the sample. Two actual Elasticsearch-backed VLM
incidents carried the exact rule/source IDs, `verdict: confirmed`, and the
model response `TRUE`. The native rule stayed active while producing results.
Deletion through the UI coordinator succeeded, did not resume history, and
left the retained native stream's inference inactive. Manual capture and the
owned publisher/server were stopped. Minimum available memory was 51.945 GiB,
with fresh telemetry and unchanged boot ID. Receipt:
`.thor/qa/continuous-visual-rule-acceptance.json`. This positive control checks
the live rule's complete publication and cleanup path; it does not establish
false-positive rates or general model accuracy.


## Final validation and operating state

The common platform entry point identifies the actual Thor host. Final health
verification passes, all four pinned GPU service identities are present, and
runtime model-download credentials are absent. Both continuous visual incidents
render correctly in Events & reports. The owned live source is paused, recording
is off, both temporary rule types are deleted, and native VLM inference is
inactive. The core app, source HMR UI and normal 6 GiB detector remain ready.
The 48 GiB guard remains enabled. All acceptance evidence is in ignored `.thor/qa/`;
no credentials, models, recordings or runtime databases are committed.

Validation includes 25 Thor bootstrap tests, three launcher tests, 17 Spark
bootstrap tests, three detector configuration tests, six guard tests, 14 telemetry
exporter tests, 46 LVS history-clock tests, 11 history API tests and 12 processing
platform component tests. Scoped UI TypeScript checks pass. The final Agent full
suite reports 2,616 passes and three failures; the missing read-only alert sibling
mount was corrected and that exact test passed on recheck, leaving two ingestion
rollback expectation failures reproduced against unchanged HEAD. Ruff passes.
The six format files and 108 Mypy diagnostics match HEAD, including line-shift
normalization for the single new appearance payload field. No test was removed
or skipped, and those existing checks are not presented as passing.

The accepted five-minute combined workload is one owned 720p10FPS single-slice
camera, not a sustained-ingestion or multi-source qualification. Keep the normal
36 GiB reserve policy and the larger current 48 GiB diagnostic floor. Native
multi-slice VIOS recording performance, concurrent heavy summarization/questions
and broad model material/object accuracy remain explicit limits. This development
candidate uses source-mounted UI hot reload; no packaged UI fallback was built.
