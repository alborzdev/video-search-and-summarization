#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

if [[ ${VST_INSTALL_ADDITIONAL_PACKAGES:-false} == true ||
      ${NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES:-false} == true ]]; then
  echo "refusing runtime package installation in the Thor VIOS codec image" >&2
  exit 70
fi

[[ -r /usr/share/vss-thor/vios-codecs/manifest.json ]] || {
  echo "verified VIOS codec manifest is missing" >&2
  exit 70
}
[[ -e /usr/lib/aarch64-linux-gnu/libavcodec.so.60 ]] || {
  echo "VIOS codec filesystem is incomplete" >&2
  exit 70
}

exec /home/vst/vst_release/launch_vst "$@"
