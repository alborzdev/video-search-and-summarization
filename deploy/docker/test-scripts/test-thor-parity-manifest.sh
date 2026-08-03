#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
verifier="${repo_root}/deploy/docker/thor-local/parity/verify_manifest.py"
official_verifier="${repo_root}/deploy/docker/thor-local/parity/verify_official_capabilities.py"
official_tests="${repo_root}/deploy/docker/thor-local/parity/tests/test_official_capabilities.py"
skill_installer="${repo_root}/deploy/docker/thor-local/install-vss-skills.sh"
spatialai_qualifier="${repo_root}/deploy/docker/thor-local/qualification/qualify-spatialai.sh"

python3 "${verifier}"
python3 "${official_verifier}"
python3 "${official_tests}"

report="$(python3 "${verifier}" --report)"
grep -q "Ledger: 55 families, 500 advertised capabilities, 16 skills" <<<"${report}"
grep -q "Thor state: external_optional=8, partial=38, source_only=2, wired=7" <<<"${report}"
grep -q "Runtime: blocked=1, not_applicable=8, not_qualified=43, passed_current=2, static_only=1" <<<"${report}"
grep -q "Completion: 2/47 local families passed current" <<<"${report}"
grep -q "smart-city: partial/not_qualified" <<<"${report}"
grep -q "warehouse-2d: partial/not_qualified" <<<"${report}"
grep -q "rt-cv-3d-sparse4d: partial/not_qualified" <<<"${report}"
grep -q "rt-cv-3d-mv3dt: partial/not_qualified" <<<"${report}"
grep -q "warehouse-3d-and-mv3dt: partial/not_qualified" <<<"${report}"
grep -q "audio-understanding: partial/blocked" <<<"${report}"
grep -q "auto-calibration: partial/not_qualified" <<<"${report}"
grep -q "vios-codecs-audio: wired/not_qualified" <<<"${report}"
grep -q "vios-ui: wired/not_qualified" <<<"${report}"
grep -q "infra-observability: partial/not_qualified" <<<"${report}"
grep -q "nemoclaw-openclaw: partial/not_qualified" <<<"${report}"
jq -e '.features[] | select(.id == "spatial-ai-utils") | .thor_state == "partial" and .runtime_state == "not_qualified"' \
  "${repo_root}/deploy/docker/thor-local/parity/manifest.json" >/dev/null
jq -e '.features[] | select(.id == "synthetic-data-tools") | .thor_state == "wired" and .runtime_state == "passed_current"' \
  "${repo_root}/deploy/docker/thor-local/parity/manifest.json" >/dev/null
jq -e '.features[] | select(.id == "mv3dt-config-utils") | .thor_state == "wired" and .runtime_state == "passed_current"' \
  "${repo_root}/deploy/docker/thor-local/parity/manifest.json" >/dev/null
grep -q "Acceptance: alternate_local_lane=14, external_optional=8, required_local=33" <<<"${report}"
grep -q "alert-notifications-slack: external_optional/not_applicable" <<<"${report}"
grep -q "helm: external_optional/not_applicable" <<<"${report}"
grep -q "enterprise-rag: external_optional/not_applicable" <<<"${report}"
grep -q "vlm-autoscaling: external_optional/not_applicable" <<<"${report}"
grep -q "brev-launchable: external_optional/not_applicable" <<<"${report}"
grep -q "secure-deployment-boundary: external_optional/not_applicable" <<<"${report}"
grep -q "official-remote-agent-models: external_optional/not_applicable" <<<"${report}"
grep -q "synthetic-data-workflows-external: external_optional/not_applicable" <<<"${report}"
jq -e '.scope.complete_product_api == false and (.scope.excluded_official_surfaces | length) == 5' \
  "${repo_root}/deploy/docker/thor-local/qualification/api_inventory.json" >/dev/null

open_report="$(sed -n '/^Open parity work:/,/^External optional boundaries:/p' <<<"${report}")"
! grep -q "alert-notifications-slack" <<<"${open_report}"
! grep -q "enterprise-rag" <<<"${open_report}"
! grep -q "helm" <<<"${open_report}"
grep -q "spatial-ai-utils" <<<"${open_report}"
! grep -q "synthetic-data-tools" <<<"${open_report}"
! grep -q "mv3dt-config-utils" <<<"${open_report}"

set +e
complete_output="$(python3 "${verifier}" --require-complete 2>&1)"
complete_status=$?
set -e
[[ ${complete_status} -eq 2 ]]
grep -q "INCOMPLETE: 45 local feature families remain open" <<<"${complete_output}"

bash -n "${spatialai_qualifier}"
"${spatialai_qualifier}" --help | grep -q 'does not download a dataset'
grep -q "torch==2.13.0+cpu" "${spatialai_qualifier}"
grep -q "pytorch3d.git@33824be" "${spatialai_qualifier}"

echo "PASS: the reviewed Thor parity ledger is valid and keeps known gaps explicit"

dense_caption_source="${repo_root}/services/video-summarization/src/via_stream_handler.py"
dense_caption_image_patch="${repo_root}/deploy/docker/thor-local/patches/patch_lvs_llm_provider.py"
! grep -q 'bool(os.environ.get("ENABLE_DENSE_CAPTION"' "${dense_caption_source}"
grep -q '"ENABLE_DENSE_CAPTION", "false"' "${dense_caption_source}"
grep -q 'old_dense_caption' "${dense_caption_image_patch}"
grep -q '"ENABLE_DENSE_CAPTION", "false"' "${dense_caption_image_patch}"
echo "PASS: LVS parses the false dense-caption flag as false"

test_skills_dir="$(mktemp -d "${TMPDIR:-/tmp}/thor-vss-skills.XXXXXX")"
cleanup() {
  rm -rf -- "${test_skills_dir}"
}
trap cleanup EXIT
VSS_SKILLS_DEST="${test_skills_dir}" bash "${skill_installer}" install >/dev/null
VSS_SKILLS_DEST="${test_skills_dir}" bash "${skill_installer}" status >/dev/null
[[ "$(find "${test_skills_dir}" -mindepth 1 -maxdepth 1 -type l | wc -l)" -eq 16 ]]
echo "PASS: the VSS skill installer creates exactly 16 safe, idempotent links"
