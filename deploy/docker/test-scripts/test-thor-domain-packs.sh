#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
thor_local="${repo_root}/deploy/docker/scripts/thor-local.sh"
failures=0

check() {
  local name="$1"
  shift
  if "$@"; then
    printf 'PASS: %s\n' "${name}"
  else
    printf 'FAIL: %s\n' "${name}" >&2
    ((failures += 1))
  fi
}

help_has_domain_command() {
  "${thor_local}" help 2>&1 | grep -q 'domain list|show <id>|apply <id>|current'
}

list_has_all_packs() {
  local output
  output="$("${thor_local}" domain list)"
  grep -q 'general' <<< "${output}" &&
    grep -q 'industrial-safety' <<< "${output}" &&
    grep -q 'retail' <<< "${output}" &&
    grep -q 'site-security' <<< "${output}"
}

show_exposes_honest_demo_contract() {
  local output
  output="$("${thor_local}" domain show retail)"
  grep -q 'Demo questions:' <<< "${output}" &&
    grep -q 'Search prompts:' <<< "${output}" &&
    grep -q 'Candidate-verification seeds:' <<< "${output}" &&
    grep -q '(4 frames)' <<< "${output}"
}

current_uses_private_selection_file() {
  local directory current output
  directory="$(mktemp -d)"
  current="${directory}/current"
  printf 'site-security\n' > "${current}"
  chmod 600 "${current}"
  output="$(env -u NEXT_PUBLIC_APP_TITLE -u NEXT_PUBLIC_APP_SUBTITLE \
    THOR_LOCAL_DOMAIN_CURRENT_FILE="${current}" "${thor_local}" domain current)"
  rm -rf "${directory}"
  grep -q '^Current domain pack: site-security$' <<< "${output}" &&
    grep -q 'THOR SITE INTELLIGENCE' <<< "${output}"
}

invalid_pack_fails_closed() {
  ! "${thor_local}" domain show '../../unsafe' >/dev/null 2>&1
}

source_mode_exposes_domain_helpers() {
  THOR_LOCAL_SOURCE_ONLY=true source "${thor_local}"
  declare -F domain_apply >/dev/null &&
    declare -F domain_list >/dev/null &&
    declare -F write_current_domain_pack >/dev/null
}

check "help exposes the domain-pack operator command" help_has_domain_command
check "list exposes all versioned packs" list_has_all_packs
check "show exposes demo, search, and bounded verification prompts" show_exposes_honest_demo_contract
check "current honors the protected pack selection" current_uses_private_selection_file
check "invalid pack ids fail closed" invalid_pack_fails_closed
check "source-only mode exposes testable domain helpers" source_mode_exposes_domain_helpers

if ((failures > 0)); then
  printf '%d Thor domain-pack test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor domain-pack shell tests passed.\n'
