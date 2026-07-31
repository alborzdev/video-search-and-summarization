#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Prepare and qualify an operator-data-only Sparse4D lane on Jetson AGX Thor.
# No command in this helper starts, stops, pulls, builds, deletes, or resets.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd -- "${script_dir}/.." && pwd)"
repo_root="$(cd -- "${deployment_dir}/../.." && pwd)"
env_renderer="${deployment_dir}/thor-local/render-warehouse-sparse4d-env.py"
input_validator="${deployment_dir}/thor-local/validate-warehouse-sparse4d-input.py"
offline_patcher="${THOR_SPARSE4D_OFFLINE_PATCHER:-${deployment_dir}/thor-local/patch-warehouse-sparse4d-offline.py}"
docker_bin="${THOR_SPARSE4D_DOCKER_BIN:-docker}"
ffprobe_bin="${THOR_SPARSE4D_FFPROBE_BIN:-ffprobe}"

state_base="${XDG_STATE_HOME:-${HOME}/.local/state}"
runtime_dir="${THOR_SPARSE4D_RUNTIME_DIR:-${state_base}/cti-vss/warehouse-sparse4d}"
runtime_apps="${runtime_dir}/source/deploy/docker"
runtime_data="${runtime_dir}/data"
runtime_env="${runtime_dir}/generated.env"
runtime_marker="${runtime_dir}/.thor-sparse4d-state"
runtime_checksums="${runtime_dir}/asset-checksums.sha256"
runtime_snapshot_checksums="${runtime_dir}/deployment-snapshot.sha256"
runtime_overlay_file="${runtime_apps}/thor-local/warehouse-sparse4d.compose.yml"
compose_project="thor-wh-sparse4d"
sample_dataset="warehouse-4cams-20mx20m-synthetic"
prepare_stage=""
prepare_stage_parent=""

minimal_services=(
  bp-configurator-3d
  bp-configurator-3d-init
  broker-health-check
  centralizedb
  ds-configurator-3d
  init-dirs
  nvstreamer-3d
  perception-3d
  redis
  render-config
  sdr-controller
  sensor-bp-wait-bp-configurator
  sensor-ms-3d
  streamprocessing-ms-3d
  vss-behavior-analytics-3d
  vst-ingress
  wait-for-docker-workloads
  wait-for-redis
  wdm-env-from-config
)

extended_only_services=(
  cadvisor
  elasticsearch
  elasticsearch-init-container
  grafana
  import-calibration-output-container-3d
  kibana
  kibana-init-container-3d
  logstash
  node-exporter
  prometheus
  vss-haproxy-ingress
  vss-video-analytics-api-3d
)

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: thor-warehouse-sparse4d.sh <command> [minimal|extended]

Commands:
  plan                     Default. Validate custom source inputs; make no changes.
  prepare                  Copy inputs and a mutable app snapshot into a new private runtime.
  validate [profile]       Resolve and enforce the exact Redis Sparse4D Compose contract.
  validate-all             Resolve minimal (19 services) and extended (31 services).
  preflight [profile]      Validate local ARM64 images, assets, ports, memory, and idleness.
  config [profile]         Print resolved Compose YAML after validation.
  launch-command [profile] Print the pull-free/build-free start command; do not execute it.
  qualify [profile]        Read-only qualification of an already-running lane.
  paths                    Print the selected private runtime paths.
  help                     Show this help.

Inputs for plan/prepare:
  THOR_SPARSE4D_INPUT_DIR    Absolute operator-owned input root; never NVIDIA's sample.
  THOR_SPARSE4D_DATASET      Lowercase kebab-case custom dataset slug.
  THOR_SPARSE4D_RUNTIME_DIR  New destination; defaults under XDG_STATE_HOME.
  THOR_SPARSE4D_FFPROBE_BIN  ffprobe-compatible command for synchronization checks.

The source contract is exactly four synchronized Camera*.mp4 files, matching
calibration, Sparse4D v2.2 ONNX, and its 900x11 kmeans NPY anchor. This helper
never executes Compose lifecycle, pulls, builds, deletes, permission changes,
or volume resets. With no command it runs the read-only plan.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

cleanup_prepare_stage() {
  [[ -n "${prepare_stage}" && -n "${prepare_stage_parent}" ]] || return 0
  case "${prepare_stage}" in
    "${prepare_stage_parent}"/.warehouse-sparse4d-staging.*)
      [[ -d "${prepare_stage}" && ! -L "${prepare_stage}" ]] && rm -rf -- "${prepare_stage}"
      ;;
    *)
      printf 'WARNING: refusing to clean unexpected Sparse4D staging path: %s\n' "${prepare_stage}" >&2
      ;;
  esac
}

deployment_snapshot_manifest() {
  local root="$1"
  (
    cd -- "${root}"
    find source/deploy/docker -type f \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/deepstream/configs/*' \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/nvstreamer/configs/*' \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/vst/configs/*' \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/vss-behavior-analytics/configs/*' \
      ! -path 'source/deploy/docker/services/analytics/video-analytics-api/configs/*' \
      -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
  )
}

validate_profile() {
  case "$1" in minimal|extended) ;; *) die "profile must be minimal or extended: $1" ;; esac
}

source_summary() {
  local input_dir="${THOR_SPARSE4D_INPUT_DIR:-}"
  local dataset="${THOR_SPARSE4D_DATASET:-}"
  [[ -n "${input_dir}" ]] || die "THOR_SPARSE4D_INPUT_DIR is required"
  [[ -n "${dataset}" ]] || die "THOR_SPARSE4D_DATASET is required"
  [[ "${input_dir}" = /* ]] || die "THOR_SPARSE4D_INPUT_DIR must be absolute"
  [[ "${runtime_dir}" = /* ]] || die "THOR_SPARSE4D_RUNTIME_DIR must be absolute"
  python3 "${input_validator}" --input-dir "${input_dir}" --dataset "${dataset}" --ffprobe "${ffprobe_bin}"
}

plan() {
  require_command python3
  require_command "${ffprobe_bin}"
  local summary
  summary="$(source_summary)"
  printf 'PASS: custom Sparse4D source contract\n'
  printf '%s\n' "${summary}" | python3 -m json.tool
  printf 'No files or containers changed.\n'
  printf 'Planned private runtime: %s\n' "${runtime_dir}"
  printf 'Next explicit step: %s prepare\n' "$0"
}

prepare_runtime() {
  require_command git
  require_command tar
  require_command python3
  require_command "${ffprobe_bin}"
  require_command sha256sum
  require_command jq
  local input_dir="${THOR_SPARSE4D_INPUT_DIR:-}"
  local dataset="${THOR_SPARSE4D_DATASET:-}"
  local summary runtime_parent stage_apps stage_data stage_cal snapshot_digest
  [[ -n "${input_dir}" && -n "${dataset}" ]] || die "THOR_SPARSE4D_INPUT_DIR and THOR_SPARSE4D_DATASET are required"
  summary="$(source_summary)"
  [[ "$(jq -r '.streams' <<< "${summary}")" == "4" ]] || die "Sparse4D source did not validate as four streams"
  [[ "${dataset}" != "${sample_dataset}" ]] || die "the excluded NVIDIA sample dataset is not accepted"
  [[ ! -e "${runtime_dir}" ]] || die "runtime destination exists; choose a new THOR_SPARSE4D_RUNTIME_DIR: ${runtime_dir}"

  runtime_parent="$(dirname -- "${runtime_dir}")"
  install -d -m 700 "${runtime_parent}"
  prepare_stage_parent="${runtime_parent}"
  prepare_stage="$(mktemp -d "${runtime_parent}/.warehouse-sparse4d-staging.XXXXXX")"
  chmod 700 "${prepare_stage}"
  trap cleanup_prepare_stage EXIT
  install -d -m 700 \
    "${prepare_stage}/source" \
    "${prepare_stage}/data/models/sparse4d/ov" \
    "${prepare_stage}/data/videos/${dataset}" \
    "${prepare_stage}/data/data_log/redis/data" \
    "${prepare_stage}/data/data_log/redis/log" \
    "${prepare_stage}/data/data_log/vst" \
    "${prepare_stage}/data/data_log/analytics_cache" \
    "${prepare_stage}/data/data_log/elastic/data" \
    "${prepare_stage}/data/data_log/elastic/logs" \
    "${prepare_stage}/data/data_log/vss_video_analytics_api"

  (
    cd -- "${repo_root}"
    git ls-files -z --cached --others --exclude-standard -- deploy/docker | tar --null --files-from=- -cf -
  ) | (
    cd -- "${prepare_stage}/source"
    tar -xf -
  )
  stage_apps="${prepare_stage}/source/deploy/docker"
  stage_data="${prepare_stage}/data"
  [[ -f "${stage_apps}/compose.yml" ]] || die "deployment snapshot is incomplete"
  python3 "${offline_patcher}" --apps-dir "${stage_apps}" >/dev/null

  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx" \
    "${input_dir}/models/sparse4d/ov/_ov_kmeans900_v2.2.npy" \
    "${stage_data}/models/sparse4d/ov/"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/videos/${dataset}/"*.mp4 "${stage_data}/videos/${dataset}/"

  stage_cal="${stage_apps}/industry-profiles/warehouse-operations/warehouse-3d-app/calibration/sample-data/${dataset}"
  [[ ! -e "${stage_cal}" ]] || die "custom dataset slug collides with calibration in snapshot: ${dataset}"
  install -d -m 700 "${stage_cal}/images"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/calibration/${dataset}/calibration.json" "${stage_cal}/"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/calibration/${dataset}/images/Top.png" \
    "${input_dir}/calibration/${dataset}/images/imageMetadata.json" \
    "${stage_cal}/images/"

  python3 "${env_renderer}" \
    --source "${stage_apps}/industry-profiles/warehouse-operations/.env" \
    --output "${prepare_stage}/generated.env" \
    --apps-dir "${runtime_dir}/source/deploy/docker" \
    --data-dir "${runtime_dir}/data" \
    --bp-configurator-env-file "${runtime_dir}/generated.env" \
    --repo-root "${repo_root}" \
    --dataset "${dataset}"

  deployment_snapshot_manifest "${prepare_stage}" > "${prepare_stage}/deployment-snapshot.sha256"
  snapshot_digest="$(sha256sum "${prepare_stage}/deployment-snapshot.sha256" | awk '{print $1}')"
  {
    printf 'schema=1\n'
    printf 'lane=warehouse-sparse4d-custom\n'
    printf 'hardware=AGX-THOR\n'
    printf 'broker=redis\n'
    printf 'dataset=%s\n' "${dataset}"
    printf 'streams=4\n'
    printf 'source_revision=%s\n' "$(git -C "${repo_root}" rev-parse HEAD)"
    printf 'deployment_snapshot_manifest_sha256=%s\n' "${snapshot_digest}"
  } > "${prepare_stage}/.thor-sparse4d-state"
  chmod 600 "${prepare_stage}/.thor-sparse4d-state" "${prepare_stage}/generated.env" \
    "${prepare_stage}/deployment-snapshot.sha256"

  summary="$(python3 "${input_validator}" \
    --input-dir "${prepare_stage}" \
    --model-dir "${stage_data}/models/sparse4d/ov" \
    --video-dir "${stage_data}/videos/${dataset}" \
    --calibration-dir "${stage_cal}" \
    --dataset "${dataset}" \
    --ffprobe "${ffprobe_bin}")"
  [[ "$(jq -r '.streams' <<< "${summary}")" == "4" ]] ||
    die "copied Sparse4D assets did not revalidate as four streams"
  (
    cd -- "${prepare_stage}"
    find data/models data/videos \
      "source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/calibration/sample-data/${dataset}" \
      -type f -print0 | sort -z | xargs -0 sha256sum
  ) > "${prepare_stage}/asset-checksums.sha256"
  chmod 600 "${prepare_stage}/asset-checksums.sha256"

  mv -- "${prepare_stage}" "${runtime_dir}"
  prepare_stage=""
  prepare_stage_parent=""
  trap - EXIT
  printf 'Prepared private Sparse4D runtime: %s\n' "${runtime_dir}"
  printf 'Streams: 4 (official Sparse4D synchronized-camera contract; AGX-THOR cap: 7)\n'
  printf 'Next read-only gate: %s validate-all\n' "$0"
}

marker_value() {
  sed -n "s/^$1=//p" "${runtime_marker}"
}

load_runtime() {
  require_command realpath
  require_command sha256sum
  [[ -f "${runtime_marker}" ]] || die "runtime marker is missing; run prepare first: ${runtime_marker}"
  [[ "$(marker_value schema)" == "1" ]] || die "unsupported runtime marker schema"
  [[ "$(marker_value lane)" == "warehouse-sparse4d-custom" ]] || die "runtime marker is for another lane"
  [[ "$(marker_value hardware)" == "AGX-THOR" ]] || die "runtime is not pinned to AGX-THOR"
  [[ "$(marker_value broker)" == "redis" ]] || die "runtime is not pinned to Redis"
  [[ "$(marker_value streams)" == "4" ]] || die "runtime is not the four-camera Sparse4D contract"
  [[ "$(marker_value dataset)" != "${sample_dataset}" ]] || die "runtime selects excluded sample data"
  [[ -f "${runtime_apps}/compose.yml" && -f "${runtime_overlay_file}" ]] || die "private deployment snapshot is missing"
  [[ -f "${runtime_env}" && -f "${runtime_checksums}" && -f "${runtime_snapshot_checksums}" ]] || die "private runtime metadata is incomplete"
  [[ -d "${runtime_data}" ]] || die "private data directory is missing"
  [[ "$(stat -c %a "${runtime_env}")" == "600" ]] || die "generated environment must have mode 0600"
  local apps_real data_real repo_real
  apps_real="$(realpath -e "${runtime_apps}")"
  data_real="$(realpath -e "${runtime_data}")"
  repo_real="$(realpath -e "${repo_root}")"
  case "${apps_real}/" in "${repo_real}/"*) die "mutable VSS_APPS_DIR resolves inside checkout" ;; esac
  case "${data_real}/" in "${repo_real}/"*) die "mutable VSS_DATA_DIR resolves inside checkout" ;; esac
  case "${apps_real}/" in "${runtime_dir}/"*) ;; *) die "mutable app path escaped private runtime" ;; esac
  case "${data_real}/" in "${runtime_dir}/"*) ;; *) die "mutable data path escaped private runtime" ;; esac
  [[ "$(sha256sum "${runtime_snapshot_checksums}" | awk '{print $1}')" == \
     "$(marker_value deployment_snapshot_manifest_sha256)" ]] || die "snapshot manifest does not match marker"
  (cd -- "${runtime_dir}" && sha256sum -c "${runtime_snapshot_checksums}" >/dev/null) ||
    die "immutable deployment snapshot files changed after prepare"
}

compose() {
  local profile="$1"
  shift
  validate_profile "${profile}"
  local minimal=true
  [[ "${profile}" == "minimal" ]] || minimal=""
  env \
    COMPOSE_PROFILES=bp_wh_redis_3d COMPOSE_PROJECT_NAME="${compose_project}" \
    MODE=3d BP_PROFILE=bp_wh_redis STREAM_TYPE=redis MINIMAL_PROFILE="${minimal}" \
    HARDWARE_PROFILE=AGX-THOR LLM_MODE=none VLM_MODE=none \
    VSS_APPS_DIR="${runtime_apps}" VSS_DATA_DIR="${runtime_data}" VSS_REPO_ROOT="${repo_root}" \
    BP_CONFIGURATOR_ENV_FILE="${runtime_env}" NGC_CLI_API_KEY= NVIDIA_API_KEY= OPENAI_API_KEY= \
    "${docker_bin}" compose -p "${compose_project}" \
      -f "${runtime_apps}/compose.yml" -f "${runtime_overlay_file}" \
      --env-file "${runtime_env}" --profile bp_wh_redis_3d "$@"
}

resolved_json() { compose "$1" config --format json; }

expected_services() {
  printf '%s\n' "${minimal_services[@]}"
  [[ "$1" == "minimal" ]] || printf '%s\n' "${extended_only_services[@]}"
}

validate_compose() {
  local profile="$1"
  validate_profile "${profile}"
  require_command "${docker_bin}"
  require_command jq
  load_runtime
  local resolved actual expected bad_writable dataset
  resolved="$(resolved_json "${profile}")" || die "Compose could not resolve ${profile} Sparse4D lane"
  actual="$(jq -r '.services | keys[]' <<< "${resolved}" | sort)"
  expected="$(expected_services "${profile}" | sort)"
  [[ "${actual}" == "${expected}" ]] || {
    printf 'Expected services:\n%s\nActual services:\n%s\n' "${expected}" "${actual}" >&2
    die "resolved ${profile} service graph does not match Sparse4D allowlist"
  }
  dataset="$(marker_value dataset)"
  jq -e --arg dataset "${dataset}" --arg apps "${runtime_apps}" --arg data "${runtime_data}" '
    .services.redis.command == ["redis-server", "/config/redis.conf", "--bind", "127.0.0.1", "--protected-mode", "yes"] and
    .services["bp-configurator-3d"].environment.HARDWARE_PROFILE == "AGX-THOR" and
    .services["bp-configurator-3d"].environment.NUM_STREAMS == "4" and
    .services["bp-configurator-3d"].environment.SAMPLE_VIDEO_DATASET == $dataset and
    .services["perception-3d"].environment.DS_MODEL_FAMILY == "sparse4d-warehouse" and
    .services["perception-3d"].environment.TRANSFORMERS_OFFLINE == "1" and
    .services["perception-3d"].environment.HF_HUB_OFFLINE == "1" and
    .services["perception-3d"].runtime == "nvidia" and
    .services["nvstreamer-3d"].runtime == "nvidia" and
    .services["nvstreamer-3d"].environment.NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES == "false" and
    .services["streamprocessing-ms-3d"].environment.VST_INSTALL_ADDITIONAL_PACKAGES == "false" and
    (.services["sensor-ms-3d"].environment.LD_LIBRARY_PATH | startswith("/usr/lib/aarch64-linux-gnu/nvidia:")) and
    ([.services["perception-3d"].volumes[] | select(.source == ($data + "/models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx"))] | length) == 1 and
    ([.services["perception-3d"].volumes[] | select(.source == ($data + "/models/sparse4d/ov/_ov_kmeans900_v2.2.npy"))] | length) == 1 and
    (.services | has("vss-agent") | not) and (.services | has("rtvi-vlm") | not) and
    (.services | has("dcgm-exporter") | not)
  ' <<< "${resolved}" >/dev/null || die "resolved Compose lost Redis/Thor/Sparse4D/offline/no-agent invariants"

  jq -e '.network.stunurl_list == ["127.0.0.1:3478"] and .network.use_twilio_stun_turn == false' \
    "${runtime_apps}/industry-profiles/warehouse-operations/warehouse-3d-app/vst/configs/vst_config.json" \
    "${runtime_apps}/industry-profiles/warehouse-operations/warehouse-3d-app/nvstreamer/configs/vst-config.json" \
    >/dev/null || die "private Sparse4D VST configs lack loopback STUN sentinel"

  if [[ "${profile}" == "extended" ]]; then
    jq -e '
      .services.logstash.image == "vss-logstash-redis:9.3.3-input-3.1.0-thor-local" and
      (.services.logstash.command == [] or .services.logstash.command == null) and
      .services.logstash.environment.STREAM_TYPE == "redis" and
      .services.prometheus.ports[0].host_ip == "127.0.0.1" and
      .services.grafana.ports[0].host_ip == "127.0.0.1" and
      .services["node-exporter"].ports[0].host_ip == "127.0.0.1" and
      .services.cadvisor.ports[0].host_ip == "127.0.0.1"
    ' <<< "${resolved}" >/dev/null || die "extended offline Logstash/loopback monitoring contract changed"
  fi

  bad_writable="$(jq -r --arg apps "${runtime_apps}" --arg data "${runtime_data}" '
    .services | to_entries[] as $service | ($service.value.volumes // [])[] |
    select(.type == "bind" and (.read_only // false | not)) |
    select((.source == $apps or .source == $data or (.source | startswith($apps + "/")) or
      (.source | startswith($data + "/")) or .source == "/var/run/docker.sock") | not) |
    "\($service.key):\(.source)"
  ' <<< "${resolved}")"
  [[ -z "${bad_writable}" ]] || {
    printf 'Writable bind mounts outside private roots:\n%s\n' "${bad_writable}" >&2
    die "resolved lane can mutate non-private host paths"
  }
  ! grep -Fq "${THOR_SPARSE4D_INPUT_DIR:-/path-that-cannot-match}" <<< "${resolved}" ||
    die "resolved Compose references operator source instead of private copies"
  printf 'PASS: Sparse4D %s Redis Compose contract (%d services, 4 synchronized streams; AGX cap 7)\n' \
    "${profile}" "$(wc -l <<< "${actual}")"
}

verify_assets() {
  load_runtime
  (cd -- "${runtime_dir}" && sha256sum -c "${runtime_checksums}" >/dev/null) ||
    die "lane-private asset checksum verification failed"
  local dataset cal_dir video_count
  dataset="$(marker_value dataset)"
  cal_dir="${runtime_apps}/industry-profiles/warehouse-operations/warehouse-3d-app/calibration/sample-data/${dataset}"
  video_count="$(find "${runtime_data}/videos/${dataset}" -maxdepth 1 -type f -name '*.mp4' | wc -l)"
  [[ "${video_count}" == "4" ]] || die "private video count is no longer four"
  [[ -f "${runtime_data}/models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx" ]] || die "private Sparse4D ONNX is missing"
  [[ -f "${runtime_data}/models/sparse4d/ov/_ov_kmeans900_v2.2.npy" ]] || die "private Sparse4D anchor is missing"
  [[ -f "${cal_dir}/images/Top.png" && -f "${cal_dir}/images/imageMetadata.json" ]] ||
    die "private top-view assets are incomplete"
}

check_images() {
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
  (( ${#missing[@]} == 0 )) || { printf 'Missing local images (preflight never pulls/builds):\n' >&2; printf '  %s\n' "${missing[@]}" >&2; }
  (( ${#wrong_arch[@]} == 0 )) || { printf 'Images that are not linux/arm64:\n' >&2; printf '  %s\n' "${wrong_arch[@]}" >&2; }
  (( ${#missing[@]} == 0 && ${#wrong_arch[@]} == 0 )) || die "stage listed ARM64 images while connected, then rerun preflight"
}

check_idle_host() {
  local resolved="$1" existing conflicts="" gpu_conflicts="" id details
  existing="$("${docker_bin}" ps -a --format '{{.Names}}')"
  while IFS= read -r name; do
    [[ -z "${name}" ]] && continue
    grep -Fxq "${name}" <<< "${existing}" && conflicts+="${name}"$'\n'
  done < <(jq -r '.services[] | .container_name // empty' <<< "${resolved}" | sort -u)
  [[ -z "${conflicts}" ]] || { printf 'Conflicting fixed-name containers exist:\n%s' "${conflicts}" >&2; die "Sparse4D requires exclusive names/ports"; }
  for id in $("${docker_bin}" ps -q); do
    details="$("${docker_bin}" inspect --format '{{.Name}}|{{.HostConfig.Runtime}}|{{json .HostConfig.DeviceRequests}}' "${id}")"
    grep -Eqi '\|nvidia\||"gpu"|"nvidia"' <<< "${details}" && gpu_conflicts+="${details#/}"$'\n'
  done
  [[ -z "${gpu_conflicts}" ]] || { printf 'GPU-enabled containers are running:\n%s' "${gpu_conflicts}" >&2; die "Sparse4D is mutually exclusive with other GPU workloads"; }
}

check_ports_and_resources() {
  local profile="$1" listeners conflicts="" available_kib disk_kib port
  local -a ports=(5001 6379 8011 8080 9000 9003 9902 30000 30001 30554 30888 31000)
  [[ "${profile}" == "minimal" ]] || ports+=(5601 7777 8081 9090 9200 18080 19100 35000)
  require_command ss
  listeners="$(ss -H -ltn)"
  for port in "${ports[@]}"; do
    awk -v port=":${port}" '$4 ~ port "$" {found=1} END {exit !found}' <<< "${listeners}" && conflicts+="tcp/${port}"$'\n'
  done
  [[ -z "${conflicts}" ]] || { printf 'Required host-network ports have listeners:\n%s' "${conflicts}" >&2; die "Sparse4D host ports are not idle"; }
  [[ "$(uname -m)" == "aarch64" ]] || die "AGX-THOR Sparse4D requires aarch64"
  grep -qi 'thor' /proc/device-tree/model 2>/dev/null || die "host model does not identify Thor"
  available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  (( available_kib >= 52428800 )) || die "less than 50 GiB unified memory is available"
  disk_kib="$(df -Pk "${runtime_dir}" | awk 'NR==2 {print $4}')"
  (( disk_kib >= 31457280 )) || die "less than 30 GiB remains on runtime filesystem"
  printf 'PASS: host floor (%d GiB memory available, %d GiB disk free)\n' \
    "$((available_kib / 1024 / 1024))" "$((disk_kib / 1024 / 1024))"
}

preflight() {
  local profile="$1" resolved
  validate_compose "${profile}"
  verify_assets
  resolved="$(resolved_json "${profile}")"
  check_images "${resolved}"
  check_idle_host "${resolved}"
  check_ports_and_resources "${profile}"
  printf 'PASS: Sparse4D %s lane is statically ready; no containers changed\n' "${profile}"
}

print_config() { validate_compose "$1" >&2; compose "$1" config; }

print_launch_command() {
  local profile="$1" minimal=true
  validate_compose "${profile}" >&2
  [[ "${profile}" == "minimal" ]] || minimal=""
  printf 'MINIMAL_PROFILE=%q docker compose -p %q -f %q -f %q --env-file %q --profile bp_wh_redis_3d up -d --no-build --pull never\n' \
    "${minimal}" "${compose_project}" "${runtime_apps}/compose.yml" "${runtime_overlay_file}" "${runtime_env}"
  printf '# Review/run manually only after preflight passes and host is dedicated to this lane.\n'
}

container_ready() {
  local name="$1" state health project
  state="$("${docker_bin}" inspect --format '{{.State.Status}}' "${name}" 2>/dev/null)" || die "required container missing: ${name}"
  [[ "${state}" == "running" ]] || die "required container not running: ${name} (${state})"
  project="$("${docker_bin}" inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "${name}")"
  [[ "${project}" == "${compose_project}" ]] || die "container belongs to another project: ${name} (${project})"
  health="$("${docker_bin}" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}")"
  [[ "${health}" == "none" || "${health}" == "healthy" ]] || die "container unhealthy: ${name} (${health})"
}

redis_length() { "${docker_bin}" exec redis redis-cli --raw XLEN "$1" 2>/dev/null | tr -dc '0-9'; }

qualify_runtime() {
  local profile="$1" dataset cal_dir sensor_json actual expected bev1 behavior1 bev2 behavior2 sample_seconds name
  validate_compose "${profile}"
  require_command curl
  dataset="$(marker_value dataset)"
  cal_dir="${runtime_apps}/industry-profiles/warehouse-operations/warehouse-3d-app/calibration/sample-data/${dataset}"
  local -a core=(redis vss-configurator vss-vios-nvstreamer vss-vios-sensor vss-vios-streamprocessing vss-rtvi-cv vss-behavior-analytics)
  for name in "${core[@]}"; do container_ready "${name}"; done
  if [[ "${profile}" == "extended" ]]; then
    for name in elasticsearch kibana logstash vss-video-analytics-api vss-haproxy-ingress prometheus grafana; do container_ready "${name}"; done
  fi
  [[ "$("${docker_bin}" inspect --format '{{.State.Status}} {{.State.ExitCode}}' vss-rtvi-cv-config-adaptor 2>/dev/null)" == "exited 0" ]] ||
    die "Sparse4D config adaptor did not exit successfully"
  curl --noproxy '*' --fail --silent --show-error --max-time 3 http://127.0.0.1:5001/readyz >/dev/null || die "Configurator readiness failed"
  sensor_json="$(curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:30888/vst/api/v1/sensor/list)" || die "VST sensor list failed"
  expected="$(jq -r '.sensors[].id' "${cal_dir}/calibration.json" | sort)"
  actual="$(jq -r '.[].name' <<< "${sensor_json}" | sort)"
  [[ "${actual}" == "${expected}" ]] || { printf 'Expected sensors:\n%s\nRuntime sensors:\n%s\n' "${expected}" "${actual}" >&2; die "VST sensor set does not match calibration"; }
  [[ "$(jq '[.[] | select(.state == "online")] | length' <<< "${sensor_json}")" == "4" ]] || die "not all four VST sensors are online"
  "${docker_bin}" logs --tail 500 vss-rtvi-cv 2>&1 | grep -E 'Active sources[^0-9]*4([^0-9]|$)' >/dev/null || die "perception logs do not prove four active sources"
  "${docker_bin}" logs --tail 500 vss-rtvi-cv 2>&1 | grep -Eqi 'FPS|frames per second' || die "perception logs lack FPS evidence"
  ! "${docker_bin}" logs --tail 500 vss-rtvi-cv 2>&1 | grep -Eqi 'failed.*(sparse4d|engine)|invalid.*calib|cuda.*error' || die "perception logs contain Sparse4D/CUDA failure"
  bev1="$(redis_length mdx-bev)"; behavior1="$(redis_length mdx-behavior)"
  sample_seconds="${THOR_SPARSE4D_QUALIFY_SAMPLE_SECONDS:-10}"
  [[ "${sample_seconds}" =~ ^([1-9]|[1-5][0-9]|60)$ ]] || die "qualification sample seconds must be 1-60"
  sleep "${sample_seconds}"
  bev2="$(redis_length mdx-bev)"; behavior2="$(redis_length mdx-behavior)"
  [[ "${bev2:-0}" -gt "${bev1:-0}" ]] || die "mdx-bev did not grow (${bev1:-0} -> ${bev2:-0})"
  [[ "${behavior2:-0}" -gt 0 ]] || die "mdx-behavior has no analytics output"
  if [[ "${profile}" == "extended" ]]; then
    curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:8081/livez >/dev/null || die "Video Analytics API liveness failed"
    curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:5601/kibana/api/status >/dev/null || die "Kibana status failed"
    curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:9090/-/ready >/dev/null || die "Prometheus readiness failed"
    curl --noproxy '*' --fail --silent --show-error --max-time 5 http://127.0.0.1:35000/api/health >/dev/null || die "Grafana health failed"
    for name in vss-import-calibration-output vss-kibana-init vss-elasticsearch-init; do
      [[ "$("${docker_bin}" inspect --format '{{.State.Status}} {{.State.ExitCode}}' "${name}" 2>/dev/null)" == "exited 0" ]] || die "extended initializer failed: ${name}"
    done
  fi
  printf 'PASS: read-only Sparse4D %s qualification (4 sensors; BEV %s->%s, behavior=%s)\n' \
    "${profile}" "${bev1}" "${bev2}" "${behavior2}"
}

print_paths() {
  printf 'Runtime root: %s\nMutable apps: %s\nPrivate data: %s\nGenerated env: %s\nPrivate overlay: %s\n' \
    "${runtime_dir}" "${runtime_apps}" "${runtime_data}" "${runtime_env}" "${runtime_overlay_file}"
}

if [[ "${THOR_SPARSE4D_SOURCE_ONLY:-false}" == "true" ]]; then
  return 0 2>/dev/null || exit 0
fi

command_name="${1:-plan}"
profile="${2:-minimal}"
case "${command_name}" in
  plan) plan ;;
  prepare) prepare_runtime ;;
  validate) validate_compose "${profile}" ;;
  validate-all) validate_compose minimal; validate_compose extended ;;
  preflight) preflight "${profile}" ;;
  config) print_config "${profile}" ;;
  launch-command) print_launch_command "${profile}" ;;
  qualify) qualify_runtime "${profile}" ;;
  paths) print_paths ;;
  help|-h|--help) usage ;;
  *) usage >&2; die "unknown command: ${command_name}" ;;
esac
