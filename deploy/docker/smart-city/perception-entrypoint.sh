#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Preserve NVIDIA's host compatibility checks and forward-compatibility setup.
exec /opt/nvidia/nvidia_entrypoint.sh /opt/city/city-worker "$@"
