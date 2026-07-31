#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cache_dir="${SDG_OFFLINE_CACHE:-${script_dir}/offline-cache}"
environment_dir="${SDG_ENV_DIR:-${script_dir}/.thor-env}"
bootstrap_dir="${environment_dir}.bootstrap"
conda_lock="${script_dir}/conda-linux-aarch64.lock"
pip_requirements="${script_dir}/requirements-pip.txt"
wheel_lock="${script_dir}/wheels-linux-aarch64.sha256"
installer_name="Miniforge3-25.3.1-0-Linux-aarch64.sh"

if [[ "$(uname -m)" != "aarch64" ]]; then
  printf 'The Thor SDG environment requires Linux aarch64, not %s.\n' "$(uname -m)" >&2
  exit 1
fi

python3 "${script_dir}/verify_offline_cache.py" \
  "${cache_dir}" "${conda_lock}" "${pip_requirements}" "${wheel_lock}"

if [[ -x "${environment_dir}/bin/python" ]]; then
  SDG_ENV_DIR="${environment_dir}" "${script_dir}/qualify-thor-env.sh"
  exit 0
fi
if [[ -e "${environment_dir}" ]]; then
  printf 'Refusing to overwrite incomplete environment path: %s\n' "${environment_dir}" >&2
  exit 1
fi

if [[ ! -x "${bootstrap_dir}/bin/conda" ]]; then
  if [[ -e "${bootstrap_dir}" ]]; then
    printf 'Refusing to overwrite incomplete bootstrap path: %s\n' "${bootstrap_dir}" >&2
    exit 1
  fi
  bash "${cache_dir}/${installer_name}" -b -p "${bootstrap_dir}" >/dev/null
fi

temporary_dir="$(mktemp -d -t vss-sdg-offline.XXXXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT
python3 "${script_dir}/materialize_local_lock.py" \
  "${conda_lock}" "${cache_dir}/conda" "${temporary_dir}/local.lock"
CONDA_NO_PLUGINS=true "${bootstrap_dir}/bin/conda" create \
  --yes --offline --prefix "${environment_dir}" \
  --file "${temporary_dir}/local.lock" >/dev/null
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 "${environment_dir}/bin/python" -m pip install \
  --disable-pip-version-check --no-index --no-deps \
  --find-links "${cache_dir}/wheels" --requirement "${pip_requirements}"

SDG_ENV_DIR="${environment_dir}" "${script_dir}/qualify-thor-env.sh"
printf 'Created and qualified the pull-free Thor SDG environment at %s\n' \
  "${environment_dir}"
