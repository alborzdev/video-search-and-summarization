#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Prepare and statically validate the first warehouse parity lane on AGX Thor.
# This milestone intentionally contains no container lifecycle operations.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd -- "${script_dir}/.." && pwd)"
repo_root="$(cd -- "${deployment_dir}/../.." && pwd)"
overlay_file="${deployment_dir}/thor-local/warehouse-2d.compose.yml"
env_renderer="${deployment_dir}/thor-local/render-warehouse-2d-env.py"
docker_bin="${THOR_WAREHOUSE_DOCKER_BIN:-docker}"

state_base="${XDG_STATE_HOME:-${HOME}/.local/state}"
runtime_dir="${THOR_WAREHOUSE_RUNTIME_DIR:-${state_base}/cti-vss/warehouse-2d}"
runtime_apps="${runtime_dir}/source/deploy/docker"
runtime_data="${runtime_dir}/data"
runtime_env="${runtime_dir}/generated.env"
runtime_marker="${runtime_dir}/.thor-warehouse-2d-state"
dataset="warehouse-loading-dock-3cams-synthetic"
model_name="rtdetr_warehouse_v1.0.2.fp16.onnx"
compose_project="thor-wh-2d"

expected_services=(
  bp-configurator-2d
  bp-configurator-2d-init
  broker-health-check
  centralizedb
  init-dirs
  nvstreamer-2d
  perception-2d
  redis
  render-config
  sdr-controller
  sensor-bp-wait-bp-configurator
  sensor-ms-2d
  streamprocessing-ms-2d
  vss-behavior-analytics-2d
  vst-ingress
  wait-for-docker-workloads
  wait-for-redis
  wdm-env-from-config
)

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: thor-warehouse-2d.sh <command>

Commands:
  prepare     Create a new mutable app snapshot and lane-private one-camera data copy.
  validate    Resolve Compose and enforce the minimal Redis service/resource contract.
  preflight   Run validate plus local ARM64 image, asset, port, memory, and idleness gates.
  config      Print the resolved Compose YAML after validate succeeds.
  paths       Print the selected private runtime paths.
  help        Show this help.

Preparation inputs:
  THOR_WAREHOUSE_APP_DATA_SOURCE  Extracted vss-warehouse-app-data:3.2.0 directory.
  THOR_WAREHOUSE_RUNTIME_DIR      New destination; defaults under XDG_STATE_HOME.
  THOR_WAREHOUSE_NUM_STREAMS     1 for the safe smoke milestone; accepts 1-3.

The script never starts/stops containers, pulls/builds images, uses sudo, or
deletes/replaces an existing runtime directory. Missing assets and images are
reported as preflight failures.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

validate_stream_count() {
  local streams="$1"
  [[ "${streams}" =~ ^[1-3]$ ]] || die "THOR_WAREHOUSE_NUM_STREAMS must be 1, 2, or 3"
}

verify_source_app_data() {
  local source_data="$1"
  local streams="$2"
  local model="${source_data}/models/mtmc/${model_name}"
  local videos_dir="${source_data}/videos/${dataset}"
  local -a videos=()

  [[ -d "${source_data}" ]] || die "warehouse app-data directory is missing: ${source_data}"
  [[ -f "${model}" ]] || die "warehouse model is missing: ${model}"
  [[ -d "${videos_dir}" ]] || die "warehouse video dataset is missing: ${videos_dir}"
  mapfile -d '' -t videos < <(find "${videos_dir}" -maxdepth 1 -type f -name '*.mp4' -print0 | sort -z)
  (( ${#videos[@]} >= streams )) ||
    die "warehouse dataset has ${#videos[@]} MP4 file(s), but ${streams} are required: ${videos_dir}"
}

prepare_runtime() {
  require_command git
  require_command tar
  require_command python3
  require_command find
  require_command sort
  require_command sha256sum

  local source_data="${THOR_WAREHOUSE_APP_DATA_SOURCE:-}"
  local streams="${THOR_WAREHOUSE_NUM_STREAMS:-1}"
  local runtime_parent stage stage_apps stage_data source_model source_videos
  local -a videos=()

  [[ -n "${source_data}" ]] ||
    die "THOR_WAREHOUSE_APP_DATA_SOURCE must point to extracted vss-warehouse-app-data:3.2.0"
  [[ "${source_data}" = /* ]] || die "THOR_WAREHOUSE_APP_DATA_SOURCE must be an absolute path"
  [[ "${runtime_dir}" = /* ]] || die "THOR_WAREHOUSE_RUNTIME_DIR must be an absolute path"
  validate_stream_count "${streams}"
  verify_source_app_data "${source_data}" "${streams}"
  [[ ! -e "${runtime_dir}" ]] ||
    die "runtime destination already exists; choose a new THOR_WAREHOUSE_RUNTIME_DIR: ${runtime_dir}"

  runtime_parent="$(dirname -- "${runtime_dir}")"
  install -d -m 700 "${runtime_parent}"
  stage="$(mktemp -d "${runtime_parent}/.warehouse-2d-staging.XXXXXX")"
  chmod 700 "${stage}"
  install -d -m 700 "${stage}/source" "${stage}/data/models/mtmc" \
    "${stage}/data/videos/${dataset}" "${stage}/data/data_log/redis/data" \
    "${stage}/data/data_log/redis/log" "${stage}/data/data_log/vst"

  # Snapshot the non-ignored deployment working tree. This includes local edits
  # and new source files while excluding the ignored 8+ GiB data-dir.
  (
    cd -- "${repo_root}"
    git ls-files -z --cached --others --exclude-standard -- deploy/docker |
      tar --null --files-from=- -cf -
  ) | (
    cd -- "${stage}/source"
    tar -xf -
  )

  stage_apps="${stage}/source/deploy/docker"
  stage_data="${stage}/data"
  [[ -f "${stage_apps}/compose.yml" ]] || die "tracked deployment snapshot is incomplete: compose.yml missing"

  source_model="${source_data}/models/mtmc/${model_name}"
  cp --reflink=auto --preserve=mode,timestamps -- "${source_model}" \
    "${stage_data}/models/mtmc/${model_name}"

  source_videos="${source_data}/videos/${dataset}"
  mapfile -d '' -t videos < <(find "${source_videos}" -maxdepth 1 -type f -name '*.mp4' -print0 | sort -z)
  local index video
  for (( index=0; index<streams; index++ )); do
    video="${videos[index]}"
    cp --reflink=auto --preserve=mode,timestamps -- "${video}" \
      "${stage_data}/videos/${dataset}/$(basename -- "${video}")"
  done

  python3 "${env_renderer}" \
    --source "${stage_apps}/industry-profiles/warehouse-operations/.env" \
    --output "${stage}/generated.env" \
    --apps-dir "${runtime_dir}/source/deploy/docker" \
    --data-dir "${runtime_dir}/data" \
    --bp-configurator-env-file "${runtime_dir}/generated.env" \
    --repo-root "${repo_root}" \
    --streams "${streams}"

  {
    printf 'schema=1\n'
    printf 'profile=warehouse-2d-minimal-redis\n'
    printf 'hardware=AGX-THOR\n'
    printf 'streams=%s\n' "${streams}"
    printf 'source_app_data=%s\n' "${source_data}"
    printf 'source_revision=%s\n' "$(git -C "${repo_root}" rev-parse HEAD)"
  } > "${stage}/.thor-warehouse-2d-state"
  chmod 600 "${stage}/.thor-warehouse-2d-state" "${stage}/generated.env"

  (
    cd -- "${stage_data}"
    find models videos -type f -print0 | sort -z | xargs -0 sha256sum
  ) > "${stage}/asset-checksums.sha256"
  chmod 600 "${stage}/asset-checksums.sha256"

  mv -- "${stage}" "${runtime_dir}"
  printf 'Prepared isolated warehouse-2D state: %s\n' "${runtime_dir}"
  printf 'Mutable Compose/config snapshot: %s\n' "${runtime_apps}"
  printf 'Lane-private model/video data: %s\n' "${runtime_data}"
  printf 'Next read-only gate: %s preflight\n' "$0"
}

load_runtime() {
  require_command realpath
  [[ -f "${runtime_marker}" ]] ||
    die "prepared runtime marker is missing: ${runtime_marker}; run prepare with the official app-data source"
  [[ -f "${runtime_apps}/compose.yml" ]] || die "mutable Compose snapshot is missing: ${runtime_apps}"
  [[ -f "${runtime_env}" ]] || die "generated environment is missing: ${runtime_env}"
  [[ -d "${runtime_data}" ]] || die "lane-private data directory is missing: ${runtime_data}"
  [[ "$(stat -c %a "${runtime_env}")" == "600" ]] || die "generated environment must have mode 0600"

  local apps_real repo_real
  apps_real="$(realpath -e "${runtime_apps}")"
  repo_real="$(realpath -e "${repo_root}")"
  case "${apps_real}/" in
    "${repo_real}/"*) die "mutable VSS_APPS_DIR unexpectedly resolves inside the checkout: ${apps_real}" ;;
  esac
}

compose() {
  env \
    COMPOSE_PROFILES=bp_wh_redis_2d \
    COMPOSE_PROJECT_NAME="${compose_project}" \
    MODE=2d \
    BP_PROFILE=bp_wh_redis \
    STREAM_TYPE=redis \
    MINIMAL_PROFILE=true \
    HARDWARE_PROFILE=AGX-THOR \
    LLM_MODE=none \
    VLM_MODE=none \
    VSS_APPS_DIR="${runtime_apps}" \
    VSS_DATA_DIR="${runtime_data}" \
    VSS_REPO_ROOT="${repo_root}" \
    BP_CONFIGURATOR_ENV_FILE="${runtime_env}" \
    NGC_CLI_API_KEY= \
    NVIDIA_API_KEY= \
    OPENAI_API_KEY= \
    "${docker_bin}" compose \
      -p "${compose_project}" \
      -f "${runtime_apps}/compose.yml" \
      -f "${overlay_file}" \
      --env-file "${runtime_env}" \
      --profile bp_wh_redis_2d \
      "$@"
}

resolved_json() {
  compose config --format json
}

validate_compose() {
  require_command "${docker_bin}"
  require_command jq
  load_runtime

  local resolved actual expected bad_mounts
  resolved="$(resolved_json)" || die "Docker Compose could not resolve the isolated warehouse lane"
  actual="$(jq -r '.services | keys[]' <<< "${resolved}")"
  expected="$(printf '%s\n' "${expected_services[@]}" | sort)"
  [[ "${actual}" == "${expected}" ]] || {
    printf 'Expected services:\n%s\nActual services:\n%s\n' "${expected}" "${actual}" >&2
    die "resolved warehouse service graph is not the 18-service minimal Redis allowlist"
  }

  jq -e '
    .services.redis.command == ["redis-server", "/config/redis.conf", "--bind", "127.0.0.1", "--protected-mode", "yes"] and
    .services["nvstreamer-2d"].runtime == "nvidia" and
    .services["nvstreamer-2d"].environment.NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES == "false" and
    .services["perception-2d"].runtime == "nvidia" and
    .services["perception-2d"].environment.TRANSFORMERS_OFFLINE == "1" and
    .services["perception-2d"].environment.HF_HUB_OFFLINE == "1" and
    .services["streamprocessing-ms-2d"].environment.VST_INSTALL_ADDITIONAL_PACKAGES == "false" and
    (.services["sensor-ms-2d"].environment.LD_LIBRARY_PATH | startswith("/usr/lib/aarch64-linux-gnu/nvidia:"))
  ' <<< "${resolved}" >/dev/null || die "resolved Compose lost a required Thor runtime/offline override"

  jq -e '
    (.services | has("elasticsearch") | not) and
    (.services | has("kafka") | not) and
    (.services | has("vss-agent") | not) and
    (.services | has("rtvi-vlm") | not) and
    (.services | has("rtvi-embed") | not)
  ' <<< "${resolved}" >/dev/null || die "minimal lane unexpectedly contains extended, agent, or model services"

  bad_mounts="$(jq -r --arg apps "${runtime_apps}" --arg data "${runtime_data}" '
    .services | to_entries[] as $service |
    ($service.value.volumes // [])[] |
    select(.type == "bind") |
    select((
      .source == $apps or
      .source == $data or
      (.source | startswith($apps + "/")) or
      (.source | startswith($data + "/")) or
      .source == "/var/run/docker.sock"
    ) | not) |
    "\($service.key):\(.source)"
  ' <<< "${resolved}")"
  [[ -z "${bad_mounts}" ]] || {
    printf 'Bind mounts outside the mutable app/data roots:\n%s\n' "${bad_mounts}" >&2
    die "resolved warehouse lane can write outside its isolated runtime roots"
  }

  printf 'PASS: warehouse-2D minimal Redis Compose contract (%d services)\n' "${#expected_services[@]}"
}

verify_runtime_assets() {
  local streams model videos_dir video_count calibration
  streams="$(sed -n 's/^streams=//p' "${runtime_marker}")"
  validate_stream_count "${streams}"
  model="${runtime_data}/models/mtmc/${model_name}"
  videos_dir="${runtime_data}/videos/${dataset}"
  calibration="${runtime_apps}/industry-profiles/warehouse-operations/warehouse-2d-app/calibration/sample-data/${dataset}/calibration.json"
  [[ -f "${model}" ]] || die "lane-private RT-DETR model is missing: ${model}"
  [[ -f "${calibration}" ]] || die "mutable calibration file is missing: ${calibration}"
  video_count="$(find "${videos_dir}" -maxdepth 1 -type f -name '*.mp4' | wc -l)"
  [[ "${video_count}" == "${streams}" ]] ||
    die "lane-private video count is ${video_count}; expected exactly ${streams}: ${videos_dir}"
  (cd -- "${runtime_data}" && sha256sum -c "${runtime_dir}/asset-checksums.sha256" >/dev/null) ||
    die "lane-private asset checksum verification failed"
}

check_required_images() {
  local resolved="$1"
  local -a images=() missing=() wrong_arch=()
  local image architecture
  mapfile -t images < <(jq -r '.services[] | .image // empty' <<< "${resolved}" | sort -u)
  for image in "${images[@]}"; do
    if ! "${docker_bin}" image inspect "${image}" >/dev/null 2>&1; then
      missing+=("${image}")
      continue
    fi
    architecture="$("${docker_bin}" image inspect "${image}" --format '{{.Os}}/{{.Architecture}}')"
    [[ "${architecture}" == "linux/arm64" ]] || wrong_arch+=("${image} (${architecture})")
  done
  if (( ${#missing[@]} > 0 )); then
    printf 'Missing local images (preflight never pulls):\n' >&2
    printf '  %s\n' "${missing[@]}" >&2
  fi
  if (( ${#wrong_arch[@]} > 0 )); then
    printf 'Images that are not linux/arm64:\n' >&2
    printf '  %s\n' "${wrong_arch[@]}" >&2
  fi
  (( ${#missing[@]} == 0 && ${#wrong_arch[@]} == 0 )) ||
    die "stage/build every listed ARM64 image while connected, then rerun preflight"
}

check_idle_host() {
  local -a fixed_names=(
    redis vss-configurator vss-broker-health-check vss-vios-postgres
    vss-vios-nvstreamer vss-rtvi-cv vss-vios-sensor
    vss-vios-streamprocessing vss-behavior-analytics vss-vios-ingress
  )
  local all_names name ids id details gpu_conflicts="" name_conflicts=""
  all_names="$("${docker_bin}" ps -a --format '{{.Names}}')"
  for name in "${fixed_names[@]}"; do
    if grep -Fxq "${name}" <<< "${all_names}"; then
      name_conflicts+="${name}"$'\n'
    fi
  done
  [[ -z "${name_conflicts}" ]] || {
    printf 'Conflicting fixed-name containers already exist:\n%s' "${name_conflicts}" >&2
    die "warehouse lane requires exclusive container names and host ports"
  }

  ids="$("${docker_bin}" ps -q)"
  for id in ${ids}; do
    details="$("${docker_bin}" inspect --format '{{.Name}}|{{.HostConfig.Runtime}}|{{json .HostConfig.DeviceRequests}}' "${id}")"
    if grep -Eqi '\|nvidia\||"gpu"|"nvidia"' <<< "${details}"; then
      gpu_conflicts+="${details#/}"$'\n'
    fi
  done
  [[ -z "${gpu_conflicts}" ]] || {
    printf 'GPU-enabled containers are still running:\n%s' "${gpu_conflicts}" >&2
    die "warehouse qualification is mutually exclusive with other GPU container workloads"
  }
}

check_host_resources() {
  [[ "$(uname -m)" == "aarch64" ]] || die "warehouse AGX-Thor lane requires an aarch64 host"
  grep -qi 'thor' /proc/device-tree/model 2>/dev/null || die "host model does not identify a Thor platform"

  local available_kib available_gib disk_kib disk_gib
  available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  (( available_kib >= 8388608 )) || die "less than 8 GiB unified memory is available"
  available_gib=$(( available_kib / 1024 / 1024 ))
  disk_kib="$(df -Pk "${runtime_dir}" | awk 'NR==2 {print $4}')"
  (( disk_kib >= 20971520 )) || die "less than 20 GiB remains on the warehouse runtime filesystem"
  disk_gib=$(( disk_kib / 1024 / 1024 ))
  printf 'PASS: host resource floor (%s GiB memory available, %s GiB disk free)\n' \
    "${available_gib}" "${disk_gib}"
}

check_host_ports() {
  require_command ss
  local -a ports=(5001 5003 6379 8011 9000 9902 30000 30001 30554 30888 31000)
  local listeners port conflicts=""
  listeners="$(ss -H -ltn)"
  for port in "${ports[@]}"; do
    if awk -v port=":${port}" '$4 ~ port "$" {found=1} END {exit !found}' <<< "${listeners}"; then
      conflicts+="tcp/${port}"$'\n'
    fi
  done
  [[ -z "${conflicts}" ]] || {
    printf 'Required host-network ports already have listeners:\n%s' "${conflicts}" >&2
    die "warehouse host ports are not idle"
  }
}

preflight() {
  require_command jq
  require_command sha256sum
  validate_compose
  local resolved
  resolved="$(resolved_json)"
  verify_runtime_assets
  check_required_images "${resolved}"
  check_idle_host
  check_host_ports
  check_host_resources
  printf 'PASS: warehouse-2D lane is statically ready; this milestone does not start it\n'
}

print_config() {
  validate_compose >&2
  compose config
}

print_paths() {
  printf 'Runtime root: %s\n' "${runtime_dir}"
  printf 'Mutable apps: %s\n' "${runtime_apps}"
  printf 'Private data: %s\n' "${runtime_data}"
  printf 'Generated env: %s\n' "${runtime_env}"
  printf 'Overlay: %s\n' "${overlay_file}"
}

if [[ "${THOR_WAREHOUSE_SOURCE_ONLY:-false}" == "true" ]]; then
  return 0 2>/dev/null || exit 0
fi

case "${1:-help}" in
  prepare) prepare_runtime ;;
  validate) validate_compose ;;
  preflight) preflight ;;
  config) print_config ;;
  paths) print_paths ;;
  help|-h|--help) usage ;;
  *) usage >&2; die "unknown command: ${1}" ;;
esac
