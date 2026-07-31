#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render the fail-closed AGX Thor warehouse-2D environment.

The checked-in warehouse .env remains the source template. This helper writes
an operator-private generated.env with literal selectors and paths so Compose
does not inherit a different profile from an ambient shell.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import tempfile


ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def absolute_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"{label} must be an absolute path: {value}")
    return path


def env_value(value: str) -> str:
    return shlex.quote(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a minimal Redis warehouse-2D generated.env for Jetson AGX Thor."
    )
    parser.add_argument("--source", required=True, help="Checked-in warehouse .env template")
    parser.add_argument("--output", required=True, help="Private generated.env to write")
    parser.add_argument("--apps-dir", required=True, help="Mutable deploy/docker snapshot")
    parser.add_argument("--data-dir", required=True, help="Lane-private warehouse app data")
    parser.add_argument(
        "--bp-configurator-env-file",
        required=True,
        help="Final generated.env path injected into Configurator",
    )
    parser.add_argument("--repo-root", required=True, help="Canonical VSS checkout root")
    parser.add_argument("--streams", type=int, default=1, help="Smoke-test stream count (1-3)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.streams <= 3:
        raise SystemExit("--streams must be between 1 and 3 for the warehouse loading-dock dataset")

    source = absolute_path(args.source, "--source")
    output = absolute_path(args.output, "--output")
    apps_dir = absolute_path(args.apps_dir, "--apps-dir")
    data_dir = absolute_path(args.data_dir, "--data-dir")
    bp_env = absolute_path(args.bp_configurator_env_file, "--bp-configurator-env-file")
    repo_root = absolute_path(args.repo_root, "--repo-root")

    if not source.is_file():
        raise SystemExit(f"warehouse environment template is missing: {source}")
    if source.resolve() == output.resolve():
        raise SystemExit("refusing to overwrite the checked-in warehouse environment template")

    overrides = {
        "MODE": "2d",
        "BP_PROFILE": "bp_wh_redis",
        "MINIMAL_PROFILE": "true",
        "SAMPLE_VIDEO_DATASET": "warehouse-loading-dock-3cams-synthetic",
        "HARDWARE_PROFILE": "AGX-THOR",
        "RT_CV_DEVICE_ID": "0",
        "RT_VLM_DEVICE_ID": "0",
        "LLM_DEVICE_ID": "0",
        "LLM_MODE": "none",
        "VLM_MODE": "none",
        "LLM_NAME_SLUG": "none",
        "VLM_NAME_SLUG": "none",
        "COMPOSE_PROFILES": "bp_wh_redis_2d",
        "COMPOSE_PROJECT_NAME": "thor-wh-2d",
        "VSS_APPS_DIR": str(apps_dir),
        "VSS_DATA_DIR": str(data_dir),
        "VSS_REPO_ROOT": str(repo_root),
        "BP_CONFIGURATOR_ENV_FILE": str(bp_env),
        "HOST_IP": "127.0.0.1",
        "EXTERNAL_IP": "127.0.0.1",
        "VSS_PUBLIC_HOST": "127.0.0.1",
        "STREAM_TYPE": "redis",
        "NUM_STREAMS": str(args.streams),
        "PERCEPTION_TAG": "3.2.1",
        "NVSTREAMER_IMAGE_TAG": "3.2.1",
        "NVSTREAMER_INSTALL_ADDITIONAL_PACKAGES": "false",
        "VST_INSTALL_ADDITIONAL_PACKAGES": "false",
        "VST_VIDEO_STORAGE_SIZE_MB": "20000",
        "THOR_WAREHOUSE_VST_STREAM_PROCESSOR_IMAGE": "vss-vios-streamprocessing:3.2.1-thor-local",
        "THOR_WAREHOUSE_NVSTREAMER_IMAGE": "vss-vios-nvstreamer:3.2.1-thor-local",
        "THOR_WAREHOUSE_CONFIGURATOR_INIT_IMAGE": "cti-vss-warehouse-configurator-init:3.2.1-thor-local",
        "THOR_WAREHOUSE_BROKER_HEALTH_IMAGE": "cti-vss-warehouse-broker-health:3.2.1-thor-local",
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
                rendered.append(f"{key}={env_value(overrides[key])}")
                replaced.add(key)
            continue
        rendered.append(line)

    for key, value in overrides.items():
        if key not in replaced:
            rendered.append(f"{key}={env_value(value)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="generated.env.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(rendered))
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
