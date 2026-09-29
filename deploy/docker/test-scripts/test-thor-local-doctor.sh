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
    declare -F doctor_check_docker_prerequisite >/dev/null
    declare -F require_docker_cgroup_driver >/dev/null
    declare -F ensure_operator_runtime_directories >/dev/null
  ' _ "${thor_local}"
}

doctor_reports_cgroup_driver() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    docker() {
      [[ "$1" == info && "$2" == --format ]] || return 91
      printf "systemd\n"
    }
    doctor_reset
    doctor_check_docker_prerequisite >"$2/doctor-cgroup.out"
    [[ ${doctor_failures} -eq 1 ]] &&
      grep -q "Docker cgroup driver is.*systemd" "$2/doctor-cgroup.out" &&
      grep -q "native.cgroupdriver=cgroupfs" "$2/doctor-cgroup.out"
  ' _ "${thor_local}" "${temporary_root}"
}

cgroupfs_driver_is_accepted() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    docker() {
      [[ "$1" == info && "$2" == --format ]] || return 91
      printf "cgroupfs\n"
    }
    require_docker_cgroup_driver
  ' _ "${thor_local}"
}

systemd_driver_is_rejected_with_remediation() {
  local output status
  set +e
  output="$(THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    docker() {
      [[ "$1" == info && "$2" == --format ]] || return 91
      printf "systemd\n"
    }
    require_docker_cgroup_driver
  ' _ "${thor_local}" 2>&1)"
  status=$?
  set -e
  [[ ${status} -ne 0 ]] &&
    grep -q "Docker cgroup driver is.*systemd" <<<"${output}" &&
    grep -q "native.cgroupdriver=cgroupfs" <<<"${output}" &&
    grep -q "/etc/docker/daemon.json" <<<"${output}" &&
    grep -q "restart Docker" <<<"${output}"
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

stop_contains_every_fail_closed_overlay_service() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    test_root="$2"
    docker() {
      printf "%s\n" "$*" >>"${test_root}/docker.out"
      if [[ "$1 $2" == "inspect --format" ]]; then
        printf "true\n"
      fi
      return 0
    }
    stop_fail_closed_containers >"${test_root}/stop.out"
    grep -q "update --restart=no vss-vios-nvstreamer" "${test_root}/docker.out" &&
      grep -q "stop --timeout 15 vss-vios-nvstreamer" "${test_root}/docker.out" &&
      grep -q "update --restart=no vss-nemotron-edge-4b" "${test_root}/docker.out" &&
      grep -q "stop --timeout 15 vss-nemotron-edge-4b" "${test_root}/docker.out" &&
      grep -q "update --restart=no vss-alert-bridge" "${test_root}/docker.out" &&
      grep -q "stop --timeout 15 vss-alert-bridge" "${test_root}/docker.out" &&
      grep -q "model, and GPU-heavy containers are stopped" "${test_root}/stop.out"
  ' _ "${thor_local}" "${temporary_root}"
}

containment_attempts_every_target_after_an_error() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    test_root="$2"
    docker() {
      printf "%s\n" "$*" >>"${test_root}/docker-errors.out"
      if [[ "$1 $2 $3" == "update --restart=no vss-nemotron-edge-4b" ]]; then
        return 42
      fi
      if [[ "$1 $2" == "inspect --format" ]]; then
        printf "true\n"
      fi
      return 0
    }
    containment_failures=0
    stop_fail_closed_containers >"${test_root}/stop-errors.out" 2>&1
    [[ ${containment_failures} -eq 1 ]] &&
      grep -q "stop --timeout 15 vss-nemotron-edge-4b" "${test_root}/docker-errors.out" &&
      grep -q "stop --timeout 15 vss-vios-sensor" "${test_root}/docker-errors.out"
  ' _ "${thor_local}" "${temporary_root}"
}

stop_does_not_require_the_runtime_env_for_containment() {
  local stop_block
  stop_block="$(sed -n '/^  stop)$/,/^    ;;/p' "${thor_local}")"
  [[ "${stop_block}" == *"stop_fail_closed_containers"* ]] &&
    [[ "${stop_block}" == *"stop_application_project_containers"* ]] &&
    [[ "${stop_block}" != *'die "Missing ${generated_env}"'* ]]
}

down_does_not_require_the_runtime_env_for_containment() {
  local down_block
  down_block="$(sed -n '/^  down)$/,/^    ;;/p' "${thor_local}")"
  [[ "${down_block}" == *"stop_fail_closed_containers"* ]] &&
    [[ "${down_block}" == *"stop_application_project_containers"* ]] &&
    [[ "${down_block}" != *'die "Missing ${generated_env}"'* ]]
}

exact_lane_doctor_enforces_empirical_headroom() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    official_edge_lane_is_deployed() { return 0; }
    nvidia-smi() { printf "NVIDIA Thor, 43, 0\n"; }
    awk() {
      if [[ "$*" == *"MemTotal:"* ]]; then
        printf "134217728\n"
      elif [[ "$*" == *"MemAvailable:"* ]]; then
        printf "111149056\n"
      else
        command awk "$@"
      fi
    }
    df() {
      printf "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
      printf "/dev/test 1000000000 800000000 200000000 80%% /\n"
    }
    data_directory="$2"
    doctor_reset
    doctor_check_gpu_and_resources >"$2/exact-memory.out"
    [[ ${doctor_failures} -eq 1 ]] &&
      grep -q "empirical admission requires at least 128 GiB" "$2/exact-memory.out"
  ' _ "${thor_local}" "${temporary_root}"
}

disk_percentage_does_not_override_ten_gib_floor() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    official_edge_lane_is_deployed() { return 1; }
    nvidia-smi() {
      printf "NVIDIA Thor, 43, 0\n"
    }
    df() {
      printf "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
      printf "/dev/test 1000000000 981125632 18874368 98%% /\n"
    }
    data_directory="$2"
    doctor_reset
    doctor_check_gpu_and_resources >"$2/disk-warning.out"
    [[ ${doctor_failures} -eq 0 && ${doctor_warnings} -eq 1 ]] &&
      grep -q "18 GiB free, 98% used" "$2/disk-warning.out"
  ' _ "${thor_local}" "${temporary_root}"
}

disk_below_ten_gib_remains_fatal() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    official_edge_lane_is_deployed() { return 1; }
    nvidia-smi() {
      printf "NVIDIA Thor, 43, 0\n"
    }
    df() {
      printf "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
      printf "/dev/test 1000000000 990562816 9437184 99%% /\n"
    }
    data_directory="$2"
    doctor_reset
    doctor_check_gpu_and_resources >"$2/disk-failure.out"
    [[ ${doctor_failures} -eq 1 ]] &&
      grep -q "9 GiB free, 99% used" "$2/disk-failure.out"
  ' _ "${thor_local}" "${temporary_root}"
}

check "shell syntax" bash -n "${thor_local}"
check "help exposes the operator doctor" help_has_doctor
check "source-only mode loads doctor helpers without dispatch" source_mode_loads_without_dispatch
check "preflight accepts NVIDIA's required cgroupfs driver" cgroupfs_driver_is_accepted
check "preflight rejects systemd cgroups with exact remediation" systemd_driver_is_rejected_with_remediation
check "doctor reports a noncompliant Docker cgroup driver" doctor_reports_cgroup_driver
check "warnings exit zero and failures exit nonzero" severity_contract_is_stable
check "startup provisioner creates a private report directory" report_directory_is_private
check "doctor is offline-only and does not disclose secrets" doctor_is_explicitly_offline_and_secret_safe
check "stop contains exact overlays and the separate media source" stop_contains_every_fail_closed_overlay_service
check "containment attempts every target after a Docker error" containment_attempts_every_target_after_an_error
check "emergency containment does not depend on the runtime env" stop_does_not_require_the_runtime_env_for_containment
check "destructive down contains first without the runtime env" down_does_not_require_the_runtime_env_for_containment
check "exact lane doctor enforces empirical headroom" exact_lane_doctor_enforces_empirical_headroom
check "98% usage with 18 GiB free is a warning" disk_percentage_does_not_override_ten_gib_floor
check "less than 10 GiB free remains fatal" disk_below_ten_gib_remains_fatal

if (( failures > 0 )); then
  printf '%d doctor test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor doctor tests passed.\n'
