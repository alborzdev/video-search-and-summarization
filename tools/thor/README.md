# Latest Spark application on Thor

This independent candidate keeps the October Spark application source and the
reviewed September Thor model identities and bounded-memory configuration.
It uses `.thor/` for private generated configuration and fresh runtime data;
it does not reuse historical receipt paths or replace the official-edge launcher.

Cache-only inference and the actual upload, playback, search, evidence, report
and replay-history workflows pass on this JetPack 7.2.1 / Docker 29 host.
The CUDA detector also passes five minutes of isolated indexed output. A bounded five-minute single-source capture/detection/embedding/caption run,
live visual question with playable evidence, and continuous visual-rule positive
control also pass; sustained ingestion remains unqualified.
See the [acceptance receipt](../../docs/qa/2026-10-07-thor-spark-port.md).
Container readiness alone does not establish working inference or sustained
ingestion. Keep source collection paused until its selected workload passes a
bounded test. See [runtime qualification rules](../runtime/README.md).

## Setup

Run from the repository root. Identify the actual platform with
`python3 tools/runtime/platforms.py`. The common entry point
`python3 tools/runtime/bootstrap.py doctor` selects Spark or Thor by GPU;
other arguments pass through to the selected helper. Platform startup commands
and budgets remain distinct.

```sh
python3 tools/thor/bootstrap.py doctor
python3 tools/thor/bootstrap.py render --host-ip <Thor-LAN-IPv4>
python3 tools/thor/bootstrap.py install-guard
python3 tools/thor/bootstrap.py stage-model
python3 tools/thor/bootstrap.py stage-embed
python3 tools/thor/bootstrap.py stage-cosmos
python3 tools/thor/bootstrap.py stage-agent-cache
python3 tools/thor/bootstrap.py stage
```

The host must have the NVIDIA runtime, cgroupfs and required kernel settings.
Use the reviewed host remediation tooling when `doctor` reports a blocker.
Do not change Docker's runtime configuration with an unrelated replacement file.

Persist the Video I/O socket buffer ceilings before the first launch. Setting
them only with `sysctl -w` loses them at reboot:

```sh
sudo install -o root -g root -m 0644 deploy/docker/thor-local/90-cti-vss-network.conf /etc/sysctl.d/90-cti-vss-network.conf
sudo sysctl -p /etc/sysctl.d/90-cti-vss-network.conf
python3 tools/thor/bootstrap.py doctor
```

This applies only the two network buffer ceilings; it does not start VSS.
The desktop preflight checks host prerequisites before changing clocks or services.

The Nemotron download is pinned by revision and every file hash; interrupted
downloads resume outside the final model directory. Image staging uses the
exact Nemotron, embedding and Cosmos runtime image digests and locked codecs.
The fresh codec lock is separate from the
historical lock; [review](../../deploy/docker/thor-current/codecs-review-2026-10-07.json)
records the three Ubuntu security package updates required by the new install.
Both lock hashes are explicitly trusted by the image installer. Image staging
and builds require stopped AI workloads and at least 200 GiB free disk space.
The helper holds an exclusive staging lease and builds one source image per
Compose invocation. Wait for that command to finish before starting another
manual image build; concurrent builds can share large NVIDIA base layers.
The Thor Video I/O derivative also changes its unique absolute CUDA-driver
lookup to `libcuda.so.1`, allowing the loader to use JetPack's injected driver
location. A changed or ambiguous vendor binary fails the build for review.
Alert and LVS builds use small generated contexts containing only their literal
Dockerfile `COPY` inputs. This avoids BuildKit traversal of private database
directories. Render and image staging refresh these source snapshots; run
`render` before manually rebuilding either image after source edits.

`stage-cosmos` first compares NGC's complete file listing with the reviewed
BF16 artifact lock, verifies each downloaded file and atomically publishes the
complete cache. It never forwards the NGC key to redirected object storage.
Its four independent weight shards download with bounded parallelism and
separate resumable partial files. An exclusive cache lease prevents concurrent
staging commands from writing the same snapshot.
Both RTVI services share the explicit `.thor/data/models/rtvi-ngc` cache.

`stage-agent-cache` prepares the small `all-MiniLM-L6-v2` text model used by
video analytics, pinned by revision, file sizes and SHA-256 hashes in
`agent-hf.lock.json`. Cached mode mounts this HF cache read-only in the agent
and video analytics MCP service and sets both HF and Transformers offline flags.
An existing container's writable-layer cache alone is insufficient for a fresh
offline container. The desktop preflight verifies this pinned cache as well.

For model staging, store the NGC key privately at
`~/.config/cti-vss/ngc-api-key` with mode 600 and authenticate Docker to `nvcr.io`.
Keep `.thor/` and Docker credentials out of Git. Once all model caches have been
verified, render with `--cached-models`, preserving the same LAN address and data
path, before starting Cosmos. This removes model download credentials from the
runtime environment. Validate real inference again after cache-only container
recreation. The optional non-cached mode reads the key only for the Cosmos
startup subprocess; generated configuration contains a deferred reference.
Cached startup mounts the verified RTVI checkpoints read-only. Cosmos keeps its
initialization lock and vLLM runtime cache under
`/tmp/huggingface/thor-cosmos-runtime` in the writable HF volume, outside the
checkpoint. Runtime initialization must not add files to the artifact whose
complete membership and hashes are verified before every startup.

The Thor Cosmos command uses `cosmos_launcher.py` behind the existing Kafka
startup gate. It verifies the pinned vendor launcher's SHA-256 and inserts an
early return in its MPS startup function, leaving the remaining vendor behavior
intact. Embedding retains its MPS server. This avoids the observed combined
startup allocation stall with two private RTVI MPS servers; it does not change
model, KV, decoder or reserve budgets. An updated vendor image requires reviewing
the launcher digest before startup. Spark uses its existing launcher.

Embedding staging uses the same `Cosmos-Embed1-448p-anomaly-detection` model,
pinned to revision `3b1455ed97c7b1d5419c0c3129b7199ca4cd9382`. The checked-in
lock records all 25 file sizes and SHA-256 hashes. Two bounded concurrent
downloads resume partial files, then verify the complete directory before
publishing it into the shared model cache. The launcher uses that local path
and verifies it again before embedding startup; it does not fetch mutable
Hugging Face HEAD during model startup. Run `verify-embed` to check the cache
without starting inference. Keep AI models stopped during model staging.
The QFormer branch's BERT configuration is separately pinned in the checked-in
auxiliary bundle, including its license. Render mounts this small configuration
read-only into HF's cache; the embedding service always runs without model
download credentials or HF network access. Support provisioning and first
embedding startup prepare only inactive candidate HF/Triton volume roots for
RTVI's runtime user. They do not change source files or active cache mounts.

## Staged startup

```sh
python3 tools/thor/bootstrap.py start --stage support
python3 tools/thor/bootstrap.py start --stage thor-llm
python3 tools/thor/bootstrap.py start --stage rtvi-embed
python3 tools/thor/bootstrap.py start --stage rtvi-vlm
python3 tools/thor/bootstrap.py start --stage app
python3 tools/thor/bootstrap.py verify
```

Keep the installed guard active. The default diagnostic floor is 48 GiB available;
each model startup additionally requires 15 GiB of allocation headroom.
Thor reads its configured floor from `.thor/settings.json`, like Spark. To apply
an explicitly selected reserve and persist it across renders and guard installs:

```sh
python3 tools/thor/bootstrap.py render --reserve-gib 10
python3 tools/thor/bootstrap.py install-guard
```

On October 9 the operator selected 10 GiB for the Anvil T5 demo. This changes the
guard and startup admission floor; model, KV-cache and container budgets remain
unchanged. Historical qualification receipts describe their original 48 GiB floor.

New live sources default to manual recording. Select capture explicitly in the
System workspace; registering a source alone does not start recording or AI
ingestion in this candidate.
The first cold model startup requires at least 90 GiB after support settles;
the helper enforces model order and checks that the live guard covers this
Compose project on the current boot.
Nemotron uses a 2 GiB KV cache, Cosmos a 3 GiB KV cache, and embeddings a batch
size of two. Detection is omitted by default until separate CUDA tracker and
memory validation. The legacy official-edge safety fuse remains intact.

The optional warehouse detector uses the non-SBSA 3.2.1 image, one source,
disabled ReID, VPI CUDA tracking and a separate `models/thor-detector` engine
cache. Never copy a Spark TensorRT engine to Thor. Stage the checksum-verified
ONNX with `stage-detector`, render with `--detector`, then explicitly select
`build-detector-engine` with all three model services and the detector stopped.
The isolated builder requires 90 GiB available and temporarily uses an 8 GiB
container limit: the first native build exceeded the normal 6 GiB limit.
The builder waits for actual `ds-ready: YES`, stops the detector, and removes
its temporary limit even if readiness fails. Then select
`start --stage thor-perception` for normal 6 GiB runtime qualification.
Rendering only changes configuration; it does not start detection. Normal
startup requires the reserve plus 15 GiB of headroom and an existing native
engine. Thor disables simulator-only SEI clock handling for ordinary camera
and file inputs; the Spark template behavior is preserved. A five-minute one-source 720p10FPS single-slice H.264 diagnostic with recording,
detection, embeddings and captions passes at a minimum 52.084 GiB available.
Additional sources, other camera encodings and sustained ingestion remain
unqualified; keep the diagnostic reserve.

Subsequent renders preserve the saved LAN address, gateway, data path and model
mode unless explicitly overridden. Use `--no-detector` or `--no-cached-models`
to change those modes deliberately.

The app is exposed through port 7777 after the app stage. Backend health must
be followed by real upload/playback, indexing, search and visual question tests.
Before additional sources or concurrent summarization, measure available
memory, workload progress, thermal telemetry and an unchanged boot ID.

## GPU resize selection

This JetPack host's packed RGB bilinear GPU resize mixes adjacent color
channels. Known primary-color pixels survive native-size decode but become
olive, teal and purple after resizing. The Thor candidate selects
`RTVI_GPU_RESIZE_INTERPOLATION=nearest` for both RTVI services; exact GPU decode
checks preserve the four original primaries at the model input size. The
existing service default stays bilinear. This trades interpolated edges for
correct colors on the tested host and does not change frame/model budgets.

## Desktop start on this Anvil T5

The installed **Start VSS · Anvil T5** shortcut starts the prepared demo from
local caches, applies `sudo -n /usr/bin/jetson_clocks`, restores the local address
and camera connection, applies the saved memory guard, starts missing service
stages serially, restores the optional NVStreamer server, verifies local readiness
and opens the live view. Already healthy services remain running.
With `auto_primary_ingestion: true` in private `.thor/desktop-config.json`,
startup schedules main-camera recording and resumes its saved analysis profile,
including after a reboot. VSS opens when its services are ready; camera readiness
cannot fail startup or stop healthy services. The background user unit
`vss-thor-primary-ingestion.service` retries camera/API availability every ten
seconds, then exits after observing both recording timelines and semantic indexing
advance. It measures arrivals during this launch rather than comparing camera
NTP timestamps with the host clock. Static retained footage cannot pass the check.
A running recorder/indexer is reused, the agent handles subsequent embedding
reconnections, and other sources are not activated. An operator pause after the
initial resume ends the helper. Camera power and Ethernet are required to produce
new footage; the helper never changes network connections or starts containers.
It requires the configured memory guard before enabling ingestion.
The Anvil T5 demo uses this mode. Other deployments without this setting preserve
their recording and analysis selections.

```sh
python3 tools/thor/desktop.py check
python3 tools/thor/desktop.py start
python3 tools/thor/desktop.py install
```

The Desktop and Applications entry is `vss-thor-start.desktop`; its progress
window reports startup stages and failures. Private logs are in
`.thor/desktop-logs/`, and the last ready receipt is `.thor/desktop-ready.json`.
The camera startup result is `.thor/primary-ingestion.json` (check its time and
boot ID); transitions are logged in `journalctl --user -u vss-thor-primary-ingestion`.
The October 9 failed startup at 14:26 had continuous five-second embedding output,
but incoming timestamps lagged host time by about a minute. The former 45-second
freshness gate incorrectly timed out and stopped the stack. The launcher no longer
uses UI question/freshness flags as a service startup gate.
Missing images or offline model configuration fail before startup; the launcher
uses the existing `--pull never --no-build` startup path. Cold model stages verify
the pinned cache hashes. It never installs packages or downloads models.

This machine's private `.thor/desktop-config.json` records the NetworkManager
connection UUIDs and primary stream ID. The `vss-local` dummy connection provides
the stable local VSS address independently of Wi-Fi or camera carrier. Camera-only
Ethernet supplies the host route to the camera. See the
[camera setup receipt](../../docs/qa/2026-10-09-thor-main-camera.md).

One-time privileged setup installed `/etc/sudoers.d/cti-vss-jetson-clocks`, allowing
only the root-owned `/usr/bin/jetson_clocks` with no arguments and its read-only
`--show` option without a password prompt. No sudo password is stored in the
launcher, desktop entry or repository. Docker is enabled at boot. A new machine
needs its own prepared caches, network UUIDs and clock permission before the
shortcut can start the demo.

An actual Wi-Fi-off cold start on October 9 passed in 9 minutes 51 seconds,
including all service probes, the optional mock server and the main camera
online. Wi-Fi was restored after the test. The browser then decoded the camera's
2560×1920 live frames and selected it in the video workflow. The receipt records
53.75 GiB available and the saved 10 GiB guard; camera analysis and recording
remained paused/off. This is startup and preview validation, not qualification
of AI ingestion at the camera's full resolution.

## UI iteration

```sh
python3 tools/thor/ui.py deps
python3 tools/thor/ui.py dev
python3 tools/thor/ui.py status
```

The default is a source-mounted Next.js Turbopack process using a CPU Node
container, a 2 GiB heap and a 4 GiB container ceiling. Direct port 3001 works
before the gateway is started. `tools/dev/ui.py` routes to this helper when
`.thor/settings.json` is present. Stop only `vss-ui` before replacing its
dependencies. Follow [the UI workflow](../../docs/ui-development.md) for scoped
typechecks, tests and browser checks. No packaged UI fallback is built by this
candidate yet.

To stop the candidate without removing data:

```sh
docker compose --project-name vss-thor -f .thor/compose.json stop
```

Do not use `down -v` or delete model/data caches as routine recovery.
