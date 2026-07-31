#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
umask 077

tool_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
wheelhouse="${tool_dir}/wheelhouse"
requirements="${tool_dir}/requirements-linux-aarch64.txt"
lock="${tool_dir}/wheels-linux-aarch64.lock.json"
verifier="${tool_dir}/verify_wheelhouse.py"
python_image="python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c"

if [[ -d "${wheelhouse}" ]] &&
   python3 "${verifier}" --lock "${lock}" --requirements "${requirements}" --wheelhouse "${wheelhouse}"; then
  echo "[OK] VIOS MCP wheelhouse is already complete."
  exit 0
fi

[[ "$(uname -m)" == "aarch64" ]] || {
  echo "[ERROR] VIOS MCP wheels must be staged on Linux/AArch64; found $(uname -m)." >&2
  exit 1
}
command -v docker >/dev/null || {
  echo "[ERROR] docker is required to stage the exact Python 3.12 wheel set." >&2
  exit 1
}

stage_dir="$(mktemp -d "${tool_dir}/.wheelhouse.stage.XXXXXX")"
cleanup() {
  rm -rf -- "${stage_dir}"
}
trap cleanup EXIT

docker run --rm --platform linux/arm64 \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=${requirements},dst=/contract/requirements.txt,readonly" \
  --mount "type=bind,src=${stage_dir},dst=/out" \
  "${python_image}" \
  python -m pip download --disable-pip-version-check --no-deps \
    --only-binary=:all: --dest /out --requirement /contract/requirements.txt

python3 "${verifier}" --lock "${lock}" --requirements "${requirements}" --wheelhouse "${stage_dir}"

previous="${tool_dir}/wheelhouse.previous.$$"
if [[ -e "${wheelhouse}" ]]; then
  mv -- "${wheelhouse}" "${previous}"
fi
mv -- "${stage_dir}" "${wheelhouse}"
if [[ -e "${previous}" ]]; then
  rm -rf -- "${previous}"
fi
trap - EXIT
echo "[OK] Atomically staged the exact VIOS MCP wheelhouse at ${wheelhouse}."
