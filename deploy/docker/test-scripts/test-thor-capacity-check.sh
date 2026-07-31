#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "${script_dir}/../../.." && pwd)
capacity_check="${repo_root}/deploy/docker/scripts/thor-capacity-check.sh"
failures=0

check() {
  local description=$1
  shift
  if "$@"; then
    printf 'PASS: %s\n' "${description}"
  else
    printf 'FAIL: %s\n' "${description}" >&2
    failures=$((failures + 1))
  fi
}

has_safe_lifecycle() {
  grep -q 'minimum_available_kib=.*3145728' "${capacity_check}" \
    && grep -q 'available < minimum_available_kib' "${capacity_check}" \
    && grep -q 'trap cleanup EXIT INT TERM' "${capacity_check}" \
    && grep -q '/api/v1/rtsp-streams/delete/' "${capacity_check}" \
    && grep -q '_delete_by_query?conflicts=proceed&refresh=true' "${capacity_check}" \
    && grep -q '/api/v1/stream/get-stream-info' "${capacity_check}"
}

does_not_mutate_stack_lifecycle() {
  ! grep -Eq 'docker (compose|restart|stop|rm|pull|build)|thor-local\.sh (up|restart|down|stop)' \
    "${capacity_check}"
}

measures_full_stream_path() {
  grep -q '/api/v1/rtsp-streams/add' "${capacity_check}" \
    && grep -Fq 'mdx-embed-filtered-*/_count' "${capacity_check}" \
    && grep -q 'fps_reading' "${capacity_check}" \
    && grep -iq 'two-stream embedding throughput' "${capacity_check}"
}

help_documents_bounds() {
  local output
  output=$("${capacity_check}" --help 2>&1)
  grep -q 'bounded 1 -> 2 live-stream capacity check' <<<"${output}"
}

check 'capacity script has valid Bash syntax' bash -n "${capacity_check}"
check 'capacity script enforces health, memory, and cleanup contracts' has_safe_lifecycle
check 'capacity script never rebuilds or restarts the shared stack' does_not_mutate_stack_lifecycle
check 'capacity script measures DeepStream and Cosmos Embed throughput' measures_full_stream_path
check 'capacity help states its bounded concurrency' help_documents_bounds

if (( failures > 0 )); then
  printf '%d capacity-check test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor capacity-check tests passed.\n'
