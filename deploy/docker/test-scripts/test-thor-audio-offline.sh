#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
audio_dir="${repo_root}/deploy/docker/thor-local/audio"
generated_env="${repo_root}/deploy/docker/thor-local/generated.env"

bash -n \
  "${audio_dir}/install-codec-bundle.sh" \
  "${audio_dir}/rtvi-vlm-offline-entrypoint.sh" \
  "${audio_dir}/thor-omni-audio.sh"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${audio_dir}/tests" -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 "${audio_dir}/codec_bundle.py" source-audit

# The Dockerfile consumes only the already-staged bundle and disables the
# released startup downloader. The runtime entrypoint contains no network tool.
grep -Fq 'RUN python3 /usr/local/libexec/vss-thor/codec_bundle.py verify --frozen' \
  "${audio_dir}/Dockerfile.rtvi-vlm-codecs"
grep -Fq 'COPY deploy/docker/thor-local/audio/codec-bundle.lock.json' \
  "${audio_dir}/Dockerfile.rtvi-vlm-codecs"
grep -Fq 'INSTALL_PROPRIETARY_CODECS=false' "${audio_dir}/rtvi-vlm-offline-entrypoint.sh"
if grep -Eq '\b(apt|apt-get|curl|wget|pip)\b' "${audio_dir}/rtvi-vlm-offline-entrypoint.sh"; then
  echo "offline RT-VLM runtime entrypoint contains a network/package tool" >&2
  exit 1
fi

# Exact 3.2.1 two-key audio gate: service capability plus request flag.
grep -Fq 'VLM_MODEL_SUPPORTS_AUDIO: "${VLM_MODEL_SUPPORTS_AUDIO:-false}"' \
  "${repo_root}/deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml"
grep -Fq 'enable_audio: bool = Field(' \
  "${repo_root}/services/rtvi/rt-vlm/src/api_models/captions.py"
grep -Fq 'VLM_MODEL_SUPPORTS_AUDIO", "false"' \
  "${repo_root}/services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py"

# Resolve the real Thor graph without creating containers. The explicit
# overlay must erase the default source build and force all audio consumers to
# the same local RT-VLM model id while keeping every credential empty.
[[ -f "${generated_env}" ]] || { echo "missing protected Thor generated.env" >&2; exit 1; }
resolved=$(mktemp)
trap 'rm -f "${resolved}"' EXIT
VSS_REPO_ROOT="${repo_root}" \
THOR_LOCAL_OMNI_MODEL_DIR=/tmp \
THOR_LOCAL_OMNI_MODEL_ID=static-omni-model-id \
docker compose --env-file "${generated_env}" \
  -f "${repo_root}/deploy/docker/compose.yml" \
  -f "${repo_root}/deploy/docker/thor-local/compose.yml" \
  -f "${audio_dir}/omni.compose.yml" \
  --profile bp_developer_thor_full_2d config --format json > "${resolved}"

jq -e '
  .services["rtvi-vlm"] as $r |
  .services["vss-agent"] as $a |
  .services["lvs-server"] as $l |
  .services["alert-bridge"] as $b |
  ($r.image == "cti-vss-rt-vlm:3.2.1-thor-audio-offline") and
  ($r.build == null) and
  ($r.environment.VLM_MODEL_TO_USE == "vllm-compatible") and
  ($r.environment.VLM_MODEL_SUPPORTS_AUDIO == "true") and
  ($r.environment.VLM_TRUST_REMOTE_CODE == "true") and
  ($r.environment.VLM_RUNTIME_STATE_DIR == "/opt/nvidia/rtvi/runtime/omni") and
  ($r.environment.VLLM_GPU_MEMORY_UTILIZATION == "0.45") and
  ($r.environment.INSTALL_PROPRIETARY_CODECS == "false") and
  ($r.environment.VLM_BATCH_SIZE == "1") and
  ($r.environment.NUM_VLM_PROCS == "1") and
  ($r.environment.VLLM_MAX_NUM_SEQS == "1") and
  ($r.environment.VIA_VLM_ENDPOINT == "") and
  ($r.environment.VIA_VLM_API_KEY == "") and
  ($r.environment.VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME == "") and
  ($r.environment.NGC_API_KEY == "") and
  ($r.environment.HF_TOKEN == "") and
  ($r.environment.HF_HUB_OFFLINE == "1") and
  ($r.environment.TRANSFORMERS_OFFLINE == "1") and
  ([$r.volumes[] | select(.target == "/opt/nvidia/rtvi/models/omni")][0].read_only == true) and
  ([ $r.tmpfs[] | contains("/opt/nvidia/rtvi/runtime") ] | any) and
  ([ $r.tmpfs[] | contains("noexec") ] | any | not) and
  ($a.environment.VLM_MODEL_TYPE == "rtvi") and
  ($a.environment.VLM_NAME == "static-omni-model-id") and
  ($a.environment.ENABLE_AUDIO == "true") and
  ($a.environment.INSTALL_PROPRIETARY_CODECS == "false") and
  ($l.environment.ENABLE_AUDIO == "true") and
  ($b.environment.VLM_NAME == "static-omni-model-id") and
  ($b.environment.REALTIME_ALERT_ENABLE_AUDIO == "true")
' "${resolved}" >/dev/null

# The only model-directory rewrite helpers are guarded for quantized
# Qwen3-VL/Cosmos3. Neither the Nemotron Omni architectures nor the locked
# BF16 Cosmos Reason2 snapshot take these branches; their model mounts remain
# read-only while cache and lock state use VLM_RUNTIME_STATE_DIR.
grep -Fq 'runtime_state_dir = _get_runtime_state_dir(self.model_path)' \
  "${repo_root}/services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py"
grep -Fq 'model_lock_path = os.path.join(runtime_state_dir, "model-init.lock")' \
  "${repo_root}/services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py"

echo "Thor RT-VLM codec and Omni audio static contracts passed"
