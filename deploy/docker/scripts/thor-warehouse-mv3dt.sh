#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Prepare and qualify an operator-data-only MV3DT lane on Jetson AGX Thor.
# No command in this helper starts, stops, pulls, builds, deletes, or resets.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd -- "${script_dir}/.." && pwd)"
repo_root="$(cd -- "${deployment_dir}/../.." && pwd)"
source_overlay_file="${deployment_dir}/thor-local/warehouse-mv3dt.compose.yml"
env_renderer="${deployment_dir}/thor-local/render-warehouse-mv3dt-env.py"
input_validator="${deployment_dir}/thor-local/validate-warehouse-mv3dt-input.py"
offline_patcher="${THOR_MV3DT_OFFLINE_PATCHER:-${deployment_dir}/thor-local/patch-warehouse-mv3dt-offline.py}"
docker_bin="${THOR_MV3DT_DOCKER_BIN:-docker}"
ffprobe_bin="${THOR_MV3DT_FFPROBE_BIN:-ffprobe}"

state_base="${XDG_STATE_HOME:-${HOME}/.local/state}"
runtime_dir="${THOR_MV3DT_RUNTIME_DIR:-${state_base}/cti-vss/warehouse-mv3dt}"
runtime_apps="${runtime_dir}/source/deploy/docker"
runtime_data="${runtime_dir}/data"
runtime_env="${runtime_dir}/generated.env"
runtime_marker="${runtime_dir}/.thor-mv3dt-state"
runtime_checksums="${runtime_dir}/asset-checksums.sha256"
runtime_snapshot_checksums="${runtime_dir}/deployment-snapshot.sha256"
runtime_overlay_file="${runtime_apps}/thor-local/warehouse-mv3dt.compose.yml"
compose_project="thor-wh-mv3dt"
sample_dataset="warehouse-4cams-20mx20m-synthetic"
prepare_stage=""
prepare_stage_parent=""

minimal_services=(
  bp-configurator-mv3dt
  bp-configurator-mv3dt-init
  broker-health-check
  centralizedb
  init-dirs
  mosquitto
  nvstreamer-mv3dt
  redis
  render-config
  sdr-controller
  sensor-bp-wait-bp-configurator
  sensor-ms-mv3dt
  streamprocessing-ms-mv3dt
  vss-behavior-analytics-mv3dt
  vss-rtvi-cv-bev-fusion
  vss-rtvi-cv-mv3dt
  vst-ingress
  wait-for-docker-workloads
  wait-for-redis
  wdm-env-from-config
)

extended_only_services=(
  elasticsearch
  elasticsearch-init-container
  import-calibration-output-container-mv3dt
  kibana
  kibana-init-container-mv3dt
  logstash
  vss-haproxy-ingress
  vss-video-analytics-api-mv3dt
)

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: thor-warehouse-mv3dt.sh <command> [minimal|extended]

Commands:
  plan                    Default. Validate custom source inputs; make no changes.
  prepare                 Copy validated inputs and a mutable app snapshot into a new private runtime.
  validate [profile]      Resolve and enforce the exact Redis MV3DT Compose contract.
  validate-all            Resolve both minimal (20 services) and extended (28 services).
  preflight [profile]     Validate plus local ARM64 images, assets, ports, memory, and idleness.
  config [profile]        Print resolved Compose YAML after validation.
  launch-command [profile] Print the pull-free/build-free start command; do not execute it.
  qualify [profile]       Read-only qualification of an already-running lane.
  paths                   Print the selected private runtime paths.
  help                    Show this help.

Inputs for plan/prepare:
  THOR_MV3DT_INPUT_DIR     Absolute operator-owned input root; never NVIDIA's excluded sample.
  THOR_MV3DT_DATASET       Lowercase kebab-case custom dataset slug.
  THOR_MV3DT_RUNTIME_DIR   New destination; defaults under XDG_STATE_HOME.
  THOR_MV3DT_FFPROBE_BIN   ffprobe-compatible command used for synchronization checks.

This helper never runs Compose lifecycle, pull, build, delete, permission, or
volume-reset operations. Destructive recovery remains a separately reviewed,
operator-confirmed action. With no command, the helper runs the read-only plan.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

cleanup_prepare_stage() {
  [[ -n "${prepare_stage}" && -n "${prepare_stage_parent}" ]] || return 0
  case "${prepare_stage}" in
    "${prepare_stage_parent}"/.warehouse-mv3dt-staging.*)
      [[ -d "${prepare_stage}" && ! -L "${prepare_stage}" ]] && rm -rf -- "${prepare_stage}"
      ;;
    *)
      printf 'WARNING: refusing to clean unexpected MV3DT staging path: %s\n' "${prepare_stage}" >&2
      ;;
  esac
  return 0
}

deployment_snapshot_manifest() {
  local root="$1"
  (
    cd -- "${root}"
    # Configurator legitimately rewrites these private config directories.
    # Everything else in the copied deploy snapshot remains content-addressed.
    find source/deploy/docker -type f \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/deepstream/configs/*' \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/nvstreamer/configs/*' \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/vst/configs/*' \
      ! -path 'source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/vss-behavior-analytics/configs/*' \
      ! -path 'source/deploy/docker/services/analytics/video-analytics-api/configs/*' \
      -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
  )
}

validate_profile() {
  case "$1" in
    minimal|extended) ;;
    *) die "profile must be minimal or extended: $1" ;;
  esac
}

source_summary() {
  local input_dir="${THOR_MV3DT_INPUT_DIR:-}"
  local dataset="${THOR_MV3DT_DATASET:-}"
  [[ -n "${input_dir}" ]] || die "THOR_MV3DT_INPUT_DIR is required"
  [[ -n "${dataset}" ]] || die "THOR_MV3DT_DATASET is required"
  [[ "${input_dir}" = /* ]] || die "THOR_MV3DT_INPUT_DIR must be absolute"
  [[ "${runtime_dir}" = /* ]] || die "THOR_MV3DT_RUNTIME_DIR must be absolute"
  python3 "${input_validator}" \
    --input-dir "${input_dir}" \
    --dataset "${dataset}" \
    --ffprobe "${ffprobe_bin}"
}

plan() {
  require_command python3
  require_command "${ffprobe_bin}"
  local summary
  summary="$(source_summary)"
  printf 'PASS: custom MV3DT source contract\n'
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

  local input_dir="${THOR_MV3DT_INPUT_DIR:-}"
  local dataset="${THOR_MV3DT_DATASET:-}"
  local summary streams runtime_parent stage_apps stage_data stage_cal snapshot_digest
  [[ -n "${input_dir}" && -n "${dataset}" ]] || die "THOR_MV3DT_INPUT_DIR and THOR_MV3DT_DATASET are required"
  summary="$(source_summary)"
  streams="$(jq -r '.streams' <<< "${summary}")"
  [[ "${dataset}" != "${sample_dataset}" ]] || die "the excluded NVIDIA sample dataset is not accepted"
  [[ ! -e "${runtime_dir}" ]] || die "runtime destination exists; choose a new THOR_MV3DT_RUNTIME_DIR: ${runtime_dir}"

  runtime_parent="$(dirname -- "${runtime_dir}")"
  install -d -m 700 "${runtime_parent}"
  prepare_stage_parent="${runtime_parent}"
  prepare_stage="$(mktemp -d "${runtime_parent}/.warehouse-mv3dt-staging.XXXXXX")"
  chmod 700 "${prepare_stage}"
  trap cleanup_prepare_stage EXIT
  install -d -m 700 "${prepare_stage}/source" \
    "${prepare_stage}/data/models/mtmc" \
    "${prepare_stage}/data/models/mv3dt/BodyPose3DNet" \
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
    git ls-files -z --cached --others --exclude-standard -- deploy/docker |
      tar --null --files-from=- -cf -
  ) | (
    cd -- "${prepare_stage}/source"
    tar -xf -
  )
  stage_apps="${prepare_stage}/source/deploy/docker"
  stage_data="${prepare_stage}/data"
  [[ -f "${stage_apps}/compose.yml" ]] || die "deployment snapshot is incomplete"

  # Configurator mutates these private copies further at runtime. Remove the
  # public Google STUN defaults first so offline Thor never attempts DNS/egress.
  python3 "${offline_patcher}" --apps-dir "${stage_apps}" >/dev/null

  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/models/mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx" \
    "${stage_data}/models/mtmc/"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/models/mv3dt/BodyPose3DNet/bodypose3dnet_accuracy.onnx" \
    "${stage_data}/models/mv3dt/BodyPose3DNet/"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/videos/${dataset}/"*.mp4 \
    "${stage_data}/videos/${dataset}/"

  stage_cal="${stage_apps}/industry-profiles/warehouse-operations/warehouse-mv3dt-app/calibration/sample-data/${dataset}"
  [[ ! -e "${stage_cal}" ]] || die "custom dataset slug collides with calibration already in the deployment snapshot: ${dataset}"
  install -d -m 700 "${stage_cal}/camInfo" "${stage_cal}/images"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/calibration/${dataset}/calibration.json" "${stage_cal}/"
  cp --reflink=auto --preserve=mode,timestamps -- \
    "${input_dir}/calibration/${dataset}/camInfo/"*.y*ml "${stage_cal}/camInfo/"
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
    --dataset "${dataset}" \
    --streams "${streams}"

  deployment_snapshot_manifest "${prepare_stage}" > "${prepare_stage}/deployment-snapshot.sha256"
  snapshot_digest="$(sha256sum "${prepare_stage}/deployment-snapshot.sha256" | awk '{print $1}')"

  {
    printf 'schema=1\n'
    printf 'lane=warehouse-mv3dt-custom\n'
    printf 'hardware=AGX-THOR\n'
    printf 'broker=redis\n'
    printf 'dataset=%s\n' "${dataset}"
    printf 'streams=%s\n' "${streams}"
    printf 'source_revision=%s\n' "$(git -C "${repo_root}" rev-parse HEAD)"
    printf 'deployment_snapshot_manifest_sha256=%s\n' "${snapshot_digest}"
  } > "${prepare_stage}/.thor-mv3dt-state"
  chmod 600 "${prepare_stage}/.thor-mv3dt-state" "${prepare_stage}/generated.env" \
    "${prepare_stage}/deployment-snapshot.sha256"

  (
    cd -- "${prepare_stage}"
    find data/models data/videos \
      "source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/calibration/sample-data/${dataset}" \
      -type f -print0 | sort -z | xargs -0 sha256sum
  ) > "${prepare_stage}/asset-checksums.sha256"
  chmod 600 "${prepare_stage}/asset-checksums.sha256"

  mv -- "${prepare_stage}" "${runtime_dir}"
  prepare_stage=""
  prepare_stage_parent=""
  trap - EXIT
  printf 'Prepared private MV3DT runtime: %s\n' "${runtime_dir}"
  printf 'Streams: %s (AGX-THOR cap: 7)\n' "${streams}"
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
  [[ "$(marker_value lane)" == "warehouse-mv3dt-custom" ]] || die "runtime marker is for another lane"
  [[ "$(marker_value hardware)" == "AGX-THOR" ]] || die "runtime is not pinned to AGX-THOR"
  [[ "$(marker_value broker)" == "redis" ]] || die "runtime is not pinned to Redis"
  [[ "$(marker_value dataset)" != "${sample_dataset}" ]] || die "runtime marker selects excluded sample data"
  [[ -f "${runtime_apps}/compose.yml" ]] || die "private deployment snapshot is missing"
  [[ -f "${runtime_env}" ]] || die "generated environment is missing"
  [[ -f "${runtime_checksums}" ]] || die "asset checksums are missing"
  [[ -f "${runtime_snapshot_checksums}" ]] || die "deployment snapshot checksums are missing"
  [[ -f "${runtime_overlay_file}" ]] || die "private MV3DT Compose overlay is missing"
  [[ -d "${runtime_data}" ]] || die "private data directory is missing"
  [[ "$(stat -c %a "${runtime_env}")" == "600" ]] || die "generated environment must have mode 0600"

  local apps_real data_real repo_real
  apps_real="$(realpath -e "${runtime_apps}")"
  data_real="$(realpath -e "${runtime_data}")"
  repo_real="$(realpath -e "${repo_root}")"
  case "${apps_real}/" in "${repo_real}/"*) die "mutable VSS_APPS_DIR resolves inside the checkout" ;; esac
  case "${data_real}/" in "${repo_real}/"*) die "mutable VSS_DATA_DIR resolves inside the checkout" ;; esac
  case "${apps_real}/" in "${runtime_dir}/"*) ;; *) die "mutable app path escaped its lane-private runtime" ;; esac
  case "${data_real}/" in "${runtime_dir}/"*) ;; *) die "mutable data path escaped its lane-private runtime" ;; esac
  [[ "$(sha256sum "${runtime_snapshot_checksums}" | awk '{print $1}')" == \
     "$(marker_value deployment_snapshot_manifest_sha256)" ]] ||
    die "deployment snapshot checksum manifest does not match the prepared marker"
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
    COMPOSE_PROFILES=bp_wh_redis_mv3dt \
    COMPOSE_PROJECT_NAME="${compose_project}" \
    MODE=mv3dt \
    BP_PROFILE=bp_wh_redis \
    STREAM_TYPE=redis \
    MINIMAL_PROFILE="${minimal}" \
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
      -f "${runtime_overlay_file}" \
      --env-file "${runtime_env}" \
      --profile bp_wh_redis_mv3dt \
      "$@"
}

resolved_json() {
  compose "$1" config --format json
}

expected_services() {
  local profile="$1"
  printf '%s\n' "${minimal_services[@]}"
  if [[ "${profile}" == "extended" ]]; then
    printf '%s\n' "${extended_only_services[@]}"
  fi
}

validate_compose() {
  local profile="$1"
  validate_profile "${profile}"
  require_command "${docker_bin}"
  require_command jq
  load_runtime
  local resolved actual expected bad_writable streams dataset
  resolved="$(resolved_json "${profile}")" || die "Compose could not resolve the ${profile} MV3DT lane"
  actual="$(jq -r '.services | keys[]' <<< "${resolved}" | sort)"
  expected="$(expected_services "${profile}" | sort)"
  [[ "${actual}" == "${expected}" ]] || {
    printf 'Expected services:\n%s\nActual services:\n%s\n' "${expected}" "${actual}" >&2
    die "resolved ${profile} service graph does not match the MV3DT allowlist"
  }
  streams="$(marker_value streams)"
  dataset="$(marker_value dataset)"
  jq -e --arg streams "${streams}" --arg dataset "${dataset}" '
    .services.redis.command == ["redis-server", "/config/redis.conf", "--bind", "127.0.0.1", "--protected-mode", "yes"] and
    .services["bp-configurator-mv3dt"].environment.HARDWARE_PROFILE == "AGX-THOR" and
    .services["bp-configurator-mv3dt"].environment.NUM_STREAMS == $streams and
    .services["bp-configurator-mv3dt"].environment.SAMPLE_VIDEO_DATASET == $dataset and
    .services["vss-rtvi-cv-mv3dt"].environment.BATCH_SIZE == $streams and
    .services["vss-rtvi-cv-mv3dt"].environment.MAX_BATCH_SIZE == $streams and
    .services["vss-rtvi-cv-mv3dt"].environment.STREAM_TYPE == "redis" and
    .services["vss-rtvi-cv-mv3dt"].environment.TRANSFORMERS_OFFLINE == "1" and
    .services["vss-rtvi-cv-mv3dt"].environment.HF_HUB_OFFLINE == "1" and
    .services["vss-rtvi-cv-bev-fusion"].environment.BROKER_TYPE == "redis" and
    .services["nvstreamer-mv3dt"].runtime == "nvidia" and
    .services["nvstreamer-mv3dt"].environment.NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES == "false" and
    .services["streamprocessing-ms-mv3dt"].environment.VST_INSTALL_ADDITIONAL_PACKAGES == "false" and
    (.services["sensor-ms-mv3dt"].environment.LD_LIBRARY_PATH | startswith("/usr/lib/aarch64-linux-gnu/nvidia:")) and
    (.services | has("vss-agent") | not) and
    (.services | has("llm") | not) and
    (.services | has("rtvi-vlm") | not)
  ' <<< "${resolved}" >/dev/null || die "resolved Compose lost Redis/Thor/offline/no-model invariants"

  jq -e '.network.stunurl_list == ["127.0.0.1:3478"] and .network.use_twilio_stun_turn == false' \
    "${runtime_apps}/industry-profiles/warehouse-operations/warehouse-mv3dt-app/vst/configs/vst_config.json" \
    "${runtime_apps}/industry-profiles/warehouse-operations/warehouse-mv3dt-app/nvstreamer/configs/vst-config.json" \
    >/dev/null || die "private MV3DT VST configs lack the loopback STUN sentinel"

  if [[ "${profile}" == "extended" ]]; then
    jq -e '
      .services.logstash.image == "vss-logstash-protobuf:9.3.3-codec-1.3.0-thor-local" and
      (.services.logstash.command == [] or .services.logstash.command == null) and
      .services.logstash.environment.STREAM_TYPE == "kafka"
    ' <<< "${resolved}" >/dev/null ||
      die "extended Logstash lost its immutable offline protobuf override"
  fi

  bad_writable="$(jq -r --arg apps "${runtime_apps}" --arg data "${runtime_data}" '
    .services | to_entries[] as $service |
    ($service.value.volumes // [])[] |
    select(.type == "bind" and (.read_only // false | not)) |
    select((
      .source == $apps or .source == $data or
      (.source | startswith($apps + "/")) or
      (.source | startswith($data + "/")) or
      .source == "/var/run/docker.sock"
    ) | not) |
    "\($service.key):\(.source)"
  ' <<< "${resolved}")"
  [[ -z "${bad_writable}" ]] || {
    printf 'Writable bind mounts outside private app/data roots:\n%s\n' "${bad_writable}" >&2
    die "resolved lane can mutate non-private host paths"
  }
  ! grep -Fq "${THOR_MV3DT_INPUT_DIR:-/path-that-cannot-match}" <<< "${resolved}" ||
    die "resolved Compose references operator source inputs instead of their private copies"

  printf 'PASS: MV3DT %s Redis Compose contract (%d services, %s/%s streams)\n' \
    "${profile}" "$(wc -l <<< "${actual}")" "${streams}" "7"
}

verify_assets() {
  load_runtime
  (cd -- "${runtime_dir}" && sha256sum -c "${runtime_checksums}" >/dev/null) ||
    die "lane-private asset checksum verification failed"
  local dataset streams cal_dir video_count caminfo_count
  dataset="$(marker_value dataset)"
  streams="$(marker_value streams)"
  cal_dir="${runtime_apps}/industry-profiles/warehouse-operations/warehouse-mv3dt-app/calibration/sample-data/${dataset}"
  video_count="$(find "${runtime_data}/videos/${dataset}" -maxdepth 1 -type f -name '*.mp4' | wc -l)"
  caminfo_count="$(find "${cal_dir}/camInfo" -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) | wc -l)"
  [[ "${video_count}" == "${streams}" && "${caminfo_count}" == "${streams}" ]] ||
    die "private video/camInfo counts no longer match NUM_STREAMS=${streams}"
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
  if (( ${#missing[@]} )); then
    printf 'Missing local images (preflight never pulls or builds):\n' >&2
    printf '  %s\n' "${missing[@]}" >&2
  fi
  if (( ${#wrong_arch[@]} )); then
    printf 'Images that are not linux/arm64:\n' >&2
    printf '  %s\n' "${wrong_arch[@]}" >&2
  fi
  (( ${#missing[@]} == 0 && ${#wrong_arch[@]} == 0 )) ||
    die "stage every listed ARM64 image while connected, then rerun preflight"
}

check_idle_host() {
  local resolved="$1" existing conflicts="" gpu_conflicts="" id details
  existing="$("${docker_bin}" ps -a --format '{{.Names}}')"
  while IFS= read -r name; do
    [[ -z "${name}" ]] && continue
    grep -Fxq "${name}" <<< "${existing}" && conflicts+="${name}"$'\n'
  done < <(jq -r '.services[] | .container_name // empty' <<< "${resolved}" | sort -u)
  [[ -z "${conflicts}" ]] || {
    printf 'Conflicting fixed-name containers already exist:\n%s' "${conflicts}" >&2
    die "MV3DT requires exclusive container names and host ports"
  }
  for id in $("${docker_bin}" ps -q); do
    details="$("${docker_bin}" inspect --format '{{.Name}}|{{.HostConfig.Runtime}}|{{json .HostConfig.DeviceRequests}}' "${id}")"
    grep -Eqi '\|nvidia\||"gpu"|"nvidia"' <<< "${details}" && gpu_conflicts+="${details#/}"$'\n'
  done
  [[ -z "${gpu_conflicts}" ]] || {
    printf 'GPU-enabled containers are running:\n%s' "${gpu_conflicts}" >&2
    die "MV3DT qualification is mutually exclusive with other GPU container workloads"
  }
}

check_ports_and_resources() {
  local profile="$1" listeners conflicts="" available_kib disk_kib
  local -a ports=(1883 5001 6379 8011 8080 9000 9902 30000 30001 30554 30888 31000)
  [[ "${profile}" == "minimal" ]] || ports+=(5601 7777 8081 9200)
  require_command ss
  listeners="$(ss -H -ltn)"
  local port
  for port in "${ports[@]}"; do
    awk -v port=":${port}" '$4 ~ port "$" {found=1} END {exit !found}' <<< "${listeners}" &&
      conflicts+="tcp/${port}"$'\n'
  done
  [[ -z "${conflicts}" ]] || {
    printf 'Required host-network ports already have listeners:\n%s' "${conflicts}" >&2
    die "MV3DT host ports are not idle"
  }
  [[ "$(uname -m)" == "aarch64" ]] || die "AGX-THOR MV3DT requires an aarch64 host"
  grep -qi 'thor' /proc/device-tree/model 2>/dev/null || die "host model does not identify a Thor platform"
  available_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  (( available_kib >= 25165824 )) || die "less than 24 GiB unified memory is available"
  disk_kib="$(df -Pk "${runtime_dir}" | awk 'NR==2 {print $4}')"
  (( disk_kib >= 31457280 )) || die "less than 30 GiB remains on the private runtime filesystem"
  printf 'PASS: host floor (%d GiB available memory, %d GiB free disk)\n' \
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
  printf 'PASS: MV3DT %s lane is statically ready; no containers were changed\n' "${profile}"
}

print_config() {
  validate_compose "$1" >&2
  compose "$1" config
}

print_launch_command() {
  local profile="$1" minimal=true
  validate_compose "${profile}" >&2
  [[ "${profile}" == "minimal" ]] || minimal=""
  printf 'MINIMAL_PROFILE=%q docker compose -p %q -f %q -f %q --env-file %q --profile bp_wh_redis_mv3dt up -d --no-build --pull never\n' \
    "${minimal}" "${compose_project}" "${runtime_apps}/compose.yml" "${runtime_overlay_file}" "${runtime_env}"
  printf '# Review and run manually only after preflight passes and the host is dedicated to this lane.\n'
}

container_ready() {
  local name="$1" state health project
  state="$("${docker_bin}" inspect --format '{{.State.Status}}' "${name}" 2>/dev/null)" || die "required container is missing: ${name}"
  [[ "${state}" == "running" ]] || die "required container is not running: ${name} (${state})"
  project="$("${docker_bin}" inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "${name}")"
  [[ "${project}" == "${compose_project}" ]] || die "container belongs to a different Compose project: ${name} (${project})"
  health="$("${docker_bin}" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}")"
  [[ "${health}" == "none" || "${health}" == "healthy" ]] || die "container is not healthy: ${name} (${health})"
}

redis_length() {
  "${docker_bin}" exec redis redis-cli --raw XLEN "$1" 2>/dev/null | tr -dc '0-9'
}

qualify_runtime() {
  local profile="$1" streams dataset cal_dir sensor_json actual expected
  local raw1 bev1 behavior1 raw2 bev2 behavior2 sample_seconds
  validate_compose "${profile}"
  require_command curl
  streams="$(marker_value streams)"
  dataset="$(marker_value dataset)"
  cal_dir="${runtime_apps}/industry-profiles/warehouse-operations/warehouse-mv3dt-app/calibration/sample-data/${dataset}"

  local -a core=(
    redis mosquitto vss-configurator-mv3dt vss-vios-nvstreamer-mv3dt
    vss-vios-sensor vss-vios-streamprocessing vss-rtvi-cv-bev-fusion
    vss-rtvi-cv-mv3dt vss-behavior-analytics-mv3dt
  )
  local name
  for name in "${core[@]}"; do container_ready "${name}"; done
  if [[ "${profile}" == "extended" ]]; then
    for name in elasticsearch kibana logstash vss-video-analytics-api-mv3dt vss-haproxy-ingress; do
      container_ready "${name}"
    done
  fi

  curl --noproxy '*' --fail --silent --show-error --max-time 3 \
    http://127.0.0.1:5001/readyz >/dev/null || die "Configurator readiness failed"
  sensor_json="$(curl --noproxy '*' --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:30888/vst/api/v1/sensor/list)" || die "VST sensor-list request failed"
  expected="$(jq -r '.sensors[].id' "${cal_dir}/calibration.json" | sort)"
  actual="$(jq -r '.[].name' <<< "${sensor_json}" | sort)"
  [[ "${actual}" == "${expected}" ]] || {
    printf 'Expected sensors:\n%s\nRuntime sensors:\n%s\n' "${expected}" "${actual}" >&2
    die "VST sensor set does not exactly match calibration"
  }
  [[ "$(jq '[.[] | select(.state == "online")] | length' <<< "${sensor_json}")" == "${streams}" ]] ||
    die "not every expected VST sensor is online"

  "${docker_bin}" logs --tail 500 vss-rtvi-cv-mv3dt 2>&1 |
    grep -E "Active sources[^0-9]*${streams}([^0-9]|$)" >/dev/null ||
    die "perception logs do not prove Active sources == ${streams}"
  "${docker_bin}" logs --tail 500 vss-rtvi-cv-mv3dt 2>&1 |
    grep -Eqi 'FPS|frames per second' || die "perception logs do not contain an FPS sample"
  ! "${docker_bin}" logs --tail 500 vss-vios-streamprocessing 2>&1 |
    grep -q 'No calibration data found for sensor' || die "VST streamprocessing cannot match runtime calibration"

  raw1="$(redis_length mdx-raw)"; bev1="$(redis_length mdx-bev)"; behavior1="$(redis_length mdx-behavior)"
  sample_seconds="${THOR_MV3DT_QUALIFY_SAMPLE_SECONDS:-10}"
  [[ "${sample_seconds}" =~ ^([1-9]|[1-5][0-9]|60)$ ]] || die "qualification sample seconds must be 1-60"
  sleep "${sample_seconds}"
  raw2="$(redis_length mdx-raw)"; bev2="$(redis_length mdx-bev)"; behavior2="$(redis_length mdx-behavior)"
  [[ "${raw2:-0}" -gt "${raw1:-0}" ]] || die "mdx-raw did not grow (${raw1:-0} -> ${raw2:-0})"
  [[ "${bev2:-0}" -gt "${bev1:-0}" ]] || die "mdx-bev did not grow (${bev1:-0} -> ${bev2:-0})"
  [[ "${behavior2:-0}" -gt 0 ]] || die "mdx-behavior has no analytics output"

  if [[ "${profile}" == "extended" ]]; then
    curl --noproxy '*' --fail --silent --show-error --max-time 5 \
      http://127.0.0.1:8081/livez >/dev/null || die "Video Analytics API liveness failed"
    curl --noproxy '*' --fail --silent --show-error --max-time 5 \
      http://127.0.0.1:5601/kibana/api/status >/dev/null || die "Kibana status failed"
    for name in vss-import-calibration-output-mv3dt vss-kibana-init-mv3dt vss-elasticsearch-init; do
      [[ "$("${docker_bin}" inspect --format '{{.State.Status}} {{.State.ExitCode}}' "${name}" 2>/dev/null)" == "exited 0" ]] ||
        die "extended initializer did not exit successfully: ${name}"
    done
  fi
  printf 'PASS: read-only MV3DT %s runtime qualification (%s sensors; raw %s->%s, BEV %s->%s, behavior=%s)\n' \
    "${profile}" "${streams}" "${raw1}" "${raw2}" "${bev1}" "${bev2}" "${behavior2}"
}

print_paths() {
  printf 'Runtime root: %s\n' "${runtime_dir}"
  printf 'Mutable apps: %s\n' "${runtime_apps}"
  printf 'Private data: %s\n' "${runtime_data}"
  printf 'Generated env: %s\n' "${runtime_env}"
  printf 'Source overlay: %s\n' "${source_overlay_file}"
  printf 'Private overlay: %s\n' "${runtime_overlay_file}"
}

if [[ "${THOR_MV3DT_SOURCE_ONLY:-false}" == "true" ]]; then
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
