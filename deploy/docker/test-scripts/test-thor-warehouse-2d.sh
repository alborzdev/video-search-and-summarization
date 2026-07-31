#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
launcher="${repo_root}/deploy/docker/scripts/thor-warehouse-2d.sh"
renderer="${repo_root}/deploy/docker/thor-local/render-warehouse-2d-env.py"
overlay="${repo_root}/deploy/docker/thor-local/warehouse-2d.compose.yml"
blueprint="${repo_root}/deploy/docker/industry-profiles/warehouse-operations/blueprint-configurator/blueprint_config.yml"
temporary_root="$(mktemp -d)"
trap 'rm -rf -- "${temporary_root}"' EXIT

failures=0

check() {
  local description="$1"
  shift
  if "$@"; then
    printf 'PASS: %s\n' "${description}"
  else
    printf 'FAIL: %s\n' "${description}" >&2
    ((failures += 1))
  fi
}

agx_profile_matches_igx_and_agent_guard() {
  python3 - "${blueprint}" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    config = yaml.safe_load(handle)

assert config["AGX-THOR"] == config["IGX-THOR"]
validations = config["commons"]["variable_validation"]["2d"]
guard = next(
    item for item in validations
    if item.get("variable") == "HARDWARE_PROFILE"
    and item.get("condition", {}).get("variable") == "BP_PROFILE"
)
assert {"IGX-THOR", "AGX-THOR", "DGX-SPARK"}.issubset(guard["disallowed_values"])
PY
}

source_mode_exposes_safe_helpers() {
  THOR_WAREHOUSE_SOURCE_ONLY=true bash -c '
    source "$1"
    declare -F prepare_runtime >/dev/null
    declare -F validate_compose >/dev/null
    declare -F check_required_images >/dev/null
    declare -F preflight >/dev/null
  ' _ "${launcher}"
}

launcher_has_no_lifecycle_or_privileged_actions() {
  ! grep -Eq '"?\$\{docker_bin\}"? compose .*(up|down|start|stop|pull|build)|docker (run|rm|restart)|sudo ' "${launcher}"
}

prepare_fixture() {
  local source_data="${temporary_root}/official-app-data"
  local runtime="${temporary_root}/runtime"
  local model_dir="${source_data}/models/mtmc"
  local videos_dir="${source_data}/videos/warehouse-loading-dock-3cams-synthetic"
  local source_hash blueprint_before blueprint_after

  mkdir -p "${model_dir}" "${videos_dir}"
  printf 'fake-onnx-for-static-test\n' > "${model_dir}/rtdetr_warehouse_v1.0.2.fp16.onnx"
  printf 'camera-0\n' > "${videos_dir}/Camera.mp4"
  printf 'camera-1\n' > "${videos_dir}/Camera_01.mp4"
  printf 'camera-2\n' > "${videos_dir}/Camera_02.mp4"
  source_hash="$(sha256sum "${model_dir}/rtdetr_warehouse_v1.0.2.fp16.onnx" "${videos_dir}/"*.mp4)"
  blueprint_before="$(sha256sum "${blueprint}")"

  THOR_WAREHOUSE_APP_DATA_SOURCE="${source_data}" \
    THOR_WAREHOUSE_RUNTIME_DIR="${runtime}" \
    THOR_WAREHOUSE_NUM_STREAMS=1 \
    "${launcher}" prepare >/dev/null

  blueprint_after="$(sha256sum "${blueprint}")"
  [[ "${blueprint_before}" == "${blueprint_after}" ]] || return 1
  [[ "${source_hash}" == "$(sha256sum "${model_dir}/rtdetr_warehouse_v1.0.2.fp16.onnx" "${videos_dir}/"*.mp4)" ]] || return 1
  [[ "$(stat -c %a "${runtime}/generated.env")" == "600" ]] || return 1
  [[ "$(find "${runtime}/data/videos/warehouse-loading-dock-3cams-synthetic" -type f -name '*.mp4' | wc -l)" == "1" ]] || return 1
  [[ "$(stat -c %i "${model_dir}/rtdetr_warehouse_v1.0.2.fp16.onnx")" != \
     "$(stat -c %i "${runtime}/data/models/mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx")" ]] || return 1
  grep -q '^HARDWARE_PROFILE=AGX-THOR$' "${runtime}/generated.env" || return 1
  grep -q '^BP_PROFILE=bp_wh_redis$' "${runtime}/generated.env" || return 1
  grep -q '^COMPOSE_PROFILES=bp_wh_redis_2d$' "${runtime}/generated.env" || return 1
  grep -q '^NUM_STREAMS=1$' "${runtime}/generated.env" || return 1
  grep -q '^NGC_CLI_API_KEY=' "${runtime}/generated.env" || return 1

  local validate_output
  if ! validate_output="$(THOR_WAREHOUSE_RUNTIME_DIR="${runtime}" \
      "${launcher}" validate 2>&1)"; then
    printf '%s\n' "${validate_output}" >&2
    return 1
  fi

  ! THOR_WAREHOUSE_APP_DATA_SOURCE="${source_data}" \
      THOR_WAREHOUSE_RUNTIME_DIR="${runtime}" \
      "${launcher}" prepare >/dev/null 2>&1
}

missing_images_fail_closed_without_pulling() {
  local output
  if output="$(THOR_WAREHOUSE_SOURCE_ONLY=true \
      THOR_WAREHOUSE_DOCKER_BIN=false \
      bash -c '
        source "$1"
        check_required_images '\''{"services":{"missing":{"image":"example.invalid/vss/missing:3.2.1"}}}'\''
      ' _ "${launcher}" 2>&1)"; then
    return 1
  fi
  grep -q 'Missing local images (preflight never pulls)' <<< "${output}" &&
    grep -q 'example.invalid/vss/missing:3.2.1' <<< "${output}"
}

missing_app_data_fails_before_state_creation() {
  local source_data="${temporary_root}/incomplete-app-data"
  local runtime="${temporary_root}/incomplete-runtime"
  local output
  mkdir -p "${source_data}/videos/warehouse-loading-dock-3cams-synthetic"
  if output="$(THOR_WAREHOUSE_APP_DATA_SOURCE="${source_data}" \
      THOR_WAREHOUSE_RUNTIME_DIR="${runtime}" "${launcher}" prepare 2>&1)"; then
    return 1
  fi
  [[ ! -e "${runtime}" ]] && grep -q 'warehouse model is missing' <<< "${output}"
}

renderer_rejects_source_overwrite() {
  local env_copy="${temporary_root}/source.env"
  cp "${repo_root}/deploy/docker/industry-profiles/warehouse-operations/.env" "${env_copy}"
  ! python3 "${renderer}" --source "${env_copy}" --output "${env_copy}" \
      --apps-dir /tmp/apps --data-dir /tmp/data \
      --bp-configurator-env-file /tmp/generated.env --repo-root "${repo_root}" \
      --streams 1 >/dev/null 2>&1
}

overlay_declares_offline_thor_contract() {
  grep -q '^  nvstreamer-2d:' "${overlay}" &&
    grep -q 'THOR_WAREHOUSE_NVSTREAMER_IMAGE' "${overlay}" &&
    grep -q 'runtime: nvidia' "${overlay}" &&
    grep -q 'TRANSFORMERS_OFFLINE: "1"' "${overlay}" &&
    grep -q 'HF_HUB_OFFLINE: "1"' "${overlay}" &&
    grep -q 'VST_INSTALL_ADDITIONAL_PACKAGES: "false"' "${overlay}" &&
    grep -q -- '--protected-mode' "${overlay}"
}

check "launcher shell syntax" bash -n "${launcher}"
check "renderer Python syntax" python3 -c "import ast; ast.parse(open('${renderer}', encoding='utf-8').read())"
check "AGX profile aliases IGX tuning and rejects bp_wh agents" agx_profile_matches_igx_and_agent_guard
check "source-only mode exposes safe test helpers" source_mode_exposes_safe_helpers
check "launcher contains no lifecycle or privileged operations" launcher_has_no_lifecycle_or_privileged_actions
check "overlay declares offline Thor runtime fixes" overlay_declares_offline_thor_contract
check "prepare copies mutable state and validates exact Compose graph" prepare_fixture
check "missing official app data fails before state creation" missing_app_data_fails_before_state_creation
check "missing local image fails closed without pulling" missing_images_fail_closed_without_pulling
check "environment renderer refuses source overwrite" renderer_rejects_source_overwrite

if (( failures > 0 )); then
  printf '%d warehouse-2D test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor warehouse-2D static tests passed.\n'
