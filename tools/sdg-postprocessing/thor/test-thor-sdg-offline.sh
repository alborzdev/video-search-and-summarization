#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sdg_root="$(cd -- "${script_dir}/.." && pwd)"

bash -n \
  "${script_dir}/stage-offline-cache.sh" \
  "${script_dir}/create-offline-env.sh" \
  "${script_dir}/qualify-thor-env.sh"
python3 -m py_compile \
  "${script_dir}/materialize_local_lock.py" \
  "${script_dir}/verify_offline_cache.py"

python3 - "${script_dir}" "${sdg_root}/requirements.txt" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
upstream = Path(sys.argv[2])
pip_requirements = root / "requirements-pip.txt"
wheel_lock = root / "wheels-linux-aarch64.sha256"
lock = root / "conda-linux-aarch64.lock"

upstream_lines = [
    line.strip()
    for line in upstream.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
thor_lines = [
    line.strip()
    for line in pip_requirements.read_text(encoding="utf-8").splitlines()
    if line.strip()
]
assert thor_lines == [line for line in upstream_lines if line != "usd-core==26.5"]
lock_lines = lock.read_text(encoding="utf-8").splitlines()
urls = [line for line in lock_lines if line.startswith("https://")]
assert len(urls) == 178, len(urls)
assert all("conda.anaconda.org/conda-forge/" in line for line in urls)
assert all(re.search(r"#[0-9a-f]{64}$", line) for line in urls)
assert any("python-3.10.20-" in line for line in urls)
assert any("openusd-26.05-py310" in line for line in urls)
assert any("ffmpeg-8.1.2-" in line for line in urls)
wheel_lines = wheel_lock.read_text(encoding="utf-8").splitlines()
assert len(wheel_lines) == 21, len(wheel_lines)
assert all(re.fullmatch(r"[0-9a-f]{64}  wheels/[^/]+\.whl", line) for line in wheel_lines)
stage_source = (root / "stage-offline-cache.sh").read_text(encoding="utf-8")
create_source = (root / "create-offline-env.sh").read_text(encoding="utf-8")
assert "--offline" in stage_source and "--offline" in create_source
assert "--no-index" in create_source
assert "wheels-linux-aarch64.sha256" in stage_source and "wheels-linux-aarch64.sha256" in create_source
assert "a57c9e3d6c0c449c0283fd07e0bfa30d95eb8d547a14e8dc06c606405d01a7f0" in stage_source
print("Thor SDG offline source contract passed")
PY

pytest -q "${sdg_root}/tests/test_sdg_regressions.py"
