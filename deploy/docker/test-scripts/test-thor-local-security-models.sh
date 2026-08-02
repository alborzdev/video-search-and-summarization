#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
thor_local="${repo_root}/deploy/docker/scripts/thor-local.sh"
model_provisioner="${repo_root}/deploy/docker/thor-local/provision-local-models.sh"
model_verifier="${repo_root}/deploy/docker/thor-local/models/verify_artifacts.py"
model_lock="${repo_root}/deploy/docker/thor-local/models/artifacts.lock.json"
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

private_model_endpoint_contract() {
  THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    validate_thor_full_contract
    [[ "$LLM_ENDPOINT_URL" == http://127.0.0.1:* || "$LLM_ENDPOINT_URL" == http://172.17.0.1:* ]]
  ' _ "${thor_local}"
}

physical_model_endpoint_is_rejected() {
  local physical_ip
  physical_ip="$(ip route get 1.1.1.1 | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
  [[ -n "${physical_ip}" ]] || return 1
  ! LLM_ENDPOINT_URL="http://${physical_ip}:18000" THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    validate_thor_full_contract
  ' _ "${thor_local}" >/dev/null 2>&1
}

model_provisioner_is_pinned_and_offline() {
  grep -q 'ghcr.io/nvidia-ai-iot/vllm@sha256:6402d5ac90223b9ba4434228f98aec798c5a8b942e770ee47528b4148e923105' "${model_provisioner}" &&
    grep -q '95a723d08a9490559dae23d0cff1d9466213d989' "${model_provisioner}" &&
    grep -q '9cdc6310a8cb770ce18efaf4e9935334512aee45' "${model_provisioner}" &&
    grep -q 'HF_HUB_OFFLINE=1' "${model_provisioner}" &&
    ! grep -Eq 'docker (pull|rm)|docker container rm' "${model_provisioner}"
}

model_artifact_lock_is_exact_and_semantic() {
  python3 - "${model_lock}" <<'PY'
import json
import sys

lock = json.load(open(sys.argv[1], encoding="utf-8"))
assert lock["schema_version"] == 1
artifacts = lock["artifacts"]
assert set(artifacts) == {
    "qwen_llm",
    "qwen_vlm",
    "cosmos_embed_model",
    "cosmos_embed_triton",
}
assert artifacts["qwen_llm"]["provenance"]["revision"] == "95a723d08a9490559dae23d0cff1d9466213d989"
assert artifacts["qwen_vlm"]["provenance"]["revision"] == "9cdc6310a8cb770ce18efaf4e9935334512aee45"
assert artifacts["cosmos_embed_model"]["provenance"]["revision"] == "3b1455ed97c7b1d5419c0c3129b7199ca4cd9382"
assert len(artifacts["qwen_llm"]["tree"]["files"]) == 52
assert len(artifacts["qwen_vlm"]["tree"]["files"]) == 11
assert len(artifacts["cosmos_embed_model"]["tree"]["files"]) == 76
assert len(artifacts["cosmos_embed_triton"]["tree"]["files"]) == 10
for artifact in artifacts.values():
    assert artifact["semantics"]["type"] in {
        "indexed_safetensors_model",
        "triton_tensorrt_repository",
    }
    for entry in artifact["tree"]["files"]:
        assert len(entry["sha256"]) == 64
PY
}

model_verification_paths_are_fail_closed_and_read_only() {
  grep -q 'verify-hf' "${model_provisioner}" &&
    grep -q 'artifacts.lock.json' "${model_provisioner}" &&
    grep -q 'qwen_llm' "${model_provisioner}" &&
    grep -q 'qwen_vlm' "${model_provisioner}" &&
    grep -q -- '--artifact "${artifact}"' "${model_provisioner}" &&
    grep -q 'stream_embedding_volume_tree' "${thor_local}" &&
    grep -q 'docker run --rm --pull never --network none --read-only' "${thor_local}" &&
    grep -q -- '--log-driver none' "${thor_local}" &&
    grep -q -- '--cap-drop ALL --security-opt no-new-privileges:true' "${thor_local}" &&
    grep -q 'readonly,volume-nocopy' "${thor_local}" &&
    grep -q -- '--artifact cosmos_embed_model' "${thor_local}" &&
    grep -q -- '--artifact cosmos_embed_triton' "${thor_local}" &&
    grep -q 'indexed_safetensors_model' "${model_verifier}" &&
    grep -q 'triton_tensorrt_repository' "${model_verifier}"
}

embedding_verification_survives_compose_down() {
  local function_body
  function_body="$(sed -n '/^staged_embedding_cache_is_present()/,/^}/p' "${thor_local}")"
  grep -q 'docker volume inspect' <<<"${function_body}" &&
    grep -q 'docker image inspect' <<<"${function_body}" &&
    ! grep -Eq 'docker (container inspect|cp)|container_name' <<<"${function_body}"
}

model_probe_fails_without_a_python_traceback() {
  local output status
  set +e
  output="$(THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    curl() { printf "not-json"; }
    model_is_served http://127.0.0.1:1 expected-model
  ' _ "${thor_local}" 2>&1)"
  status=$?
  set -e
  [[ ${status} -ne 0 ]] &&
    ! grep -q 'Traceback' <<< "${output}" &&
    ! grep -q 'JSONDecodeError' <<< "${output}"
}

memory_gate_rejects_an_overcommit() {
  ! THOR_LOCAL_SOURCE_ONLY=true bash -c '
    source "$1"
    require_memory_headroom "unit-test overcommit" 999999
  ' _ "${thor_local}" >/dev/null 2>&1
}

startup_paths_apply_memory_gates() {
  grep -q 'require_memory_headroom "starting ${role} ${expected_model}"' "${thor_local}" &&
    grep -q 'require_memory_headroom "starting the Thor VSS stack"' "${thor_local}"
}

check "shell syntax" bash -n "${thor_local}"
check "model provisioner shell syntax" bash -n "${model_provisioner}"
check "help exposes model and security contracts" help_exposes_contract_and_security
check "firewall plan is interface-scoped and does not touch SSH" firewall_plan_is_narrow
check "firewall refuses loopback/container interfaces" firewall_rejects_container_interfaces
check "mock provider contract requires four images and hides API key from argv" mock_model_contract_accepts_four_images_without_key_in_argv
check "operator docs state Moondream and LAN limitations" documentation_is_honest_about_moondream
check "model endpoints default to loopback or the private Docker bridge" private_model_endpoint_contract
check "physical model endpoints are rejected from the operator contract" physical_model_endpoint_is_rejected
check "model provisioner pins image and revisions and remains offline" model_provisioner_is_pinned_and_offline
check "model artifact lock covers all four exact semantic trees" model_artifact_lock_is_exact_and_semantic
check "model verification paths are fail-closed and read-only" model_verification_paths_are_fail_closed_and_read_only
check "embedding verification remains valid after compose down" embedding_verification_survives_compose_down
check "model artifact adversarial verifier suite" \
  python3 -m pytest -q "${repo_root}/deploy/docker/thor-local/models/tests/test_verify_artifacts.py"
check "failed model probes stay concise and traceback-free" model_probe_fails_without_a_python_traceback
check "memory gate rejects an unsafe unified-memory overcommit" memory_gate_rejects_an_overcommit
check "model and stack startup paths apply memory gates" startup_paths_apply_memory_gates

if (( failures > 0 )); then
  printf '%d security/model test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor security/model tests passed.\n'
