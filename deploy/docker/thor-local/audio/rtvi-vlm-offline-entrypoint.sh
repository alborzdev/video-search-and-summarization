#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# The immutable derivative already contains the codec root.  Keep NVIDIA's
# mutable startup downloader disabled even if a parent environment says true.
# shellcheck disable=SC1091
source /opt/nvidia/rtvi/thor-codecs/codec_env.sh
export INSTALL_PROPRIETARY_CODECS=false
exec /opt/nvidia/rtvi/start_rtvi_vlm.sh "$@"
