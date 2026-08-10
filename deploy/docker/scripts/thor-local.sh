#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
deployment_dir="${repo_root}/deploy/docker"
default_data_directory="${deployment_dir}/data-dir"
profile="${THOR_LOCAL_PROFILE:-thor-full}"
profile_env="${deployment_dir}/developer-profiles/dev-profile-${profile}/.env"
profile_generated_env="${deployment_dir}/developer-profiles/dev-profile-${profile}/generated.env"
# Production Thor commands intentionally do not consume the profile-generated
# file directly: upstream tests rewrite that file with many profile variants.
# This protected, gitignored copy can be generated from the versioned contract
# offline; a connected bootstrap additionally proves images/assets are staged.
generated_env="${THOR_LOCAL_GENERATED_ENV_FILE:-${deployment_dir}/thor-local/generated.env}"
ngc_key_file="${NGC_CLI_API_KEY_FILE:-${HOME}/.config/cti-vss/ngc-api-key}"
domain_pack_dir="${deployment_dir}/thor-local/domain-packs"
domain_pack_tool="${domain_pack_dir}/domain_pack.py"
qualification_tool="${deployment_dir}/thor-local/qualification/qualify.py"
runtime_qualification_tool="${deployment_dir}/thor-local/qualification/runtime.py"
stateful_acceptance_tool="${deployment_dir}/thor-local/qualification/acceptance.py"
official_edge_dir="${deployment_dir}/thor-local/official-edge"
official_edge_llm_endpoint="http://127.0.0.1:30081"
official_edge_vlm_endpoint="http://127.0.0.1:8018"
official_edge_llm_model="nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8"
official_edge_vlm_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final"
local_model_provisioner="${deployment_dir}/thor-local/provision-local-models.sh"
model_artifact_verifier="${deployment_dir}/thor-local/models/verify_artifacts.py"
model_artifact_lock="${deployment_dir}/thor-local/models/artifacts.lock.json"
vios_mcp_wheelhouse_stager="${deployment_dir}/thor-local/vios-mcp/stage-wheelhouse.sh"
domain_pack_state="${THOR_LOCAL_DOMAIN_STATE_FILE:-${deployment_dir}/thor-local/.domain-pack-state.json}"
domain_pack_current_file="${THOR_LOCAL_DOMAIN_CURRENT_FILE:-${deployment_dir}/thor-local/.domain-pack-current}"

export VSS_REPO_ROOT="${repo_root}"
export VSS_DATA_DIR="${VSS_DATA_DIR:-${default_data_directory}}"
data_directory="${VSS_DATA_DIR}"
export HOST_IP="${HOST_IP:-$(ip route get 1.1.1.1 | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')}"
export EXTERNAL_IP="${EXTERNAL_IP:-${HOST_IP}}"
export COMPOSE_FILE="${deployment_dir}/compose.yml:${deployment_dir}/thor-local/compose.yml"
docker_bridge_ip="$(ip -4 -o address show docker0 2>/dev/null | awk 'NR == 1 {split($4, address, "/"); print address[1]}')"
export THOR_LOCAL_MODEL_BIND_HOST="${THOR_LOCAL_MODEL_BIND_HOST:-${docker_bridge_ip:-127.0.0.1}}"
# Bind operator-managed model servers to Docker's private host bridge when it
# exists. Host-network VSS services and bridged RTVI can both reach this
# address, while the models remain absent from physical/LAN interfaces.
export LLM_ENDPOINT_URL="${LLM_ENDPOINT_URL:-http://${THOR_LOCAL_MODEL_BIND_HOST}:8000}"
export VLM_ENDPOINT_URL="${VLM_ENDPOINT_URL:-http://${THOR_LOCAL_MODEL_BIND_HOST}:8003}"
# Host-network services can use the operator endpoint directly. RTVI-VLM runs
# on a Compose bridge, so rewrite a loopback-only endpoint to Thor's private
# host address; a Docker-bridge endpoint already works from both sides.
export VLM_CONTAINER_ENDPOINT_URL="${VLM_CONTAINER_ENDPOINT_URL:-${VLM_ENDPOINT_URL}}"
VLM_CONTAINER_ENDPOINT_URL="$(python3 - "${VLM_CONTAINER_ENDPOINT_URL}" "${HOST_IP}" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit, urlunsplit

endpoint, host_ip = sys.argv[1:]
parsed = urlsplit(endpoint)
try:
    is_loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
except ValueError:
    is_loopback = (parsed.hostname or "").lower() == "localhost"
if is_loopback:
    port = f":{parsed.port}" if parsed.port is not None else ""
    parsed = parsed._replace(netloc=f"{host_ip}{port}")
print(urlunsplit(parsed))
PY
)"
export VLM_CONTAINER_ENDPOINT_URL
export THOR_LOCAL_LLM_MODEL="${THOR_LOCAL_LLM_MODEL:-datasheet-chat}"
export THOR_LOCAL_VLM_MODEL="${THOR_LOCAL_VLM_MODEL:-datasheet-vision}"
export THOR_LOCAL_LLM_MODEL_TYPE="${THOR_LOCAL_LLM_MODEL_TYPE:-vllm}"
export THOR_LOCAL_VLM_MODEL_TYPE="${THOR_LOCAL_VLM_MODEL_TYPE:-vllm}"
export THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE="${THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE:-openai}"
export THOR_LOCAL_LLM_CONTAINER="${THOR_LOCAL_LLM_CONTAINER:-datasheet-vllm-30}"
export THOR_LOCAL_VLM_CONTAINER="${THOR_LOCAL_VLM_CONTAINER:-cti-vss-qwen3-vl}"
export THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS="${THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS:-900}"
export THOR_LOCAL_MODEL_CONTRACT_TIMEOUT_SECONDS="${THOR_LOCAL_MODEL_CONTRACT_TIMEOUT_SECONDS:-120}"
export THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START="${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START:-50}"
export THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START="${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START:-20}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-local}"
export VSS_AGENT_PORT="${VSS_AGENT_PORT:-8100}"
export VSS_UI_PORT="${VSS_UI_PORT:-3001}"
export HAPROXY_PORT="${HAPROXY_PORT:-7777}"
export VSS_PUBLIC_PORT="${VSS_PUBLIC_PORT:-${HAPROXY_PORT}}"
export VST_PORT="${VST_PORT:-30888}"
export VST_INGRESS_HTTP_PORT="${VST_INGRESS_HTTP_PORT:-${VST_PORT}}"
export VST_MCP_PORT="${VST_MCP_PORT:-8001}"
export VIOS_MCP_ENDPOINT="${VIOS_MCP_ENDPOINT:-http://127.0.0.1:${VST_MCP_PORT}/mcp}"
export SENSOR_HTTP_PORT="${SENSOR_HTTP_PORT:-30000}"
export STREAM_PROCESSOR_HTTP_PORT="${STREAM_PROCESSOR_HTTP_PORT:-30001}"
export SDR_STREAMPROCESSING_PORT="${SDR_STREAMPROCESSING_PORT:-4003}"
export RTVI_EMBED_PORT="${RTVI_EMBED_PORT:-8017}"
export RTVI_VLM_PORT="${RTVI_VLM_PORT:-8018}"
export RTVI_CV_PORT="${RTVI_CV_PORT:-9000}"
export VIDEO_ANALYTICS_API_PORT="${VIDEO_ANALYTICS_API_PORT:-8081}"
export MDX_PORT="${MDX_PORT:-${VIDEO_ANALYTICS_API_PORT}}"
export SMARTCITY_MAP_PORT="${SMARTCITY_MAP_PORT:-3002}"
export ALERT_BRIDGE_PORT="${ALERT_BRIDGE_PORT:-9080}"
export KAFKA_PORT="${KAFKA_PORT:-9092}"
export VSS_ES_PORT="${VSS_ES_PORT:-9200}"
export VSS_VA_MCP_PORT="${VSS_VA_MCP_PORT:-9901}"
export BACKEND_PORT="${BACKEND_PORT:-38111}"
export LVS_MCP_PORT="${LVS_MCP_PORT:-38112}"
export LVS_ENABLE_MCP="${LVS_ENABLE_MCP:-true}"
export VIA_DEV_API="${VIA_DEV_API:-true}"
export KIBANA_PORT="${KIBANA_PORT:-5601}"
export PHOENIX_HOST="${PHOENIX_HOST:-127.0.0.1}"
export PHOENIX_PORT="${PHOENIX_PORT:-6006}"
export LOGSTASH_API_PORT="${LOGSTASH_API_PORT:-9600}"
export THOR_FULL_ENABLE_KIBANA="${THOR_FULL_ENABLE_KIBANA:-true}"
export MONITORING_BIND_ADDRESS="${MONITORING_BIND_ADDRESS:-127.0.0.1}"
export PROMETHEUS_CONFIG_FILE="${PROMETHEUS_CONFIG_FILE:-${deployment_dir}/thor-local/observability/prometheus.yml}"
export PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
export GRAFANA_PORT="${GRAFANA_PORT:-35000}"
export NODE_EXPORTER_PORT="${NODE_EXPORTER_PORT:-19100}"
export CADVISOR_PORT="${CADVISOR_PORT:-18080}"
export TEGRASTATS_PORT="${TEGRASTATS_PORT:-19101}"
export TEGRASTATS_BIND_ADDRESS="${TEGRASTATS_BIND_ADDRESS:-${docker_bridge_ip:-127.0.0.1}}"
export THOR_FULL_STAGE_TIMEOUT_SECONDS="${THOR_FULL_STAGE_TIMEOUT_SECONDS:-1800}"
export THOR_FULL_READINESS_TIMEOUT_SECONDS="${THOR_FULL_READINESS_TIMEOUT_SECONDS:-1200}"
export RTVI_EMBED_BATCH_SIZE="${RTVI_EMBED_BATCH_SIZE:-8}"
export RTVI_VLM_BATCH_SIZE="${RTVI_VLM_BATCH_SIZE:-1}"
export RTVI_VLM_NUM_VLM_PROCS="${RTVI_VLM_NUM_VLM_PROCS:-1}"
export RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT="${RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT:-true}"
export RTVI_TIMESTAMP_PROMPT_PREFIX_FILE_SOURCE="${RTVI_TIMESTAMP_PROMPT_PREFIX_FILE_SOURCE:-}"
export RTVI_TIMESTAMP_PROMPT_SUFFIX_FILE_SOURCE="${RTVI_TIMESTAMP_PROMPT_SUFFIX_FILE_SOURCE:-}"
export RTVI_TIMESTAMP_PROMPT_PREFIX_RTSP_SOURCE="${RTVI_TIMESTAMP_PROMPT_PREFIX_RTSP_SOURCE:-}"
export RTVI_TIMESTAMP_PROMPT_SUFFIX_RTSP_SOURCE="${RTVI_TIMESTAMP_PROMPT_SUFFIX_RTSP_SOURCE:-}"
export RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS="${RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS:-false}"
export LVS_LLM_ENABLE_THINKING="${LVS_LLM_ENABLE_THINKING:-false}"
export LVS_LLM_MAX_TOKENS="${LVS_LLM_MAX_TOKENS:-1024}"
export THOR_LOCAL_LVS_IMAGE="${THOR_LOCAL_LVS_IMAGE:-cti-vss-video-summarization:thor-local}"
export THOR_LOCAL_ALERT_BRIDGE_IMAGE="${THOR_LOCAL_ALERT_BRIDGE_IMAGE:-cti-vss-alert-bridge:thor-local}"
export THOR_LOCAL_RTVI_VLM_IMAGE="${THOR_LOCAL_RTVI_VLM_IMAGE:-cti-vss-rt-vlm:thor-local}"
export THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE="${THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE:-cti-vss-behavior-analytics:thor-local}"
export THOR_LOCAL_VIOS_MCP_IMAGE="${THOR_LOCAL_VIOS_MCP_IMAGE:-cti-vss-vios-mcp:thor-local}"
export VLM_MAX_FRAMES_PER_REQUEST="${VLM_MAX_FRAMES_PER_REQUEST:-4}"
export VLM_WARMUP_ENABLED=false
export REALTIME_ALERT_CHUNK_DURATION="${REALTIME_ALERT_CHUNK_DURATION:-10}"
export REALTIME_ALERT_CHUNK_OVERLAP_DURATION="${REALTIME_ALERT_CHUNK_OVERLAP_DURATION:-2}"
export REALTIME_ALERT_FRAMES_PER_CHUNK="${REALTIME_ALERT_FRAMES_PER_CHUNK:-4}"
export REALTIME_ALERT_USE_FPS="${REALTIME_ALERT_USE_FPS:-false}"
export REALTIME_ALERT_VLM_INPUT_WIDTH="${REALTIME_ALERT_VLM_INPUT_WIDTH:-512}"
export REALTIME_ALERT_VLM_INPUT_HEIGHT="${REALTIME_ALERT_VLM_INPUT_HEIGHT:-512}"
export REALTIME_ALERT_ENABLE_REASONING="${REALTIME_ALERT_ENABLE_REASONING:-false}"
export REALTIME_ALERT_MAX_TOKENS="${REALTIME_ALERT_MAX_TOKENS:-128}"
export REALTIME_ALERT_ENABLE_AUDIO="${REALTIME_ALERT_ENABLE_AUDIO:-false}"
export ALERT_DIRECT_MEDIA_ENABLED="${ALERT_DIRECT_MEDIA_ENABLED:-true}"
export ALERT_ENRICHMENT_ENABLED="${ALERT_ENRICHMENT_ENABLED:-true}"
export ALERT_ALWAYS_ON_ENABLED="${ALERT_ALWAYS_ON_ENABLED:-false}"
export ALERT_WEBSOCKET_ENABLED="${ALERT_WEBSOCKET_ENABLED:-true}"
export VST_VIDEO_STORAGE_SIZE_MB="${VST_VIDEO_STORAGE_SIZE_MB:-20000}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
active_domain_pack_id="general"
if [[ -f "${domain_pack_current_file}" ]]; then
  IFS= read -r candidate_domain_pack_id < "${domain_pack_current_file}" || true
  if [[ "${candidate_domain_pack_id}" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] &&
     [[ -f "${domain_pack_dir}/${candidate_domain_pack_id}.json" ]]; then
    active_domain_pack_id="${candidate_domain_pack_id}"
  fi
fi
domain_default_title="$(python3 "${domain_pack_tool}" get "${active_domain_pack_id}" title 2>/dev/null || printf 'THOR LOCAL VSS')"
domain_default_subtitle="$(python3 "${domain_pack_tool}" get "${active_domain_pack_id}" subtitle 2>/dev/null || printf 'OFFLINE VIDEO INTELLIGENCE')"
export NEXT_PUBLIC_APP_TITLE="${NEXT_PUBLIC_APP_TITLE:-${domain_default_title}}"
export NEXT_PUBLIC_APP_SUBTITLE="${NEXT_PUBLIC_APP_SUBTITLE:-${domain_default_subtitle}}"
export NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE="${NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE:-true}"
export VSS_PRESERVE_DATA_ON_UP="${VSS_PRESERVE_DATA_ON_UP:-true}"
export VSS_PRUNE_DANGLING_VOLUMES="${VSS_PRUNE_DANGLING_VOLUMES:-false}"
export THOR_LOCAL_FORCE_BOOTSTRAP="${THOR_LOCAL_FORCE_BOOTSTRAP:-false}"
# Thor-local uses operator-hosted model endpoints and one unified application
# profile. Perception is selected separately so the Smart City and Search
# pipelines can never compete for Thor's one GPU/RT-CV host port.
export COMPOSE_PROFILES="${THOR_LOCAL_COMPOSE_PROFILES:-bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d}"
smartcity_profile_enabled=false
case ",${COMPOSE_PROFILES}," in
  *,bp_developer_thor_smartcity_2d,*) smartcity_profile_enabled=true ;;
esac
export NEXT_PUBLIC_ENABLE_MAP_TAB="${NEXT_PUBLIC_ENABLE_MAP_TAB:-${smartcity_profile_enabled}}"
export NEXT_PUBLIC_MAP_URL="${NEXT_PUBLIC_MAP_URL:-http://127.0.0.1:${VSS_PUBLIC_PORT}/smartcity-map/}"

usage() {
  cat <<'EOF'
Usage: thor-local.sh <command>

Commands:
  preflight  Validate this Thor, local models, ports, disk, and Docker.
  model-check
             Exercise the local OpenAI-compatible LLM and four-image VLM contract.
  contract   Show the effective non-secret Thor-local environment contract.
  qualify --tier contract|runtime
             Verify checked-in contracts offline, or probe a running stack through
             bounded, GET-only loopback requests. Neither tier mutates VSS state.
  acceptance [plan|execute|recover] ...
             Compile the inert stateful plan by default. The narrowly scoped RTVI
             file canary requires the explicit execute/recover opt-in contract.
  kernel-check
             Check required VSS kernel settings without changing the host.
  kernel-settings
             Apply and persist required settings; uses sudo only when needed.
  up         Connected bootstrap. Requires NGC_CLI_API_KEY to obtain NVIDIA images.
             Reuses a complete offline stage; set THOR_LOCAL_FORCE_BOOTSTRAP=true
             to rebuild and restage from connected sources.
  refresh-runtime
             Generate or refresh the protected runtime env without network access.
  verify-offline
             Prove runtime env, images, host models, and embedding caches are staged.
  restart    Start the staged stack without pulls or builds (offline-safe).
  ready      Wait for the complete container and HTTP readiness contract.
  doctor     Read-only, offline-safe Thor/operator/application health report.
  security audit
             Audit runtime secrets, supported ingress, and LAN-visible VSS ports.
  security firewall-plan <interface> [interface ...]
             Print a narrow nftables rule that blocks VSS ports only on the named
             physical interfaces while preserving loopback and Docker bridges.
  security firewall-apply <interface> [interface ...]
             Apply that volatile rule after THOR_LOCAL_CONFIRM_FIREWALL=yes.
  security firewall-status|firewall-remove
             Inspect or remove only the cti_vss nftables table.
  domain list|show <id>|apply <id>|current
             Inspect or apply an offline, configuration-driven demo domain.
  stop       Stop containers without deleting data.
  down       Remove containers and networks while preserving volumes and data.
  status     Show service and local-model status.

Optional environment overrides:
  LLM_ENDPOINT_URL, VLM_ENDPOINT_URL, VLM_CONTAINER_ENDPOINT_URL,
  THOR_LOCAL_MODEL_BIND_HOST,
  THOR_LOCAL_LLM_MODEL, THOR_LOCAL_VLM_MODEL, THOR_LOCAL_LLM_MODEL_TYPE,
  THOR_LOCAL_VLM_MODEL_TYPE, THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE,
  THOR_LOCAL_LLM_CONTAINER, THOR_LOCAL_VLM_CONTAINER,
  THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS, VSS_AGENT_PORT, VSS_UI_PORT, HAPROXY_PORT,
  THOR_LOCAL_MODEL_CONTRACT_TIMEOUT_SECONDS,
  THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START (defaults 50) and
  THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START (defaults 20),
  VST_PORT, VST_MCP_PORT, VIOS_MCP_ENDPOINT, SENSOR_HTTP_PORT, STREAM_PROCESSOR_HTTP_PORT,
  SDR_STREAMPROCESSING_PORT,
  RTVI_EMBED_PORT, RTVI_VLM_PORT, RTVI_CV_PORT,
  VIDEO_ANALYTICS_API_PORT, SMARTCITY_MAP_PORT, ALERT_BRIDGE_PORT, KAFKA_PORT, VSS_ES_PORT,
  VSS_VA_MCP_PORT, BACKEND_PORT, KIBANA_PORT, PHOENIX_PORT,
  MONITORING_BIND_ADDRESS, PROMETHEUS_CONFIG_FILE,
  PROMETHEUS_PORT, GRAFANA_PORT, NODE_EXPORTER_PORT, CADVISOR_PORT,
  TEGRASTATS_PORT (fixed at 19101 by the checked-in Prometheus target),
  TEGRASTATS_BIND_ADDRESS (fixed to the detected private docker0 gateway),
  VLM_MAX_FRAMES_PER_REQUEST, VST_VIDEO_STORAGE_SIZE_MB.
  NPM_CONFIG_REGISTRY (defaults to https://registry.npmmirror.com).
  NEXT_PUBLIC_APP_TITLE, NEXT_PUBLIC_APP_SUBTITLE,
  NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE.
  THOR_LOCAL_COMPOSE_PROFILES defaults to the shared Thor-full services plus
  bp_developer_thor_search_perception_2d. Replace that perception profile with
  bp_developer_thor_smartcity_2d for the one-camera Smart City workload.
  THOR_FULL_ENABLE_KIBANA (defaults to true).
  THOR_FULL_STAGE_TIMEOUT_SECONDS (defaults to 1800).
  THOR_FULL_READINESS_TIMEOUT_SECONDS (defaults to 1200).
  RTVI_EMBED_BATCH_SIZE (defaults to 8 for the single-stream Thor profile).
  RTVI_VLM_BATCH_SIZE and RTVI_VLM_NUM_VLM_PROCS (both fixed at 1 for
  the single-stream, OpenAI-compatible local VLM profile).
  RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT (defaults true), the four
  RTVI_TIMESTAMP_PROMPT_{PREFIX,SUFFIX}_{FILE,RTSP}_SOURCE templates, and
  RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS (defaults false) expose the 3.2.1
  timestamp contract. Enable absolute metadata only for a compatible model.
  LVS_LLM_ENABLE_THINKING (defaults false) and LVS_LLM_MAX_TOKENS
  (defaults 1024) bound local summary aggregation.
  LVS_ENABLE_MCP (defaults true) and LVS_MCP_PORT (defaults 38112) expose
  the released local LVS SSE MCP server.
  VST_MCP_PORT (defaults 8001) and VIOS_MCP_ENDPOINT expose the source-shipped
  VIOS FastMCP gateway on loopback; VST_MCP_URL remains the legacy REST root.
  VIA_DEV_API (defaults true) exposes the file-management and VLM-caption
  routes required by the complete released LVS MCP tool set.
  REALTIME_ALERT_CHUNK_DURATION, REALTIME_ALERT_CHUNK_OVERLAP_DURATION,
  REALTIME_ALERT_FRAMES_PER_CHUNK, REALTIME_ALERT_USE_FPS,
  REALTIME_ALERT_VLM_INPUT_WIDTH, REALTIME_ALERT_VLM_INPUT_HEIGHT,
  REALTIME_ALERT_ENABLE_REASONING, REALTIME_ALERT_MAX_TOKENS, and
  REALTIME_ALERT_ENABLE_AUDIO tune the local live-alert frame contract.
  ALERT_DIRECT_MEDIA_ENABLED, ALERT_ENRICHMENT_ENABLED,
  ALERT_ALWAYS_ON_ENABLED, and ALERT_WEBSOCKET_ENABLED expose the released
  local-only alert extensions (all default true in the Thor-full profile).
  VSS_DATA_DIR (defaults to deploy/docker/data-dir).
  THOR_LOCAL_FORCE_BOOTSTRAP (defaults to false).
  NGC_CLI_API_KEY_FILE (defaults to ~/.config/cti-vss/ngc-api-key).

Domain packs:
  deploy/docker/thor-local/domain-packs/*.json (versioned, no secrets).
  Applying a pack updates only its exactly tracked verification rules and the
  protected runtime branding. Conflicting operator rules are preserved.

Runtime environment:
  deploy/docker/thor-local/generated.env (gitignored, mode 0600).
  It can be refreshed offline from the versioned thor-full contract. Registry
  credentials are blanked before lifecycle commands use it.
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command is missing: $1"
}

edge_cache_cleaner_is_running() {
  pgrep -f '^(bash|/bin/bash) /usr/local/bin/sys-cache-cleaner\.sh$' >/dev/null 2>&1
}

require_edge_cache_cleaner() {
  # Thor shares system memory between CPU and GPU. NVIDIA's edge deployment
  # contract requires periodic page-cache eviction so long-running video and
  # inference workloads do not lose usable GPU memory to filesystem cache.
  if ! edge_cache_cleaner_is_running; then
    die "Thor cache cleaner is not running. Start it after every reboot with: sudo -b /usr/local/bin/sys-cache-cleaner.sh"
  fi
}

model_is_served() {
  local endpoint="$1"
  local expected_model="$2"
  local response
  response="$(
    curl --connect-timeout 3 --max-time 10 --fail --silent --show-error \
      "${endpoint}/v1/models"
  )" || return 1
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
    models = payload.get("data", []) if isinstance(payload, dict) else []
    served = {item.get("id") for item in models if isinstance(item, dict)}
except (json.JSONDecodeError, OSError, TypeError):
    raise SystemExit(1)
raise SystemExit(0 if sys.argv[1] in served else 1)
' "${expected_model}" <<< "${response}"
}

official_edge_demo_lane_is_deployed() {
  local config_files
  config_files="$(docker container inspect --format \
    '{{index .Config.Labels "com.docker.compose.project.config_files"}}' \
    vss-agent 2>/dev/null)" || return 1
  [[ "${config_files}" == *"${official_edge_dir}/compose.yml"* ]] &&
    [[ "${config_files}" == *"${official_edge_dir}/compose.thor-demo-memory.yml"* ]]
}

container_mount_source() {
  local container_name="$1"
  local destination="$2"
  docker container inspect --format \
    "{{range .Mounts}}{{if eq .Destination \"${destination}\"}}{{.Source}}{{end}}{{end}}" \
    "${container_name}" 2>/dev/null
}

require_official_edge_demo_models() {
  model_is_served "${official_edge_llm_endpoint}" "${official_edge_llm_model}" ||
    die "Official Thor LLM ${official_edge_llm_model} is not available at ${official_edge_llm_endpoint}/v1/models"
  model_is_served "${official_edge_vlm_endpoint}" "${official_edge_vlm_model}" ||
    die "Official Thor VLM ${official_edge_vlm_model} is not available at ${official_edge_vlm_endpoint}/v1/models"
}

openai_chat_contract() {
  local role="$1"
  local endpoint="$2"
  local expected_model="$3"
  local image_count="$4"
  local temporary_directory request_file response_file header_file http_status
  temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/thor-model-contract.XXXXXX")"
  request_file="${temporary_directory}/request.json"
  response_file="${temporary_directory}/response.json"
  header_file="${temporary_directory}/authorization.header"
  chmod 700 "${temporary_directory}"
  printf 'Authorization: Bearer %s\n' "${OPENAI_API_KEY}" > "${header_file}"
  chmod 600 "${header_file}"

  python3 - "${request_file}" "${expected_model}" "${image_count}" <<'PY'
import json
import sys

output_path, model, image_count_text = sys.argv[1:]
image_count = int(image_count_text)
if image_count:
    # A complete, tiny PNG keeps this capability probe deterministic and avoids
    # reading any operator footage. Repeating it proves request cardinality,
    # which is the contract the alert and report paths depend on.
    pixel = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    content = [
        {
            "type": "text",
            "text": (
                f"There are {image_count} attached test images. "
                "Reply with a short acknowledgement."
            ),
        }
    ]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{pixel}"},
        }
        for _ in range(image_count)
    )
else:
    content = "Reply with a short acknowledgement."

with open(output_path, "w", encoding="utf-8") as stream:
    json.dump(
        {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 8,
            "temperature": 0,
        },
        stream,
    )
PY

  http_status="$(curl --connect-timeout 3 \
    --max-time "${THOR_LOCAL_MODEL_CONTRACT_TIMEOUT_SECONDS}" \
    --silent --show-error --output "${response_file}" --write-out '%{http_code}' \
    --header 'Content-Type: application/json' --header "@${header_file}" \
    --data-binary "@${request_file}" \
    "${endpoint%/}/v1/chat/completions")" || {
      rm -rf -- "${temporary_directory}"
      echo "[ERROR] ${role} chat-completions request failed at ${endpoint}." >&2
      return 1
    }

  if [[ "${http_status}" != "200" ]] || ! python3 - "${response_file}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        payload = json.load(stream)
    choices = payload.get("choices")
    content = choices[0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty assistant content")
except (OSError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
    raise SystemExit(1)
PY
  then
    rm -rf -- "${temporary_directory}"
    echo "[ERROR] ${role} does not satisfy the OpenAI chat-completions response contract (HTTP ${http_status})." >&2
    return 1
  fi

  rm -rf -- "${temporary_directory}"
}

check_local_model_contracts() {
  local llm_endpoint="${LLM_ENDPOINT_URL}"
  local vlm_endpoint="${VLM_ENDPOINT_URL}"
  local llm_model="${THOR_LOCAL_LLM_MODEL}"
  local vlm_model="${THOR_LOCAL_VLM_MODEL}"
  require_command curl
  require_command python3
  validate_thor_full_contract
  if official_edge_demo_lane_is_deployed; then
    llm_endpoint="${official_edge_llm_endpoint}"
    vlm_endpoint="${official_edge_vlm_endpoint}"
    llm_model="${official_edge_llm_model}"
    vlm_model="${official_edge_vlm_model}"
    echo "[INFO] Active exact-model Thor demo lane detected."
  fi
  model_is_served "${llm_endpoint}" "${llm_model}" ||
    die "LLM ${llm_model} is not advertised at ${llm_endpoint}/v1/models"
  model_is_served "${vlm_endpoint}" "${vlm_model}" ||
    die "VLM ${vlm_model} is not advertised at ${vlm_endpoint}/v1/models"
  openai_chat_contract LLM "${llm_endpoint}" "${llm_model}" 0 ||
    die "LLM provider contract failed"
  echo "[OK] LLM implements OpenAI-compatible /v1/models and /v1/chat/completions."
  openai_chat_contract VLM "${vlm_endpoint}" "${vlm_model}" \
    "${VLM_MAX_FRAMES_PER_REQUEST}" || die "VLM multi-image provider contract failed"
  echo "[OK] VLM accepted ${VLM_MAX_FRAMES_PER_REQUEST} ordered images through OpenAI-compatible chat completions."
}

wait_for_model() {
  local role="$1"
  local endpoint="$2"
  local expected_model="$3"
  local deadline=$((SECONDS + THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if model_is_served "${endpoint}" "${expected_model}" 2>/dev/null; then
      echo "[OK] ${role} ${expected_model} is ready at ${endpoint}."
      return 0
    fi
    sleep 5
  done
  die "${role} container started, but ${expected_model} did not appear at ${endpoint}/v1/models within ${THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS} seconds"
}

ensure_local_model_is_running() {
  local role="$1"
  local container_name="$2"
  local endpoint="$3"
  local expected_model="$4"
  if model_is_served "${endpoint}" "${expected_model}" 2>/dev/null; then
    echo "[OK] ${role} ${expected_model} is already ready."
    return 0
  fi
  [[ "${container_name}" != "none" ]] ||
    die "${role} endpoint is unavailable and its THOR_LOCAL_*_CONTAINER is 'none'; start the operator-managed model server first"
  docker container inspect "${container_name}" >/dev/null 2>&1 ||
    die "Configured ${role} container does not exist: ${container_name}"
  require_memory_headroom "starting ${role} ${expected_model}" \
    "${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START}"
  echo "[INFO] Starting ${role} container ${container_name}..."
  docker start "${container_name}" >/dev/null
  wait_for_model "${role}" "${endpoint}" "${expected_model}"
}

ensure_local_models_are_running() {
  require_command curl
  require_command docker
  require_command pgrep
  require_edge_cache_cleaner
  if official_edge_demo_lane_is_deployed; then
    die "The exact-model Thor demo lane is deployed. Generic up/restart would replace its Nemotron 3 Nano + Cosmos3 consumer wiring; use ${official_edge_dir}/thor_demo.py for this deployment."
  fi
  # Sequential startup is intentional on unified memory: simultaneous vLLM
  # initialization makes each server measure the other's temporary allocation
  # as available capacity and can overcommit the Thor.
  ensure_local_model_is_running LLM "${THOR_LOCAL_LLM_CONTAINER}" "${LLM_ENDPOINT_URL}" "${THOR_LOCAL_LLM_MODEL}"
  ensure_local_model_is_running VLM "${THOR_LOCAL_VLM_CONTAINER}" "${VLM_ENDPOINT_URL}" "${THOR_LOCAL_VLM_MODEL}"
}

expected_container_running() {
  local container_name="$1"
  if [[ "$(docker inspect --format '{{.State.Running}}' "${container_name}" 2>/dev/null || true)" == "true" ]]; then
    return 0
  fi
  # Services without an explicit container_name use Compose-generated names
  # such as mdx-node-exporter-1. Match only the active mdx project/service
  # labels so an unrelated similarly named container cannot claim the port.
  [[ -n "$(docker ps --quiet \
    --filter 'label=com.docker.compose.project=mdx' \
    --filter "label=com.docker.compose.service=${container_name}" \
    --filter status=running 2>/dev/null)" ]]
}

require_available_port() {
  local port="$1"
  local expected_container="$2"
  if ss -H -ltn "sport = :${port}" | grep -q . && ! expected_container_running "${expected_container}"; then
    die "Port ${port} is already in use by something other than ${expected_container}"
  fi
}

require_valid_port() {
  local name="$1"
  local port="$2"
  if [[ ! "${port}" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    die "${name} must be an integer from 1 through 65535; found '${port}'"
  fi
}

available_memory_gb() {
  awk '/^MemAvailable:/ {print int($2 / 1024 / 1024); exit}' /proc/meminfo
}

require_memory_headroom() {
  local operation="$1"
  local required_gb="$2"
  local available_gb
  available_gb="$(available_memory_gb)"
  [[ "${available_gb}" =~ ^[0-9]+$ ]] ||
    die "Cannot determine unified-memory headroom before ${operation}"
  (( available_gb >= required_gb )) ||
    die "Only ${available_gb} GiB unified memory is available before ${operation}; require ${required_gb} GiB. Stop unrelated GPU workloads and retry."
}

require_local_model_endpoint() {
  local name="$1"
  local endpoint="$2"
  python3 - "${name}" "${endpoint}" <<'PY'
import ipaddress
import json
import subprocess
import sys
from urllib.parse import urlparse

name, endpoint = sys.argv[1:]
parsed = urlparse(endpoint)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit(f"[ERROR] {name} must be an HTTP(S) URL; found {endpoint!r}")
try:
    address = ipaddress.ip_address(parsed.hostname)
except ValueError:
    if parsed.hostname.lower() == "localhost":
        raise SystemExit(0)
    raise SystemExit(f"[ERROR] {name} must use a literal local address or localhost; found {endpoint!r}")
if address.is_loopback:
    raise SystemExit(0)

try:
    interfaces = json.loads(
        subprocess.run(
            ["ip", "-j", "address", "show"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout
    )
except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
    raise SystemExit(f"[ERROR] cannot validate {name} against local interfaces: {exc}")

for interface in interfaces:
    interface_name = interface.get("ifname", "")
    if not (
        interface_name == "docker0"
        or interface_name.startswith("br-")
        or interface_name.startswith("l4tbr")
    ):
        continue
    for info in interface.get("addr_info", []):
        if info.get("local") == str(address):
            raise SystemExit(0)

raise SystemExit(
    f"[ERROR] {name} must remain on loopback or a local Docker bridge; found {endpoint!r}"
)
PY
}

require_rtvi_model_endpoint() {
  local endpoint="$1"
  if [[ "${endpoint}" == "http://${HOST_IP}" ||
        "${endpoint}" == "http://${HOST_IP}:"* ||
        "${endpoint}" == "http://${HOST_IP}/"* ||
        "${endpoint}" == "https://${HOST_IP}" ||
        "${endpoint}" == "https://${HOST_IP}:"* ||
        "${endpoint}" == "https://${HOST_IP}/"* ]]; then
    return 0
  fi
  if ! require_local_model_endpoint VLM_CONTAINER_ENDPOINT_URL "${endpoint}"; then
    die "VLM_CONTAINER_ENDPOINT_URL must use this Thor's HOST_IP or a local Docker bridge; found '${endpoint}'"
  fi
}

validate_thor_full_contract() {
  local item name port value model_container
  [[ "${profile}" == "thor-full" ]] || die "THOR_LOCAL_PROFILE must be thor-full; found '${profile}'"
  case "${COMPOSE_PROFILES}" in
    bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d)
      [[ "${NEXT_PUBLIC_ENABLE_MAP_TAB}" == "false" ]] ||
        die "NEXT_PUBLIC_ENABLE_MAP_TAB must be false for the Thor Search perception profile"
      ;;
    bp_developer_thor_full_2d,bp_developer_thor_smartcity_2d)
      [[ "${NEXT_PUBLIC_ENABLE_MAP_TAB}" == "true" ]] ||
        die "NEXT_PUBLIC_ENABLE_MAP_TAB must be true for the Thor Smart City profile"
      ;;
    *)
      die "THOR_LOCAL_COMPOSE_PROFILES must select Thor-full plus exactly one of bp_developer_thor_search_perception_2d or bp_developer_thor_smartcity_2d"
      ;;
  esac
  [[ "${THOR_FULL_ENABLE_KIBANA}" == "true" || "${THOR_FULL_ENABLE_KIBANA}" == "false" ]] ||
    die "THOR_FULL_ENABLE_KIBANA must be true or false"
  [[ "${MONITORING_BIND_ADDRESS}" == "127.0.0.1" ]] ||
    die "MONITORING_BIND_ADDRESS must remain 127.0.0.1 for Thor-local"
  [[ "${PROMETHEUS_CONFIG_FILE}" == "${deployment_dir}/thor-local/observability/prometheus.yml" ]] ||
    die "PROMETHEUS_CONFIG_FILE must use the versioned Thor-local target set"
  [[ "${PHOENIX_HOST}" == "127.0.0.1" ]] ||
    die "PHOENIX_HOST must remain 127.0.0.1 for Thor-local"
  [[ "${LOGSTASH_API_PORT}" == "9600" ]] ||
    die "LOGSTASH_API_PORT must remain 9600 while the versioned Thor Logstash config uses that port"
  [[ "${BACKEND_PORT}" == "38111" ]] ||
    die "BACKEND_PORT must remain 38111 while the versioned Thor Prometheus config scrapes LVS on that port"
  [[ "${TEGRASTATS_PORT}" == "19101" ]] ||
    die "TEGRASTATS_PORT must remain 19101 while the versioned Thor Prometheus config scrapes tegrastats on that port"
  [[ "${TEGRASTATS_BIND_ADDRESS}" == "${docker_bridge_ip:-127.0.0.1}" ]] ||
    die "TEGRASTATS_BIND_ADDRESS must use Docker's private host gateway ${docker_bridge_ip:-127.0.0.1}"
  [[ "${VIOS_MCP_ENDPOINT}" == "http://127.0.0.1:${VST_MCP_PORT}/mcp" ]] ||
    die "VIOS_MCP_ENDPOINT must remain the loopback VIOS MCP endpoint http://127.0.0.1:${VST_MCP_PORT}/mcp"
  [[ "${THOR_LOCAL_FORCE_BOOTSTRAP}" == "true" || "${THOR_LOCAL_FORCE_BOOTSTRAP}" == "false" ]] ||
    die "THOR_LOCAL_FORCE_BOOTSTRAP must be true or false"
  [[ "${THOR_FULL_STAGE_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] ||
    die "THOR_FULL_STAGE_TIMEOUT_SECONDS must be a positive integer"
  [[ "${THOR_FULL_READINESS_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] ||
    die "THOR_FULL_READINESS_TIMEOUT_SECONDS must be a positive integer"
  [[ "${THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] ||
    die "THOR_LOCAL_MODEL_START_TIMEOUT_SECONDS must be a positive integer"
  [[ "${THOR_LOCAL_MODEL_CONTRACT_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] ||
    die "THOR_LOCAL_MODEL_CONTRACT_TIMEOUT_SECONDS must be a positive integer"
  [[ "${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START}" =~ ^[1-9][0-9]*$ ]] ||
    die "THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START must be a positive integer"
  [[ "${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START}" =~ ^[1-9][0-9]*$ ]] ||
    die "THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START must be a positive integer"
  [[ "${VLM_MAX_FRAMES_PER_REQUEST}" =~ ^[1-9][0-9]*$ ]] ||
    die "VLM_MAX_FRAMES_PER_REQUEST must be a positive integer"
  (( VLM_MAX_FRAMES_PER_REQUEST <= 16 )) ||
    die "VLM_MAX_FRAMES_PER_REQUEST must not exceed 16 on the Thor local profile"
  [[ "${RTVI_EMBED_BATCH_SIZE}" =~ ^[1-9][0-9]*$ ]] ||
    die "RTVI_EMBED_BATCH_SIZE must be a positive integer"
  (( RTVI_EMBED_BATCH_SIZE <= 64 )) ||
    die "RTVI_EMBED_BATCH_SIZE must not exceed the Cosmos-Embed maximum batch size of 64"
  [[ "${RTVI_VLM_BATCH_SIZE}" == "1" ]] ||
    die "RTVI_VLM_BATCH_SIZE must be 1 for the single-stream local Qwen VLM profile"
  [[ "${RTVI_VLM_NUM_VLM_PROCS}" == "1" ]] ||
    die "RTVI_VLM_NUM_VLM_PROCS must be 1 for the OpenAI-compatible RTVI routing contract"
  [[ "${RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT}" == "true" || "${RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT}" == "false" ]] ||
    die "RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT must be true or false"
  [[ "${RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS}" == "true" || "${RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS}" == "false" ]] ||
    die "RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS must be true or false"
  [[ "${LVS_LLM_ENABLE_THINKING}" == "true" || "${LVS_LLM_ENABLE_THINKING}" == "false" ]] ||
    die "LVS_LLM_ENABLE_THINKING must be true or false"
  [[ "${LVS_ENABLE_MCP}" == "true" || "${LVS_ENABLE_MCP}" == "false" ]] ||
    die "LVS_ENABLE_MCP must be true or false"
  [[ "${VIA_DEV_API}" == "true" || "${VIA_DEV_API}" == "false" ]] ||
    die "VIA_DEV_API must be true or false"
  [[ "${LVS_LLM_MAX_TOKENS}" =~ ^[1-9][0-9]*$ ]] ||
    die "LVS_LLM_MAX_TOKENS must be a positive integer"
  (( LVS_LLM_MAX_TOKENS <= 4096 )) ||
    die "LVS_LLM_MAX_TOKENS must not exceed 4096 on the Thor local profile"
  [[ "${REALTIME_ALERT_CHUNK_DURATION}" =~ ^[1-9][0-9]*$ ]] ||
    die "REALTIME_ALERT_CHUNK_DURATION must be a positive integer"
  [[ "${REALTIME_ALERT_CHUNK_OVERLAP_DURATION}" =~ ^[0-9]+$ ]] ||
    die "REALTIME_ALERT_CHUNK_OVERLAP_DURATION must be a non-negative integer"
  (( REALTIME_ALERT_CHUNK_OVERLAP_DURATION < REALTIME_ALERT_CHUNK_DURATION )) ||
    die "REALTIME_ALERT_CHUNK_OVERLAP_DURATION must be smaller than REALTIME_ALERT_CHUNK_DURATION"
  [[ "${REALTIME_ALERT_FRAMES_PER_CHUNK}" =~ ^[1-9][0-9]*$ ]] ||
    die "REALTIME_ALERT_FRAMES_PER_CHUNK must be a positive integer"
  (( REALTIME_ALERT_FRAMES_PER_CHUNK <= VLM_MAX_FRAMES_PER_REQUEST )) ||
    die "REALTIME_ALERT_FRAMES_PER_CHUNK must not exceed VLM_MAX_FRAMES_PER_REQUEST (${VLM_MAX_FRAMES_PER_REQUEST})"
  [[ "${REALTIME_ALERT_USE_FPS}" == "true" || "${REALTIME_ALERT_USE_FPS}" == "false" ]] ||
    die "REALTIME_ALERT_USE_FPS must be true or false"
  [[ "${REALTIME_ALERT_ENABLE_REASONING}" == "true" || "${REALTIME_ALERT_ENABLE_REASONING}" == "false" ]] ||
    die "REALTIME_ALERT_ENABLE_REASONING must be true or false"
  [[ "${REALTIME_ALERT_ENABLE_AUDIO}" == "true" || "${REALTIME_ALERT_ENABLE_AUDIO}" == "false" ]] ||
    die "REALTIME_ALERT_ENABLE_AUDIO must be true or false"
  for item in \
    "ALERT_DIRECT_MEDIA_ENABLED:${ALERT_DIRECT_MEDIA_ENABLED}" \
    "ALERT_ENRICHMENT_ENABLED:${ALERT_ENRICHMENT_ENABLED}" \
    "ALERT_ALWAYS_ON_ENABLED:${ALERT_ALWAYS_ON_ENABLED}" \
    "ALERT_WEBSOCKET_ENABLED:${ALERT_WEBSOCKET_ENABLED}"; do
    name="${item%%:*}"
    value="${item#*:}"
    [[ "${value}" == "true" || "${value}" == "false" ]] ||
      die "${name} must be true or false"
  done
  for item in \
    "REALTIME_ALERT_VLM_INPUT_WIDTH:${REALTIME_ALERT_VLM_INPUT_WIDTH}" \
    "REALTIME_ALERT_VLM_INPUT_HEIGHT:${REALTIME_ALERT_VLM_INPUT_HEIGHT}" \
    "REALTIME_ALERT_MAX_TOKENS:${REALTIME_ALERT_MAX_TOKENS}"; do
    name="${item%%:*}"
    value="${item#*:}"
    [[ "${value}" =~ ^[1-9][0-9]*$ ]] || die "${name} must be a positive integer"
    (( value <= 4096 )) || die "${name} must not exceed 4096"
  done

  for model_container in "${THOR_LOCAL_LLM_CONTAINER}" "${THOR_LOCAL_VLM_CONTAINER}"; do
    [[ "${model_container}" == "none" || "${model_container}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] ||
      die "Local model container names must be valid Docker names or 'none'; found '${model_container}'"
  done
  [[ "${THOR_LOCAL_LLM_MODEL_TYPE}" =~ ^(nim|openai|vllm)$ ]] ||
    die "THOR_LOCAL_LLM_MODEL_TYPE must be nim, openai, or vllm"
  [[ "${THOR_LOCAL_VLM_MODEL_TYPE}" =~ ^(nim|openai|vllm)$ ]] ||
    die "THOR_LOCAL_VLM_MODEL_TYPE must be nim, openai, or vllm"
  [[ "${THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE}" =~ ^(nim|openai)$ ]] ||
    die "THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE must be nim or openai because the standalone VA-MCP image does not register vllm"

  require_local_model_endpoint LLM_ENDPOINT_URL "${LLM_ENDPOINT_URL}"
  require_local_model_endpoint VLM_ENDPOINT_URL "${VLM_ENDPOINT_URL}"
  require_rtvi_model_endpoint "${VLM_CONTAINER_ENDPOINT_URL}"

  local -A seen_ports=()
  for item in \
    "VSS_AGENT_PORT:${VSS_AGENT_PORT}" \
    "VSS_UI_PORT:${VSS_UI_PORT}" \
    "HAPROXY_PORT:${HAPROXY_PORT}" \
    "VST_PORT:${VST_PORT}" \
    "VST_MCP_PORT:${VST_MCP_PORT}" \
    "SENSOR_HTTP_PORT:${SENSOR_HTTP_PORT}" \
    "STREAM_PROCESSOR_HTTP_PORT:${STREAM_PROCESSOR_HTTP_PORT}" \
    "SDR_STREAMPROCESSING_PORT:${SDR_STREAMPROCESSING_PORT}" \
    "RTVI_EMBED_PORT:${RTVI_EMBED_PORT}" \
    "RTVI_VLM_PORT:${RTVI_VLM_PORT}" \
    "RTVI_CV_PORT:${RTVI_CV_PORT}" \
    "VIDEO_ANALYTICS_API_PORT:${VIDEO_ANALYTICS_API_PORT}" \
    "SMARTCITY_MAP_PORT:${SMARTCITY_MAP_PORT}" \
    "ALERT_BRIDGE_PORT:${ALERT_BRIDGE_PORT}" \
    "KAFKA_PORT:${KAFKA_PORT}" \
    "VSS_ES_PORT:${VSS_ES_PORT}" \
    "VSS_VA_MCP_PORT:${VSS_VA_MCP_PORT}" \
    "BACKEND_PORT:${BACKEND_PORT}" \
    "LVS_MCP_PORT:${LVS_MCP_PORT}" \
    "KIBANA_PORT:${KIBANA_PORT}" \
    "PHOENIX_PORT:${PHOENIX_PORT}" \
    "LOGSTASH_API_PORT:${LOGSTASH_API_PORT}" \
    "PROMETHEUS_PORT:${PROMETHEUS_PORT}" \
    "GRAFANA_PORT:${GRAFANA_PORT}" \
    "NODE_EXPORTER_PORT:${NODE_EXPORTER_PORT}" \
    "CADVISOR_PORT:${CADVISOR_PORT}" \
    "TEGRASTATS_PORT:${TEGRASTATS_PORT}"; do
    name="${item%%:*}"
    port="${item#*:}"
    require_valid_port "${name}" "${port}"
    if [[ -n "${seen_ports[${port}]:-}" ]]; then
      die "${name} and ${seen_ports[${port}]} both claim host port ${port}"
    fi
    seen_ports["${port}"]="${name}"
  done
}

load_ngc_api_key() {
  if [[ -z "${NGC_CLI_API_KEY:-}" ]] && [[ -r "${ngc_key_file}" ]]; then
    local key_mode key_owner
    key_mode="$(stat -c '%a' "${ngc_key_file}")"
    key_owner="$(stat -c '%u' "${ngc_key_file}")"
    [[ "${key_mode}" == "600" ]] || die "${ngc_key_file} must have mode 0600; found ${key_mode}"
    [[ "${key_owner}" == "$(id -u)" ]] || die "${ngc_key_file} must be owned by the current user"
    NGC_CLI_API_KEY="$(<"${ngc_key_file}")"
    export NGC_CLI_API_KEY
  fi
  [[ -n "${NGC_CLI_API_KEY:-}" ]] || die "NGC access is required. Set NGC_CLI_API_KEY or create ${ngc_key_file}"
}

print_runtime_contract() {
  printf '%s=%s\n' \
    MODE 2d \
    BP_PROFILE bp_developer_thor_full \
    HARDWARE_PROFILE AGX-THOR \
    COMPOSE_PROFILES "${COMPOSE_PROFILES}" \
    LLM_MODE remote \
    VLM_MODE remote \
    LLM_MODEL_TYPE "${THOR_LOCAL_LLM_MODEL_TYPE}" \
    VLM_MODEL_TYPE "${THOR_LOCAL_VLM_MODEL_TYPE}" \
    VA_MCP_LLM_MODEL_TYPE "${THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE}" \
    LLM_ENDPOINT_URL "${LLM_ENDPOINT_URL}" \
    VLM_ENDPOINT_URL "${VLM_ENDPOINT_URL}" \
    VLM_CONTAINER_ENDPOINT_URL "${VLM_CONTAINER_ENDPOINT_URL}" \
    LLM_BASE_URL "${LLM_ENDPOINT_URL}" \
    VLM_BASE_URL "${VLM_ENDPOINT_URL}" \
    LLM_NAME "${THOR_LOCAL_LLM_MODEL}" \
    VLM_NAME "${THOR_LOCAL_VLM_MODEL}" \
    LLM_NAME_SLUG none \
    VLM_NAME_SLUG none \
    THOR_LOCAL_LLM_MODEL "${THOR_LOCAL_LLM_MODEL}" \
    THOR_LOCAL_VLM_MODEL "${THOR_LOCAL_VLM_MODEL}" \
    THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START "${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START}" \
    THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START "${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START}" \
    THOR_LOCAL_ALERT_BRIDGE_IMAGE "${THOR_LOCAL_ALERT_BRIDGE_IMAGE}" \
    THOR_LOCAL_RTVI_VLM_IMAGE "${THOR_LOCAL_RTVI_VLM_IMAGE}" \
    THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE "${THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE}" \
    THOR_LOCAL_VIOS_MCP_IMAGE "${THOR_LOCAL_VIOS_MCP_IMAGE}" \
    OPENAI_API_KEY "${OPENAI_API_KEY}" \
    VLM_WARMUP_ENABLED false \
    REALTIME_ALERT_CHUNK_DURATION "${REALTIME_ALERT_CHUNK_DURATION}" \
    REALTIME_ALERT_CHUNK_OVERLAP_DURATION "${REALTIME_ALERT_CHUNK_OVERLAP_DURATION}" \
    REALTIME_ALERT_FRAMES_PER_CHUNK "${REALTIME_ALERT_FRAMES_PER_CHUNK}" \
    REALTIME_ALERT_USE_FPS "${REALTIME_ALERT_USE_FPS}" \
    REALTIME_ALERT_VLM_INPUT_WIDTH "${REALTIME_ALERT_VLM_INPUT_WIDTH}" \
    REALTIME_ALERT_VLM_INPUT_HEIGHT "${REALTIME_ALERT_VLM_INPUT_HEIGHT}" \
    REALTIME_ALERT_ENABLE_REASONING "${REALTIME_ALERT_ENABLE_REASONING}" \
    REALTIME_ALERT_MAX_TOKENS "${REALTIME_ALERT_MAX_TOKENS}" \
    REALTIME_ALERT_ENABLE_AUDIO "${REALTIME_ALERT_ENABLE_AUDIO}" \
    ALERT_DIRECT_MEDIA_ENABLED "${ALERT_DIRECT_MEDIA_ENABLED}" \
    ALERT_ENRICHMENT_ENABLED "${ALERT_ENRICHMENT_ENABLED}" \
    ALERT_ALWAYS_ON_ENABLED "${ALERT_ALWAYS_ON_ENABLED}" \
    ALERT_WEBSOCKET_ENABLED "${ALERT_WEBSOCKET_ENABLED}" \
    VSS_APPS_DIR "${deployment_dir}" \
    VSS_DATA_DIR "${VSS_DATA_DIR}" \
    HOST_IP "${HOST_IP}" \
    EXTERNAL_IP "${EXTERNAL_IP}" \
    VSS_AGENT_CONFIG_FILE "/vss-agent/deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/config.yml" \
    VSS_AGENT_PORT "${VSS_AGENT_PORT}" \
    VSS_UI_PORT "${VSS_UI_PORT}" \
    HAPROXY_PORT "${HAPROXY_PORT}" \
    HAPROXY_BIND_ADDR 127.0.0.1 \
    VSS_PUBLIC_HOST 127.0.0.1 \
    VSS_PUBLIC_PORT "${VSS_PUBLIC_PORT}" \
    VST_PORT "${VST_PORT}" \
    VST_INGRESS_HTTP_PORT "${VST_INGRESS_HTTP_PORT}" \
    VST_MCP_PORT "${VST_MCP_PORT}" \
    VIOS_MCP_ENDPOINT "${VIOS_MCP_ENDPOINT}" \
    SENSOR_HTTP_PORT "${SENSOR_HTTP_PORT}" \
    STREAM_PROCESSOR_HTTP_PORT "${STREAM_PROCESSOR_HTTP_PORT}" \
    SDR_STREAMPROCESSING_PORT "${SDR_STREAMPROCESSING_PORT}" \
    SENSOR_MODULE_ENDPOINT "http://localhost:${SENSOR_HTTP_PORT}" \
    STREAM_PROCESSOR_MODULE_ENDPOINT "http://localhost:${STREAM_PROCESSOR_HTTP_PORT}" \
    RTVI_EMBED_PORT "${RTVI_EMBED_PORT}" \
    RTVI_EMBED_BATCH_SIZE "${RTVI_EMBED_BATCH_SIZE}" \
    RTVI_VLM_PORT "${RTVI_VLM_PORT}" \
    RTVI_VLM_BASE_URL "http://127.0.0.1:${RTVI_VLM_PORT}" \
    RTVI_VLM_ENDPOINT "${VLM_CONTAINER_ENDPOINT_URL%/}/v1" \
    RTVI_VLM_MODEL_TO_USE openai-compat \
    RTVI_VLM_MODEL_PATH none \
    RTVI_VLM_BATCH_SIZE "${RTVI_VLM_BATCH_SIZE}" \
    RTVI_VLM_NUM_VLM_PROCS "${RTVI_VLM_NUM_VLM_PROCS}" \
    RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT "${RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT}" \
    RTVI_TIMESTAMP_PROMPT_PREFIX_FILE_SOURCE "${RTVI_TIMESTAMP_PROMPT_PREFIX_FILE_SOURCE}" \
    RTVI_TIMESTAMP_PROMPT_SUFFIX_FILE_SOURCE "${RTVI_TIMESTAMP_PROMPT_SUFFIX_FILE_SOURCE}" \
    RTVI_TIMESTAMP_PROMPT_PREFIX_RTSP_SOURCE "${RTVI_TIMESTAMP_PROMPT_PREFIX_RTSP_SOURCE}" \
    RTVI_TIMESTAMP_PROMPT_SUFFIX_RTSP_SOURCE "${RTVI_TIMESTAMP_PROMPT_SUFFIX_RTSP_SOURCE}" \
    RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS "${RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS}" \
    RTVI_CV_PORT "${RTVI_CV_PORT}" \
    COSMOS_EMBED_PORT "${RTVI_EMBED_PORT}" \
    COSMOS_EMBED_ENDPOINT "http://127.0.0.1:${RTVI_EMBED_PORT}" \
    VIDEO_ANALYTICS_API_PORT "${VIDEO_ANALYTICS_API_PORT}" \
    MDX_PORT "${MDX_PORT}" \
    SMARTCITY_MAP_PORT "${SMARTCITY_MAP_PORT}" \
    ALERT_BRIDGE_PORT "${ALERT_BRIDGE_PORT}" \
    ALERT_BRIDGE_URL "http://127.0.0.1:${ALERT_BRIDGE_PORT}" \
    KAFKA_PORT "${KAFKA_PORT}" \
    KAFKA_BOOTSTRAP_SERVERS "127.0.0.1:${KAFKA_PORT}" \
    VSS_ES_PORT "${VSS_ES_PORT}" \
    ELASTIC_SEARCH_PORT "${VSS_ES_PORT}" \
    ELASTIC_SEARCH_ENDPOINT "http://127.0.0.1:${VSS_ES_PORT}" \
    ELASTIC_SEARCH_INDEX mdx-embed-filtered-2025-01-01 \
    VSS_VA_MCP_PORT "${VSS_VA_MCP_PORT}" \
    VIDEO_ANALYSIS_MCP_URL "http://127.0.0.1:${VSS_VA_MCP_PORT}" \
    VST_MCP_URL "http://127.0.0.1:${VST_PORT}" \
    BACKEND_PORT "${BACKEND_PORT}" \
    LVS_BACKEND_URL "http://127.0.0.1:${BACKEND_PORT}" \
    LVS_MCP_PORT "${LVS_MCP_PORT}" \
    LVS_ENABLE_MCP "${LVS_ENABLE_MCP}" \
    VIA_DEV_API "${VIA_DEV_API}" \
    LVS_LLM_ENABLE_THINKING "${LVS_LLM_ENABLE_THINKING}" \
    LVS_LLM_MAX_TOKENS "${LVS_LLM_MAX_TOKENS}" \
    THOR_LOCAL_LVS_IMAGE "${THOR_LOCAL_LVS_IMAGE}" \
    MODEL_ROOT_DIR "${data_directory}/models" \
    KIBANA_PORT "${KIBANA_PORT}" \
    PHOENIX_HOST "${PHOENIX_HOST}" \
    PHOENIX_PORT "${PHOENIX_PORT}" \
    PHOENIX_ENDPOINT "http://127.0.0.1:${PHOENIX_PORT}" \
    LOGSTASH_API_PORT "${LOGSTASH_API_PORT}" \
    MONITORING_BIND_ADDRESS "${MONITORING_BIND_ADDRESS}" \
    PROMETHEUS_CONFIG_FILE "${PROMETHEUS_CONFIG_FILE}" \
    PROMETHEUS_PORT "${PROMETHEUS_PORT}" \
    GRAFANA_PORT "${GRAFANA_PORT}" \
    NODE_EXPORTER_PORT "${NODE_EXPORTER_PORT}" \
    CADVISOR_PORT "${CADVISOR_PORT}" \
    TEGRASTATS_PORT "${TEGRASTATS_PORT}" \
    TEGRASTATS_BIND_ADDRESS "${TEGRASTATS_BIND_ADDRESS}" \
    NUM_STREAMS 1 \
    NUM_SENSORS 1 \
    ENABLE_CRITIC true \
    VSS_VA_MCP_CONFIG_FILE "/vss-agent/deploy/docker/developer-profiles/dev-profile-thor-full/vss-agent/configs/va_mcp_server_config.yml" \
    VSS_AGENT_TEMPLATE_PATH "/vss-agent/deploy/docker/developer-profiles/dev-profile-alerts/vss-agent/templates" \
    VSS_AGENT_TEMPLATE_NAME incident_report_template.md \
    VLM_AS_VERIFIER_CONFIG_FILE "${deployment_dir}/developer-profiles/dev-profile-alerts/vlm-as-verifier/configs/config.yml" \
    VLM_AS_VERIFIER_CONFIG_FILE_REALTIME "${deployment_dir}/developer-profiles/dev-profile-thor-full/vlm-as-verifier/configs/realtime-config.yml" \
    VLM_AS_VERIFIER_ALERT_TYPE_CONFIG_FILE "${deployment_dir}/developer-profiles/dev-profile-thor-full/vlm-as-verifier/configs/alert_type_config.json" \
    VLM_MAX_FRAMES_PER_REQUEST "${VLM_MAX_FRAMES_PER_REQUEST}" \
    VST_VIDEO_STORAGE_SIZE_MB "${VST_VIDEO_STORAGE_SIZE_MB}" \
    NPM_CONFIG_REGISTRY "${NPM_CONFIG_REGISTRY}" \
    NEXT_PUBLIC_APP_TITLE "${NEXT_PUBLIC_APP_TITLE}" \
    NEXT_PUBLIC_APP_SUBTITLE "${NEXT_PUBLIC_APP_SUBTITLE}" \
    NEXT_PUBLIC_ENABLE_MAP_TAB "${NEXT_PUBLIC_ENABLE_MAP_TAB}" \
    NEXT_PUBLIC_MAP_URL "${NEXT_PUBLIC_MAP_URL}" \
    NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE "${NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE}" \
    NGC_CLI_API_KEY '' \
    NGC_API_KEY '' \
    NVIDIA_API_KEY '' \
    HF_TOKEN '' \
    RTVI_VLM_API_KEY ''
}

set_env_file_value() {
  local env_file="$1"
  local key="$2"
  local value="$3"
  local tmp
  [[ "${key}" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "Invalid runtime environment key: ${key}"
  [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] || die "Runtime environment value for ${key} contains a newline"
  tmp="$(mktemp "$(dirname -- "${env_file}")/.env-update.XXXXXX")"
  chmod 600 "${tmp}"
  awk -v target="${key}" -v replacement="${value}" '
    BEGIN { found=0 }
    index($0, target "=") == 1 { print target "=" replacement; found=1; next }
    { print }
    END { if (!found) print target "=" replacement }
  ' "${env_file}" > "${tmp}"
  chmod 600 "${tmp}"
  mv -f "${tmp}" "${env_file}"
}

runtime_env_value() {
  local key="$1"
  awk -v target="${key}" '
    index($0, target "=") == 1 { print substr($0, length(target) + 2); exit }
  ' "${generated_env}"
}

require_runtime_env() {
  [[ -f "${generated_env}" ]] || die "Missing ${generated_env}; run the connected bootstrap first"
  [[ "$(stat -c '%a' "${generated_env}")" == "600" ]] || die "${generated_env} must have mode 0600"
  [[ "$(stat -c '%u' "${generated_env}")" == "$(id -u)" ]] || die "${generated_env} must be owned by the current user"

  local key expected actual
  while IFS='=' read -r key expected; do
    actual="$(runtime_env_value "${key}")"
    [[ "${actual}" == "${expected}" ]] ||
      die "Protected runtime environment does not match the Thor-local contract for ${key}; run a connected bootstrap to refresh it"
  done < <(print_runtime_contract)
}

ensure_operator_runtime_directories() {
  local reports_directory="${data_directory}/agent-reports"
  mkdir -p -- "${reports_directory}"
  chmod 0700 -- "${reports_directory}"
  [[ "$(stat -c '%u' "${reports_directory}")" == "$(id -u)" ]] ||
    die "${reports_directory} must be owned by the invoking user ($(id -un)); fix its ownership before starting Thor VSS"
  [[ "$(stat -c '%a' "${reports_directory}")" == "700" ]] ||
    die "${reports_directory} must have mode 0700"
}

show_contract() {
  cat <<EOF
Thor-local environment contract:
  Blueprint: bp_developer_thor_full (AGX-THOR, mode 2d)
  Compose profile: ${COMPOSE_PROFILES}
  Smart City map: enabled=${NEXT_PUBLIC_ENABLE_MAP_TAB}, URL=${NEXT_PUBLIC_MAP_URL}
  Domain pack: ${active_domain_pack_id}
  UI: port ${VSS_UI_PORT}, title '${NEXT_PUBLIC_APP_TITLE}', subtitle '${NEXT_PUBLIC_APP_SUBTITLE}'
  RTSP add control: ${NEXT_PUBLIC_VIDEO_MANAGEMENT_TAB_ADD_RTSP_ENABLE}
  LLM: ${THOR_LOCAL_LLM_MODEL} via ${THOR_LOCAL_LLM_MODEL_TYPE} at ${LLM_ENDPOINT_URL} (container ${THOR_LOCAL_LLM_CONTAINER})
  VA-MCP LLM adapter: ${THOR_LOCAL_VA_MCP_LLM_MODEL_TYPE} (same local model endpoint)
  VLM: ${THOR_LOCAL_VLM_MODEL} via ${THOR_LOCAL_VLM_MODEL_TYPE} at ${VLM_ENDPOINT_URL} (container ${THOR_LOCAL_VLM_CONTAINER})
  RTVI-VLM upstream: ${VLM_CONTAINER_ENDPOINT_URL}/v1 (bridge-to-host)
  Runtime ports: agent=${VSS_AGENT_PORT}, UI=${VSS_UI_PORT}, ingress=${HAPROXY_PORT}, VIOS=${VST_PORT}/${SENSOR_HTTP_PORT}/${STREAM_PROCESSOR_HTTP_PORT}, SDR=${SDR_STREAMPROCESSING_PORT}, VIOS-MCP=${VST_MCP_PORT}
  Intelligence ports: embed=${RTVI_EMBED_PORT} (batch ${RTVI_EMBED_BATCH_SIZE}), RTVI-VLM=${RTVI_VLM_PORT} (batch ${RTVI_VLM_BATCH_SIZE}, processes ${RTVI_VLM_NUM_VLM_PROCS}), perception=${RTVI_CV_PORT}, analytics=${VIDEO_ANALYTICS_API_PORT}, alerts=${ALERT_BRIDGE_PORT}, LVS=${BACKEND_PORT}
  RTVI timestamps: prompt=${RTVI_ADD_TIMESTAMP_TO_VLM_PROMPT}, absolute_metadata=${RTVI_VIDEO_METADATA_ABSOLUTE_TIMESTAMPS}
  LVS aggregation: provider=${THOR_LOCAL_LLM_MODEL_TYPE}, thinking=${LVS_LLM_ENABLE_THINKING}, max_tokens=${LVS_LLM_MAX_TOKENS}, MCP=${LVS_ENABLE_MCP}@${LVS_MCP_PORT}
  LVS extended routes: VIA_DEV_API=${VIA_DEV_API}
  Live alerts: ${REALTIME_ALERT_CHUNK_DURATION}s chunks/${REALTIME_ALERT_CHUNK_OVERLAP_DURATION}s overlap, ${REALTIME_ALERT_FRAMES_PER_CHUNK} fixed frames at ${REALTIME_ALERT_VLM_INPUT_WIDTH}x${REALTIME_ALERT_VLM_INPUT_HEIGHT}, reasoning=${REALTIME_ALERT_ENABLE_REASONING}, max_tokens=${REALTIME_ALERT_MAX_TOKENS}
  Alert extensions: direct_media=${ALERT_DIRECT_MEDIA_ENABLED}, enrichment=${ALERT_ENRICHMENT_ENABLED}, always_on=${ALERT_ALWAYS_ON_ENABLED}, websocket=${ALERT_WEBSOCKET_ENABLED}
  Memory gates: model_start=${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_MODEL_START} GiB, stack_start=${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START} GiB
  Data ports: Kafka=${KAFKA_PORT}, Elasticsearch=${VSS_ES_PORT}, VA-MCP=${VSS_VA_MCP_PORT}, Kibana=${KIBANA_PORT}, Phoenix=${PHOENIX_HOST}:${PHOENIX_PORT}, Logstash API=127.0.0.1:${LOGSTASH_API_PORT}
  Observability ports: Prometheus=${PROMETHEUS_PORT}, Grafana=${GRAFANA_PORT}, node-exporter=${NODE_EXPORTER_PORT}, cAdvisor=${CADVISOR_PORT}, tegrastats=${TEGRASTATS_PORT}
  Runtime env: ${generated_env}
  Registry credentials: removed from runtime env and offline Compose process
EOF
  if [[ -f "${generated_env}" ]]; then
    if (require_runtime_env) >/dev/null 2>&1; then
      echo "  Runtime env status: valid (mode 0600)"
    else
      echo "  Runtime env status: stale or invalid (run refresh-runtime or a connected bootstrap)"
    fi
  else
    echo "  Runtime env status: not staged"
  fi
}

write_current_domain_pack() {
  local pack_id="$1"
  local current_dir current_tmp
  current_dir="$(dirname -- "${domain_pack_current_file}")"
  mkdir -p -- "${current_dir}"
  if [[ -e "${domain_pack_current_file}" ]]; then
    [[ "$(stat -c '%u' "${domain_pack_current_file}")" == "$(id -u)" ]] ||
      die "${domain_pack_current_file} must be owned by the current user"
    [[ "$(stat -c '%a' "${domain_pack_current_file}")" == "600" ]] ||
      die "${domain_pack_current_file} must have mode 0600"
  fi
  current_tmp="$(mktemp "${current_dir}/.domain-pack-current.XXXXXX")"
  chmod 600 "${current_tmp}"
  printf '%s\n' "${pack_id}" > "${current_tmp}"
  mv -f "${current_tmp}" "${domain_pack_current_file}"
}

domain_list() {
  require_command python3
  python3 "${domain_pack_tool}" validate >/dev/null
  while IFS=$'\t' read -r pack_id pack_name pack_description; do
    local marker=' '
    [[ "${pack_id}" == "${active_domain_pack_id}" ]] && marker='*'
    printf '%s %-20s %-28s %s\n' "${marker}" "${pack_id}" "${pack_name}" "${pack_description}"
  done < <(python3 "${domain_pack_tool}" list)
  printf '\n* current domain pack\n'
}

domain_show() {
  local pack_id="${1:-}"
  [[ -n "${pack_id}" ]] || die "Usage: thor-local.sh domain show <pack-id>"
  require_command python3
  python3 "${domain_pack_tool}" show "${pack_id}"
}

domain_current() {
  printf 'Current domain pack: %s\n\n' "${active_domain_pack_id}"
  python3 "${domain_pack_tool}" show "${active_domain_pack_id}"
  if [[ -f "${domain_pack_state}" ]]; then
    printf '\nManaged-rule state: %s (owner-only mode 0600)\n' "${domain_pack_state}"
  else
    printf '\nManaged-rule state: not initialized (apply a pack to initialize it)\n'
  fi
}

domain_apply() {
  local pack_id="${1:-}"
  [[ -n "${pack_id}" ]] || die "Usage: thor-local.sh domain apply <pack-id>"
  require_command docker
  require_command python3
  python3 "${domain_pack_tool}" validate >/dev/null

  [[ -f "${generated_env}" ]] || die "Missing ${generated_env}; start the Thor stack before applying a domain pack"
  [[ "$(stat -c '%a' "${generated_env}")" == "600" ]] || die "${generated_env} must have mode 0600"
  [[ "$(stat -c '%u' "${generated_env}")" == "$(id -u)" ]] || die "${generated_env} must be owned by the current user"

  local next_title next_subtitle old_title old_subtitle branding_changed=false
  next_title="$(python3 "${domain_pack_tool}" get "${pack_id}" title)"
  next_subtitle="$(python3 "${domain_pack_tool}" get "${pack_id}" subtitle)"
  old_title="$(runtime_env_value NEXT_PUBLIC_APP_TITLE)"
  old_subtitle="$(runtime_env_value NEXT_PUBLIC_APP_SUBTITLE)"
  if [[ "${next_title}" != "${old_title}" || "${next_subtitle}" != "${old_subtitle}" ]]; then
    branding_changed=true
  fi

  # Only the loopback Alert Bridge is contacted. The helper refuses any remote
  # URL and preserves conflicting operator-authored rules.
  python3 "${domain_pack_tool}" apply-rules "${pack_id}" \
    --api-url "http://127.0.0.1:${ALERT_BRIDGE_PORT}/api/v1" \
    --state "${domain_pack_state}"

  set_env_file_value "${generated_env}" NEXT_PUBLIC_APP_TITLE "${next_title}"
  set_env_file_value "${generated_env}" NEXT_PUBLIC_APP_SUBTITLE "${next_subtitle}"
  write_current_domain_pack "${pack_id}"
  active_domain_pack_id="${pack_id}"
  export NEXT_PUBLIC_APP_TITLE="${next_title}"
  export NEXT_PUBLIC_APP_SUBTITLE="${next_subtitle}"

  if [[ "${branding_changed}" == "true" ]] &&
     [[ "$(docker inspect --format '{{.State.Running}}' vss-agent-ui 2>/dev/null || true)" == "true" ]]; then
    echo "[INFO] Recreating only the UI container to load the new runtime branding..."
    compose up --detach --no-deps --force-recreate --pull never --no-build vss-ui
  elif [[ "${branding_changed}" == "true" ]]; then
    echo "[INFO] UI is stopped; the new branding will load on the next Thor-local start."
  else
    echo "[OK] Runtime branding already matches; no container was recreated."
  fi
  echo "[OK] Domain pack '${pack_id}' is active. Suggested demo questions and searches:"
  python3 "${domain_pack_tool}" show "${pack_id}"
}

domain_command() {
  local action="${1:-}"
  case "${action}" in
    list)
      domain_list
      ;;
    show)
      domain_show "${2:-}"
      ;;
    apply)
      domain_apply "${2:-}"
      ;;
    current)
      domain_current
      ;;
    *)
      die "Usage: thor-local.sh domain list|show <pack-id>|apply <pack-id>|current"
      ;;
  esac
}

stage_runtime_env() {
  [[ -f "${profile_generated_env}" ]] ||
    die "Bootstrap completed without producing ${profile_generated_env}"

  local runtime_dir runtime_tmp
  runtime_dir="$(dirname -- "${generated_env}")"
  mkdir -p "${runtime_dir}"
  runtime_tmp="$(mktemp "${runtime_dir}/.generated.env.tmp.XXXXXX")"
  chmod 600 "${runtime_tmp}"

  # Start from the generated profile so the complete upstream service contract
  # is retained, then overwrite the Thor-owned values below. This makes the
  # protected file deterministic even when profile tests have different
  # defaults. Registry keys are deliberately set to blank by the contract.
  awk '{ print }' "${profile_generated_env}" > "${runtime_tmp}"

  local key value
  while IFS='=' read -r key value; do
    set_env_file_value "${runtime_tmp}" "${key}" "${value}"
  done < <(print_runtime_contract)

  chmod 600 "${runtime_tmp}"
  mv -f "${runtime_tmp}" "${generated_env}"
  # The upstream generated file contains the bootstrap credential. The
  # protected copy above has already blanked it, so remove the transient source
  # immediately rather than leaving a second secret-bearing artifact behind.
  rm -f "${profile_generated_env}"
  write_image_lock_manifest
  echo "[OK] Protected Thor runtime environment refreshed at ${generated_env} (mode 0600; NGC credential removed)."
}

refresh_runtime_env() {
  [[ -f "${profile_env}" ]] || die "Missing Thor-full source environment: ${profile_env}"
  if [[ -e "${generated_env}" ]]; then
    [[ "$(stat -c '%a' "${generated_env}")" == "600" ]] || die "${generated_env} must have mode 0600"
    [[ "$(stat -c '%u' "${generated_env}")" == "$(id -u)" ]] || die "${generated_env} must be owned by the current user"
  fi

  local runtime_tmp key value
  mkdir -p "$(dirname -- "${generated_env}")"
  runtime_tmp="$(mktemp "$(dirname -- "${generated_env}")/.generated.env.tmp.XXXXXX")"
  chmod 600 "${runtime_tmp}"
  # Re-seed from the versioned thor-full source so a stale base runtime cannot
  # retain disabled tabs or blank Search/Alerts/LVS endpoints.
  awk '{ print }' "${profile_env}" > "${runtime_tmp}"
  while IFS='=' read -r key value; do
    set_env_file_value "${runtime_tmp}" "${key}" "${value}"
  done < <(print_runtime_contract)
  chmod 600 "${runtime_tmp}"
  mv -f "${runtime_tmp}" "${generated_env}"
  require_runtime_env
  if configured_images_are_present; then
    write_image_lock_manifest
  else
    echo "[WARNING] Runtime env refreshed, but its deterministic image lock is pending until a connected bootstrap stages every selected image."
  fi
  echo "[OK] Thor-full runtime environment generated without a registry login."
}

require_docker_cgroup_driver() {
  # NVIDIA VSS 3.2.1 Prerequisites > Configure Docker requires cgroupfs:
  # https://docs.nvidia.com/vss/3.2.1/prerequisites.html#configure-docker
  local cgroup_driver
  cgroup_driver="$(docker info --format '{{.CgroupDriver}}' 2>/dev/null)" ||
    die "Docker daemon is unavailable"
  [[ "${cgroup_driver}" == "cgroupfs" ]] ||
    die "Docker cgroup driver is '${cgroup_driver:-unknown}'; NVIDIA VSS edge deployment requires 'cgroupfs'. Merge 'native.cgroupdriver=cgroupfs' into /etc/docker/daemon.json and restart Docker, then retry."
}

preflight() {
  require_command curl
  require_command docker
  require_command nvidia-smi
  require_command pgrep
  require_command python3
  require_command sha256sum
  require_command ss

  validate_thor_full_contract

  [[ "$(uname -m)" == "aarch64" ]] || die "Thor-local requires aarch64; found $(uname -m)"
  grep -q "^# R38 " /etc/nv_tegra_release 2>/dev/null || die "Jetson Linux R38.x was not detected"
  nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | grep -qi thor || die "NVIDIA Thor GPU was not detected"
  docker info >/dev/null 2>&1 || die "Docker daemon is unavailable"
  require_docker_cgroup_driver
  [[ -x /usr/bin/tegrastats ]] || die "Jetson tegrastats is missing or not executable: /usr/bin/tegrastats"
  [[ -x /lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 ]] || die "Jetson AArch64 runtime loader is missing"
  [[ -r /lib/aarch64-linux-gnu/libc.so.6 && -r /lib/aarch64-linux-gnu/libm.so.6 ]] ||
    die "Jetson tegrastats runtime libraries are missing"
  /lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 \
    --library-path /lib/aarch64-linux-gnu \
    /usr/bin/tegrastats --help 2>&1 | grep -q '^Usage: tegrastats' ||
    die "Jetson tegrastats does not execute with its mounted host runtime"

  if ! "${script_dir}/dev-profile.sh" check-kernel-settings; then
    die "Required kernel settings are incomplete. Run '${script_dir}/thor-local.sh kernel-settings' once, then retry."
  fi
  require_edge_cache_cleaner

  if official_edge_demo_lane_is_deployed; then
    require_official_edge_demo_models
  else
    model_is_served "${LLM_ENDPOINT_URL}" "${THOR_LOCAL_LLM_MODEL}" ||
      die "LLM ${THOR_LOCAL_LLM_MODEL} is not available at ${LLM_ENDPOINT_URL}/v1/models"
    model_is_served "${VLM_ENDPOINT_URL}" "${THOR_LOCAL_VLM_MODEL}" ||
      die "VLM ${THOR_LOCAL_VLM_MODEL} is not available at ${VLM_ENDPOINT_URL}/v1/models"
  fi
  # Discovery alone is insufficient: image-only caption/query servers can
  # advertise a model but cannot run the multi-frame VSS workflows.
  check_local_model_contracts

  require_available_port "${VSS_AGENT_PORT}" vss-agent
  require_available_port "${VSS_UI_PORT}" vss-agent-ui
  require_available_port "${HAPROXY_PORT}" vss-haproxy-ingress
  require_available_port "${VST_PORT}" vss-vios-ingress
  require_available_port "${VST_MCP_PORT}" vss-vios-mcp
  require_available_port "${SENSOR_HTTP_PORT}" vss-vios-sensor
  require_available_port "${STREAM_PROCESSOR_HTTP_PORT}" vss-vios-streamprocessing
  require_available_port "${SDR_STREAMPROCESSING_PORT}" vss-vios-sdr
  require_available_port "${RTVI_EMBED_PORT}" vss-rtvi-embed
  require_available_port "${RTVI_VLM_PORT}" vss-rtvi-vlm
  require_available_port "${RTVI_CV_PORT}" vss-rtvi-cv
  require_available_port "${VIDEO_ANALYTICS_API_PORT}" vss-video-analytics-api
  if [[ "${smartcity_profile_enabled}" == "true" ]]; then
    require_available_port "${SMARTCITY_MAP_PORT}" vss-smartcity-map-thor
  fi
  require_available_port "${ALERT_BRIDGE_PORT}" vss-alert-bridge
  require_available_port "${KAFKA_PORT}" kafka
  require_available_port "${VSS_ES_PORT}" elasticsearch
  require_available_port "${VSS_VA_MCP_PORT}" vss-va-mcp
  require_available_port "${BACKEND_PORT}" vss-lvs
  if [[ "${LVS_ENABLE_MCP}" == "true" ]]; then
    require_available_port "${LVS_MCP_PORT}" vss-lvs
  fi
  if [[ "${THOR_FULL_ENABLE_KIBANA}" == "true" ]]; then
    require_available_port "${KIBANA_PORT}" kibana
  fi
  require_available_port "${PHOENIX_PORT}" phoenix
  require_available_port "${LOGSTASH_API_PORT}" logstash
  require_available_port "${PROMETHEUS_PORT}" prometheus
  require_available_port "${GRAFANA_PORT}" grafana
  require_available_port "${NODE_EXPORTER_PORT}" node-exporter
  require_available_port "${CADVISOR_PORT}" cadvisor
  require_available_port "${TEGRASTATS_PORT}" tegrastats-exporter

  local free_gb
  free_gb="$(df -Pk "${deployment_dir}" | awk 'NR==2 {print int($4/1024/1024)}')"
  if (( free_gb < 150 )); then
    echo "[WARNING] Only ${free_gb} GiB is free. Base qualification may fit, but the full staged VSS image/model set will not."
  fi

  echo "[OK] AGX Thor platform and local model endpoints are ready."
  echo "[OK] Planned core ports: UI=${VSS_UI_PORT}, agent=${VSS_AGENT_PORT}, ingress=${HAPROXY_PORT}, VIOS=${VST_PORT}/${SENSOR_HTTP_PORT}/${STREAM_PROCESSOR_HTTP_PORT}, SDR=${SDR_STREAMPROCESSING_PORT}, VIOS-MCP=${VST_MCP_PORT}."
  echo "[OK] Planned intelligence ports: embed=${RTVI_EMBED_PORT}, RTVI-VLM=${RTVI_VLM_PORT}, perception=${RTVI_CV_PORT}, analytics=${VIDEO_ANALYTICS_API_PORT}, alerts=${ALERT_BRIDGE_PORT}, VA-MCP=${VSS_VA_MCP_PORT}, LVS=${BACKEND_PORT}."
  echo "[OK] Planned data ports: Kafka=${KAFKA_PORT}, Elasticsearch=${VSS_ES_PORT}, Kibana=${KIBANA_PORT} (enabled=${THOR_FULL_ENABLE_KIBANA}), Phoenix=${PHOENIX_HOST}:${PHOENIX_PORT}, Logstash API=127.0.0.1:${LOGSTASH_API_PORT}."
  echo "[OK] Planned observability ports: Prometheus=${PROMETHEUS_PORT}, Grafana=${GRAFANA_PORT}, node-exporter=${NODE_EXPORTER_PORT}, cAdvisor=${CADVISOR_PORT} on loopback; tegrastats=${TEGRASTATS_BIND_ADDRESS}:${TEGRASTATS_PORT} on Docker's private gateway."
  echo "[OK] VLM frame request limit: ${VLM_MAX_FRAMES_PER_REQUEST}."
}

compose() {
  # Shell variables take precedence over --env-file in Compose interpolation.
  # Explicitly remove registry credentials so even an inherited interactive
  # shell cannot inject them during an offline lifecycle command.
  require_runtime_env
  env -u NGC_CLI_API_KEY -u NGC_API_KEY -u NVIDIA_API_KEY -u HF_TOKEN \
    -u RTVI_VLM_API_KEY -u VIA_VLM_API_KEY \
    docker compose --env-file "${generated_env}" "$@"
}

configured_images_are_present() {
  local image configured_images
  configured_images="$(compose config --images)" || return 1
  [[ -n "${configured_images//[[:space:]]/}" ]] || return 1
  while IFS= read -r image; do
    [[ -n "${image}" ]] || continue
    docker image inspect "${image}" >/dev/null 2>&1 || return 1
  done < <(sort -u <<< "${configured_images}")
}

write_image_lock_manifest() {
  local tmp image image_id configured_images
  configured_images_are_present || die "Cannot write the offline image lock until every selected image is staged"
  configured_images="$(compose config --images)" || die "Cannot resolve selected images for the offline image lock"
  [[ -n "${configured_images//[[:space:]]/}" ]] || die "Cannot write a vacuous offline image lock"
  tmp="$(mktemp "$(dirname -- "${generated_env}")/.image-lock.XXXXXX")"
  chmod 600 "${tmp}"
  awk '$1 != "#" || $2 != "THOR_LOCAL_IMAGE_LOCK" { print }' "${generated_env}" > "${tmp}"
  while IFS= read -r image; do
    [[ -n "${image}" ]] || continue
    image_id="$(docker image inspect --format '{{.Id}}' "${image}")"
    printf '# THOR_LOCAL_IMAGE_LOCK %s %s\n' "${image}" "${image_id}" >> "${tmp}"
  done < <(sort -u <<< "${configured_images}")
  chmod 600 "${tmp}"
  mv -f "${tmp}" "${generated_env}"
  echo "[OK] Content-addressed image lock recorded in the protected runtime environment."
}

require_staged_images() {
  local missing=0 lock_count=0
  local image expected_id actual_id configured_images
  local -A locked_ids=()
  while read -r _marker _lock_marker image expected_id; do
    [[ "${_marker}" == "#" && "${_lock_marker}" == "THOR_LOCAL_IMAGE_LOCK" ]] || continue
    locked_ids["${image}"]="${expected_id}"
    ((lock_count++)) || true
  done < "${generated_env}"

  if (( lock_count == 0 )); then
    die "Protected runtime environment has no deterministic image lock; run 'thor-local.sh refresh-runtime' with the staged images present"
  fi

  configured_images="$(compose config --images)" || die "Cannot resolve the selected offline image set"
  [[ -n "${configured_images//[[:space:]]/}" ]] || die "Selected offline image set is empty"

  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue
    if ! docker image inspect "${image}" >/dev/null 2>&1; then
      echo "[ERROR] Offline image is not staged: ${image}" >&2
      missing=1
      continue
    fi
    expected_id="${locked_ids[${image}]:-}"
    actual_id="$(docker image inspect --format '{{.Id}}' "${image}")"
    if [[ -z "${expected_id}" ]]; then
      echo "[ERROR] Offline image has no protected image lock: ${image}" >&2
      missing=1
    elif [[ "${actual_id}" != "${expected_id}" ]]; then
      echo "[ERROR] Offline image changed since staging: ${image}" >&2
      missing=1
    fi
  done < <(sort -u <<< "${configured_images}")
  (( missing == 0 )) || die "Restage or explicitly refresh the deterministic image lock before offline restart"
  echo "[OK] Every selected image matches its protected content-addressed lock."
}

print_required_host_assets() {
  printf '%s\n' \
    "${data_directory}/models/rtdetr-its/model_epoch_035.fp16.onnx" \
    "${data_directory}/models/gdino/mgdino_mask_head_pruned_dynamic_batch.onnx" \
    "${data_directory}/models/rtdetr_warehouse_v1.0.2.fp16.onnx" \
    "${data_directory}/models/siglip_v2_v1.1.onnx" \
    "${data_directory}/models/siglip_v2_v1.1_weights.bin" \
    "${data_directory}/models/siglip_v2_v1.1_tokenizer" \
    "${data_directory}/models/siglip2_v1.1_weights.bin" \
    "${data_directory}/models/.siglip_v2_v1.1.done"
}

# These versions are already pinned by the Thor-full profile's NGC resource
# coordinates. Pinning their content as well catches partial writes, poisoned
# marker files, and an unexpected upstream artifact replacement before an
# offline start. TensorRT engines are host-generated, so they are validated by
# path and minimum size rather than a non-portable digest.
print_required_host_asset_checksums() {
  cat <<'EOF'
545a447b913d54eee476381436ebea4ad2aa876cfbe0a6d9f3b0302f08a7415d  rtdetr-its/model_epoch_035.fp16.onnx
46331941ef96b9045687b523c044a92a8597ed8cca45ba026037dbf1e9e9dfca  gdino/mgdino_mask_head_pruned_dynamic_batch.onnx
0a22264542514149bead6e8582499d9758d51e3fde2892d9d2cc378a60426267  rtdetr_warehouse_v1.0.2.fp16.onnx
425134cfd151d19e15da5cddb2a90d557991964c251f99d874e5f5f7a39a3927  siglip_v2_v1.1.onnx
e3dca7562d65a3b97a61ce7d0575d1c64b9248d8d48273ff4eadb666e78cccf3  siglip_v2_v1.1_weights.bin
ecd6ae513fe103f0eb62e8ab5bfa8d0fe45c1074fa398b089c93a7e70c15cfd6  siglip_v2_v1.1_tokenizer/chat_template.jinja
baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351  siglip_v2_v1.1_tokenizer/special_tokens_map.json
1de36bea24b2b16b25cc27a4b5ea9c86e2e2ecc3c018cb7d5338f0030d84e4bb  siglip_v2_v1.1_tokenizer/tokenizer.json
61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2  siglip_v2_v1.1_tokenizer/tokenizer.model
b8da4388ad2e2cd6d3493ecd75cc703be6b88dabc9fbf1c4681f267a36c28b60  siglip_v2_v1.1_tokenizer/tokenizer_config.json
EOF
}

staged_host_asset_checksums_are_valid() {
  local expected relative actual
  while read -r expected relative; do
    [[ -n "${expected}" && -n "${relative}" ]] || return 1
    [[ -f "${data_directory}/models/${relative}" ]] || return 1
    actual="$(sha256sum "${data_directory}/models/${relative}" | awk '{print $1}')" || return 1
    [[ "${actual}" == "${expected}" ]] || return 1
  done < <(print_required_host_asset_checksums)
}

staged_host_assets_are_present() {
  local asset
  while IFS= read -r asset; do
    [[ -e "${asset}" ]] || return 1
  done < <(print_required_host_assets)
  # A path-only check accepted the tiny mock files used by failure tests. Real
  # ONNX models are many megabytes; reject truncated, placeholder, or poisoned
  # artifacts before starting any offline workload.
  local model
  for model in \
    "${data_directory}/models/rtdetr-its/model_epoch_035.fp16.onnx" \
    "${data_directory}/models/gdino/mgdino_mask_head_pruned_dynamic_batch.onnx" \
    "${data_directory}/models/rtdetr_warehouse_v1.0.2.fp16.onnx" \
    "${data_directory}/models/siglip_v2_v1.1.onnx"; do
    [[ -f "${model}" && "$(stat -c '%s' "${model}")" -ge 1048576 ]] || return 1
  done
  [[ -f "${data_directory}/models/siglip_v2_v1.1_weights.bin" ]] || return 1
  [[ "$(stat -c '%s' "${data_directory}/models/siglip_v2_v1.1_weights.bin")" -gt 4000000000 ]] || return 1
  [[ -L "${data_directory}/models/siglip2_v1.1_weights.bin" ]] || return 1
  [[ "$(readlink "${data_directory}/models/siglip2_v1.1_weights.bin")" == "siglip_v2_v1.1_weights.bin" ]] || return 1
  find "${data_directory}/models/siglip_v2_v1.1_tokenizer" -type f -size +0c -print -quit 2>/dev/null | grep -q . || return 1
}

require_staged_assets() {
  local missing=0
  local asset
  while IFS= read -r asset; do
    if [[ ! -e "${asset}" ]]; then
      echo "[ERROR] Offline asset is not staged: ${asset}" >&2
      missing=1
    fi
  done < <(print_required_host_assets)
  if (( missing == 0 )) && ! staged_host_assets_are_present; then
    echo "[ERROR] One or more staged model assets are truncated, empty, or invalid." >&2
    missing=1
  fi
  (( missing == 0 )) || die "Stage the missing model assets with 'thor-local.sh up' while connected"
}

require_host_asset_checksums() {
  if ! staged_host_asset_checksums_are_valid; then
    die "One or more pinned host model checksums differ from the Thor-full artifact contract; restage while connected"
  fi
  echo "[OK] Pinned host model checksums match."
}

embedding_cache_contract() {
  compose config --format json | python3 -c '
import json, sys
config = json.load(sys.stdin)
volumes = config["volumes"]
service = config["services"]["rtvi-embed"]
print(volumes["rtvi-ngc-model-cache"]["name"])
print(volumes["rtvi-triton-model-repo"]["name"])
print(service["image"])
print(service["build"]["args"]["BASE_IMAGE"])
print(service["environment"]["MODEL_PATH"])
'
}

stream_embedding_volume_tree() {
  local volume="$1"
  local archive_root="$2"
  local image="$3"

  # Verification must also work immediately after `compose down`, when only
  # the named volumes and locked image remain. Use a disposable, networkless,
  # read-only helper and disable volume copy-up so neither source volume can be
  # modified while its exact subtree is streamed to the host verifier. Disable
  # Docker's container log driver: the attached stdout stream still feeds the
  # verifier, while the multi-gigabyte tar stream is not duplicated into a
  # json-file container log and cannot exhaust the host filesystem.
  docker run --rm --pull never --network none --read-only --log-driver none \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --entrypoint /bin/tar \
    --mount "type=volume,src=${volume},dst=/artifact,readonly,volume-nocopy" \
    "${image}" -C /artifact -cf - "${archive_root}"
}

staged_embedding_cache_is_present() {
  local ngc_volume triton_volume embed_image provenance_image source_spec
  local ngc_root triton_root ngc_path triton_path
  local -a cache_contract=()
  mapfile -t cache_contract < <(embedding_cache_contract) || return 1
  (( ${#cache_contract[@]} == 5 )) || return 1
  ngc_volume="${cache_contract[0]}"
  triton_volume="${cache_contract[1]}"
  embed_image="${cache_contract[2]}"
  provenance_image="${cache_contract[3]}"
  source_spec="${cache_contract[4]}"
  ngc_root="Cosmos-Embed1-448p-anomaly-detection"
  triton_root="cosmos-embed1-448p-anomaly-detection"
  ngc_path="/opt/nvidia/rtvi/.rtvi/ngc_model_cache/${ngc_root}"
  triton_path="/tmp/triton_model_repo/${triton_root}"

  [[ -r "${model_artifact_verifier}" && -r "${model_artifact_lock}" ]] || return 1
  docker volume inspect "${ngc_volume}" "${triton_volume}" >/dev/null 2>&1 || return 1
  docker image inspect "${embed_image}" >/dev/null 2>&1 || return 1

  stream_embedding_volume_tree "${ngc_volume}" "${ngc_root}" "${embed_image}" |
    python3 "${model_artifact_verifier}" verify-tar \
      --lock "${model_artifact_lock}" \
      --artifact cosmos_embed_model \
      --source-spec "${source_spec}" \
      --image "${provenance_image}" \
      --container-path "${ngc_path}" \
      --batch-size "${RTVI_EMBED_BATCH_SIZE}" || return 1
  stream_embedding_volume_tree "${triton_volume}" "${triton_root}" "${embed_image}" |
    python3 "${model_artifact_verifier}" verify-tar \
      --lock "${model_artifact_lock}" \
      --artifact cosmos_embed_triton \
      --source-spec "${source_spec}" \
      --image "${provenance_image}" \
      --container-path "${triton_path}" \
      --batch-size "${RTVI_EMBED_BATCH_SIZE}" || return 1
}

require_staged_embedding_cache() {
  if ! staged_embedding_cache_is_present; then
    die "Cosmos-Embed model or Thor batch-${RTVI_EMBED_BATCH_SIZE} Triton repository differs from the exact reviewed artifact lock; restage and review while connected"
  fi
  echo "[OK] Exact Cosmos-Embed model and Thor batch-${RTVI_EMBED_BATCH_SIZE} Triton repository are staged."
}

require_staged_local_models() {
  [[ -x "${local_model_provisioner}" ]] ||
    die "Missing executable local model verifier: ${local_model_provisioner}"
  "${local_model_provisioner}" status
  echo "[OK] Pinned local model image, snapshots, and container contracts are staged."
}

verify_offline_stage() {
  require_runtime_env
  require_staged_images
  require_staged_assets
  require_host_asset_checksums
  require_staged_embedding_cache
  require_staged_local_models
  echo "[OK] Offline stage is complete; restart needs no image pull, build, NGC key, or model download."
}

offline_stage_is_complete() {
  (verify_offline_stage) >/dev/null 2>&1
}

assert_no_registry_credentials_in_containers() {
  local container_id container_name exposed=0
  while IFS= read -r container_id; do
    [[ -n "${container_id}" ]] || continue
    container_name="$(docker inspect --format '{{.Name}}' "${container_id}" | sed 's|^/||')"
    if docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${container_id}" |
      python3 -c '
import sys
sensitive = {"NGC_CLI_API_KEY", "NGC_API_KEY", "RTVI_VLM_API_KEY", "VIA_VLM_API_KEY", "HF_TOKEN"}
for line in sys.stdin:
    key, separator, value = line.rstrip("\n").partition("=")
    if separator and key in sensitive and value.strip("\"\x27"):
        raise SystemExit(1)
'; then
      continue
    fi
    echo "[ERROR] ${container_name} retains a non-empty registry/model-download credential in Docker configuration." >&2
    exposed=1
  done < <(compose ps --all --quiet)
  (( exposed == 0 )) || die "Refusing to leave credential-bearing Thor VSS containers on disk"
  echo "[OK] Selected Docker container configurations contain no registry/model-download credentials."
}

endpoint_port() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit

parsed = urlsplit(sys.argv[1])
if parsed.port is not None:
    print(parsed.port)
elif parsed.scheme == "https":
    print(443)
else:
    print(80)
PY
}

security_internal_ports() {
  # Host-network NVIDIA services intentionally share localhost. Some released
  # binaries cannot select a bind address, so interface-scoped filtering is
  # safer than rewriting their inter-service topology. Ports 3000 and 8000 are
  # included because Docker DNAT exposes those container targets in FORWARD.
  printf '%s\n' \
    80 1935 3000 "${VSS_UI_PORT}" 4000 5201 "${PHOENIX_PORT}" 6379 \
    "$(endpoint_port "${LLM_ENDPOINT_URL}")" \
    "$(endpoint_port "${VLM_ENDPOINT_URL}")" \
    8000 "${RTVI_EMBED_PORT}" "${RTVI_VLM_PORT}" "${VIDEO_ANALYTICS_API_PORT}" "${SMARTCITY_MAP_PORT}" \
    "${VSS_AGENT_PORT}" 8554 8787 8888 8889 8892 "${RTVI_CV_PORT}" \
    "${ALERT_BRIDGE_PORT}" "${KAFKA_PORT}" "${VSS_ES_PORT}" 9300 "${KIBANA_PORT}" "${LOGSTASH_API_PORT}" \
    "${VSS_VA_MCP_PORT}" "${SENSOR_HTTP_PORT}" "${STREAM_PROCESSOR_HTTP_PORT}" "${SDR_STREAMPROCESSING_PORT}" \
    30554 30555 30556 30557 30558 30559 30560 30561 30562 30563 30564 \
    "${VST_PORT}" "${VST_MCP_PORT}" "${BACKEND_PORT}" "${LVS_MCP_PORT}" \
    "${PROMETHEUS_PORT}" "${GRAFANA_PORT}" "${NODE_EXPORTER_PORT}" "${CADVISOR_PORT}" "${TEGRASTATS_PORT}" | sort -n -u
}

listener_scope() {
  local port="$1"
  ss -H -ltn "sport = :${port}" 2>/dev/null | awk '
    BEGIN { found=0; exposed=0 }
    {
      found=1
      address=$4
      sub(/:[^:]*$/, "", address)
      gsub(/^\[/, "", address)
      gsub(/\]$/, "", address)
      if (address != "127.0.0.1" && address != "::1" && address != "localhost") {
        exposed=1
      }
    }
    END {
      if (!found) print "down"
      else if (exposed) print "exposed"
      else print "loopback"
    }
  '
}

security_default_interfaces() {
  local interface
  while IFS= read -r interface; do
    [[ -n "${interface}" && -e "/sys/class/net/${interface}" ]] || continue
    [[ "${interface}" != "lo" && "${interface}" != docker* && "${interface}" != br-* && "${interface}" != veth* ]] || continue
    [[ ! -e "/sys/class/net/${interface}/bridge" ]] || continue
    [[ "$(cat "/sys/class/net/${interface}/operstate" 2>/dev/null || true)" != "down" ]] || continue
    printf '%s\n' "${interface}"
  done < <(
    ip route show default 2>/dev/null |
      awk '{for (i=1; i<=NF; i++) if ($i == "dev") print $(i+1)}' |
      sort -u
  )
}

security_firewall_is_active() {
  command -v nft >/dev/null 2>&1 || return 1
  if [[ "$(id -u)" == "0" ]]; then
    nft list table inet cti_vss >/dev/null 2>&1
  else
    sudo -n nft list table inet cti_vss >/dev/null 2>&1
  fi
}

security_validate_interfaces() {
  (( $# > 0 )) || die "Specify at least one physical ingress interface (for example: $(security_default_interfaces | paste -sd' ' -))"
  local interface
  for interface in "$@"; do
    [[ "${interface}" =~ ^[A-Za-z0-9_.:-]+$ ]] || die "Invalid interface name: ${interface}"
    [[ -e "/sys/class/net/${interface}" ]] || die "Network interface does not exist: ${interface}"
    [[ "${interface}" != "lo" && "${interface}" != docker* && "${interface}" != br-* && "${interface}" != veth* && ! -e "/sys/class/net/${interface}/bridge" ]] ||
      die "Refusing to filter loopback or a container bridge: ${interface}"
  done
}

security_firewall_ruleset() {
  security_validate_interfaces "$@"
  local interface interface_set="" ports
  for interface in "$@"; do
    [[ -z "${interface_set}" ]] || interface_set+=", "
    interface_set+="\"${interface}\""
  done
  ports="$(security_internal_ports | paste -sd, -)"
  cat <<EOF
table inet cti_vss {
  chain input {
    type filter hook input priority -10; policy accept;
    iifname { ${interface_set} } tcp dport { ${ports} } counter drop comment "cti-vss internal host ports"
  }
  chain forward {
    type filter hook forward priority -10; policy accept;
    iifname { ${interface_set} } tcp dport { ${ports} } counter drop comment "cti-vss internal container ports"
  }
}
EOF
}

security_audit() {
  require_command ss
  require_command python3
  validate_thor_full_contract
  local failures=0 exposed=0 scope port ingress_scope
  printf 'Thor VSS security audit (read-only; no external network calls)\n\n'

  if [[ -f "${generated_env}" ]] && (require_runtime_env) >/dev/null 2>&1; then
    echo "[PASS] Protected runtime contract is current-user owned, mode 0600, and credential-blank."
  else
    echo "[FAIL] Protected runtime contract is absent, stale, or insecure."
    failures=1
  fi
  if [[ -f "${generated_env}" ]] && (assert_no_registry_credentials_in_containers) >/dev/null 2>&1; then
    echo "[PASS] Selected container metadata contains no registry/model-download credentials."
  else
    echo "[FAIL] Container credential audit could not pass."
    failures=1
  fi

  ingress_scope="$(listener_scope "${HAPROXY_PORT}")"
  if [[ "${ingress_scope}" == "loopback" ]]; then
    echo "[PASS] Supported operator ingress ${HAPROXY_PORT}/tcp is loopback-only."
  elif [[ "${ingress_scope}" == "down" ]]; then
    echo "[INFO] Supported operator ingress ${HAPROXY_PORT}/tcp is not listening."
  else
    echo "[FAIL] Supported operator ingress ${HAPROXY_PORT}/tcp is reachable beyond loopback."
    failures=1
  fi

  while IFS= read -r port; do
    scope="$(listener_scope "${port}")"
    if [[ "${scope}" == "exposed" ]]; then
      ((exposed += 1))
    fi
  done < <(security_internal_ports)

  if (( exposed == 0 )); then
    echo "[PASS] No known VSS internal TCP listener is reachable beyond loopback."
  elif security_firewall_is_active; then
    echo "[PASS] ${exposed} internal TCP listener(s) bind beyond loopback, with the cti_vss physical-interface filter active."
  else
    echo "[WARN] ${exposed} internal TCP listener(s) bind beyond loopback and the cti_vss filter is not confirmed active."
    echo "       Review: ${script_dir}/thor-local.sh security firewall-plan $(security_default_interfaces | paste -sd' ' -)"
  fi

  echo
  echo "LAN policy: the supported UI/API is 127.0.0.1:${HAPROXY_PORT}. Use an SSH tunnel for a remote operator."
  echo "The firewall rule blocks only named physical interfaces; loopback and Docker bridges remain usable."
  (( failures == 0 ))
}

security_command() {
  local action="${1:-audit}"
  shift || true
  case "${action}" in
    audit)
      (( $# == 0 )) || die "security audit accepts no additional arguments"
      security_audit
      ;;
    firewall-plan)
      security_firewall_ruleset "$@"
      ;;
    firewall-apply)
      [[ "${THOR_LOCAL_CONFIRM_FIREWALL:-}" == "yes" ]] ||
        die "Set THOR_LOCAL_CONFIRM_FIREWALL=yes after reviewing 'security firewall-plan'. This rule is volatile and must be reapplied after reboot."
      security_validate_interfaces "$@"
      require_command nft
      sudo -v
      sudo nft list table inet cti_vss >/dev/null 2>&1 && sudo nft delete table inet cti_vss || true
      security_firewall_ruleset "$@" | sudo nft -f -
      # Fail safe when the application is already running: prove both host
      # loopback and the RTVI container-to-host VLM path, then roll back this
      # table automatically if either side of the single-node graph broke.
      if [[ -f "${generated_env}" ]] &&
         [[ -n "$(doctor_compose ps --status running --quiet 2>/dev/null || true)" ]] &&
         ! (stack_container_states_are_ready && critical_http_endpoints_are_ready); then
        sudo nft delete table inet cti_vss >/dev/null 2>&1 || true
        die "Firewall readiness check failed; the cti_vss table was rolled back automatically"
      fi
      echo "[OK] cti_vss now blocks internal VSS TCP ports on: $*."
      echo "[OK] Loopback, Docker bridges, outbound RTSP, and SSH are unchanged."
      ;;
    firewall-status)
      (( $# == 0 )) || die "security firewall-status accepts no additional arguments"
      require_command nft
      sudo nft list table inet cti_vss
      ;;
    firewall-remove)
      (( $# == 0 )) || die "security firewall-remove accepts no additional arguments"
      require_command nft
      sudo nft delete table inet cti_vss
      echo "[OK] Removed only the cti_vss nftables table."
      ;;
    *)
      die "Unknown security action '${action}'; use audit, firewall-plan, firewall-apply, firewall-status, or firewall-remove"
      ;;
  esac
}

replay_persisted_alert_rules() {
  local response_file http_status
  response_file="$(mktemp "${TMPDIR:-/tmp}/thor-alert-replay.XXXXXX")"
  http_status="$(curl --connect-timeout 5 --max-time 300 --silent --show-error \
    --output "${response_file}" --write-out '%{http_code}' \
    --request POST \
    "http://127.0.0.1:${ALERT_BRIDGE_PORT}/api/v1/realtime/replay")" || {
      rm -f -- "${response_file}"
      die "Failed to replay persisted alert rules after recreating RTVI-VLM"
    }
  if [[ "${http_status}" != "200" ]]; then
    sed 's/^/[ALERT-REPLAY] /' "${response_file}" >&2 || true
    rm -f -- "${response_file}"
    die "Alert replay returned HTTP ${http_status} after recreating RTVI-VLM"
  fi
  if ! python3 - "${response_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    response = json.load(stream)
failed = int(response.get("failed", 0))
if response.get("status") != "success" or failed:
    print(json.dumps(response, indent=2), file=sys.stderr)
    raise SystemExit(1)
print(
    "[OK] Persisted alert rules restored after RTVI recreation "
    f"(replayed={int(response.get('replayed', 0))}, total={int(response.get('total', 0))})."
)
PY
  then
    rm -f -- "${response_file}"
    die "One or more persisted alert rules failed to restore after RTVI recreation"
  fi
  rm -f -- "${response_file}"
}

start_offline_stack() {
  if ! expected_container_running vss-agent; then
    require_memory_headroom "starting the Thor VSS stack" \
      "${THOR_LOCAL_MIN_MEMORY_GB_BEFORE_STACK_START}"
  fi
  ensure_operator_runtime_directories
  compose up --detach --pull never --no-build --force-recreate
  assert_no_registry_credentials_in_containers
  wait_for_stack_ready
  replay_persisted_alert_rules
}

container_is_healthy() {
  local container_name="$1"
  [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_name}" 2>/dev/null || true)" == "healthy" ]]
}

wait_for_connected_staging() {
  local deadline=$((SECONDS + THOR_FULL_STAGE_TIMEOUT_SECONDS))
  echo "[INFO] Waiting for host model assets and RTVI model caches to finish staging..."
  while (( SECONDS < deadline )); do
    if staged_host_assets_are_present && container_is_healthy vss-rtvi-embed && container_is_healthy vss-rtvi-vlm; then
      echo "[OK] Host model assets and RTVI model caches are staged for offline restart."
      return 0
    fi
    sleep 5
  done
  require_staged_assets || true
  docker inspect --format '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    vss-rtvi-embed vss-rtvi-vlm 2>/dev/null || true
  die "Connected staging did not complete within ${THOR_FULL_STAGE_TIMEOUT_SECONDS} seconds"
}

stack_container_states_are_ready() {
  local expected_count actual_count service container_id state exit_code health
  local pending=0
  expected_count="$(compose config --services | sed '/^[[:space:]]*$/d' | wc -l)"
  actual_count="$(compose ps --all --quiet | sed '/^[[:space:]]*$/d' | wc -l)"
  if (( expected_count <= 0 || actual_count < expected_count )); then
    echo "[WAIT] Compose containers: expected=${expected_count}, present=${actual_count}."
    return 1
  fi

  while IFS= read -r service; do
    [[ -z "${service}" ]] && continue
    container_id="$(compose ps --all --quiet "${service}" | head -n 1)"
    if [[ -z "${container_id}" ]]; then
      echo "[WAIT] ${service}: container is absent."
      pending=1
      continue
    fi
    read -r state exit_code health < <(
      docker inspect --format '{{.State.Status}} {{.State.ExitCode}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_id}"
    )
    if [[ "${state}" == "running" && ( "${health}" == "healthy" || "${health}" == "none" ) ]]; then
      continue
    fi
    if [[ "${state}" == "exited" && "${exit_code}" == "0" ]]; then
      continue
    fi
    echo "[WAIT] ${service}: state=${state}, exit=${exit_code}, health=${health}."
    pending=1
  done < <(compose config --services)

  (( pending == 0 ))
}

rtvi_vlm_upstream_is_ready() {
  docker exec vss-rtvi-vlm \
    curl --connect-timeout 2 --max-time 5 --fail --silent \
      "${VLM_CONTAINER_ENDPOINT_URL%/}/v1/models" 2>/dev/null |
    python3 -c 'import json,sys; expected=sys.argv[1]; data=json.load(sys.stdin).get("data", []); sys.exit(0 if expected in {item.get("id") for item in data} else 1)' \
      "${THOR_LOCAL_VLM_MODEL}"
}

critical_http_endpoints_are_ready() {
  local item name url pending=0
  for item in \
    "agent|http://127.0.0.1:${VSS_AGENT_PORT}/health" \
    "operator-ui|http://127.0.0.1:${VSS_UI_PORT}/" \
    "video-analytics-mcp|http://127.0.0.1:${VSS_VA_MCP_PORT}/health" \
    "video-summarization|http://127.0.0.1:${BACKEND_PORT}/v1/ready" \
    "vios-sdr|http://127.0.0.1:${SDR_STREAMPROCESSING_PORT}/healthz" \
    "rtvi-embed|http://127.0.0.1:${RTVI_EMBED_PORT}/v1/ready" \
    "rtvi-vlm|http://127.0.0.1:${RTVI_VLM_PORT}/v1/health/ready" \
    "deepstream-perception|http://127.0.0.1:${RTVI_CV_PORT}/api/v1/health/get-dsready-state"; do
    name="${item%%|*}"
    url="${item#*|}"
    if ! curl --connect-timeout 2 --max-time 5 --fail --silent "${url}" >/dev/null; then
      echo "[WAIT] ${name}: ${url} is not ready."
      pending=1
    fi
  done
  local vios_mcp_status
  vios_mcp_status="$(curl --connect-timeout 2 --max-time 5 --silent --output /dev/null --write-out '%{http_code}' \
    -H 'Accept: application/json' "${VIOS_MCP_ENDPOINT}" 2>/dev/null || true)"
  if [[ "${vios_mcp_status}" != "200" && "${vios_mcp_status}" != "400" && "${vios_mcp_status}" != "406" ]]; then
    echo "[WAIT] VIOS MCP: ${VIOS_MCP_ENDPOINT} is not ready (HTTP ${vios_mcp_status:-connection-failed})."
    pending=1
  fi
  if ! rtvi_vlm_upstream_is_ready; then
    echo "[WAIT] rtvi-vlm upstream: ${VLM_CONTAINER_ENDPOINT_URL%/}/v1/models is not reachable from the proxy container."
    pending=1
  fi
  if [[ "${smartcity_profile_enabled}" == "true" ]] &&
     ! curl --connect-timeout 2 --max-time 5 --fail --silent "http://127.0.0.1:${SMARTCITY_MAP_PORT}/" >/dev/null; then
    echo "[WAIT] Smart City map: http://127.0.0.1:${SMARTCITY_MAP_PORT}/ is not ready."
    pending=1
  fi
  (( pending == 0 ))
}

wait_for_stack_ready() {
  local expected_count deadline=$((SECONDS + THOR_FULL_READINESS_TIMEOUT_SECONDS))
  expected_count="$(compose config --services | sed '/^[[:space:]]*$/d' | wc -l)"
  echo "[INFO] Waiting for the complete ${expected_count}-service Thor VSS readiness contract..."
  while (( SECONDS < deadline )); do
    if stack_container_states_are_ready && critical_http_endpoints_are_ready; then
      echo "[OK] Every selected container and critical HTTP endpoint is ready."
      return 0
    fi
    sleep 10
  done
  compose ps --all || true
  die "Thor VSS did not become ready within ${THOR_FULL_READINESS_TIMEOUT_SECONDS} seconds"
}

doctor_passes=0
doctor_warnings=0
doctor_failures=0
doctor_stack_state="unknown"

doctor_reset() {
  doctor_passes=0
  doctor_warnings=0
  doctor_failures=0
  doctor_stack_state="unknown"
}

doctor_pass() {
  printf '[PASS] %s\n' "$*"
  ((doctor_passes += 1))
}

doctor_warn() {
  printf '[WARN] %s\n' "$*"
  ((doctor_warnings += 1))
}

doctor_fail() {
  printf '[FAIL] %s\n' "$*"
  ((doctor_failures += 1))
}

doctor_compose() {
  env -u NGC_CLI_API_KEY -u NGC_API_KEY -u NVIDIA_API_KEY -u HF_TOKEN \
    -u RTVI_VLM_API_KEY -u VIA_VLM_API_KEY \
    docker compose --env-file "${generated_env}" "$@"
}

doctor_check_runtime_security() {
  if [[ ! -f "${generated_env}" ]]; then
    doctor_fail "Protected runtime env is absent: ${generated_env}"
    return
  fi

  local mode owner reports_directory
  mode="$(stat -c '%a' "${generated_env}" 2>/dev/null || true)"
  owner="$(stat -c '%u' "${generated_env}" 2>/dev/null || true)"
  if [[ "${mode}" == "600" && "${owner}" == "$(id -u)" ]]; then
    doctor_pass "Protected runtime env is owner-only (mode 0600)."
  else
    doctor_fail "Protected runtime env permissions are invalid (expected current-user ownership and mode 0600)."
  fi

  if (require_runtime_env) >/dev/null 2>&1; then
    doctor_pass "Protected runtime env matches the Thor-local contract."
  else
    doctor_fail "Protected runtime env is stale or inconsistent; run: ${script_dir}/thor-local.sh refresh-runtime"
  fi

  if python3 - "${generated_env}" <<'PY'
import sys

sensitive = {
    "HF_TOKEN",
    "NGC_API_KEY",
    "NGC_CLI_API_KEY",
    "NVIDIA_API_KEY",
    "RTVI_VLM_API_KEY",
    "VIA_VLM_API_KEY",
}
with open(sys.argv[1], encoding="utf-8") as stream:
    for raw_line in stream:
        key, separator, value = raw_line.rstrip("\n").partition("=")
        if separator and key in sensitive and value.strip().strip("'\""):
            raise SystemExit(1)
PY
  then
    doctor_pass "Runtime registry/model-download credentials are blank."
  else
    doctor_fail "Protected runtime env contains a non-empty registry/model-download credential (value not displayed)."
  fi

  reports_directory="${data_directory}/agent-reports"
  if [[ -d "${reports_directory}" ]] &&
     [[ "$(stat -c '%u' "${reports_directory}" 2>/dev/null || true)" == "$(id -u)" ]] &&
     [[ "$(stat -c '%a' "${reports_directory}" 2>/dev/null || true)" == "700" ]]; then
    doctor_pass "Durable report directory is current-user owned and mode 0700."
  else
    doctor_fail "Durable report directory is missing or insecure: ${reports_directory}; repair with: sudo chown $(id -un):$(id -gn) ${reports_directory} && chmod 0700 ${reports_directory}"
  fi
}

doctor_check_network_security() {
  local ingress_scope exposed=0 port
  ingress_scope="$(listener_scope "${HAPROXY_PORT}")"
  if [[ "${ingress_scope}" == "loopback" ]]; then
    doctor_pass "Supported operator ingress is loopback-only (${HAPROXY_PORT}/tcp)."
  elif [[ "${ingress_scope}" == "down" ]]; then
    doctor_warn "Supported operator ingress is not listening (${HAPROXY_PORT}/tcp)."
  else
    doctor_fail "Supported operator ingress is reachable beyond loopback (${HAPROXY_PORT}/tcp)."
  fi
  while IFS= read -r port; do
    [[ "$(listener_scope "${port}")" == "exposed" ]] && ((exposed += 1))
  done < <(security_internal_ports)
  if (( exposed == 0 )); then
    doctor_pass "Known internal VSS TCP listeners are loopback-only."
  elif security_firewall_is_active; then
    doctor_pass "Physical-interface firewall protects ${exposed} broadly bound internal TCP listener(s)."
  else
    doctor_warn "${exposed} internal TCP listener(s) bind beyond loopback; review: ${script_dir}/thor-local.sh security audit"
  fi
}

doctor_check_docker_prerequisite() {
  local cgroup_driver
  if ! command -v docker >/dev/null 2>&1 ||
     ! cgroup_driver="$(docker info --format '{{.CgroupDriver}}' 2>/dev/null)"; then
    doctor_fail "Docker daemon is unavailable; cgroup-driver readiness cannot be verified."
  elif [[ "${cgroup_driver}" == "cgroupfs" ]]; then
    doctor_pass "Docker uses NVIDIA VSS-required cgroupfs cgroups."
  else
    doctor_fail "Docker cgroup driver is '${cgroup_driver:-unknown}'; merge 'native.cgroupdriver=cgroupfs' into /etc/docker/daemon.json and restart Docker."
  fi
}

doctor_check_kernel() {
  if "${script_dir}/dev-profile.sh" check-kernel-settings >/dev/null 2>&1; then
    doctor_pass "Required VSS kernel settings are active."
  else
    doctor_fail "Required VSS kernel settings are incomplete; run: ${script_dir}/thor-local.sh kernel-settings"
  fi
  if edge_cache_cleaner_is_running; then
    doctor_pass "Thor unified-memory cache cleaner is running."
  else
    doctor_fail "Thor cache cleaner is not running; run: sudo -b /usr/local/bin/sys-cache-cleaner.sh"
  fi
}

doctor_check_gpu_and_resources() {
  local gpu_line gpu_name gpu_temp gpu_util available_kib total_kib available_gib available_pct
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    doctor_fail "nvidia-smi is unavailable; NVIDIA GPU readiness cannot be verified."
  else
    gpu_line="$(nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -n 1 || true)"
    if [[ -z "${gpu_line}" ]]; then
      doctor_fail "NVIDIA GPU is not responding to nvidia-smi."
    else
      IFS=',' read -r gpu_name gpu_temp gpu_util <<< "${gpu_line}"
      gpu_name="${gpu_name#${gpu_name%%[![:space:]]*}}"
      gpu_temp="${gpu_temp//[[:space:]]/}"
      gpu_util="${gpu_util//[[:space:]]/}"
      if [[ "${gpu_name,,}" == *thor* ]]; then
        doctor_pass "GPU detected: ${gpu_name} (utilization ${gpu_util:-unknown}%)."
      else
        doctor_fail "Expected NVIDIA Thor GPU; detected: ${gpu_name}."
      fi
      if [[ "${gpu_temp}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        if awk -v value="${gpu_temp}" 'BEGIN { exit !(value >= 95) }'; then
          doctor_fail "GPU temperature is critical (${gpu_temp} C)."
        elif awk -v value="${gpu_temp}" 'BEGIN { exit !(value >= 80) }'; then
          doctor_warn "GPU temperature is elevated (${gpu_temp} C)."
        else
          doctor_pass "GPU temperature is ${gpu_temp} C."
        fi
      elif command -v tegrastats >/dev/null 2>&1; then
        local tegra_line
        tegra_line="$(timeout 2 tegrastats --interval 1000 2>/dev/null | head -n 1 || true)"
        gpu_temp="$(sed -n 's/.* gpu@\([0-9.]*\)C.*/\1/p' <<< "${tegra_line}")"
        if [[ -n "${gpu_temp}" ]]; then
          doctor_pass "GPU temperature is ${gpu_temp} C (tegrastats)."
        else
          doctor_warn "GPU temperature is unavailable from nvidia-smi and tegrastats."
        fi
      else
        doctor_warn "GPU temperature is unavailable."
      fi
    fi
  fi

  total_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
  available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  if [[ "${total_kib}" =~ ^[0-9]+$ && "${available_kib}" =~ ^[0-9]+$ && "${total_kib}" -gt 0 ]]; then
    available_gib=$(( available_kib / 1024 / 1024 ))
    available_pct=$(( available_kib * 100 / total_kib ))
    if (( available_kib < 1048576 || available_pct < 1 )); then
      doctor_fail "Unified memory is critically low (${available_gib} GiB / ${available_pct}% available)."
    elif (( available_kib < 8388608 || available_pct < 8 )); then
      doctor_warn "Unified memory headroom is low (${available_gib} GiB / ${available_pct}% available); close unrelated workloads before a demo."
    else
      doctor_pass "Unified memory headroom: ${available_gib} GiB (${available_pct}% available)."
    fi
  else
    doctor_warn "Unified-memory pressure could not be read from /proc/meminfo."
  fi

  local disk_values disk_available_kib disk_used_pct disk_available_gib
  disk_values="$(df -Pk "${data_directory}" 2>/dev/null | awk 'NR==2 {gsub(/%/, "", $5); print $4, $5}' || true)"
  if read -r disk_available_kib disk_used_pct <<< "${disk_values}" &&
     [[ "${disk_available_kib}" =~ ^[0-9]+$ && "${disk_used_pct}" =~ ^[0-9]+$ ]]; then
    disk_available_gib=$(( disk_available_kib / 1024 / 1024 ))
    if (( disk_available_kib < 10485760 || disk_used_pct >= 98 )); then
      doctor_fail "VSS data disk is critically full (${disk_available_gib} GiB free, ${disk_used_pct}% used)."
    elif (( disk_available_kib < 52428800 || disk_used_pct >= 90 )); then
      doctor_warn "VSS data disk headroom is low (${disk_available_gib} GiB free, ${disk_used_pct}% used)."
    else
      doctor_pass "VSS data disk headroom: ${disk_available_gib} GiB free (${disk_used_pct}% used)."
    fi
  else
    doctor_fail "VSS data disk is unavailable: ${data_directory}"
  fi
}

doctor_check_compose() {
  doctor_stack_state="down"
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    doctor_fail "Docker daemon is unavailable."
    return
  fi
  if [[ ! -f "${generated_env}" ]]; then
    doctor_fail "Compose contract cannot be resolved without the protected runtime env."
    return
  fi

  local configured_services compose_ps summary running completed expected state problems
  configured_services="$(doctor_compose config --services 2>/dev/null || true)"
  if [[ -z "${configured_services//[[:space:]]/}" ]]; then
    doctor_fail "Thor Compose service contract could not be resolved."
    return
  fi
  compose_ps="$(doctor_compose ps --all --format json 2>/dev/null || true)"
  summary="$(python3 - "${configured_services}" "${compose_ps}" <<'PY'
import json
import sys

services = [line for line in sys.argv[1].splitlines() if line]
containers = {}
for line in sys.argv[2].splitlines():
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        continue
    containers[item.get("Service", "")] = item

running = completed = 0
problems = []
for service in services:
    item = containers.get(service)
    if item is None:
        problems.append(f"{service}=absent")
        continue
    state = str(item.get("State", "unknown")).lower()
    health = str(item.get("Health", "")).lower() or "none"
    exit_code = int(item.get("ExitCode", 1))
    if state == "running" and health in {"healthy", "none"}:
        running += 1
    elif state == "exited" and exit_code == 0:
        completed += 1
    else:
        problems.append(f"{service}={state}/{health}/exit-{exit_code}")

if running == 0 and completed == 0:
    stack_state = "down"
elif not problems and running + completed == len(services):
    stack_state = "ready"
else:
    stack_state = "partial"
print(f"{running}|{completed}|{len(services)}|{stack_state}|{','.join(problems)}")
PY
)"
  IFS='|' read -r running completed expected state problems <<< "${summary}"
  if [[ ! "${running}" =~ ^[0-9]+$ || ! "${completed}" =~ ^[0-9]+$ || ! "${expected}" =~ ^[0-9]+$ ]]; then
    doctor_fail "Thor Compose container state could not be parsed."
    doctor_stack_state="partial"
    return
  fi
  doctor_stack_state="${state}"

  if [[ -z "${problems}" ]]; then
    doctor_pass "Compose services are ready (${running} running, ${completed} one-shot complete, ${expected} total)."
  else
    doctor_fail "Compose services are incomplete (${running} running, ${completed} one-shot complete, ${expected} expected): ${problems}"
  fi
}

doctor_http_status() {
  local name="$1"
  local url="$2"
  shift 2
  local status expected
  status="$(curl --connect-timeout 2 --max-time 5 --silent --output /dev/null --write-out '%{http_code}' "${url}" 2>/dev/null || true)"
  for expected in "$@"; do
    if [[ "${status}" == "${expected}" ]]; then
      doctor_pass "${name} is ready (HTTP ${status})."
      return
    fi
  done
  doctor_fail "${name} is unavailable at ${url} (HTTP ${status:-connection-failed})."
}

doctor_json_contract() {
  local name="$1"
  local url="$2"
  local validator="$3"
  if curl --connect-timeout 2 --max-time 5 --fail --silent "${url}" 2>/dev/null |
     python3 -c "${validator}" >/dev/null 2>&1; then
    doctor_pass "${name} contract is ready."
  else
    doctor_fail "${name} contract failed at ${url}."
  fi
}

doctor_check_endpoints() {
  local llm_endpoint="${LLM_ENDPOINT_URL}"
  local vlm_endpoint="${VLM_ENDPOINT_URL}"
  local llm_model="${THOR_LOCAL_LLM_MODEL}"
  local vlm_model="${THOR_LOCAL_VLM_MODEL}"
  local llm_recovery="docker start ${THOR_LOCAL_LLM_CONTAINER}"
  local vlm_recovery="docker start ${THOR_LOCAL_VLM_CONTAINER}"
  if official_edge_demo_lane_is_deployed; then
    llm_endpoint="${official_edge_llm_endpoint}"
    vlm_endpoint="${official_edge_vlm_endpoint}"
    llm_model="${official_edge_llm_model}"
    vlm_model="${official_edge_vlm_model}"
    llm_recovery="${official_edge_dir}/thor_demo.py"
    vlm_recovery="${official_edge_dir}/thor_demo.py"
    doctor_pass "Exact-model Thor demo lane is the active Compose deployment."
  fi
  if model_is_served "${llm_endpoint}" "${llm_model}" 2>/dev/null; then
    doctor_pass "Local LLM ${llm_model} is served at ${llm_endpoint}."
  else
    doctor_fail "Local LLM ${llm_model} is unavailable; recover with ${llm_recovery}"
  fi
  if model_is_served "${vlm_endpoint}" "${vlm_model}" 2>/dev/null; then
    doctor_pass "Local VLM ${vlm_model} is served at ${vlm_endpoint}."
  else
    doctor_fail "Local VLM ${vlm_model} is unavailable; recover with ${vlm_recovery}"
  fi

  if [[ "${doctor_stack_state}" == "down" ]]; then
    doctor_warn "Application endpoint checks skipped because the Thor VSS stack is down."
    return
  fi

  doctor_http_status "Operator UI" "http://127.0.0.1:${VSS_UI_PORT}/" 200
  doctor_http_status "Public ingress/UI" "http://127.0.0.1:${HAPROXY_PORT}/" 200
  doctor_json_contract "VSS API" "http://127.0.0.1:${VSS_AGENT_PORT}/health" \
    'import json,sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("value", {}).get("isAlive") is True else 1)'
  doctor_json_contract "Search API route" "http://127.0.0.1:${VSS_AGENT_PORT}/openapi.json" \
    'import json,sys; payload=json.load(sys.stdin); raise SystemExit(0 if "/api/v1/search" in payload.get("paths", {}) else 1)'
  doctor_http_status "Search ingress route" "http://127.0.0.1:${HAPROXY_PORT}/api/v1/search" 405
  doctor_http_status "Cosmos-Embed" "http://127.0.0.1:${RTVI_EMBED_PORT}/v1/ready" 200
  doctor_http_status "RTVI-VLM proxy" "http://127.0.0.1:${RTVI_VLM_PORT}/v1/health/ready" 200
  doctor_http_status "VST/VIOS" "http://127.0.0.1:${VST_PORT}/health" 200
  doctor_http_status "VIOS MCP" "${VIOS_MCP_ENDPOINT}" 200 400 406
  doctor_http_status "VIOS SDR dispatcher" "http://127.0.0.1:${SDR_STREAMPROCESSING_PORT}/healthz" 200
  doctor_http_status "Elasticsearch search backend" "http://127.0.0.1:${VSS_ES_PORT}/_cluster/health" 200
  if [[ "${THOR_FULL_ENABLE_KIBANA}" == "true" ]]; then
    doctor_http_status "Kibana" "http://127.0.0.1:${KIBANA_PORT}/kibana/api/status" 200
  fi
  doctor_http_status "Phoenix" "http://127.0.0.1:${PHOENIX_PORT}/readyz" 200
  doctor_http_status "Logstash" "http://127.0.0.1:${LOGSTASH_API_PORT}/" 200
  doctor_http_status "Alert bridge" "http://127.0.0.1:${ALERT_BRIDGE_PORT}/health" 200
  doctor_json_contract "Alert verification API" "http://127.0.0.1:${ALERT_BRIDGE_PORT}/api/v1/verification/config" \
    'import json,sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("status") == "success" and isinstance(payload.get("configs"), list) else 1)'
  doctor_json_contract "Realtime alert API" "http://127.0.0.1:${ALERT_BRIDGE_PORT}/api/v1/realtime" \
    'import json,sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("status") == "success" and isinstance(payload.get("rules"), list) else 1)'
  if [[ "${ALERT_WEBSOCKET_ENABLED}" == "true" ]]; then
    doctor_json_contract "Alert WebSocket service" "http://127.0.0.1:${ALERT_BRIDGE_PORT}/ws/health" \
      'import json,sys; payload=json.load(sys.stdin); raise SystemExit(0 if payload.get("status") == "healthy" and payload.get("service") == "websocket" else 1)'
  fi
  doctor_http_status "Video summarization" "http://127.0.0.1:${BACKEND_PORT}/v1/ready" 200
  doctor_http_status "Prometheus" "http://127.0.0.1:${PROMETHEUS_PORT}/-/ready" 200
  doctor_http_status "Grafana" "http://127.0.0.1:${GRAFANA_PORT}/api/health" 200
  doctor_http_status "Node exporter" "http://127.0.0.1:${NODE_EXPORTER_PORT}/metrics" 200
  doctor_http_status "cAdvisor" "http://127.0.0.1:${CADVISOR_PORT}/healthz" 200
  doctor_http_status "Thor tegrastats exporter" "http://${TEGRASTATS_BIND_ADDRESS}:${TEGRASTATS_PORT}/readyz" 200
  if [[ "${LVS_ENABLE_MCP}" == "true" ]]; then
    if ss -H -ltn "sport = :${LVS_MCP_PORT}" | grep -q .; then
      doctor_pass "Video summarization MCP is listening on ${LVS_MCP_PORT}."
    else
      doctor_fail "Video summarization MCP is not listening on ${LVS_MCP_PORT}."
    fi
  fi
}

doctor_finish() {
  printf '\nThor doctor summary: %d PASS, %d WARN, %d FAIL\n' \
    "${doctor_passes}" "${doctor_warnings}" "${doctor_failures}"
  if official_edge_demo_lane_is_deployed; then
    local edge_snapshot cosmos_cache_root cosmos_cache
    edge_snapshot="$(container_mount_source vss-nemotron-edge-4b /models/edge4b)"
    cosmos_cache_root="$(container_mount_source vss-rtvi-vlm /opt/nvidia/rtvi/.rtvi/ngc_model_cache)"
    cosmos_cache="${cosmos_cache_root}/${official_edge_vlm_model}"
    cat <<EOF
Recovery commands (exact-model Thor demo lane; offline-safe):
  Verify identity: python3 ${official_edge_dir}/thor_demo.py --edge4b-snapshot ${edge_snapshot} --cosmos3-cache ${cosmos_cache} readiness
  Render recovery: python3 ${official_edge_dir}/thor_demo.py --edge4b-snapshot ${edge_snapshot} --cosmos3-cache ${cosmos_cache} render-command
  Re-check:        ${script_dir}/thor-local.sh doctor
  Service status:  ${script_dir}/thor-local.sh status
  Service logs:    docker logs --tail 150 <container-name>

Run the single pull-free command printed by "Render recovery"; generic
thor-local.sh up/restart is intentionally blocked for this active model lane.
EOF
  else
    cat <<EOF
Recovery commands (offline-safe):
  Start/recover: ${script_dir}/thor-local.sh restart
  Wait for ready: ${script_dir}/thor-local.sh ready
  Re-check:       ${script_dir}/thor-local.sh doctor
  Service status: ${script_dir}/thor-local.sh status
  Service logs:   docker logs --tail 150 <container-name>
EOF
  fi
  if (( doctor_failures > 0 )); then
    return 1
  fi
  return 0
}

doctor() {
  doctor_reset
  printf 'Thor VSS doctor (read-only; no external network calls)\n\n'
  doctor_check_runtime_security
  doctor_check_network_security
  doctor_check_docker_prerequisite
  doctor_check_kernel
  doctor_check_gpu_and_resources
  doctor_check_compose
  doctor_check_endpoints
  doctor_finish
}

qualify_contract() {
  local argument
  for argument in "$@"; do
    [[ "${argument}" != "--regenerate" ]] ||
      die "thor-local.sh qualify is read-only; run the qualification Python tool directly for reviewed regeneration"
  done
  require_command python3
  if [[ "${1:-}" == "--tier" && "${2:-}" == "runtime" ]]; then
    shift 2
    python3 "${runtime_qualification_tool}" "$@"
    return
  fi
  python3 "${qualification_tool}" "$@"
}

stateful_acceptance() {
  require_command python3
  python3 "${stateful_acceptance_tool}" "$@"
}

if [[ "${THOR_LOCAL_SOURCE_ONLY:-false}" == "true" ]]; then
  return 0 2>/dev/null || exit 0
fi

command_name="${1:-}"
case "${command_name}" in
  contract)
    validate_thor_full_contract
    show_contract
    ;;
  qualify)
    shift
    qualify_contract "$@"
    ;;
  acceptance)
    shift
    stateful_acceptance "$@"
    ;;
  kernel-check)
    "${script_dir}/dev-profile.sh" check-kernel-settings
    ;;
  kernel-settings)
    "${script_dir}/dev-profile.sh" kernel-settings
    ;;
  preflight)
    preflight
    ;;
  model-check)
    check_local_model_contracts
    ;;
  up)
    validate_thor_full_contract
    ensure_operator_runtime_directories
    ensure_local_models_are_running
    preflight
    if [[ "${THOR_LOCAL_FORCE_BOOTSTRAP}" == "false" ]] && offline_stage_is_complete; then
      echo "[OK] Complete offline stage detected; skipping connected downloads and builds."
      start_offline_stack
    else
      load_ngc_api_key
      # Connected staging depends on the NGC CLI. Check it before
      # dev-profile.sh can tear down an existing deployment.
      require_command ngc
      [[ -x "${vios_mcp_wheelhouse_stager}" ]] ||
        die "Missing executable VIOS MCP wheelhouse stager: ${vios_mcp_wheelhouse_stager}"
      "${vios_mcp_wheelhouse_stager}"

      bootstrap_docker_config="$(mktemp -d "${TMPDIR:-/tmp}/thor-local-docker-config.XXXXXX")"
      chmod 700 "${bootstrap_docker_config}"
      bootstrap_started=false
      bootstrap_scrubbed=false
      cleanup_connected_bootstrap() {
        local cleanup_status=$?
        rm -f -- "${profile_generated_env}"
        rm -rf -- "${bootstrap_docker_config}"
        if [[ "${bootstrap_started}" == "true" && "${bootstrap_scrubbed}" != "true" ]]; then
          echo "[WARNING] Removing credential-bearing bootstrap containers after an incomplete staging run." >&2
          (cd "${deployment_dir}" && docker compose -p mdx down --remove-orphans) >/dev/null 2>&1 || true
        fi
        return "${cleanup_status}"
      }
      trap cleanup_connected_bootstrap EXIT

      # Use an ephemeral Docker config so docker login cannot persist the NGC
      # token in ~/.docker/config.json. The NGC CLI itself receives the key only
      # through this child process environment.
      bootstrap_started=true
      DOCKER_CONFIG="${bootstrap_docker_config}" "${script_dir}/dev-profile.sh" up \
        --profile "${profile}" \
        --hardware-profile AGX-THOR \
        --use-remote-llm \
        --llm "${THOR_LOCAL_LLM_MODEL}" \
        --llm-model-type "${THOR_LOCAL_LLM_MODEL_TYPE}" \
        --use-remote-vlm \
        --vlm "${THOR_LOCAL_VLM_MODEL}" \
        --vlm-model-type "${THOR_LOCAL_VLM_MODEL_TYPE}"
      stage_runtime_env
      require_staged_images
      wait_for_connected_staging
      verify_offline_stage

      # Recreate from the protected blank-credential runtime contract. This
      # removes the transient NGC key from Docker's persisted container config,
      # not merely from the env file used for future starts.
      start_offline_stack
      bootstrap_scrubbed=true
      trap - EXIT
      cleanup_connected_bootstrap
    fi
    ;;
  refresh-runtime)
    refresh_runtime_env
    ;;
  verify-offline)
    validate_thor_full_contract
    verify_offline_stage
    ;;
  restart)
    [[ -f "${generated_env}" ]] || die "Missing ${generated_env}; run the connected bootstrap first"
    validate_thor_full_contract
    ensure_local_models_are_running
    preflight
    verify_offline_stage
    start_offline_stack
    ;;
  ready)
    [[ -f "${generated_env}" ]] || die "Missing ${generated_env}; run the connected bootstrap first"
    preflight
    assert_no_registry_credentials_in_containers
    wait_for_stack_ready
    ;;
  doctor)
    doctor
    ;;
  security)
    security_command "${2:-audit}" "${@:3}"
    ;;
  domain)
    domain_command "${2:-}" "${3:-}"
    ;;
  stop)
    [[ -f "${generated_env}" ]] || die "Missing ${generated_env}"
    compose stop
    ;;
  down)
    [[ -f "${generated_env}" ]] || die "Missing ${generated_env}"
    compose down --remove-orphans
    ;;
  status)
    if [[ -f "${generated_env}" ]]; then
      compose ps
    else
      echo "VSS stack has not been bootstrapped (generated.env is absent)."
    fi
    if official_edge_demo_lane_is_deployed; then
      model_is_served "${official_edge_llm_endpoint}" "${official_edge_llm_model}" &&
        echo "Official Nemotron 3 LLM endpoint: ready" || echo "Official Nemotron 3 LLM endpoint: unavailable"
      model_is_served "${official_edge_vlm_endpoint}" "${official_edge_vlm_model}" &&
        echo "Official Cosmos3 VLM endpoint: ready" || echo "Official Cosmos3 VLM endpoint: unavailable"
    else
      model_is_served "${LLM_ENDPOINT_URL}" "${THOR_LOCAL_LLM_MODEL}" &&
        echo "LLM endpoint: ready" || echo "LLM endpoint: unavailable"
      model_is_served "${VLM_ENDPOINT_URL}" "${THOR_LOCAL_VLM_MODEL}" &&
        echo "VLM endpoint: ready" || echo "VLM endpoint: unavailable"
    fi
    edge_cache_cleaner_is_running &&
      echo "Thor cache cleaner: ready" || echo "Thor cache cleaner: unavailable"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
