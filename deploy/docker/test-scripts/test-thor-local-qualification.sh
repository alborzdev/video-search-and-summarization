#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
thor_local="${repo_root}/deploy/docker/scripts/thor-local.sh"
qualifier="${repo_root}/deploy/docker/thor-local/qualification/qualify.py"
tests="${repo_root}/deploy/docker/thor-local/qualification/tests"

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

help_has_qualification() {
  "${thor_local}" help 2>&1 | grep -q 'qualify --tier contract|runtime'
}

source_mode_exposes_qualification() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    declare -F qualify_contract >/dev/null
  ' _ "${thor_local}"
}

contract_command_is_offline() {
  local output
  output="$("${thor_local}" qualify --tier contract 2>&1)" &&
    grep -q 'PASS: qualified 17 Thor VSS API surfaces offline' <<< "${output}" &&
    grep -q '44 MCP tools plus 5 MCP prompts' <<< "${output}" &&
    ! grep -Eqi 'docker|container start|https?://' <<< "${output}"
}

operator_wrapper_rejects_regeneration() {
  local output
  if output="$("${thor_local}" qualify --regenerate 2>&1)"; then
    return 1
  fi
  grep -q 'qualify is read-only' <<< "${output}"
}

runtime_wrapper_routes_without_probing() {
  "${thor_local}" qualify --tier runtime --help 2>&1 |
    grep -q 'isolated, read-only runtime qualification'
}

json_result_is_machine_readable() {
  python3 "${qualifier}" --tier contract --json |
    python3 -c 'import json,sys; value=json.load(sys.stdin); raise SystemExit(0 if value.get("result") == "pass" and value.get("offline") is True else 1)'
}

check "Thor-local shell syntax" bash -n "${thor_local}"
check "help exposes offline contract qualification" help_has_qualification
check "source-only mode exposes qualification helper" source_mode_exposes_qualification
check "qualification unit tests" python3 -m unittest discover -s "${tests}" -p 'test_*.py'
check "Thor-local qualification command is offline" contract_command_is_offline
check "operator wrapper rejects manifest regeneration" operator_wrapper_rejects_regeneration
check "operator wrapper exposes read-only runtime qualification" runtime_wrapper_routes_without_probing
check "qualification JSON is machine-readable" json_result_is_machine_readable

if (( failures > 0 )); then
  printf '%d qualification test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor-local qualification tests passed.\n'
