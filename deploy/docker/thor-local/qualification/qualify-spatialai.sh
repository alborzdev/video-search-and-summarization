#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../../.." && pwd)"
package_dir="${repo_root}/libs/analytics/spatialai-data-utils"
python_bin="${SPATIALAI_QUALIFY_PYTHON:-python3}"

if [[ "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: qualify-spatialai.sh

Create an isolated temporary Python environment and run the complete
SpatialAI data-utils test suite on Thor. This connected tooling qualification
downloads pinned Python wheels and builds pinned PyTorch3D from source. It
does not download a dataset or interact with the VSS deployment.

Optional environment:
  SPATIALAI_QUALIFY_PYTHON  Python >=3.11 interpreter (default: python3)
  MAX_JOBS                 PyTorch3D build parallelism (default: 1)
EOF
  exit 0
fi

if (( $# != 0 )); then
  echo "Unknown argument: $1" >&2
  exit 2
fi

command -v "${python_bin}" >/dev/null 2>&1 || {
  echo "Missing Python interpreter: ${python_bin}" >&2
  exit 1
}

venv_dir="$(mktemp -d "${TMPDIR:-/tmp}/vss-spatialai-qual.XXXXXX")"
cleanup() {
  if [[ -n "${venv_dir:-}" && -d "${venv_dir}" ]]; then
    find "${venv_dir}" -depth -delete
  fi
}
trap cleanup EXIT

"${python_bin}" -m venv "${venv_dir}"
qual_python="${venv_dir}/bin/python"

"${qual_python}" -m pip install 'pip==26.2'
"${qual_python}" -m pip install -e "${package_dir}/release[eval,viz]" 'pytest==9.0.3'
"${qual_python}" -m pip install 'torch==2.13.0+cpu' \
  --index-url https://download.pytorch.org/whl/cpu
MAX_JOBS="${MAX_JOBS:-1}" "${qual_python}" -m pip install \
  'pytorch3d @ git+https://github.com/facebookresearch/pytorch3d.git@33824be' \
  --no-build-isolation

PYTHONDONTWRITEBYTECODE=1 "${qual_python}" -m pytest -q "${package_dir}/tests"
