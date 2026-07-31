#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
runner="${repo_root}/deploy/docker/thor-local/qualification/acceptance.py"
tests="${repo_root}/deploy/docker/thor-local/qualification/tests/test_acceptance.py"

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

plan_is_complete_and_inert() {
  python3 "${runner}" --run-id shell-plan-001 |
    python3 -c '
import json
import sys

plan = json.load(sys.stdin)
required = {
    "execution_enabled": False,
    "mode": "plan-only",
    "network_requests_made": 0,
    "processes_started": 0,
    "resources_mutated": 0,
    "result": "pass",
}
if any(plan.get(key) != value for key, value in required.items()):
    raise SystemExit(1)
coverage = plan.get("coverage", {})
if not all(coverage.get(key, 0) > 0 for key in (
    "api_surfaces",
    "feature_capabilities",
    "feature_families",
    "mcp_prompts",
    "mcp_tools",
    "rest_operations",
    "skills",
)):
    raise SystemExit(1)
'
}

help_has_no_execution_mode() {
  local output
  output="$(python3 "${runner}" --help 2>&1)" || return 1
  ! grep -Eq -- '(^|[[:space:]])--(execute|run|apply)([=[:space:]]|$)' <<< "${output}"
}

check "stateful acceptance Python unit tests" python3 "${tests}"
check "default acceptance plan is complete and inert" plan_is_complete_and_inert
check "Phase 0 exposes no execution option" help_has_no_execution_mode

if (( failures > 0 )); then
  printf '%d stateful acceptance test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor stateful acceptance Phase 0 tests passed.\n'
