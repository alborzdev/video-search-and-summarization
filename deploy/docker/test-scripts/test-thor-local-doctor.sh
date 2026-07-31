#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
thor_local="${repo_root}/deploy/docker/scripts/thor-local.sh"
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

help_has_doctor() {
  "${thor_local}" help 2>&1 | grep -q 'doctor.*Read-only, offline-safe'
}

source_mode_loads_without_dispatch() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    declare -F doctor >/dev/null
    declare -F doctor_check_runtime_security >/dev/null
    declare -F doctor_check_network_security >/dev/null
    declare -F ensure_operator_runtime_directories >/dev/null
  ' _ "${thor_local}"
}

severity_contract_is_stable() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    set +e
    doctor_reset
    doctor_pass "unit pass" >"$2/events.out"
    doctor_warn "unit warning" >>"$2/events.out"
    doctor_finish >"$2/warn.out"
    warning_status=$?
    doctor_fail "unit failure" >>"$2/events.out"
    doctor_finish >"$2/fail.out"
    failure_status=$?
    [[ ${warning_status} -eq 0 && ${failure_status} -eq 1 ]] &&
      grep -q "1 PASS, 1 WARN, 0 FAIL" "$2/warn.out" &&
      grep -q "1 PASS, 1 WARN, 1 FAIL" "$2/fail.out"
  ' _ "${thor_local}" "${temporary_root}"
}

report_directory_is_private() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    data_directory="$2/data"
    ensure_operator_runtime_directories
    report_dir="$data_directory/agent-reports"
    [[ -d "$report_dir" ]] &&
      [[ "$(stat -c %a "$report_dir")" == 700 ]] &&
      [[ "$(stat -c %u "$report_dir")" == "$(id -u)" ]]
  ' _ "${thor_local}" "${temporary_root}"
}

doctor_is_explicitly_offline_and_secret_safe() {
  grep -q 'Thor VSS doctor (read-only; no external network calls)' "${thor_local}" &&
    grep -q 'value not displayed' "${thor_local}" &&
    grep -q 'env -u NGC_CLI_API_KEY -u NGC_API_KEY' "${thor_local}" &&
    ! sed -n '/^doctor()/,/^}/p' "${thor_local}" | grep -Eq 'curl .*https?://[^$]*\.(com|io|ai|org)'
}

check "shell syntax" bash -n "${thor_local}"
check "help exposes the operator doctor" help_has_doctor
check "source-only mode loads doctor helpers without dispatch" source_mode_loads_without_dispatch
check "warnings exit zero and failures exit nonzero" severity_contract_is_stable
check "startup provisioner creates a private report directory" report_directory_is_private
check "doctor is offline-only and does not disclose secrets" doctor_is_explicitly_offline_and_secret_safe

if (( failures > 0 )); then
  printf '%d doctor test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor doctor tests passed.\n'
