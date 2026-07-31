#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sdg_root="$(cd -- "${script_dir}/.." && pwd)"
environment_dir="${SDG_ENV_DIR:-${script_dir}/.thor-env}"
python_bin="${environment_dir}/bin/python"

if [[ ! -x "${python_bin}" ]]; then
  printf 'Missing Thor SDG Python environment: %s\n' "${environment_dir}" >&2
  exit 1
fi

MPLBACKEND=Agg "${python_bin}" - <<'PY'
import importlib.metadata
import platform
import sys

from pxr import Gf, Usd, UsdSemantics

expected = {
    "annotated-types": "0.7.0",
    "contourpy": "1.3.2",
    "cycler": "0.12.1",
    "fonttools": "4.63.0",
    "h5py": "3.16.0",
    "kiwisolver": "1.5.0",
    "matplotlib": "3.10.9",
    "numpy": "2.2.6",
    "opencv-python-headless": "4.13.0.92",
    "packaging": "26.2",
    "pillow": "12.2.0",
    "pydantic": "2.13.4",
    "pydantic-core": "2.46.4",
    "pyparsing": "3.3.2",
    "pyquaternion": "0.9.9",
    "python-dateutil": "2.9.0.post0",
    "scipy": "1.15.3",
    "six": "1.17.0",
    "tqdm": "4.67.3",
    "typing-extensions": "4.15.0",
    "typing-inspection": "0.4.2",
}
assert platform.machine() == "aarch64", platform.machine()
assert sys.version_info[:2] == (3, 10), sys.version
for distribution, version in expected.items():
    assert importlib.metadata.version(distribution) == version, distribution
assert Usd.GetVersion() == (0, 26, 5), Usd.GetVersion()
assert Gf.Matrix4d(1.0) == Gf.Matrix4d().SetIdentity()
assert UsdSemantics.LabelsAPI
print("Pinned Python/OpenUSD import contract passed")
PY

"${environment_dir}/bin/ffmpeg" -version >/dev/null
"${environment_dir}/bin/ffprobe" -version >/dev/null
for source in \
  "${sdg_root}"/data_conversion/*.py \
  "${sdg_root}"/data_sanity_check/*.py \
  "${sdg_root}"/semantic_labeling/*.py \
  "${sdg_root}"/utils/*.py; do
  MPLBACKEND=Agg "${python_bin}" "${source}" --help >/dev/null
done

fixture_dir="$(mktemp -d -t vss-sdg-qualify.XXXXXXXX)"
trap 'rm -rf -- "${fixture_dir}"' EXIT
mkdir -p \
  "${fixture_dir}/dataset/_World_Cameras_Camera/rgb" \
  "${fixture_dir}/dataset/_World_Cameras_Camera/distance_to_image_plane"
"${python_bin}" - "${fixture_dir}" <<'PY'
from pathlib import Path
import sys

import cv2
import numpy as np
from pxr import Usd, UsdGeom

root = Path(sys.argv[1])
camera = root / "dataset" / "_World_Cameras_Camera"
image = np.full((16, 16, 3), 127, dtype=np.uint8)
assert cv2.imwrite(str(camera / "rgb" / "rgb_00000.jpg"), image)
np.save(
    camera / "distance_to_image_plane" / "distance_to_image_plane_00000.npy",
    np.full((16, 16), 1.25, dtype=np.float32),
)
stage = Usd.Stage.CreateNew(str(root / "scene.usda"))
world = UsdGeom.Xform.Define(stage, "/World")
world.AddRotateXYZOp().Set((10.0, 20.0, 30.0))
UsdGeom.Mesh.Define(stage, "/World/FlatBox_body")
stage.GetRootLayer().Save()
PY

"${python_bin}" "${sdg_root}/data_conversion/convert_npy_to_png_depthmap.py" \
  "${fixture_dir}/dataset" >/dev/null
"${python_bin}" "${sdg_root}/data_conversion/convert_single_camera_rgb_depth_to_h5.py" \
  --input "${fixture_dir}/dataset/_World_Cameras_Camera" >/dev/null
PATH="${environment_dir}/bin:${PATH}" \
  bash "${sdg_root}/data_conversion/convert_images_to_videos_no_bframes.sh" \
  "${fixture_dir}/dataset" >/dev/null 2>&1
PATH="${environment_dir}/bin:${PATH}" \
  bash "${sdg_root}/data_sanity_check/dataset_sanity_check_videos.sh" \
  "${fixture_dir}/dataset" >/dev/null
"${python_bin}" "${sdg_root}/semantic_labeling/box_check.py" \
  --stage "${fixture_dir}/scene.usda" --output "${fixture_dir}/boxes.txt" --apply \
  >/dev/null
"${python_bin}" "${sdg_root}/utils/export_xform_semantics.py" \
  --stage "${fixture_dir}/scene.usda" --output "${fixture_dir}/xforms.json" \
  >/dev/null
"${python_bin}" - "${fixture_dir}" <<'PY'
from pathlib import Path
import json
import sys

import h5py
from pxr import Usd, UsdSemantics

root = Path(sys.argv[1])
camera = root / "dataset" / "_World_Cameras_Camera"
assert (camera / "distance_to_image_plane_png" / "distance_to_image_plane_00000.png").is_file()
assert (root / "dataset" / "_World_Cameras_Camera.h5").is_file()
assert (camera / "video.mp4").is_file()
with h5py.File(root / "dataset" / "_World_Cameras_Camera.h5", "r") as archive:
    assert set(archive) == {"distance_to_image_plane_png", "rgb"}
stage = Usd.Stage.Open(str(root / "scene.usda"))
prim = stage.GetPrimAtPath("/World/FlatBox_body")
assert list(UsdSemantics.LabelsAPI.Get(prim, "class").GetLabelsAttr().Get()) == ["flatbox"]
assert json.loads((root / "xforms.json").read_text())["/World/FlatBox_body"]["rotate"] == [10.0, 20.0, 30.0]
print("Native depth/HDF5/video/OpenUSD fixture passed")
PY
"${python_bin}" "${sdg_root}/semantic_labeling/remove_label.py" \
  --stage "${fixture_dir}/scene.usda" >/dev/null

printf 'Thor SDG environment qualification passed.\n'
