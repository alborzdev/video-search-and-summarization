#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
launcher="${repo_root}/deploy/docker/scripts/thor-warehouse-mv3dt.sh"
validator="${repo_root}/deploy/docker/thor-local/validate-warehouse-mv3dt-input.py"
renderer="${repo_root}/deploy/docker/thor-local/render-warehouse-mv3dt-env.py"
offline_patcher="${repo_root}/deploy/docker/thor-local/patch-warehouse-mv3dt-offline.py"
overlay="${repo_root}/deploy/docker/thor-local/warehouse-mv3dt.compose.yml"
warehouse_env="${repo_root}/deploy/docker/industry-profiles/warehouse-operations/.env"
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

fixture_input="${temporary_root}/operator-input"
fixture_runtime="${temporary_root}/runtime"
fixture_dataset="operator-yard-2cams"
fake_ffprobe="${temporary_root}/ffprobe"

source_mode_exposes_helpers() {
  THOR_MV3DT_SOURCE_ONLY=true bash -c '
    source "$1"
    declare -F plan >/dev/null
    declare -F prepare_runtime >/dev/null
    declare -F validate_compose >/dev/null
    declare -F qualify_runtime >/dev/null
  ' _ "${launcher}"
}

launcher_has_no_lifecycle_or_privileged_execution() {
  ! grep -Eq '"\$\{docker_bin\}" compose .*(up|down|start|stop|pull|build)|docker (run|rm|restart)|sudo |setfacl|chmod 777' "${launcher}"
}

valid_source_plans_and_prepares_without_touching_source() {
  local input_before env_before plan_output
  input_before="$(find "${fixture_input}" -type f -print0 | sort -z | xargs -0 sha256sum)"
  env_before="$(sha256sum "${warehouse_env}")"
  plan_output="$(THOR_MV3DT_INPUT_DIR="${fixture_input}" \
    THOR_MV3DT_DATASET="${fixture_dataset}" \
    THOR_MV3DT_RUNTIME_DIR="${fixture_runtime}" \
    THOR_MV3DT_FFPROBE_BIN="${fake_ffprobe}" \
    "${launcher}" 2>&1)" || { printf '%s\n' "${plan_output}" >&2; return 1; }
  [[ ! -e "${fixture_runtime}" ]] || return 1
  grep -q 'No files or containers changed' <<< "${plan_output}" || return 1

  THOR_MV3DT_INPUT_DIR="${fixture_input}" \
    THOR_MV3DT_DATASET="${fixture_dataset}" \
    THOR_MV3DT_RUNTIME_DIR="${fixture_runtime}" \
    THOR_MV3DT_FFPROBE_BIN="${fake_ffprobe}" \
    "${launcher}" prepare >/dev/null
  [[ "${input_before}" == "$(find "${fixture_input}" -type f -print0 | sort -z | xargs -0 sha256sum)" ]] || return 1
  [[ "${env_before}" == "$(sha256sum "${warehouse_env}")" ]] || return 1
  [[ "$(stat -c %a "${fixture_runtime}/generated.env")" == "600" ]] || return 1
  [[ -s "${fixture_runtime}/deployment-snapshot.sha256" ]] || return 1
  grep -Eq '^deployment_snapshot_manifest_sha256=[0-9a-f]{64}$' \
    "${fixture_runtime}/.thor-mv3dt-state" || return 1
  grep -q '^MODE=mv3dt$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^BP_PROFILE=bp_wh_redis$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^HARDWARE_PROFILE=AGX-THOR$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^NUM_STREAMS=2$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^LLM_MODE=none$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^VLM_MODE=none$' "${fixture_runtime}/generated.env" || return 1
  ! find "${fixture_runtime}/data" -type f -name '*.engine' | grep -q . || return 1
  [[ "$(stat -c %i "${fixture_input}/models/mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx")" != \
     "$(stat -c %i "${fixture_runtime}/data/models/mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx")" ]] || return 1
  jq -e '.network.stunurl_list == ["127.0.0.1:3478"] and .network.use_twilio_stun_turn == false' \
    "${fixture_runtime}/source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/vst/configs/vst_config.json" \
    "${fixture_runtime}/source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/nvstreamer/configs/vst-config.json" >/dev/null &&
    ! grep -Rqi 'stun.*google' \
      "${fixture_runtime}/source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/vst/configs/vst_config.json" \
      "${fixture_runtime}/source/deploy/docker/industry-profiles/warehouse-operations/warehouse-mv3dt-app/nvstreamer/configs/vst-config.json"
}

both_compose_profiles_resolve_exactly() {
  local output
  output="$(THOR_MV3DT_RUNTIME_DIR="${fixture_runtime}" "${launcher}" validate-all 2>&1)" || {
    printf '%s\n' "${output}" >&2
    return 1
  }
  grep -q 'minimal Redis Compose contract (20 services, 2/7 streams)' <<< "${output}" &&
    grep -q 'extended Redis Compose contract (28 services, 2/7 streams)' <<< "${output}"
}

launch_command_is_offline_and_nonexecuting() {
  local before after output
  before="$(docker ps -aq | sort)"
  output="$(THOR_MV3DT_RUNTIME_DIR="${fixture_runtime}" "${launcher}" launch-command extended 2>/dev/null)" || return 1
  after="$(docker ps -aq | sort)"
  [[ "${before}" == "${after}" ]] &&
    grep -q -- '--no-build --pull never' <<< "${output}" &&
    grep -q 'MINIMAL_PROFILE=' <<< "${output}" &&
    grep -Fq "${fixture_runtime}/source/deploy/docker/thor-local/warehouse-mv3dt.compose.yml" <<< "${output}" &&
    ! grep -Fq "${overlay}" <<< "${output}"
}

timeline_drift_fails_closed() {
  local output
  if output="$(FAKE_FFPROBE_DRIFT=true \
      THOR_MV3DT_INPUT_DIR="${fixture_input}" THOR_MV3DT_DATASET="${fixture_dataset}" \
      THOR_MV3DT_RUNTIME_DIR="${temporary_root}/drift-runtime" THOR_MV3DT_FFPROBE_BIN="${fake_ffprobe}" \
      "${launcher}" plan 2>&1)"; then
    return 1
  fi
  grep -q 'videos are not synchronized' <<< "${output}"
}

sample_slug_fails_closed() {
  local output
  if output="$(python3 "${validator}" --input-dir "${fixture_input}" \
      --dataset warehouse-4cams-20mx20m-synthetic --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'bundled sample slug' <<< "${output}"
}

nonfinite_calibration_fails_closed() {
  local invalid_input="${temporary_root}/invalid-calibration" output
  cp -a "${fixture_input}" "${invalid_input}"
  python3 - "${invalid_input}/calibration/${fixture_dataset}/calibration.json" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    document = json.load(handle)
document["sensors"][0]["globalCoordinates"][0]["z"] = float("nan")
with open(path, "w", encoding="utf-8") as handle:
    json.dump(document, handle)
PY
  if output="$(python3 "${validator}" --input-dir "${invalid_input}" \
      --dataset "${fixture_dataset}" --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'finite globalCoordinates x/y/z' <<< "${output}"
}

malformed_caminfo_projection_fails_closed() {
  local invalid_input="${temporary_root}/invalid-caminfo" output
  cp -a "${fixture_input}" "${invalid_input}"
  printf 'projectionMatrix_3x4_w2p: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, .nan, 0]\n' \
    > "${invalid_input}/calibration/${fixture_dataset}/camInfo/Camera_01.yml"
  if output="$(python3 "${validator}" --input-dir "${invalid_input}" \
      --dataset "${fixture_dataset}" --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'finite projectionMatrix_3x4_w2p\[12\]' <<< "${output}"
}

failed_prepare_cleans_staging_on_exit() {
  local cleanup_parent="${temporary_root}/cleanup-parent"
  local failing_patcher="${temporary_root}/failing-patcher.py"
  install -d "${cleanup_parent}"
  printf 'raise SystemExit(9)\n' > "${failing_patcher}"
  if THOR_MV3DT_INPUT_DIR="${fixture_input}" \
      THOR_MV3DT_DATASET="${fixture_dataset}" \
      THOR_MV3DT_RUNTIME_DIR="${cleanup_parent}/runtime" \
      THOR_MV3DT_FFPROBE_BIN="${fake_ffprobe}" \
      THOR_MV3DT_OFFLINE_PATCHER="${failing_patcher}" \
      "${launcher}" prepare >/dev/null 2>&1; then
    return 1
  fi
  [[ ! -e "${cleanup_parent}/runtime" ]] &&
    ! compgen -G "${cleanup_parent}/.warehouse-mv3dt-staging.*" >/dev/null
}

snapshot_checksum_detects_private_source_drift() {
  local private_overlay="${fixture_runtime}/source/deploy/docker/thor-local/warehouse-mv3dt.compose.yml"
  local output
  printf '\n# checksum-drift-test\n' >> "${private_overlay}"
  if output="$(THOR_MV3DT_RUNTIME_DIR="${fixture_runtime}" "${launcher}" validate minimal 2>&1)"; then
    cp "${overlay}" "${private_overlay}"
    return 1
  fi
  cp "${overlay}" "${private_overlay}"
  grep -q 'immutable deployment snapshot files changed' <<< "${output}"
}

overlay_has_thor_offline_contract() {
  grep -q '^  vss-rtvi-cv-mv3dt:' "${overlay}" &&
    grep -q 'TRANSFORMERS_OFFLINE: "1"' "${overlay}" &&
    grep -q 'HF_HUB_OFFLINE: "1"' "${overlay}" &&
    grep -q '^  vss-rtvi-cv-bev-fusion:' "${overlay}" &&
    grep -q 'BROKER_TYPE: redis' "${overlay}" &&
    grep -q '^  logstash:' "${overlay}" &&
    grep -q 'THOR_LOCAL_LOGSTASH_IMAGE.*vss-logstash-protobuf:9.3.3-codec-1.3.0-thor-local' "${overlay}" &&
    grep -q 'command: \[\]' "${overlay}" &&
    grep -q 'STREAM_TYPE: kafka' "${overlay}" &&
    grep -q -- '--protected-mode' "${overlay}"
}

# Portable fixture setup (source files are test data, not repository edits).
install -d \
  "${fixture_input}/models/mtmc" \
  "${fixture_input}/models/mv3dt/BodyPose3DNet" \
  "${fixture_input}/videos/${fixture_dataset}" \
  "${fixture_input}/calibration/${fixture_dataset}/camInfo" \
  "${fixture_input}/calibration/${fixture_dataset}/images"
printf 'detector-onnx\n' > "${fixture_input}/models/mtmc/rtdetr_warehouse_v1.0.2.fp16.onnx"
printf 'bodypose-onnx\n' > "${fixture_input}/models/mv3dt/BodyPose3DNet/bodypose3dnet_accuracy.onnx"
printf 'camera-a\n' > "${fixture_input}/videos/${fixture_dataset}/Camera.mp4"
printf 'camera-b\n' > "${fixture_input}/videos/${fixture_dataset}/Camera_01.mp4"
printf 'projectionMatrix_3x4_w2p: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]\n' > "${fixture_input}/calibration/${fixture_dataset}/camInfo/Camera.yml"
cp "${fixture_input}/calibration/${fixture_dataset}/camInfo/Camera.yml" "${fixture_input}/calibration/${fixture_dataset}/camInfo/Camera_01.yml"
printf 'png\n' > "${fixture_input}/calibration/${fixture_dataset}/images/Top.png"
printf '{"images":[{"place":"building=Operator","view":"plan-view","fileName":"Top.png"}]}\n' > "${fixture_input}/calibration/${fixture_dataset}/images/imageMetadata.json"
python3 - "${fixture_input}/calibration/${fixture_dataset}/calibration.json" <<'PY'
import json
import sys
sensors = []
for index, camera_id in enumerate(("Camera", "Camera_01")):
    sensors.append({"id": camera_id, "coordinates": {"x": index, "y": index},
                    "group": {"name": "operator-bev", "origin": [0, 0], "dimensions": [0, 0, 10, 10]},
                    "region": {"placeLevel": "region"}, "place": [{"name": "region", "value": "Operator"}],
                    "imageCoordinates": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
                    "globalCoordinates": [{"x": 0, "y": 0, "z": 1}, {"x": 1, "y": 1, "z": 1}]})
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"sensors": sensors}, handle)
PY
printf '%s\n' '#!/usr/bin/env bash' \
  'frames=300' \
  'if [[ "${FAKE_FFPROBE_DRIFT:-false}" == "true" && "${!#}" == *Camera_01.mp4 ]]; then frames=299; fi' \
  'printf '\''{"streams":[{"codec_name":"h264","width":1920,"height":1080,"avg_frame_rate":"30/1","nb_frames":"%s"}],"format":{"start_time":"0.0","duration":"10.0"}}\n'\'' "${frames}"' \
  > "${fake_ffprobe}"
chmod +x "${fake_ffprobe}"

check "launcher shell syntax" bash -n "${launcher}"
check "validator Python syntax" python3 -c "import ast; ast.parse(open('${validator}', encoding='utf-8').read())"
check "renderer Python syntax" python3 -c "import ast; ast.parse(open('${renderer}', encoding='utf-8').read())"
check "offline patcher Python syntax" python3 -c "import ast; ast.parse(open('${offline_patcher}', encoding='utf-8').read())"
check "source-only mode exposes safe helpers" source_mode_exposes_helpers
check "launcher has no lifecycle or privileged execution" launcher_has_no_lifecycle_or_privileged_execution
check "overlay pins Thor, Redis, and offline runtime behavior" overlay_has_thor_offline_contract
check "valid custom source plans and copies into private state" valid_source_plans_and_prepares_without_touching_source
check "minimal and extended Compose graphs resolve exactly" both_compose_profiles_resolve_exactly
check "launch command is pull-free, build-free, and non-executing" launch_command_is_offline_and_nonexecuting
check "unsynchronized videos fail closed" timeline_drift_fails_closed
check "non-finite 3D calibration fails closed" nonfinite_calibration_fails_closed
check "malformed camInfo projection matrix fails closed" malformed_caminfo_projection_fails_closed
check "excluded NVIDIA sample slug fails closed" sample_slug_fails_closed
check "failed prepare removes only its private staging directory" failed_prepare_cleans_staging_on_exit
check "private deployment snapshot drift fails checksum validation" snapshot_checksum_detects_private_source_drift

if (( failures > 0 )); then
  printf '%d Thor MV3DT static test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor MV3DT static tests passed.\n'
