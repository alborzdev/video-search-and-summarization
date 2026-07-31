#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Read-only readiness gate and command renderer for the alternate Omni lane.
# It never starts, stops, creates, pulls, or builds a container.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../../.." && pwd)"
deployment_dir="${repo_root}/deploy/docker"
base_compose="${deployment_dir}/compose.yml"
thor_compose="${deployment_dir}/thor-local/compose.yml"
audio_compose="${script_dir}/omni.compose.yml"
snapshot_tool="${script_dir}/omni_snapshot.py"
generated_env="${THOR_LOCAL_GENERATED_ENV_FILE:-${deployment_dir}/thor-local/generated.env}"
audio_image="${THOR_LOCAL_RTVI_AUDIO_IMAGE:-cti-vss-rt-vlm:3.2.1-thor-audio-offline}"
default_vlm_container="${THOR_LOCAL_DEFAULT_VLM_CONTAINER:-cti-vss-qwen3-vl}"
minimum_memory_gib="${THOR_LOCAL_OMNI_MIN_AVAILABLE_MEMORY_GIB:-80}"

usage() {
  cat <<'EOF'
Usage: thor-omni-audio.sh audit|launch-command

Required environment:
  THOR_LOCAL_OMNI_MODEL_DIR       Absolute local model snapshot directory.
  THOR_LOCAL_OMNI_MODEL_MANIFEST Absolute manifest made by omni_snapshot.py.
  THOR_LOCAL_OMNI_MODEL_ID        Exact model id expected from RT-VLM /v1/models.

Both commands are read-only. launch-command prints an exact pull-free,
build-free Compose command but does not execute it.
EOF
}

failures=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'BLOCK %s\n' "$*" >&2; failures=$((failures + 1)); }

require_contract() {
  local model_dir=${THOR_LOCAL_OMNI_MODEL_DIR:-}
  local manifest=${THOR_LOCAL_OMNI_MODEL_MANIFEST:-}
  local model_id=${THOR_LOCAL_OMNI_MODEL_ID:-}

  [[ "$(uname -m)" == aarch64 ]] && pass "host architecture is aarch64" || fail "Omni lane is AGX Thor ARM64 only"
  if [[ -r /proc/device-tree/model ]] && grep -aFqi 'NVIDIA Jetson AGX Thor' /proc/device-tree/model; then
    pass "host reports NVIDIA Jetson AGX Thor"
  else
    fail "host does not report NVIDIA Jetson AGX Thor"
  fi

  if [[ "${minimum_memory_gib}" =~ ^[0-9]+$ ]] && (( minimum_memory_gib >= 80 )); then
    available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
    required_kib=$((minimum_memory_gib * 1024 * 1024))
    if (( available_kib >= required_kib )); then
      pass "available unified memory meets ${minimum_memory_gib} GiB conservative gate"
    else
      fail "available unified memory is $((available_kib / 1024 / 1024)) GiB; ${minimum_memory_gib} GiB is required before model start"
    fi
  else
    fail "THOR_LOCAL_OMNI_MIN_AVAILABLE_MEMORY_GIB cannot weaken the 80 GiB floor"
  fi

  if [[ -n "${model_dir}" && "${model_dir}" == /* && -d "${model_dir}" ]]; then
    case "${model_dir}/" in
      "${repo_root}/"*) fail "Omni model snapshot must remain outside the Git checkout" ;;
      *) pass "Omni model snapshot is an absolute directory outside Git" ;;
    esac
  else
    fail "THOR_LOCAL_OMNI_MODEL_DIR is not an existing absolute directory"
  fi

  if [[ -n "${manifest}" && "${manifest}" == /* && -f "${manifest}" && ! -L "${manifest}" ]]; then
    manifest_mode=$(stat -c '%a' "${manifest}")
    if [[ "${manifest_mode}" != 600 && "${manifest_mode}" != 400 ]]; then
      fail "Omni snapshot manifest must be private (mode 0600 or 0400), got ${manifest_mode}"
    elif [[ -n "${model_dir}" ]] && python3 "${snapshot_tool}" verify --model-dir "${model_dir}" --manifest "${manifest}" >/dev/null; then
      pass "Omni model snapshot matches its immutable manifest"
    else
      fail "Omni model snapshot verification failed"
    fi
  else
    fail "THOR_LOCAL_OMNI_MODEL_MANIFEST is not an existing absolute regular non-symlink file"
  fi

  if [[ -n "${model_id}" && "${model_id}" != *[[:space:]]* ]]; then
    pass "an explicit runtime /v1/models id is configured"
  else
    fail "THOR_LOCAL_OMNI_MODEL_ID must be a non-empty whitespace-free id"
  fi

  if [[ -f "${generated_env}" ]] && [[ "$(stat -c '%a' "${generated_env}")" == 600 ]]; then
    pass "protected Thor generated environment exists with mode 0600"
  else
    fail "protected Thor generated environment is missing or not mode 0600: ${generated_env}"
  fi

  if docker ps >/dev/null 2>&1; then
    pass "Docker is readable without privilege escalation"
    image_contract=$(docker image inspect --format '{{.Architecture}}|{{index .Config.Labels "com.nvidia.vss.thor.rtvi-vlm-codecs"}}|{{index .Config.Labels "com.nvidia.vss.thor.rtvi-vlm-base"}}' "${audio_image}" 2>/dev/null || true)
    if [[ "${image_contract}" == 'arm64|ubuntu-noble-arm64-offline|3.2.1' ]]; then
      pass "immutable RT-VLM codec image is staged with the expected labels"
    else
      fail "RT-VLM codec image is absent or does not match the 3.2.1 ARM64 offline contract: ${audio_image}"
    fi

    if docker ps --format '{{.Names}}' | grep -Fxq "${default_vlm_container}"; then
      fail "default image-only VLM container is still running: ${default_vlm_container}"
    else
      pass "default image-only VLM container is stopped (mutual exclusion)"
    fi
  else
    fail "Docker is not readable; image and mutual-exclusion state cannot be audited"
  fi

  for path in "${base_compose}" "${thor_compose}" "${audio_compose}"; do
    [[ -f "${path}" ]] || fail "missing Compose input: ${path}"
  done

  if (( failures == 0 )); then
    if VSS_REPO_ROOT="${repo_root}" \
      THOR_LOCAL_RTVI_AUDIO_IMAGE="${audio_image}" \
      docker compose --env-file "${generated_env}" \
        -f "${base_compose}" -f "${thor_compose}" -f "${audio_compose}" \
        --profile bp_developer_thor_full_2d config --quiet; then
      pass "resolved audio Compose graph is valid"
    else
      fail "resolved audio Compose graph is invalid"
    fi
  fi
}

print_launch_command() {
  printf '%q ' env \
    "VSS_REPO_ROOT=${repo_root}" \
    "THOR_LOCAL_OMNI_MODEL_DIR=${THOR_LOCAL_OMNI_MODEL_DIR}" \
    "THOR_LOCAL_OMNI_MODEL_ID=${THOR_LOCAL_OMNI_MODEL_ID}" \
    "THOR_LOCAL_RTVI_AUDIO_IMAGE=${audio_image}" \
    docker compose --env-file "${generated_env}" \
    -f "${base_compose}" -f "${thor_compose}" -f "${audio_compose}" \
    --profile bp_developer_thor_full_2d up -d --no-build --pull never --force-recreate \
    rtvi-vlm vss-agent lvs-server alert-bridge
  printf '\n'
}

command=${1:-}
case "${command}" in
  audit)
    require_contract
    (( failures == 0 )) || exit 2
    ;;
  launch-command)
    require_contract
    (( failures == 0 )) || exit 2
    print_launch_command
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
