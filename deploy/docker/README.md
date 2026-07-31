# Docker deployment (`deploy/docker`)

This tree is the Docker Compose packaging for **Video Search & Summarization**. The root **`compose.yml`** pulls three layers together:

| Include | Role |
|---------|------|
| **`services/compose.yml`** | Shared microservices (infra, VIOS, UI, RTVI, NIMs, etc.) |
| **`developer-profiles/compose.yml`** | Developer profiles: **base**, **lvs**, **alerts**, **search** |
| **`industry-profiles/compose.yml`** | Industry blueprints (e.g. **warehouse-operations**) |

Run Compose from **`deploy/docker`** so relative paths resolve correctly.

---

## Developer profiles (recommended path)

Use the **`dev-profile`** helper instead of hand-editing Compose for day-to-day developer stacks (**base**, **lvs**, **search**, **alerts**).

**Script:** `deploy/docker/scripts/dev-profile.sh`

**Examples:**

```bash
cd /path/to/video-search-and-summarization

# Required for bring-up: NGC CLI API key (pull + NIM)
export NGC_CLI_API_KEY="<your-key>"

# Base profile — minimal developer stack (hardware profile required)
./deploy/docker/scripts/dev-profile.sh up \
  --profile base \
  --hardware-profile H100

# LVS profile — video summarization / LVS-oriented bundle (hardware profile required)
./deploy/docker/scripts/dev-profile.sh up \
  --profile lvs \
  --hardware-profile H100

# Alerts profile — set --mode to verification or real-time
./deploy/docker/scripts/dev-profile.sh up \
  --profile alerts \
  --mode verification \
  --hardware-profile H100

# Search profile
./deploy/docker/scripts/dev-profile.sh up \
  --profile search \
  --hardware-profile H100

# Tear down (no profile flags — brings down the Compose project `mdx`)
./deploy/docker/scripts/dev-profile.sh down
```

**Full options** (models, remote LLM/VLM, device IDs, edge hardware, etc.):

```bash
./deploy/docker/scripts/dev-profile.sh --help
```

Each profile may also ship a **`.env`** under **`developer-profiles/<profile>/`** for defaults; the script generates or merges runtime env (e.g. **`generated.env`**) as documented in the script help.

### AGX Thor: fully local base profile

`scripts/thor-local.sh` is the supported operator entry point for an AGX Thor
running both models on the device. Its defaults are:

| Component | Local endpoint / value |
|-----------|------------------------|
| LLM | `datasheet-chat` at `http://127.0.0.1:8000` |
| VLM | `datasheet-vision` at `http://127.0.0.1:8001` |
| VLM images per request | `4` (longer frame sets are split temporally) |
| Cosmos embedding batch | `8` (single-stream Thor default; override with `RTVI_EMBED_BATCH_SIZE`) |
| RTVI-VLM batch / proxy processes | `1 / 1` (matches the single-stream local Qwen endpoint) |
| LVS aggregation | vLLM thinking disabled, `1024` output-token cap |
| Operator UI | `http://127.0.0.1:3001` |
| Public ingress | `http://127.0.0.1:7777` |
| Agent API | `http://127.0.0.1:8100` |

Model families are replaceable, but the local API contract is not: the LLM
must provide OpenAI-compatible discovery and chat completions, and the VLM
must accept four ordered image items per request by default. Qualify the exact
replacement server and model locally with:

```bash
./deploy/docker/scripts/thor-local.sh model-check
```

A native Moondream `caption`/`query` endpoint handles one image and does not
satisfy the full live-video contract without an adapter. Provider and frame
details are in [`thor-local/README.md`](thor-local/README.md).

Store the NGC API key once without placing it in the repository or shell
history:

```bash
install -d -m 700 ~/.config/cti-vss
umask 077
read -rsp 'NGC API key: ' KEY; echo
printf '%s\n' "$KEY" > ~/.config/cti-vss/ngc-api-key
chmod 600 ~/.config/cti-vss/ngc-api-key
unset KEY
```

The key is used only for the connected image and asset staging pass. The
protected runtime contract blanks `NGC_CLI_API_KEY`, `NGC_API_KEY`, and the
RTVI-VLM provider key; the loopback Qwen endpoint uses the non-secret local
OpenAI-compatible credential instead. `RTVI_VLM_BATCH_SIZE=1` and
`RTVI_VLM_NUM_VLM_PROCS=1` are intentional: the Thor profile processes one
stream and the local Qwen server accepts one sequence at a time. This also
avoids the released RTVI launcher's total-memory-based batch-128 default and
keeps its text-only routing index consistent with the single proxy process.
The host-network agent calls the loopback VLM URL directly. RTVI-VLM runs on a
Compose bridge, so `thor-local.sh` writes a separate bridge-to-host upstream
using `HOST_IP`; this is required for summaries and live VLM processing and is
validated independently from the proxy's own health endpoint.

Apply the upstream VIOS networking requirements once. The command checks the
active values first and only invokes `sudo` when a change is required:

```bash
./deploy/docker/scripts/thor-local.sh kernel-settings
```

Thor shares system RAM with the GPU. Install NVIDIA's edge cache cleaner once
so long-running video and inference workloads do not lose usable GPU memory to
the filesystem page cache:

```bash
sudo tee /usr/local/bin/sys-cache-cleaner.sh >/dev/null <<'EOF'
#!/bin/bash
set -e
echo 0 | tee /proc/sys/vm/nr_hugepages
echo "Starting cache cleaner"
while true; do
  sync
  echo 3 | tee /proc/sys/vm/drop_caches >/dev/null
  sleep 3
done
EOF
sudo chmod +x /usr/local/bin/sys-cache-cleaner.sh
sudo -b /usr/local/bin/sys-cache-cleaner.sh
```

The background process does not survive a reboot. Start it before every later
deployment with `sudo -b /usr/local/bin/sys-cache-cleaner.sh`; Thor preflight
fails closed when it is absent.

The first connected bootstrap validates Thor/Jetson Linux, both model IDs,
ports, disk space, kernel settings, images, model checksums, persistent
embedding caches, and the full Compose graph:

```bash
./deploy/docker/scripts/thor-local.sh up
```

`up` is idempotent once that complete offline stage exists: it uses the staged
images and caches and does not log in, download, or build again. To deliberately
refresh connected artifacts after a source/image update, opt in explicitly:

```bash
THOR_LOCAL_FORCE_BOOTSTRAP=true ./deploy/docker/scripts/thor-local.sh up
```

The connected path uses a temporary `DOCKER_CONFIG`, then deletes it. It also
recreates the selected containers from the blank-credential runtime contract
after all NGC-backed downloads finish. Thus neither `~/.docker/config.json` nor
Docker's persistent container configuration receives the NGC token. If an
older launcher already logged in globally, remove that legacy entry after the
active E2E workload is stopped:

```bash
docker logout nvcr.io
```

The Thor overlay deliberately caps Cosmos-Embed at batch 8. The upstream
automatic batch of 64 reserves roughly 20 GiB of activation memory and leaves
too little unified-memory headroom beside the local LLM and VLM. Increase this
only after measuring a multi-stream workload and preserving a safe memory
reserve.

The validated tradeshow operating point is **one continuous live stream plus
uploaded archives**. A bounded two-stream test on the full local stack also
completed, but reached only 3.71 GiB of available unified memory; treat two
live streams as a measured ceiling for short demos, not an unattended default.
Re-run the guarded check after changing a model, input resolution, embedding
batch, or background workload:

```bash
./deploy/docker/scripts/thor-capacity-check.sh
```

It drives the real agent ingest path, DeepStream, VIOS recording, and Cosmos
Embed; aborts below 3 GiB or on service degradation; and removes its unique
test sources. The measured FPS, chunk rate, resource envelope, and limitations
are documented in [`thor-local/README.md`](thor-local/README.md#measured-live-stream-envelope).
The customer-facing walkthrough is in
[`thor-local/DEMO.md`](thor-local/DEMO.md).

After images are staged, later starts are offline-safe: they neither pull nor
build images and they do not pass the NGC credential to Compose. Verify that
contract before disconnecting the device:

```bash
./deploy/docker/scripts/thor-local.sh verify-offline
./deploy/docker/scripts/thor-local.sh restart
./deploy/docker/scripts/thor-local.sh ready
./deploy/docker/scripts/thor-local.sh status
```

`verify-offline` fails closed unless all selected image references exist, the
pinned RT-DETR/Grounding-DINO/SigLIP files match their expected SHA-256 digests,
and the persistent Cosmos-Embed volume contains all ten weight shards plus the
Thor TensorRT engines for the configured embedding batch. It also compares
every selected Docker image with the content-addressed image ID recorded in the
mode-`0600` runtime environment, so a mutable tag cannot silently change the
offline deployment. Its cache inspection runs with `--network none`.

`restart` force-recreates all 27 selected application containers from the
protected blank-credential environment, but preserves named volumes and
`VSS_DATA_DIR`. This is intentional: it also scrubs credentials from container
metadata left by an interrupted or older connected bootstrap.

After the fresh RTVI-VLM endpoint is ready, `restart` replays persisted active
alert rules from Elasticsearch and fails if any rule cannot be restored. The
Thor profile uses 10-second live chunks with two seconds of overlap, four fixed
512-pixel frames, reasoning disabled, and a 64-token response bound. These are
environment-selectable and stay within the local VLM's four-image request
contract; NVIDIA's generic profile defaults remain unchanged when the Thor
variables are absent. The alert bridge's NIM-specific warmup is disabled here
because both the direct vLLM endpoint and the RTVI proxy are independently
checked by the readiness gate.

After a host reboot, start the cache cleaner and run the normal restart. The
launcher starts the configured LLM container, waits for the exact model ID at
its endpoint, then starts and waits for the VLM before touching the VSS stack.
This sequencing matters: starting both vLLM processes at once can make each
process overestimate available unified memory.

```bash
sudo -b /usr/local/bin/sys-cache-cleaner.sh
./deploy/docker/scripts/thor-local.sh restart
```

The defaults are `THOR_LOCAL_LLM_CONTAINER=datasheet-vllm-30` and
`THOR_LOCAL_VLM_CONTAINER=datasheet-qwen3-vl`. If the operator replaces either
model server, set the corresponding container, endpoint, and model-ID override.
Set a container override to `none` when that loopback endpoint is managed by
another supervisor; the launcher then validates it without trying to start it.
No model image is pulled by this path.

Before joining a tradeshow or customer LAN, run the read-only security audit.
The supported ingress is loopback-only, while some NVIDIA host-network
services intentionally bind broadly for single-node communication:

```bash
./deploy/docker/scripts/thor-local.sh security audit
./deploy/docker/scripts/thor-local.sh security firewall-plan enP2p1s0
```

The optional, confirmation-gated `security firewall-apply` rule blocks known
VSS internal ports only on named physical interfaces and preserves loopback,
Docker bridges, SSH, and outbound RTSP. It is volatile across reboot. Prefer an
SSH tunnel to `127.0.0.1:7777` for a remote operator; use an authenticated TLS
reverse proxy if direct LAN access is required. Exact commands and tradeoffs
are documented in
[`thor-local/README.md`](thor-local/README.md#single-device-network-security).

`restart` waits for the readiness gate automatically. The explicit `ready`
command is useful after inspecting or manually restarting a service. It only
passes when every selected container is running (or a one-shot job exited 0),
all Docker health checks are healthy, and the agent, UI, MCP, summarization,
embedding, VLM, and DeepStream endpoints answer successfully.

The protected runtime contract is stored in the gitignored file
`deploy/docker/thor-local/generated.env`, owned by the current user with mode
`0600`. Registry credential fields are forced blank. If launcher defaults are
updated after an earlier bootstrap, normalize that existing file without a
registry login:

```bash
./deploy/docker/scripts/thor-local.sh refresh-runtime
./deploy/docker/scripts/thor-local.sh contract
```

Stop services without deleting persisted data, or remove containers and
networks while preserving volumes:

```bash
./deploy/docker/scripts/thor-local.sh stop
./deploy/docker/scripts/thor-local.sh down
```

To place persistent data outside the checkout, set the same absolute path for
every lifecycle command. Model staging, checksum verification, and Compose
mounts all follow this value:

```bash
export VSS_DATA_DIR=/srv/cti-vss
./deploy/docker/scripts/thor-local.sh up
```

### Direct Compose data directories

The helper scripts provision missing data directories automatically with a
shared service group and never recursively change existing persisted data. The
default **`VSS_DATA_GID=1000`** matches the NVIDIA, Elasticsearch, Kafka, and
Redis images; override it only when those container identities are remapped.
If you run
`docker compose -f compose.yml ...` directly, set **`VSS_DATA_DIR`** and create writable
host directories for the bind-mounted infrastructure volumes before starting the stack:

```bash
export VSS_DATA_DIR=/path/to/vss-apps-data
export VSS_DATA_GID=1000

install -d -m 2770 -g "$VSS_DATA_GID" \
  "$VSS_DATA_DIR/data_log/elastic/data" \
  "$VSS_DATA_DIR/data_log/elastic/logs" \
  "$VSS_DATA_DIR/data_log/kafka" \
  "$VSS_DATA_DIR/data_log/redis/data" \
  "$VSS_DATA_DIR/data_log/redis/log"
```

The root compose maps Elasticsearch data/log volumes to
`$VSS_DATA_DIR/data_log/elastic/{data,logs}`, Kafka data to
`$VSS_DATA_DIR/data_log/kafka`, and Redis data/logs to
`$VSS_DATA_DIR/data_log/redis`. Missing or non-writable host directories can cause
startup failures such as Kafka being unable to write `/tmp/kafka-data/cluster_id` or
Elasticsearch being unable to open `gc.log`.
### LVS Compose notes

Docker Compose does not use Kubernetes secrets or the NIM Operator. For the LVS profile, local model bring-up uses the **`NGC_CLI_API_KEY`** environment variable directly for image pulls and NIM/RT-VLM model access.

Default LVS model wiring:

| Component | Local Compose behavior | Default model name |
|-----------|------------------------|--------------------|
| LLM | Starts the **`nvidia-nemotron-nano-9b-v2`** NIM container on **`LLM_PORT=30081`** when `LLM_MODE` is `local` or `local_shared`. | `nvidia/nvidia-nemotron-nano-9b-v2` |
| VLM / RT-VLM | Starts **`rtvi-vlm`** on **`RTVI_VLM_PORT=8018`**. The LVS profile sets **`VLM_NAME_SLUG=none`**, so Compose does not start a separate Cosmos VLM NIM by default; RT-VLM loads the integrated checkpoint. | `nim_nvidia_cosmos-reason2-8b_hf-1208` |

For external endpoints, including operator-hosted vLLM services running on the same
machine, use the helper flags instead of editing Compose files directly:

```bash
export LLM_ENDPOINT_URL='<REMOTE LLM SERVICE ROOT, no trailing /v1>'
export VLM_ENDPOINT_URL='<REMOTE VLM SERVICE ROOT, no trailing /v1>'

./deploy/docker/scripts/dev-profile.sh up \
  --profile lvs \
  --hardware-profile H100 \
  --use-remote-llm \
  --use-remote-vlm \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 \
  --vlm nim_nvidia_cosmos-reason2-8b_hf-1208
```

For an OpenAI-compatible vLLM endpoint, pass `--llm-model-type vllm` and
`--vlm-model-type vllm`. The dedicated vLLM LLM profile can carry local
chat-template controls without coupling them to a generic OpenAI or NIM
provider. This path is supported on AGX Thor and IGX Thor and prevents the
helper from starting or selecting a bundled model for that endpoint.

The helper probes **`${LLM_ENDPOINT_URL}/v1/models`** and **`${VLM_ENDPOINT_URL}/v1/models`**, and the agent config appends **`/v1`** to **`LLM_BASE_URL`** / **`VLM_BASE_URL`**. Do not include **`/v1`** in the endpoint environment variables.

Post-deploy checks for the default local LVS ports:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
curl -f http://127.0.0.1:38111/v1/ready
curl -f http://127.0.0.1:8018/v1/health/ready
curl -f http://127.0.0.1:30081/v1/health/ready
curl -f http://127.0.0.1:38111/models
curl -f http://127.0.0.1:30081/v1/models
```

If a local NIM container keeps restarting and logs include **`No available memory for the cache blocks`**, reduce the NIM max model length and/or sequence count for the active hardware profile. One non-destructive way is to pass an override env file through **`--llm-env-file`**:

```env
# /tmp/lvs-nim-low-memory.env
NIM_MAX_MODEL_LEN=65536
NIM_MAX_NUM_SEQS=2
```

```bash
./deploy/docker/scripts/dev-profile.sh up \
  --profile lvs \
  --hardware-profile RTXPRO6000BW \
  --llm-env-file /tmp/lvs-nim-low-memory.env
```

Those numeric values are only an example shape for reducing cache pressure; validate the final values on your GPU and workload.

---

## Warehouse industry profile

The **warehouse** blueprint is driven by **`industry-profiles/warehouse-operations/`**

1. **Download warehouse app data**

```bash
ngc \
   registry \
   resource \
   download-version \
   nvidia/vss-warehouse/vss-warehouse-app-data:3.2.0

# OR Manually download the tar file from NGC
# URL https://catalog.ngc.nvidia.com/orgs/nvidia/teams/vss-warehouse/resources/vss-warehouse-app-data?version=3.2.0

# Extract the package

cd vss-warehouse-app-data_v3.2.0
tar -xvf vss-warehouse-app-data.tar.gz

# Set permissions

sudo chmod -R 777 /path/to/vss-warehouse-app-data

# This is the path to the data directory. It is set in the industry-profiles/warehouse-operations/.env file for VSS_DATA_DIR.
#VSS_DATA_DIR="/path/to/vss-warehouse-app-data"
```

2. **Edit environment**  
   Update **`deploy/docker/industry-profiles/warehouse-operations/.env`** for your deployment:

   - **`MODE`**: `2d`, `3d`, or `mv3dt`
   - **`BP_PROFILE`**: `bp_wh`, `bp_wh_kafka`, `bp_wh_redis`, `bp_wh_auto_calib` (see comments in that file for 2d, 3d, and mv3dt combinations)
   - **`MINIMAL_PROFILE`**, GPU hosts, API keys, and any other variables described in the file header

3. **Start the stack**

```bash
cd /path/to/video-search-and-summarization/deploy/docker
docker compose -f compose.yml --env-file industry-profiles/warehouse-operations/.env up --detach \
--pull always \
--force-recreate \
--build
```

4. **Stop the stack**

```bash
# Stop the running deployment
docker compose -f compose.yml --env-file industry-profiles/warehouse-operations/.env down

# Alternatively to remove all the containers, images and volume
docker compose --env-file industry-profiles/warehouse-operations/.env down -v --rmi all

# Tear down all dangling volumes
docker volume ls -q -f "dangling=true" | xargs docker volume rm
```

5. **Data / backup cleanup**  
   To reset **`data_log`** volumes, calibration/VST data, and blueprint-configurator backups in a way that matches how you deployed, use **`deploy/docker/scripts/cleanup_all_datalog.sh`**.  
   Pass **`-e`** / **`--env-file`** with the **same env file** you used for **`docker compose --env-file …`**.

```bash
bash scripts/cleanup_all_datalog.sh -e industry-profiles/warehouse-operations/.env
```

Compose profiles for warehouse slices are defined under **`warehouse-operations/compose.yml`** and related **`warehouse-2d-app`** / **`warehouse-3d-app`** includes; the **`.env`** file selects **MODE** / **BP_PROFILE** behavior as documented there.

---

## Requirements

- **Docker** and **Docker Compose** (Compose v2: `docker compose`)
- **bash** (for **`dev-profile.sh`**)
- **NVIDIA GPU driver** on the host, at a version supported by your hardware and by the GPU containers you run (see NVIDIA release notes for CUDA / NIM images). Check with **`nvidia-smi`** before starting stacks that use GPUs.
- **NVIDIA Container Toolkit** (nvidia-docker) so containers can access the GPU; required alongside the driver for GPU-backed Compose services.
- Valid **NGC** credentials where images or NIMs require **`NGC_CLI_API_KEY`**


---
