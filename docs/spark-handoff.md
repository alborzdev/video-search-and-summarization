# Continue the demo on DGX Spark

## Status and purpose

Prepared September 29, 2026. This checkout contains the demo UI redesign, backend
fixes, research, presenter runbook, tests, and an independent **Spark candidate**
bootstrap. It is ready to hand to Codex on the Spark for deployment and continued
work. It is **not yet a hardware-qualified Spark installation**. Compose rendering
and source tests on Thor cannot prove first model download, GB10 engine compilation,
video decoding, or latency under Isaac Sim load.

The user's target is **Isaac Sim and VSS running together on the same Spark**,
with a live RTSP stream from Sim. Do not stop or reconfigure Sim without discussing
it with the user. Start with one stream. Keep the 48 GiB diagnostic reserve until
measured joint operation justifies a different budget. The Spark guard stops only
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

`stage` verifies the bundled Logstash plugin archive, downloads the checksum-locked
VIOS MCP wheelhouse, pulls released services, and builds source derivatives,
including the current UI. It refuses to build while this candidate stack runs.
Keep Sim idle during large image builds if unified-memory pressure is high; the
helper cannot qualify someone else's GPU workload. It does not prune caches.

`up` provisions missing data roots, requires the guard, starts dependencies and
models serially, and waits for readiness before continuing. Each model admission
requires 63 GiB available (48 GiB reserve plus 15 GiB startup headroom). A failed
admission is a real capacity constraint to investigate with Sim, not permission
to automatically lower the reserve. The guard remains a user systemd service;
ensure the operator's user session remains active, or configure user lingering
when unattended operation is desired. Services deliberately do not auto-restart.

Stop only this candidate graph with:

```sh
python3 tools/spark/bootstrap.py stop
```

Use `docker compose -p vss-spark -f .spark/compose.json logs --tail 100 SERVICE`
for diagnosis. Rendered config contains a generated database password; do not
paste the whole file or `docker inspect` environment output into chat/logs.

## What is portable and what changes on Spark

| Component | Spark candidate |
|---|---|
| UI / Agent / VIOS MCP / evidence support | Current source; independent new data roots |
| Vision model | Cosmos3 reasoner inside source-built RT-VLM 3.2.1 SBSA |
| Language model | Supported Spark Nemotron Nano 9B NIM variant; different from Thor Edge 4B |
| Search embeddings | Cosmos Embed1 448p; downloads weights and compiles a fresh GB10 TensorRT cache |
| Summaries / graph Q&A | Source-patched LVS SBSA, local model endpoints, 768-dimension embeddings |
| Video | Released ARM64 VIOS; Spark uses its codec installer, not Thor's Tegra codec bundle |
| Safety / startup | Independent 48 GiB guard, serial admission, saved sources and always-on rules paused |
| Detectors | Omitted initially, matching the current Thor core runtime; enable/qualify separately |
| Telemetry | Shared CPU/service monitoring; Thor tegrastats omitted; Spark GPU monitoring needs target verification |

No Thor TensorRT engines, bare local image IDs, fixed Thor paths/IPs, external
Docker volumes or existing containers are needed by the Spark graph. Existing
Thor scripts and historical artifacts remain for recovery, not Spark startup.
Do not run `artifacts/thor-memory-2026-09-09/manage.py` or `tools/dev/ui.py` on Spark:
those intentionally operate the Thor candidate. A Spark hot-reload workflow is
still to be qualified; the initial bootstrap builds the UI from source.

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
