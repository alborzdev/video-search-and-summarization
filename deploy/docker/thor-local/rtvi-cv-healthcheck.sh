#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -u

readonly health_url="${RTVI_CV_HEALTHCHECK_URL:-http://127.0.0.1:9000/api/v1/health/get-dsready-state}"
readonly state_dir="${RTVI_CV_HEALTHCHECK_STATE_DIR:-/tmp/rtvi-cv-healthcheck}"
readonly ready_file="${state_dir}/ready-ever"
readonly failures_file="${state_dir}/failures"
readonly restart_marker="${RTVI_CV_HEALTHCHECK_RESTART_MARKER:-}"
readonly threshold="${RTVI_CV_HEALTHCHECK_FAILURE_THRESHOLD:-3}"

if [[ ! "${threshold}" =~ ^[1-9][0-9]*$ ]]; then
  echo "rtvi-cv healthcheck: failure threshold must be a positive integer" >&2
  exit 2
fi

mkdir -p "${state_dir}"

if curl --fail --silent --show-error --connect-timeout 2 --max-time 4 "${health_url}" >/dev/null; then
  : >"${ready_file}"
  rm -f "${failures_file}"
  exit 0
fi

# TensorRT engine creation can legitimately make the first startup long. Do
# not self-restart until this exact container has answered a health request at
# least once; Docker's start_period continues to govern initial readiness.
if [[ ! -f "${ready_file}" ]]; then
  exit 1
fi

failures=0
if [[ -r "${failures_file}" ]]; then
  read -r failures <"${failures_file}" || failures=0
fi
if [[ ! "${failures}" =~ ^[0-9]+$ ]]; then
  failures=0
fi
failures=$((failures + 1))
printf '%s\n' "${failures}" >"${failures_file}"

if (( failures >= threshold )); then
  echo "rtvi-cv healthcheck: API failed ${failures} consecutive runtime probes; requesting restart" >&2
  rm -f "${failures_file}"
  if [[ -n "${restart_marker}" ]]; then
    : >"${restart_marker}"
  else
    # The supervisor is PID 1 and explicitly handles this recovery-only
    # signal. A process in a child PID namespace cannot forcibly kill that
    # namespace's init process, so an intentional handler is required.
    kill -USR1 1
  fi
fi

exit 1
