#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
compose_file="${repo_root}/deploy/docker/services/auto-calibration/compose.yml"

resolve_ui_api_url() {
  local canonical_value="$1"
  local legacy_value="$2"
  local -a overrides=()
  local resolved

  if [[ "${canonical_value}" != "__UNSET__" ]]; then
    overrides+=("VSS_AUTO_CALIBRATION_MS_API_URL=${canonical_value}")
  fi
  if [[ "${legacy_value}" != "__UNSET__" ]]; then
    overrides+=("AUTO_CALIBRATION_MS_API_URL=${legacy_value}")
  fi

  resolved="$({
    env \
      -u VSS_AUTO_CALIBRATION_MS_API_URL \
      -u AUTO_CALIBRATION_MS_API_URL \
      "${overrides[@]}" \
      COMPOSE_PROFILES=auto_calib \
      VSS_APPS_DIR="${repo_root}/deploy/docker" \
      VSS_DATA_DIR="${repo_root}/deploy/docker/data-dir" \
      HOST_IP=192.0.2.10 \
      VSS_AUTO_CALIBRATION_PORT=18010 \
      docker compose -f "${compose_file}" config --format json
  } 2>/dev/null)"

  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
print(payload["services"]["vss-auto-calibration-ui"]["environment"]["API_URL"])
' <<< "${resolved}"
}

canonical_url="http://127.0.0.1:28010/v1"
legacy_url="http://legacy.example.test:38010/v1"

[[ "$(resolve_ui_api_url "${canonical_url}" "${legacy_url}")" == "${canonical_url}" ]]
[[ "$(resolve_ui_api_url __UNSET__ "${legacy_url}")" == "${legacy_url}" ]]
[[ "$(resolve_ui_api_url __UNSET__ __UNSET__)" == "http://192.0.2.10:18010/v1" ]]

echo "Auto-calibration UI endpoint Compose contract passed."
