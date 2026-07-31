#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cache_dir="${SDG_OFFLINE_CACHE:-${script_dir}/offline-cache}"
conda_lock="${script_dir}/conda-linux-aarch64.lock"
pip_requirements="${script_dir}/requirements-pip.txt"
wheel_lock="${script_dir}/wheels-linux-aarch64.sha256"
installer_name="Miniforge3-25.3.1-0-Linux-aarch64.sh"
installer_url="https://github.com/conda-forge/miniforge/releases/download/25.3.1-0/${installer_name}"
installer_sha256="a57c9e3d6c0c449c0283fd07e0bfa30d95eb8d547a14e8dc06c606405d01a7f0"

if [[ "$(uname -m)" != "aarch64" ]]; then
  printf 'The Thor SDG cache must be staged on Linux aarch64, not %s.\n' "$(uname -m)" >&2
  exit 1
fi

if [[ -f "${cache_dir}/SHA256SUMS" ]]; then
  python3 "${script_dir}/verify_offline_cache.py" \
    "${cache_dir}" "${conda_lock}" "${pip_requirements}" "${wheel_lock}"
  printf 'The verified Thor SDG cache is already staged at %s\n' "${cache_dir}"
  exit 0
fi

mkdir -p "${cache_dir}/conda" "${cache_dir}/wheels"
installer="${cache_dir}/${installer_name}"
if [[ ! -f "${installer}" ]] || \
   [[ "$(sha256sum "${installer}" | awk '{print $1}')" != "${installer_sha256}" ]]; then
  curl --fail --location --silent --show-error \
    --output "${installer}.partial" "${installer_url}"
  printf '%s  %s\n' "${installer_sha256}" "${installer}.partial" \
    | sha256sum --check --status
  mv -- "${installer}.partial" "${installer}"
fi

python3 - "${conda_lock}" "${cache_dir}/conda" <<'PY'
import concurrent.futures
import hashlib
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

lock = Path(sys.argv[1])
destination = Path(sys.argv[2])

def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()

def fetch(entry):
    url, expected = entry
    name = unquote(Path(urlparse(url).path).name)
    target = destination / name
    if target.is_file() and digest(target) == expected:
        return name
    partial = destination / f"{name}.partial"
    request = Request(url, headers={"User-Agent": "VSS-Thor-SDG-stager/1"})
    with urlopen(request, timeout=120) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    actual = digest(partial)
    if actual != expected:
        raise ValueError(f"Checksum mismatch for {name}: expected {expected}, got {actual}")
    os.replace(partial, target)
    return name

entries = []
for raw in lock.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line.startswith("https://"):
        url, separator, expected = line.partition("#")
        if not separator or len(expected) != 64:
            raise ValueError(f"Unpinned conda lock entry: {line}")
        entries.append((url, expected))
if not entries:
    raise ValueError(f"No conda package entries found in {lock}")
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    for index, name in enumerate(executor.map(fetch, entries), 1):
        if index % 25 == 0 or index == len(entries):
            print(f"Staged {index}/{len(entries)} conda packages ({name})")
PY

temporary_dir="$(mktemp -d -t vss-sdg-stage.XXXXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT
bash "${installer}" -b -p "${temporary_dir}/miniforge" >/dev/null
python3 "${script_dir}/materialize_local_lock.py" \
  "${conda_lock}" "${cache_dir}/conda" "${temporary_dir}/local.lock"
CONDA_NO_PLUGINS=true "${temporary_dir}/miniforge/bin/conda" create \
  --yes --offline --prefix "${temporary_dir}/postpro" \
  --file "${temporary_dir}/local.lock" >/dev/null
PIP_NO_CACHE_DIR=1 "${temporary_dir}/postpro/bin/python" -m pip download \
  --disable-pip-version-check --only-binary=:all: --no-deps \
  --dest "${cache_dir}/wheels" --requirement "${pip_requirements}"

python3 - "${cache_dir}" <<'PY'
import hashlib
import os
from pathlib import Path
import sys

cache = Path(sys.argv[1]).resolve()
sidecar = cache / "SHA256SUMS"
lines = []
for artifact in sorted(path for path in cache.rglob("*") if path.is_file()):
    if artifact == sidecar or artifact.name.endswith(".partial"):
        continue
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    lines.append(f"{digest}  {artifact.relative_to(cache)}")
partial = cache / "SHA256SUMS.partial"
partial.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.replace(partial, sidecar)
PY

python3 "${script_dir}/verify_offline_cache.py" \
  "${cache_dir}" "${conda_lock}" "${pip_requirements}" "${wheel_lock}"
printf 'Staged the complete Thor SDG offline cache at %s\n' "${cache_dir}"
