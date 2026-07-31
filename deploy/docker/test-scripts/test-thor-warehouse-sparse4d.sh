#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
launcher="${repo_root}/deploy/docker/scripts/thor-warehouse-sparse4d.sh"
validator="${repo_root}/deploy/docker/thor-local/validate-warehouse-sparse4d-input.py"
renderer="${repo_root}/deploy/docker/thor-local/render-warehouse-sparse4d-env.py"
offline_patcher="${repo_root}/deploy/docker/thor-local/patch-warehouse-sparse4d-offline.py"
overlay="${repo_root}/deploy/docker/thor-local/warehouse-sparse4d.compose.yml"
dockerfile="${repo_root}/deploy/docker/thor-local/Dockerfile.logstash-redis-offline"
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
fixture_dataset="operator-yard-4cams"
fake_ffprobe="${temporary_root}/ffprobe"

source_mode_exposes_helpers() {
  THOR_SPARSE4D_SOURCE_ONLY=true bash -c '
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
  local input_before env_before output
  input_before="$(find "${fixture_input}" -type f -print0 | sort -z | xargs -0 sha256sum)"
  env_before="$(sha256sum "${warehouse_env}")"
  output="$(THOR_SPARSE4D_INPUT_DIR="${fixture_input}" \
    THOR_SPARSE4D_DATASET="${fixture_dataset}" \
    THOR_SPARSE4D_RUNTIME_DIR="${fixture_runtime}" \
    THOR_SPARSE4D_FFPROBE_BIN="${fake_ffprobe}" \
    "${launcher}" 2>&1)" || { printf '%s\n' "${output}" >&2; return 1; }
  [[ ! -e "${fixture_runtime}" ]] || return 1
  grep -q 'No files or containers changed' <<< "${output}" || return 1
  THOR_SPARSE4D_INPUT_DIR="${fixture_input}" \
    THOR_SPARSE4D_DATASET="${fixture_dataset}" \
    THOR_SPARSE4D_RUNTIME_DIR="${fixture_runtime}" \
    THOR_SPARSE4D_FFPROBE_BIN="${fake_ffprobe}" \
    "${launcher}" prepare >/dev/null
  [[ "${input_before}" == "$(find "${fixture_input}" -type f -print0 | sort -z | xargs -0 sha256sum)" ]] || return 1
  [[ "${env_before}" == "$(sha256sum "${warehouse_env}")" ]] || return 1
  [[ "$(stat -c %a "${fixture_runtime}/generated.env")" == "600" ]] || return 1
  grep -q '^MODE=3d$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^BP_PROFILE=bp_wh_redis$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^HARDWARE_PROFILE=AGX-THOR$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^NUM_STREAMS=4$' "${fixture_runtime}/generated.env" || return 1
  grep -q '^LLM_MODE=none$' "${fixture_runtime}/generated.env" || return 1
  ! find "${fixture_runtime}/data" -type f -name '*.engine' | grep -q . || return 1
  [[ "$(stat -c %i "${fixture_input}/models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx")" != \
     "$(stat -c %i "${fixture_runtime}/data/models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx")" ]] || return 1
  jq -e '.network.stunurl_list == ["127.0.0.1:3478"] and .network.use_twilio_stun_turn == false' \
    "${fixture_runtime}/source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/vst/configs/vst_config.json" \
    "${fixture_runtime}/source/deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/nvstreamer/configs/vst-config.json" >/dev/null
}

both_profiles_resolve_exactly() {
  local output
  output="$(THOR_SPARSE4D_RUNTIME_DIR="${fixture_runtime}" "${launcher}" validate-all 2>&1)" || {
    printf '%s\n' "${output}" >&2
    return 1
  }
  grep -q 'minimal Redis Compose contract (19 services, 4 synchronized streams' <<< "${output}" &&
    grep -q 'extended Redis Compose contract (31 services, 4 synchronized streams' <<< "${output}"
}

launch_command_is_offline_and_nonexecuting() {
  local before after output
  before="$(docker ps -aq | sort)"
  output="$(THOR_SPARSE4D_RUNTIME_DIR="${fixture_runtime}" "${launcher}" launch-command extended 2>/dev/null)" || return 1
  after="$(docker ps -aq | sort)"
  [[ "${before}" == "${after}" ]] &&
    grep -q -- '--no-build --pull never' <<< "${output}" &&
    grep -Fq "${fixture_runtime}/source/deploy/docker/thor-local/warehouse-sparse4d.compose.yml" <<< "${output}" &&
    ! grep -Fq "${overlay}" <<< "${output}"
}

timeline_drift_fails_closed() {
  local output
  if output="$(FAKE_FFPROBE_DRIFT=true THOR_SPARSE4D_INPUT_DIR="${fixture_input}" \
      THOR_SPARSE4D_DATASET="${fixture_dataset}" THOR_SPARSE4D_RUNTIME_DIR="${temporary_root}/drift" \
      THOR_SPARSE4D_FFPROBE_BIN="${fake_ffprobe}" "${launcher}" plan 2>&1)"; then
    return 1
  fi
  grep -q 'videos are not synchronized' <<< "${output}"
}

invalid_anchor_fails_closed() {
  local invalid="${temporary_root}/bad-anchor" output
  cp -a "${fixture_input}" "${invalid}"
  python3 - "${invalid}/models/sparse4d/ov/_ov_kmeans900_v2.2.npy" <<'PY'
import numpy as np
import sys
np.save(sys.argv[1], np.zeros((899, 11), dtype=np.float32))
PY
  if output="$(python3 "${validator}" --input-dir "${invalid}" --dataset "${fixture_dataset}" --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'shape must be (900, 11)' <<< "${output}"
}

invalid_onnx_fails_closed() {
  local invalid="${temporary_root}/bad-onnx" output
  cp -a "${fixture_input}" "${invalid}"
  printf 'not-onnx\n' > "${invalid}/models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx"
  if output="$(python3 "${validator}" --input-dir "${invalid}" --dataset "${fixture_dataset}" --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'not a valid self-contained ONNX' <<< "${output}"
}

invalid_top_view_png_fails_closed() {
  local invalid="${temporary_root}/bad-top-view" output
  cp -a "${fixture_input}" "${invalid}"
  printf 'not-a-png\n' > "${invalid}/calibration/${fixture_dataset}/images/Top.png"
  if output="$(python3 "${validator}" --input-dir "${invalid}" \
      --dataset "${fixture_dataset}" --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'top-view image is not a decodable PNG' <<< "${output}"
}

copied_assets_are_revalidated_before_publish() {
  local mutable="${temporary_root}/copy-race-input"
  local destination="${temporary_root}/copy-race-runtime"
  local output
  cp -a "${fixture_input}" "${mutable}"
  if output="$(
    THOR_SPARSE4D_INPUT_DIR="${mutable}" \
    THOR_SPARSE4D_DATASET="${fixture_dataset}" \
    THOR_SPARSE4D_RUNTIME_DIR="${destination}" \
    THOR_SPARSE4D_FFPROBE_BIN="${fake_ffprobe}" \
    bash -s -- "${launcher}" 2>&1 <<'BASH'
set -euo pipefail
THOR_SPARSE4D_SOURCE_ONLY=true source "$1"
source_summary() {
  local result
  result="$(python3 "${input_validator}" \
    --input-dir "${THOR_SPARSE4D_INPUT_DIR}" \
    --dataset "${THOR_SPARSE4D_DATASET}" \
    --ffprobe "${ffprobe_bin}")"
  printf 'changed-after-source-validation\n' \
    > "${THOR_SPARSE4D_INPUT_DIR}/calibration/${THOR_SPARSE4D_DATASET}/images/Top.png"
  printf '%s\n' "${result}"
}
prepare_runtime
BASH
  )"; then
    return 1
  fi
  grep -q 'top-view image is not a decodable PNG' <<< "${output}" &&
    [[ ! -e "${destination}" ]] &&
    ! compgen -G "${temporary_root}/.warehouse-sparse4d-staging.*" >/dev/null
}

matrix_and_group_fail_closed() {
  local invalid="${temporary_root}/bad-calibration" output
  cp -a "${fixture_input}" "${invalid}"
  python3 - "${invalid}/calibration/${fixture_dataset}/calibration.json" <<'PY'
import json
import sys
path = sys.argv[1]
document = json.load(open(path, encoding="utf-8"))
document["sensors"][0]["intrinsicMatrix"][1][1] = float("nan")
json.dump(document, open(path, "w", encoding="utf-8"))
PY
  if output="$(python3 "${validator}" --input-dir "${invalid}" --dataset "${fixture_dataset}" --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'finite intrinsicMatrix' <<< "${output}"
}

sample_slug_fails_closed() {
  local output
  if output="$(python3 "${validator}" --input-dir "${fixture_input}" \
      --dataset warehouse-4cams-20mx20m-synthetic --ffprobe "${fake_ffprobe}" 2>&1)"; then
    return 1
  fi
  grep -q 'bundled sample slug' <<< "${output}"
}

failed_prepare_cleans_staging() {
  local parent="${temporary_root}/cleanup" patcher="${temporary_root}/failing.py"
  install -d "${parent}"
  printf 'raise SystemExit(9)\n' > "${patcher}"
  if THOR_SPARSE4D_INPUT_DIR="${fixture_input}" THOR_SPARSE4D_DATASET="${fixture_dataset}" \
      THOR_SPARSE4D_RUNTIME_DIR="${parent}/runtime" THOR_SPARSE4D_FFPROBE_BIN="${fake_ffprobe}" \
      THOR_SPARSE4D_OFFLINE_PATCHER="${patcher}" "${launcher}" prepare >/dev/null 2>&1; then
    return 1
  fi
  [[ ! -e "${parent}/runtime" ]] && ! compgen -G "${parent}/.warehouse-sparse4d-staging.*" >/dev/null
}

snapshot_drift_fails_closed() {
  local private_overlay="${fixture_runtime}/source/deploy/docker/thor-local/warehouse-sparse4d.compose.yml" output
  printf '\n# drift\n' >> "${private_overlay}"
  if output="$(THOR_SPARSE4D_RUNTIME_DIR="${fixture_runtime}" "${launcher}" validate minimal 2>&1)"; then
    return 1
  fi
  grep -q 'immutable deployment snapshot files changed' <<< "${output}"
}

overlay_has_offline_contract() {
  grep -q '^  perception-3d:' "${overlay}" &&
    grep -q 'TRANSFORMERS_OFFLINE: "1"' "${overlay}" &&
    grep -q 'THOR_SPARSE4D_LOGSTASH_IMAGE.*vss-logstash-redis' "${overlay}" &&
    grep -q 'network: none' "${overlay}" &&
    grep -q 'LOGSTASH_BASE_IMAGE:.*@sha256:a7ad817ec23e' "${overlay}" &&
    grep -q 'command: \[\]' "${overlay}" &&
    grep -q 'STREAM_TYPE: redis' "${overlay}" &&
    grep -q 'profiles: !override.*thor-sparse4d-dcgm-disabled' "${overlay}" &&
    grep -q 'ef29e5c3056057a872c78369a7a672f48d9fe1434e8eff654d3ad0b68ba85183' "${dockerfile}" &&
    grep -q 'logstash-plugin install' "${dockerfile}"
}

install -d \
  "${fixture_input}/models/sparse4d/ov" \
  "${fixture_input}/videos/${fixture_dataset}" \
  "${fixture_input}/calibration/${fixture_dataset}/images"
python3 - "${fixture_input}" "${fixture_dataset}" <<'PY'
import json
from pathlib import Path
import struct
import sys
import zlib
import numpy as np
import onnx
from onnx import TensorProto, helper

root = Path(sys.argv[1])
dataset = sys.argv[2]
node = helper.make_node("Identity", ["input"], ["output"])
graph = helper.make_graph(
    [node], "fixture-sparse4d",
    [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1])],
    [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1])],
)
model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
onnx.save(model, root / "models/sparse4d/ov/sparse4d_warehouse_v2.2.onnx")
np.save(root / "models/sparse4d/ov/_ov_kmeans900_v2.2.npy", np.zeros((900, 11), dtype=np.float32))

def matrix(rows, cols):
    return [[1.0 if row == col else 0.0 for col in range(cols)] for row in range(rows)]

sensors = []
for index, camera in enumerate(("Camera", "Camera_01", "Camera_02", "Camera_03")):
    sensors.append({
        "type": "camera", "id": camera,
        "coordinates": {"x": index, "y": index}, "scaleFactor": 1.0,
        "translationToGlobalCoordinates": {"x": 0, "y": 0},
        "group": {"name": "operator-bev", "type": "bev", "origin": [0, 0], "dimensions": [-5, -5, 5, 5]},
        "region": {"placeLevel": "region"}, "place": [{"name": "region", "value": "Operator"}],
        "imageCoordinates": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
        "globalCoordinates": [{"x": 0, "y": 0, "z": 1}, {"x": 1, "y": 0, "z": 1}, {"x": 1, "y": 1, "z": 1}, {"x": 0, "y": 1, "z": 1}],
        "cameraMatrix": matrix(3, 4), "intrinsicMatrix": matrix(3, 3),
        "extrinsicMatrix": matrix(3, 4), "homography": matrix(3, 3),
        "attributes": [{"name": "fps", "value": "30"}, {"name": "frameWidth", "value": "1920"}, {"name": "frameHeight", "value": "1080"}],
    })
cal = root / "calibration" / dataset
(cal / "calibration.json").write_text(json.dumps({"sensors": sensors}), encoding="utf-8")

def png_chunk(kind, payload):
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

png = (
    b"\x89PNG\r\n\x1a\n"
    + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
    + png_chunk(b"IEND", b"")
)
(cal / "images/Top.png").write_bytes(png)
(cal / "images/imageMetadata.json").write_text(json.dumps({"images": [{"view": "plan-view", "fileName": "Top.png"}]}), encoding="utf-8")
for camera in ("Camera", "Camera_01", "Camera_02", "Camera_03"):
    (root / "videos" / dataset / f"{camera}.mp4").write_bytes(camera.encode())
PY
printf '%s\n' '#!/usr/bin/env bash' \
  'frames=300' \
  'if [[ "${FAKE_FFPROBE_DRIFT:-false}" == "true" && "${!#}" == *Camera_03.mp4 ]]; then frames=299; fi' \
  'printf '\''{"streams":[{"codec_name":"h264","width":1920,"height":1080,"avg_frame_rate":"30/1","nb_frames":"%s"}],"format":{"start_time":"0.0","duration":"10.0"}}\n'\'' "${frames}"' \
  > "${fake_ffprobe}"
chmod +x "${fake_ffprobe}"

check "launcher shell syntax" bash -n "${launcher}"
check "validator Python syntax" python3 -c "import ast; ast.parse(open('${validator}', encoding='utf-8').read())"
check "renderer Python syntax" python3 -c "import ast; ast.parse(open('${renderer}', encoding='utf-8').read())"
check "offline patcher Python syntax" python3 -c "import ast; ast.parse(open('${offline_patcher}', encoding='utf-8').read())"
check "source-only mode exposes helpers" source_mode_exposes_helpers
check "launcher has no lifecycle or privileged execution" launcher_has_no_lifecycle_or_privileged_execution
check "overlay pins Sparse4D, Redis, offline Logstash, and no DCGM" overlay_has_offline_contract
check "valid custom source plans and copies into private state" valid_source_plans_and_prepares_without_touching_source
check "minimal and extended Compose graphs resolve exactly" both_profiles_resolve_exactly
check "launch command is pull-free, build-free, and non-executing" launch_command_is_offline_and_nonexecuting
check "unsynchronized videos fail closed" timeline_drift_fails_closed
check "malformed Sparse4D anchor fails closed" invalid_anchor_fails_closed
check "malformed Sparse4D ONNX fails closed" invalid_onnx_fails_closed
check "malformed top-view PNG fails closed" invalid_top_view_png_fails_closed
check "copied assets are revalidated before publish" copied_assets_are_revalidated_before_publish
check "non-finite calibration matrix fails closed" matrix_and_group_fail_closed
check "excluded NVIDIA sample slug fails closed" sample_slug_fails_closed
check "failed prepare removes only its staging directory" failed_prepare_cleans_staging
check "private snapshot drift fails checksum validation" snapshot_drift_fails_closed

if (( failures > 0 )); then
  printf '%d Thor Sparse4D static test(s) failed\n' "${failures}" >&2
  exit 1
fi
printf 'All Thor Sparse4D static tests passed.\n'
