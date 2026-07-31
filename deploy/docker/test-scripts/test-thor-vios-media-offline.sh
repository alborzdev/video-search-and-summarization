#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
media_dir="${repo_root}/deploy/docker/thor-local/vios-codecs"

bash -n "${media_dir}/install-codec-bundle.sh" "${media_dir}/vios-offline-entrypoint.sh"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "${repo_root}/deploy/docker/thor-local/audio/tests" -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 "${media_dir}/vios_media.py" source-audit

for dockerfile in \
  "${repo_root}/deploy/docker/thor-local/Dockerfile.vios-streamprocessing" \
  "${repo_root}/deploy/docker/thor-local/Dockerfile.vios-nvstreamer"; do
  grep -Fq 'COPY deploy/docker/thor-local/vios-codecs/bundle/' "${dockerfile}"
  grep -Fq 'COPY deploy/docker/thor-local/audio/codec-bundle.lock.json' "${dockerfile}"
  grep -Fq 'ENTRYPOINT ["/usr/local/bin/vios-offline-entrypoint"]' "${dockerfile}"
  grep -Fq 'com.nvidia.vss.thor.vios-runtime-network-install="disabled"' "${dockerfile}"
  if grep -Eq '\b(apt|apt-get|curl|wget|pip)\b' "${dockerfile}"; then
    echo "network/package operation remains in ${dockerfile}" >&2
    exit 1
  fi
done

# The build-time installer is itself the frozen verifier. Before any extraction
# it binds the manifest to an exact unique archive set, verifies every hash and
# ARM64 control record, and recomputes the committed package-identity digest.
grep -Fq 'codec manifest contains duplicate archive filenames' \
  "${media_dir}/install-codec-bundle.sh"
grep -Fq 'codec manifest archive inventory does not match the bundle' \
  "${media_dir}/install-codec-bundle.sh"
grep -Fq 'codec bundle package identities do not match the VSS 3.2.1 set' \
  "${media_dir}/install-codec-bundle.sh"
grep -Fq 'codec bundle manifest does not match the canonical lock' \
  "${media_dir}/install-codec-bundle.sh"

for script in \
  "${media_dir}/install-codec-bundle.sh" \
  "${media_dir}/vios-offline-entrypoint.sh"; do
  if grep -Eq '\b(apt|apt-get|curl|wget|pip)\b' "${script}"; then
    echo "offline build/runtime script contains a network/package operation: ${script}" >&2
    exit 1
  fi
done

for overlay in \
  "${repo_root}/deploy/docker/thor-local/compose.yml" \
  "${repo_root}/deploy/docker/thor-local/warehouse-2d.compose.yml" \
  "${repo_root}/deploy/docker/thor-local/warehouse-mv3dt.compose.yml" \
  "${repo_root}/deploy/docker/thor-local/warehouse-sparse4d.compose.yml"; do
  grep -Fq 'network: none' "${overlay}"
  grep -Fq 'entrypoint: ["/usr/local/bin/vios-offline-entrypoint"]' "${overlay}"
done

# Preflight must either pass against fully staged artifacts or fail closed with
# explicit blockers. It must never attempt a container lifecycle operation.
preflight_output=$(mktemp)
set +e
PYTHONDONTWRITEBYTECODE=1 python3 "${media_dir}/vios_media.py" preflight >"${preflight_output}" 2>&1
preflight_rc=$?
set -e
if [[ ${preflight_rc} -ne 0 && ${preflight_rc} -ne 2 ]]; then
  cat "${preflight_output}" >&2
  exit 1
fi
if [[ ${preflight_rc} -eq 2 ]]; then
  grep -Fq 'BLOCKED ' "${preflight_output}"
fi

echo "Thor VIOS offline media static contracts passed (preflight rc=${preflight_rc})"
