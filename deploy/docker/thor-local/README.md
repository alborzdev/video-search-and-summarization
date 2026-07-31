# Thor-local deployment

The current upstream feature-by-feature acceptance state is tracked in the
[machine-checked parity ledger](parity/README.md). Source presence, Thor wiring,
and current runtime proof are recorded separately so an imported upstream
feature cannot be mistaken for a locally qualified one.

This overlay runs NVIDIA Video Search and Summarization on Jetson AGX Thor while keeping inference and application data on the device. The initial image bootstrap requires network access and an NGC key; subsequent starts are pull-free and build-free. Bootstrap also creates a Thor-local derivative of the VIOS stream-processing image. It restores codec libraries represented in the released ARM64 package database but omitted from its filesystem, so VIOS never runs `apt` during an offline restart.

The resource-isolated minimal Redis warehouse-2D milestone is documented in
[`WAREHOUSE_2D.md`](WAREHOUSE_2D.md). Its helper prepares and statically
validates a private mutable Configurator snapshot; it intentionally has no
container lifecycle or artifact-download command yet.

## Local model contract

The default deployment expects OpenAI-compatible model servers on the Thor host:

| Role | Endpoint | Model | Notes |
| --- | --- | --- | --- |
| LLM | `http://DOCKER_BRIDGE:8000` | `datasheet-chat` | Qwen text model |
| VLM | `http://DOCKER_BRIDGE:8003` | `datasheet-vision` | Qwen vision model, up to four images per request |

`DOCKER_BRIDGE` is detected from `docker0` (normally `172.17.0.1`) and is
private to this host. This lets both host-network VSS services and bridged RTVI
reach the same local models without publishing either endpoint on a physical
LAN interface. When Docker has no default bridge, the launcher falls back to
loopback and rewrites only RTVI's VLM route to `HOST_IP`.

Both defaults use the dedicated `vllm` provider profile. Set
`THOR_LOCAL_LLM_MODEL_TYPE` or `THOR_LOCAL_VLM_MODEL_TYPE` to `nim`, `openai`,
or `vllm` when changing providers; provider-specific request options remain
isolated to their matching profile.

The portable boundary is the API, not a model family. A replacement must
advertise the configured ID from `GET /v1/models` and implement OpenAI-style
`POST /v1/chat/completions`. The VLM must accept
`VLM_MAX_FRAMES_PER_REQUEST` ordered `image_url` content items in one chat
message (four by default). Prove the exact server/model combination without
using footage or a cloud service:

```bash
./scripts/thor-local.sh model-check
```

`preflight` runs the same text and four-image capability probe. The probe uses
tiny generated pixels, a bounded response, and the protected local API key; it
does not print prompts, model output, or credentials.

The exact qualified Qwen snapshots and ARM64 vLLM image can be provisioned
from already-staged local assets without a pull or model download:

```bash
deploy/docker/thor-local/provision-local-models.sh provision
deploy/docker/thor-local/provision-local-models.sh status
```

Provisioning is additive and idempotent. It never removes or recreates an
existing container; a mismatched existing container stops the operation with
an explicit error. Containers are created stopped and are started sequentially
by `thor-local.sh restart` after the unified-memory cache cleaner is active.

Moondream's native `caption` and `query` skills are useful for one still image,
but they are not this multi-image OpenAI chat contract. A stock Moondream
server therefore is not a drop-in VLM for live chunks, verification, or video
reports. It can be used only behind an adapter that implements the contract
and defines ordered multi-image behavior; otherwise keep Qwen-VL (or another
qualified multi-image VLM) for the full product.

The VSS agent uses host networking and reaches the operator models through
loopback or the private Docker bridge. RTVI-VLM uses a Compose bridge, so the
launcher preserves a private bridge endpoint or rewrites only a loopback
authority to `HOST_IP` while keeping the same VLM port and path. Use the
physical-interface firewall below whenever a model must listen on `HOST_IP`.
Override the endpoint or model variables documented by
`scripts/thor-local.sh help` when using another OpenAI-compatible provider.

Sampled video frames are divided into ordered groups of `VLM_MAX_FRAMES_PER_REQUEST` before VLM inference. The segment responses are labeled and passed back to the agent for synthesis, so a provider with a small multimodal limit does not silently lose later frames.

The single-stream profile pins RTVI-VLM to batch size `1` and one proxy
process. This matches the local Qwen server's one-sequence admission policy and
prevents the released launcher from selecting batch `128` from Thor's total
unified-memory size. The NGC key remains available to the connected staging
step, but is blank in the protected runtime and RTVI-VLM container environment;
the loopback OpenAI-compatible endpoint uses the non-secret `local` key.

The Thor LVS derivative adds provider-aware LLM request options to NVIDIA's
released summarization image. Local vLLM aggregation defaults to
`LVS_LLM_ENABLE_THINKING=false` and `LVS_LLM_MAX_TOKENS=1024`; NIM and generic
OpenAI providers do not receive the vLLM chat-template extension.

## First connected bootstrap

From `deploy/docker`:

```bash
sudo -b /usr/local/bin/sys-cache-cleaner.sh
./thor-local/provision-local-models.sh provision
install -d -m 700 ~/.config/cti-vss
read -rsp 'NGC API key: ' NGC_CLI_API_KEY; echo
printf '%s\n' "$NGC_CLI_API_KEY" > ~/.config/cti-vss/ngc-api-key
chmod 600 ~/.config/cti-vss/ngc-api-key
unset NGC_CLI_API_KEY
./scripts/thor-local.sh up
```

The model provisioner is offline-only and requires the pinned vLLM image and
Qwen snapshots to have been staged on the host already. It validates those
assets before creating anything. `up` starts the model containers sequentially
and runs the full preflight before entering connected VSS image/model staging.

The `read -s` prompt does not echo the key, and the protected key file lives outside the repository. Do not paste the key into chat or put it in a repository file. The generated profile environment is ignored by Git but should still be treated as a secret-bearing local artifact.

The base profile exposes:

- UI: `http://127.0.0.1:3001`
- public ingress: `http://127.0.0.1:7777`
- agent API: `http://127.0.0.1:8100`

Video Management supports file upload and RTSP registration. The base agent can ask questions about uploaded videos and stored RTSP time ranges, and can generate summaries and reports with the local models.

## Tradeshow operator check

For the customer-facing demonstration sequence, use the concise
[`DEMO.md`](DEMO.md) runbook. The checks and recovery details below are the
operator reference behind that flow.

Run the doctor after boot, after `restart`, and before a demonstration:

```bash
./scripts/thor-local.sh doctor
```

The doctor is read-only and offline-safe. It makes no cloud or registry calls
and never prints credential values. Its concise `PASS`/`WARN`/`FAIL` report
covers the protected runtime contract, kernel and cache-cleaner prerequisites,
Thor GPU temperature/utilization, unified-memory and disk pressure, every
selected Compose service (including successful one-shot containers), the local
LLM and VLM model IDs, UI and ingress, VSS/search, Cosmos-Embed, VST/VIOS,
Elasticsearch, alert verification/realtime alerts, and video summarization.

Warnings such as modest unified-memory headroom do not make the command fail.
The command exits nonzero only when it finds a real blocker, such as an absent
model, insecure runtime file, incomplete kernel settings, unhealthy service, or
failed local endpoint. A deliberately stopped stack is reported cleanly as a
blocker; model and host checks still run, while the unavailable application
route checks are skipped.

The normal offline recovery sequence is:

```bash
./scripts/thor-local.sh restart
./scripts/thor-local.sh ready
./scripts/thor-local.sh doctor
```

For a failing service, inspect only that container without changing state:

```bash
./scripts/thor-local.sh status
docker logs --tail 150 <container-name>
```

The launcher also creates `${VSS_DATA_DIR}/agent-reports` as an invoking-user
owned mode-`0700` directory before startup. This is the private durable report
store; the doctor fails if its ownership or permissions become unsafe.

## Measured live-stream envelope

For the current local Qwen + Cosmos configuration, use **one continuous live
camera plus uploaded archives** as the conservative tradeshow operating point.
Two live inputs work for a short, supervised demonstration, but the measured
memory reserve is too narrow to call that an unattended production limit.

The July 15, 2026 qualification used the complete 27-service Thor profile with
both local model servers loaded and two looped H.264 1280×720/60 fps RTSP
inputs. It registered each source through the public agent transaction so the
test covered VIOS proxy/recording, DeepStream detection and tracking, Cosmos
Embed, Kafka/Elasticsearch, and cleanup—not just video decode.

| Phase | Observed result |
| --- | --- |
| Idle full stack | 5.77 GiB minimum available unified memory |
| One live input, 50 s | 4.10 GiB minimum; all monitored services healthy |
| Two live inputs, 65 s | 3.71 GiB minimum; all monitored services healthy |
| DeepStream at two inputs | 26.25 and 26.10 average fps (about 52.35 aggregate); instantaneous samples 13.6–30.8 fps |
| Cosmos Embed at two inputs | one five-second chunk per stream about every five seconds; 29 + 15 documents indexed over the full staggered run |
| Agent ingest control plane | 2.013 s and 2.009 s |
| Two-input GPU telemetry | 55 °C average; separate 11-s sample averaged 34.9 W (`VDD_GPU`), 22.5–60.0 W range |

The guard never crossed 3 GiB, but the two-input low point left only 0.71 GiB
above it. Do not raise the Cosmos batch or add a third live stream on this
model mix without a new qualification. Avoid scheduling report generation,
large interactive VLM requests, or unrelated GPU applications during a
two-camera demo. The two-input log also emitted intermittent optical-flow
buffer-allocation warnings even though health stayed green and throughput
recovered; at about 26 fps per 60 fps source, this is a useful demo ceiling but
not full-frame-rate analytics. A single live camera leaves materially safer
headroom.

Run the repeatable check only when the DeepStream source list is idle:

```bash
cd /home/nvidia/cti-saa-thor/video-search-and-summarization
./deploy/docker/scripts/thor-capacity-check.sh
```

To retain raw evidence, provide a path that does not exist yet:

```bash
THOR_CAPACITY_OUTPUT_DIR=/tmp/thor-capacity-$(date -u +%Y%m%dT%H%M%SZ) \
  ./deploy/docker/scripts/thor-capacity-check.sh
```

The command never rebuilds or restarts the shared stack. It stops immediately
if available memory falls below 3 GiB or a core service becomes unhealthy,
then deletes its uniquely named sources from RTVI, VIOS, and the agent and
stops its local publishers. It also deletes only its exact temporary sensor
names from the Cosmos index. Success includes a final DeepStream stream count
of zero, absent VIOS test streams, and zero matching embedding documents.

This is an application-envelope measurement, not a universal camera-count
claim. Both inputs were copies of one local H.264 sample, so the result does
not cover adverse RTSP networks, higher resolutions, different codecs,
simultaneous Q&A/report/VLM traffic, or another model pair. Re-run it after any
such change. The cleanup proof uses the authoritative per-sensor stream lookup
and DeepStream stream-info endpoint instead of relying only on the cached
sensor-list view.

## Single-device network security

The supported operator surface is `http://127.0.0.1:7777`; it fronts the UI
and API through one loopback-only HAProxy listener. NVIDIA's single-node graph
also contains host-network services whose released binaries bind to all host
addresses. Do not treat those internal ports as a supported LAN API.

Audit the resolved runtime, container credential metadata, ingress bind, and
known internal listeners without changing the host:

```bash
./scripts/thor-local.sh security audit
```

For a tradeshow, block internal VSS ports on every physical interface that can
receive untrusted traffic. Review the narrow nftables table first, then apply
it explicitly (replace the examples with interfaces shown by `ip -br link`):

```bash
./scripts/thor-local.sh security firewall-plan enP2p1s0 wlP1p1s0
THOR_LOCAL_CONFIRM_FIREWALL=yes \
  ./scripts/thor-local.sh security firewall-apply enP2p1s0 wlP1p1s0
./scripts/thor-local.sh security firewall-status
```

The rule has an `accept` default and drops only the enumerated VSS TCP ports on
the named ingress interfaces. It does not modify SSH, outbound RTSP, loopback,
or Docker bridge traffic. Consequently, local UI/API access and the bridged
RTVI-to-VLM path continue to work. When the stack is running, `firewall-apply`
checks both sides of that path and automatically removes its table if readiness
regresses. The rule is intentionally volatile and must be reapplied after a
reboot; remove only this product-owned table with `security firewall-remove`.

For remote operation, use an SSH tunnel instead of opening the internal ports:

```bash
ssh -L 7777:127.0.0.1:7777 nvidia@THOR_ADDRESS
```

Then browse `http://127.0.0.1:7777` on the operator laptop. If a customer
deployment requires direct LAN users, place an authenticated TLS reverse proxy
in front of the loopback ingress and define a trusted-client policy; disabling
the firewall or exposing Kafka, Elasticsearch, model, VST, or agent ports is
not an equivalent production design.

## Tradeshow domain packs

The Thor fork includes four offline, versioned demo configurations: `general`,
`industrial-safety`, `retail`, and `site-security`. Inspect them before a demo:

```bash
./scripts/thor-local.sh domain list
./scripts/thor-local.sh domain show industrial-safety
```

With the full stack ready, apply one locally:

```bash
./scripts/thor-local.sh domain apply industrial-safety
./scripts/thor-local.sh domain current
```

A pack changes the runtime application title/subtitle, prints a curated set of
questions and searches for the operator, and synchronizes a bounded one-to-four
frame candidate-verification prompt through the loopback Alert Bridge API. A
branding change recreates only `vss-ui` with `--pull never --no-build`; model,
video, search, and analytics containers continue running.

The verification seed customizes how an existing analytics candidate is
checked. It does not create a new detector or claim that the VLM continuously
watches every frame. The supplied Thor perception path currently produces the
person-presence candidate used by these packs; the pack prompt decides whether
that candidate represents the domain event.

Pack ownership is conservative. The launcher tracks the exact rule payload it
applied in a current-user-owned mode-`0600` state file. It updates only that
exact payload. If an operator edits it, or an unrelated rule already uses the
same `alert_type`, the launcher leaves the rule untouched and reports a
warning. It never bulk-deletes alert rules. Pack definitions contain no
credentials and applying one refuses non-loopback Alert Bridge URLs.

Start and end a general-purpose demo with:

```bash
./scripts/thor-local.sh domain apply general
```

See [`domain-packs/README.md`](domain-packs/README.md) for the validated schema
and the safe customization boundary.

## Offline restart

After the connected bootstrap has staged every image, use:

```bash
./scripts/thor-local.sh stop
./scripts/thor-local.sh restart
```

`restart` verifies that every resolved Compose image exists locally, then starts with `--pull never --no-build`. Missing images fail closed with an explicit list instead of causing an unexpected network request.

Use `stop` for a temporary shutdown. Use `down` to recreate containers and networks while preserving volumes and application data. Neither command deletes model files, Docker images, or volumes.

## Storage

The wrapper limits VST video storage to 20 GB by default. Override `VST_VIDEO_STORAGE_SIZE_MB` deliberately if the device has a larger data disk. Keep enough free space for NVIDIA service images before bootstrapping; the preflight warns below 150 GiB because the search and alerts stacks require substantially more than the base profile.

## Source overlay

The Thor Compose overlay mounts the local agent source read-only and places it first on `PYTHONPATH`. This lets the fork run its Thor-specific fixes with the versioned NVIDIA agent runtime without rebuilding the closed runtime image. The UI is built locally from this repository with the configured npm mirror and has no runtime font or stylesheet CDN dependency.
