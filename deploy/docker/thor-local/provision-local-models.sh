#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Provision the pinned, operator-managed OpenAI-compatible model containers
# used by the Thor-local VSS profile. The command is additive: it never removes
# or recreates an existing container, and it never pulls an image or model.

set -euo pipefail
umask 077

provisioner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
thor_local="${provisioner_dir}/../scripts/thor-local.sh"

export THOR_LOCAL_SOURCE_ONLY=true
# shellcheck source=../scripts/thor-local.sh
source "${thor_local}"

model_image="${THOR_LOCAL_VLLM_IMAGE:-ghcr.io/nvidia-ai-iot/vllm@sha256:6402d5ac90223b9ba4434228f98aec798c5a8b942e770ee47528b4148e923105}"
model_cache="${THOR_LOCAL_HF_CACHE_DIR:-${HOME}/.cache/huggingface}"
model_artifact_verifier="${provisioner_dir}/models/verify_artifacts.py"
model_artifact_lock="${provisioner_dir}/models/artifacts.lock.json"
llm_repository="${THOR_LOCAL_LLM_REPOSITORY:-Qwen/Qwen3.6-35B-A3B-FP8}"
llm_revision="${THOR_LOCAL_LLM_REVISION:-95a723d08a9490559dae23d0cff1d9466213d989}"
vlm_repository="${THOR_LOCAL_VLM_REPOSITORY:-Qwen/Qwen3-VL-8B-Instruct-FP8}"
vlm_revision="${THOR_LOCAL_VLM_REVISION:-9cdc6310a8cb770ce18efaf4e9935334512aee45}"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: provision-local-models.sh <status|provision>

  status     Verify the pinned image, model snapshots, and configured containers.
  provision  Create only missing configured containers from already-staged assets.

The command never pulls, removes, recreates, or downloads. Container names,
endpoints, and cache path can be overridden with THOR_LOCAL_* variables. The
model repositories and revisions are accepted only when they match the
reviewed artifacts.lock.json identity; changing them requires a reviewed lock.
EOF
}

endpoint_authority() {
  python3 - "$1" <<'PY'
import ipaddress
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
if parsed.scheme not in {"http", "https"} or parsed.hostname is None or parsed.port is None:
    raise SystemExit(1)
try:
    ipaddress.ip_address(parsed.hostname)
except ValueError:
    raise SystemExit(1)
print(parsed.hostname)
print(parsed.port)
PY
}

snapshot_directory() {
  local repository="$1"
  local revision="$2"
  printf '%s/models--%s/snapshots/%s\n' \
    "${model_cache}" "${repository//\//--}" "${revision}"
}

require_snapshot() {
  local role="$1"
  local repository="$2"
  local revision="$3"
  local artifact="$4"
  local snapshot repository_root
  snapshot="$(snapshot_directory "${repository}" "${revision}")"
  repository_root="$(dirname -- "$(dirname -- "${snapshot}")")"
  [[ -r "${model_artifact_verifier}" && -r "${model_artifact_lock}" ]] ||
    die "Missing Thor model artifact verifier or reviewed lock"
  python3 "${model_artifact_verifier}" verify-hf \
    --lock "${model_artifact_lock}" \
    --artifact "${artifact}" \
    --snapshot "${snapshot}" \
    --repository-root "${repository_root}" \
    --repository "${repository}" \
    --revision "${revision}" ||
    die "${role} snapshot differs from the exact reviewed artifact lock"
  echo "[OK] ${role} snapshot exactly matches revision ${revision}."
}

container_matches() {
  local role="$1"
  local container="$2"
  local repository="$3"
  local revision="$4"
  local served_model="$5"
  local endpoint="$6"
  local expected_image_id actual_image_id command_text
  local -a authority=()

  mapfile -t authority < <(endpoint_authority "${endpoint}") ||
    die "${role} endpoint must contain a literal IP address and explicit port: ${endpoint}"
  expected_image_id="$(docker image inspect --format '{{.Id}}' "${model_image}" 2>/dev/null)" ||
    die "Pinned vLLM image is not staged: ${model_image}"
  actual_image_id="$(docker inspect --format '{{.Image}}' "${container}" 2>/dev/null)" || return 1
  [[ "${actual_image_id}" == "${expected_image_id}" ]] ||
    die "${container} exists but does not use the pinned vLLM image"
  command_text="$(docker inspect --format '{{json .Config.Cmd}}' "${container}")"
  [[ "${command_text}" == *"${repository}"* &&
     "${command_text}" == *"${served_model}"* &&
     "${command_text}" == *"${authority[0]}"* &&
     "${command_text}" == *"${authority[1]}"* ]] ||
    die "${container} exists but its model, served name, or bind address differs from the Thor contract"
  if [[ "${command_text}" != *"${revision}"* ]]; then
    echo "[WARN] ${container} does not pin revision ${revision} in its command; its staged snapshot still matches the accepted revision."
  fi
  echo "[OK] ${role} container ${container} matches the pinned local model contract."
}

create_llm() {
  local -a authority=()
  mapfile -t authority < <(endpoint_authority "${LLM_ENDPOINT_URL}") ||
    die "LLM endpoint must contain a literal IP address and explicit port: ${LLM_ENDPOINT_URL}"
  docker create \
    --name "${THOR_LOCAL_LLM_CONTAINER}" \
    --label com.nvidia.vss.thor-local.model-role=llm \
    --runtime nvidia \
    --network host \
    --restart no \
    --mount "type=bind,src=${model_cache},dst=/data/models/huggingface" \
    --env HF_HOME=/data/models/huggingface \
    --env HUGGINGFACE_HUB_CACHE=/data/models/huggingface \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    --env HF_HUB_DISABLE_TELEMETRY=1 \
    --env NVIDIA_VISIBLE_DEVICES=all \
    --env NVIDIA_DRIVER_CAPABILITIES=all \
    "${model_image}" \
    vllm serve "${llm_repository}" \
      --revision "${llm_revision}" \
      --tokenizer-revision "${llm_revision}" \
      --host "${authority[0]}" \
      --port "${authority[1]}" \
      --served-model-name "${THOR_LOCAL_LLM_MODEL}" \
      --max-model-len 32768 \
      --gpu-memory-utilization 0.40 \
      --kv-cache-memory-bytes 4G \
      --max-num-seqs 1 \
      --enforce-eager \
      --reasoning-parser qwen3 \
      --language-model-only \
      --enable-auto-tool-choice \
      --tool-call-parser qwen3_coder >/dev/null
  echo "[OK] Created stopped LLM container ${THOR_LOCAL_LLM_CONTAINER}."
}

create_vlm() {
  local -a authority=()
  mapfile -t authority < <(endpoint_authority "${VLM_ENDPOINT_URL}") ||
    die "VLM endpoint must contain a literal IP address and explicit port: ${VLM_ENDPOINT_URL}"
  docker create \
    --name "${THOR_LOCAL_VLM_CONTAINER}" \
    --label com.nvidia.vss.thor-local.model-role=vlm \
    --runtime nvidia \
    --network host \
    --restart no \
    --mount "type=bind,src=${model_cache},dst=/data/models/huggingface" \
    --env HF_HOME=/data/models/huggingface \
    --env HUGGINGFACE_HUB_CACHE=/data/models/huggingface \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    --env HF_HUB_DISABLE_TELEMETRY=1 \
    --env NVIDIA_VISIBLE_DEVICES=all \
    --env NVIDIA_DRIVER_CAPABILITIES=all \
    "${model_image}" \
    vllm serve "${vlm_repository}" \
      --revision "${vlm_revision}" \
      --tokenizer-revision "${vlm_revision}" \
      --host "${authority[0]}" \
      --port "${authority[1]}" \
      --served-model-name "${THOR_LOCAL_VLM_MODEL}" \
      --max-model-len 16384 \
      --gpu-memory-utilization 0.18 \
      --max-num-seqs 1 \
      --enforce-eager \
      --limit-mm-per-prompt '{"image":4,"video":0}' >/dev/null
  echo "[OK] Created stopped VLM container ${THOR_LOCAL_VLM_CONTAINER}."
}

status() {
  require_snapshot LLM "${llm_repository}" "${llm_revision}" qwen_llm
  require_snapshot VLM "${vlm_repository}" "${vlm_revision}" qwen_vlm
  container_matches LLM "${THOR_LOCAL_LLM_CONTAINER}" "${llm_repository}" \
    "${llm_revision}" "${THOR_LOCAL_LLM_MODEL}" "${LLM_ENDPOINT_URL}" ||
    die "Configured LLM container does not exist: ${THOR_LOCAL_LLM_CONTAINER}"
  container_matches VLM "${THOR_LOCAL_VLM_CONTAINER}" "${vlm_repository}" \
    "${vlm_revision}" "${THOR_LOCAL_VLM_MODEL}" "${VLM_ENDPOINT_URL}" ||
    die "Configured VLM container does not exist: ${THOR_LOCAL_VLM_CONTAINER}"
}

provision() {
  require_snapshot LLM "${llm_repository}" "${llm_revision}" qwen_llm
  require_snapshot VLM "${vlm_repository}" "${vlm_revision}" qwen_vlm
  docker image inspect "${model_image}" >/dev/null 2>&1 ||
    die "Pinned vLLM image is not staged; this offline command will not pull it: ${model_image}"
  if ! docker container inspect "${THOR_LOCAL_LLM_CONTAINER}" >/dev/null 2>&1; then
    create_llm
  fi
  if ! docker container inspect "${THOR_LOCAL_VLM_CONTAINER}" >/dev/null 2>&1; then
    create_vlm
  fi
  status
}

case "${1:-}" in
  status) status ;;
  provision) provision ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 2 ;;
esac
