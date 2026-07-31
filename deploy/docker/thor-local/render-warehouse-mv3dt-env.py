#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render a fail-closed Redis MV3DT environment for Jetson AGX Thor."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import tempfile


ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def absolute(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise SystemExit(f"{label} must be absolute: {value}")
    return path


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Thor-local MV3DT generated.env")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--apps-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--bp-configurator-env-file", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--streams", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    options = args()
    if not 2 <= options.streams <= 7:
        raise SystemExit("--streams must be between 2 and the AGX-THOR MV3DT cap of 7")
    source = absolute(options.source, "--source")
    output = absolute(options.output, "--output")
    apps = absolute(options.apps_dir, "--apps-dir")
    data = absolute(options.data_dir, "--data-dir")
    bp_env = absolute(options.bp_configurator_env_file, "--bp-configurator-env-file")
    repo = absolute(options.repo_root, "--repo-root")
    if not source.is_file():
        raise SystemExit(f"warehouse environment template is missing: {source}")
    if source.resolve() == output.resolve():
        raise SystemExit("refusing to overwrite the checked-in warehouse environment template")

    overrides = {
        "MODE": "mv3dt",
        "BP_PROFILE": "bp_wh_redis",
        "STREAM_TYPE": "redis",
        "MINIMAL_PROFILE": "true",
        "COMPOSE_PROFILES": "bp_wh_redis_mv3dt",
        "COMPOSE_PROJECT_NAME": "thor-wh-mv3dt",
        "SAMPLE_VIDEO_DATASET": options.dataset,
        "NUM_STREAMS": str(options.streams),
        "HARDWARE_PROFILE": "AGX-THOR",
        "RT_CV_DEVICE_ID": "0",
        "LLM_MODE": "none",
        "VLM_MODE": "none",
        "LLM_NAME_SLUG": "none",
        "VLM_NAME_SLUG": "none",
        "VSS_APPS_DIR": str(apps),
        "VSS_DATA_DIR": str(data),
        "VSS_REPO_ROOT": str(repo),
        "BP_CONFIGURATOR_ENV_FILE": str(bp_env),
        "HOST_IP": "127.0.0.1",
        "EXTERNAL_IP": "127.0.0.1",
        "VSS_PUBLIC_HOST": "127.0.0.1",
        "MQTT_HOST": "127.0.0.1",
        "MQTT_PORT": "1883",
        "SENSOR_INFO_SOURCE": "nvstreamer",
        "PERCEPTION_TAG": "3.2.1",
        "BEV_FUSION_MV3DT_TAG": "3.2.0",
        "NVSTREAMER_IMAGE_TAG": "3.2.1",
        "NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES": "false",
        "VST_INSTALL_ADDITIONAL_PACKAGES": "false",
        "VST_VIDEO_STORAGE_SIZE_MB": "20000",
        "OTEL_SDK_DISABLED": "true",
        "THOR_MV3DT_VST_STREAM_PROCESSOR_IMAGE": "vss-vios-streamprocessing:3.2.1-thor-local",
        "THOR_MV3DT_NVSTREAMER_IMAGE": "vss-vios-nvstreamer:3.2.1-thor-local",
        "THOR_MV3DT_CONFIGURATOR_INIT_IMAGE": "cti-vss-mv3dt-configurator-init:3.2.1-thor-local",
        "THOR_MV3DT_BROKER_HEALTH_IMAGE": "cti-vss-mv3dt-broker-health:3.2.1-thor-local",
        "THOR_MV3DT_ELASTICSEARCH_IMAGE": "cti-vss-mv3dt-elasticsearch:3.2.1-thor-local",
        "THOR_MV3DT_ELASTIC_INIT_IMAGE": "cti-vss-mv3dt-elastic-init:3.2.1-thor-local",
        "THOR_MV3DT_KIBANA_INIT_IMAGE": "cti-vss-mv3dt-kibana-init:3.2.1-thor-local",
        "THOR_MV3DT_CALIBRATION_IMPORT_IMAGE": "cti-vss-mv3dt-calibration-import:3.2.1-thor-local",
        "NGC_CLI_API_KEY": "",
        "NVIDIA_API_KEY": "",
        "OPENAI_API_KEY": "",
    }

    rendered: list[str] = []
    replaced: set[str] = set()
    for line in source.read_text(encoding="utf-8").splitlines():
        match = ASSIGNMENT.match(line)
        if match and match.group(1) in overrides:
            key = match.group(1)
            if key not in replaced:
                rendered.append(f"{key}={shlex.quote(overrides[key])}")
                replaced.add(key)
            continue
        rendered.append(line)
    for key, value in overrides.items():
        if key not in replaced:
            rendered.append(f"{key}={shlex.quote(value)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="generated.env.", dir=output.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(rendered) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
