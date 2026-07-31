#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

python3 - "${repo_root}" <<'PY'
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1])
warehouse = root / "deploy/docker/industry-profiles/warehouse-operations"
blueprint = yaml.safe_load(
    (warehouse / "blueprint-configurator/blueprint_config.yml").read_text(encoding="utf-8")
)

thor = blueprint["AGX-THOR"]
igx_thor = blueprint["IGX-THOR"]
assert thor == igx_thor
assert thor["3d"]["max_streams_supported"] == 7
assert thor["mv3dt"]["max_streams_supported"] == 7

skill = (root / "skills/vss-deploy-detection-tracking-3d/SKILL.md").read_text(encoding="utf-8")
camera_reference = (
    root / "skills/vss-deploy-detection-tracking-3d/references/configure-cameras.md"
).read_text(encoding="utf-8")
assert "| Jetson AGX Thor | `AGX-THOR` | 7 |" in skill
assert "AGX-THOR)      CAP=7" in camera_reference

sparse_compose = (warehouse / "warehouse-3d-app/warehouse-3d-app.yml").read_text(encoding="utf-8")
mv3dt_compose = (warehouse / "warehouse-mv3dt-app/warehouse-mv3dt-app.yml").read_text(encoding="utf-8")
assert "${PERCEPTION_IMAGE:-nvcr.io/nvidia/vss-core/vss-rt-cv}:${PERCEPTION_TAG:-3.2.1}" in mv3dt_compose
assert "${BEV_FUSION_MV3DT_IMAGE:-nvcr.io/nvidia/vss-core/vss-rt-cv-mv3dt-bev-fusion}:${BEV_FUSION_MV3DT_TAG:-3.2.0}" in mv3dt_compose
for asset in ("sparse4d_warehouse_v2.2.onnx", "_ov_kmeans900_v2.2.npy"):
    assert asset in sparse_compose
assert "BodyPose3DNet" in mv3dt_compose

calibration_root = warehouse / "warehouse-mv3dt-app/calibration/sample-data/warehouse-4cams-20mx20m-synthetic"
assert (calibration_root / "calibration.json").is_file()
assert (calibration_root / "images/Top.png").is_file()
assert (calibration_root / "images/imageMetadata.json").is_file()
assert len(list((calibration_root / "camInfo").glob("Camera*.yml"))) == 4

print("All Thor RT-CV-3D static platform contracts passed.")
PY

for image in \
  nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1 \
  nvcr.io/nvidia/vss-core/vss-rt-cv-mv3dt-bev-fusion:3.2.0; do
  if docker image inspect "${image}" >/dev/null 2>&1; then
    [[ "$(docker image inspect "${image}" --format '{{.Os}}/{{.Architecture}}')" == "linux/arm64" ]]
    printf 'PASS: exact staged image is Linux/ARM64: %s\n' "${image}"
  else
    printf 'SKIP: exact 3D image is not staged: %s\n' "${image}"
  fi
done
