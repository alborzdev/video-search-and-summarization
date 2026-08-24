#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -u

child_pid=""
requested_exit=-1
child_status=1

forward_signal() {
  local signal_name="$1"
  local exit_status="$2"
  requested_exit="${exit_status}"
  if [[ -n "${child_pid}" ]] && kill -0 "${child_pid}" 2>/dev/null; then
    kill -"${signal_name}" "${child_pid}" 2>/dev/null || true
  fi
}

# USR1 is private to the Thor-local healthcheck. Exit 70 so Docker's
# on-failure/unless-stopped policy replaces the container after the child has
# shut down. Normal Docker stops remain successful and do not restart.
trap 'forward_signal TERM 70' USR1
trap 'forward_signal TERM 0' TERM INT

"$@" &
child_pid=$!

while kill -0 "${child_pid}" 2>/dev/null; do
  wait "${child_pid}"
  child_status=$?
done

if (( requested_exit >= 0 )); then
  exit "${requested_exit}"
fi
exit "${child_status}"
