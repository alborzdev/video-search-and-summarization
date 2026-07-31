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

help_exposes_contract_and_security() {
  "${thor_local}" help 2>&1 | grep -q 'model-check' &&
    "${thor_local}" help 2>&1 | grep -q 'security firewall-plan'
}

firewall_plan_is_narrow() {
  local interface
  interface="$(ip route show default | awk '/ dev / {for(i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')"
  [[ -n "${interface}" ]] || return 1
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    plan="$(security_firewall_ruleset "$2")"
    grep -q "table inet cti_vss" <<<"$plan" &&
      grep -q "hook input" <<<"$plan" &&
      grep -q "hook forward" <<<"$plan" &&
      grep -q "iifname.*\"$2\"" <<<"$plan" &&
      ! grep -Eq "(^|[, {])22([, }]|$)" <<<"$plan"
  ' _ "${thor_local}" "${interface}"
}

firewall_rejects_container_interfaces() {
  ! THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    security_firewall_ruleset lo >/dev/null 2>&1
  ' _ "${thor_local}"
}

mock_model_contract_accepts_four_images_without_key_in_argv() {
  local fake_bin="${temporary_root}/bin"
  mkdir -p "${fake_bin}"
  cat > "${fake_bin}/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${MOCK_CURL_LOG}"
url="${!#}"
if [[ "${url}" == */v1/models ]]; then
  if [[ "${url}" == *:18000/* ]]; then
    printf '{"data":[{"id":"test-llm"}]}\n'
  else
    printf '{"data":[{"id":"test-vlm"}]}\n'
  fi
  exit 0
fi
output=""
request=""
previous=""
for argument in "$@"; do
  if [[ "${previous}" == "--output" ]]; then output="${argument}"; fi
  if [[ "${previous}" == "--data-binary" ]]; then request="${argument#@}"; fi
  previous="${argument}"
done
[[ -n "${output}" && -n "${request}" ]]
if [[ "${url}" == *:18001/* ]]; then
  python3 - "${request}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
content = payload["messages"][0]["content"]
assert sum(item.get("type") == "image_url" for item in content) == 4
PY
fi
printf '{"choices":[{"message":{"content":"ok"}}]}\n' > "${output}"
printf '200'
MOCK
  chmod +x "${fake_bin}/curl"
  MOCK_CURL_LOG="${temporary_root}/curl.log" \
  PATH="${fake_bin}:${PATH}" \
  LLM_ENDPOINT_URL=http://127.0.0.1:18000 \
  VLM_ENDPOINT_URL=http://127.0.0.1:18001 \
  THOR_LOCAL_LLM_MODEL=test-llm \
  THOR_LOCAL_VLM_MODEL=test-vlm \
  OPENAI_API_KEY=unit-test-secret \
  THOR_LOCAL_SOURCE_ONLY=true \
    bash -c 'source "$1"; check_local_model_contracts' _ "${thor_local}" >/dev/null &&
    ! grep -q 'unit-test-secret' "${temporary_root}/curl.log"
}

documentation_is_honest_about_moondream() {
  grep -q "Moondream's native" "${repo_root}/deploy/docker/thor-local/README.md" &&
    grep -q "not a drop-in VLM" "${repo_root}/deploy/docker/thor-local/README.md" &&
    grep -q "physical-interface firewall" "${repo_root}/deploy/docker/thor-local/README.md"
}

check "shell syntax" bash -n "${thor_local}"
check "help exposes model and security contracts" help_exposes_contract_and_security
check "firewall plan is interface-scoped and does not touch SSH" firewall_plan_is_narrow
check "firewall refuses loopback/container interfaces" firewall_rejects_container_interfaces
check "mock provider contract requires four images and hides API key from argv" mock_model_contract_accepts_four_images_without_key_in_argv
check "operator docs state Moondream and LAN limitations" documentation_is_honest_about_moondream

if (( failures > 0 )); then
  printf '%d security/model test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor security/model tests passed.\n'
