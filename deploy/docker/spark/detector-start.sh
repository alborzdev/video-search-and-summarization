#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

app=/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app
export GST_PLUGIN_PATH="/opt/nvidia/deepstream/deepstream/lib/gst-plugins:/usr/lib/aarch64-linux-gnu/gstreamer-1.0/deepstream${GST_PLUGIN_PATH:+:${GST_PLUGIN_PATH}}"
python3 /opt/spark/configure-detector.py --hardware "${VSS_DETECTOR_PLATFORM:-spark}"
cd "$app"
exec ./metropolis_perception_app -c /opt/storage/configs/ds-main-config.txt \
  -m 1 -t 0 -l 5 --message-rate 1 --show-sensor-id
