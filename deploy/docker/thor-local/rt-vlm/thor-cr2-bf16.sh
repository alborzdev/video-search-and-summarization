#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Read-only gate and pull-free command renderer. It never changes containers.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../../.." && pwd)"
deployment_dir="${repo_root}/deploy/docker"
matrix="${script_dir}/model-matrix.json"
artifact_lock="${script_dir}/artifacts.lock.json"
matrix_tool="${script_dir}/model_matrix.py"
budget_tool="${script_dir}/memory_budget.py"
base_compose="${deployment_dir}/compose.yml"
thor_compose="${deployment_dir}/thor-local/compose.yml"
cr2_compose="${script_dir}/cr2-bf16.compose.yml"
runtime_source="${repo_root}/services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py"
generated_env="${THOR_LOCAL_GENERATED_ENV_FILE:-${deployment_dir}/thor-local/generated.env}"
repository_root="${THOR_LOCAL_CR2_REPOSITORY_ROOT:-}"
rtvi_image="${THOR_LOCAL_RTVI_VLM_IMAGE:-cti-vss-rt-vlm:thor-local}"
utilization="${THOR_LOCAL_CR2_GPU_MEMORY_UTILIZATION:-0.35}"
default_vlm_container="${THOR_LOCAL_DEFAULT_VLM_CONTAINER:-cti-vss-qwen3-vl}"

usage() {
  cat <<'EOF'
Usage: thor-cr2-bf16.sh audit|launch-command

Required environment:
  THOR_LOCAL_CR2_REPOSITORY_ROOT  Absolute Hugging Face repository cache root
                                  for nvidia/Cosmos-Reason2-8B.

Both commands are read-only. launch-command prints a pull-free, build-free
Compose command and does not execute it. No Thor runtime qualification is
implied by a successful audit.
EOF
}

failures=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'BLOCK %s\n' "$*" >&2; failures=$((failures + 1)); }

require_contract() {
  if PYTHONDONTWRITEBYTECODE=1 python3 "${matrix_tool}" \
      --matrix "${matrix}" --artifact-lock "${artifact_lock}" \
      --repo-root "${repo_root}" validate >/dev/null; then
    pass "reviewed model matrix matches its source and artifact locks"
  else
    fail "reviewed model matrix validation failed"
  fi

  [[ "$(uname -m)" == aarch64 ]] && pass "host architecture is aarch64" || fail "CR2 lane is AGX Thor ARM64 only"
  if [[ -r /proc/device-tree/model ]] && grep -aFqi 'NVIDIA Jetson AGX Thor' /proc/device-tree/model; then
    pass "host reports NVIDIA Jetson AGX Thor"
  else
    fail "host does not report NVIDIA Jetson AGX Thor"
  fi

  if [[ -n "${repository_root}" && "${repository_root}" == /* && -d "${repository_root}" ]]; then
    case "${repository_root}/" in
      "${repo_root}/"*) fail "CR2 Hugging Face repository must remain outside the Git checkout" ;;
      *) pass "CR2 Hugging Face repository is an absolute directory outside Git" ;;
    esac
    if PYTHONDONTWRITEBYTECODE=1 python3 "${matrix_tool}" \
        --matrix "${matrix}" --artifact-lock "${artifact_lock}" \
        --repo-root "${repo_root}" verify-local \
        --artifact cosmos_reason2_8b_bf16_hf \
        --repository-root "${repository_root}" >/dev/null; then
      pass "official Cosmos Reason2 8B snapshot matches every locked byte and semantic"
    else
      fail "official Cosmos Reason2 8B snapshot verification failed"
    fi
  else
    fail "THOR_LOCAL_CR2_REPOSITORY_ROOT is not an existing absolute directory"
  fi

  if PYTHONDONTWRITEBYTECODE=1 python3 "${budget_tool}" --utilization "${utilization}" >/dev/null; then
    pass "unified memory preserves the fixed 20% reserve at utilization ${utilization}"
  else
    fail "unified memory cannot preserve the fixed 20% reserve at utilization ${utilization}"
  fi

  if [[ -f "${runtime_source}" && ! -L "${runtime_source}" ]] \
      && grep -Fq 'VLM_RUNTIME_STATE_DIR' "${runtime_source}"; then
    pass "writable runtime-state source overlay is present"
  else
    fail "writable runtime-state source overlay is absent or linked"
  fi

  if [[ -f "${generated_env}" ]] && [[ "$(stat -c '%a' "${generated_env}")" == 600 ]]; then
    pass "protected Thor generated environment exists with mode 0600"
  else
    fail "protected Thor generated environment is missing or not mode 0600: ${generated_env}"
  fi

  if docker ps >/dev/null 2>&1; then
    pass "Docker is readable without privilege escalation"
    image_arch=$(docker image inspect --format '{{.Architecture}}' "${rtvi_image}" 2>/dev/null || true)
    [[ "${image_arch}" == arm64 ]] && pass "pull-free ARM64 RT-VLM image is staged" || fail "ARM64 RT-VLM image is absent: ${rtvi_image}"
    if docker ps --format '{{.Names}}' | grep -Fxq "${default_vlm_container}"; then
      fail "default image-only VLM container is still running: ${default_vlm_container}"
    else
      pass "default image-only VLM container is stopped (mutual exclusion)"
    fi
  else
    fail "Docker is not readable; image and mutual-exclusion state cannot be audited"
  fi

  for path in "${base_compose}" "${thor_compose}" "${cr2_compose}"; do
    [[ -f "${path}" ]] || fail "missing Compose input: ${path}"
  done
  if (( failures == 0 )); then
    if VSS_REPO_ROOT="${repo_root}" \
      THOR_LOCAL_CR2_REPOSITORY_ROOT="${repository_root}" \
      THOR_LOCAL_CR2_GPU_MEMORY_UTILIZATION="${utilization}" \
      docker compose --env-file "${generated_env}" \
        -f "${base_compose}" -f "${thor_compose}" -f "${cr2_compose}" \
        --profile bp_developer_thor_full_2d config --quiet; then
      pass "resolved CR2 Compose graph is valid"
    else
      fail "resolved CR2 Compose graph is invalid"
    fi
  fi
}

print_launch_command() {
  printf '%q ' env \
    "VSS_REPO_ROOT=${repo_root}" \
    "THOR_LOCAL_CR2_REPOSITORY_ROOT=${repository_root}" \
    "THOR_LOCAL_CR2_GPU_MEMORY_UTILIZATION=${utilization}" \
    "THOR_LOCAL_RTVI_VLM_IMAGE=${rtvi_image}" \
    docker compose --env-file "${generated_env}" \
    -f "${base_compose}" -f "${thor_compose}" -f "${cr2_compose}" \
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
