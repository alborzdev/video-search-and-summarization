#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
skills_source="${repo_root}/skills"
skills_destination="${VSS_SKILLS_DEST:-${CODEX_HOME:-${HOME}/.codex}/skills}"
action="${1:-status}"

usage() {
  cat <<'EOF'
Usage: install-vss-skills.sh [status|install]

  status   Check all NVIDIA VSS skill links without changing the host (default).
  install  Add missing symlinks under $VSS_SKILLS_DEST, $CODEX_HOME/skills, or
           ~/.codex/skills. Existing non-matching paths are never overwritten.
EOF
}

case "${action}" in
  status|install) ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ "${action}" == "install" ]]; then
  mkdir -p -- "${skills_destination}"
fi

found=0
ready=0
missing=0
conflicts=0
for skill_file in "${skills_source}"/*/SKILL.md; do
  [[ -f "${skill_file}" ]] || continue
  ((found += 1))
  skill_dir="${skill_file%/SKILL.md}"
  skill_name="${skill_dir##*/}"
  destination="${skills_destination}/${skill_name}"

  if [[ -L "${destination}" ]] &&
     [[ "$(readlink -f -- "${destination}")" == "$(readlink -f -- "${skill_dir}")" ]]; then
    echo "READY ${skill_name}"
    ((ready += 1))
    continue
  fi
  if [[ -e "${destination}" || -L "${destination}" ]]; then
    echo "CONFLICT ${skill_name}: ${destination} already exists and does not point at this checkout" >&2
    ((conflicts += 1))
    continue
  fi
  if [[ "${action}" == "install" ]]; then
    ln -s -- "${skill_dir}" "${destination}"
    echo "INSTALLED ${skill_name}"
    ((ready += 1))
  else
    echo "MISSING ${skill_name}"
    ((missing += 1))
  fi
done

if (( found != 16 )); then
  echo "ERROR: expected 16 VSS skills in ${skills_source}; found ${found}" >&2
  exit 1
fi
if (( conflicts > 0 )); then
  echo "ERROR: ${conflicts} conflicting skill path(s); no existing path was changed" >&2
  exit 1
fi
if [[ "${action}" == "status" ]] && (( missing > 0 )); then
  echo "INCOMPLETE: ${ready}/16 VSS skills point at this checkout" >&2
  exit 1
fi

echo "PASS: ${ready}/16 VSS skills point at this checkout"
