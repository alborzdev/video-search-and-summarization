#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove public STUN dependencies from private MV3DT VST configs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile


RELATIVE_CONFIGS = (
    Path("industry-profiles/warehouse-operations/warehouse-mv3dt-app/vst/configs/vst_config.json"),
    Path("industry-profiles/warehouse-operations/warehouse-mv3dt-app/nvstreamer/configs/vst-config.json"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch private MV3DT VST configs for offline use")
    parser.add_argument("--apps-dir", required=True)
    options = parser.parse_args()
    apps = Path(options.apps_dir)
    if not apps.is_absolute() or apps.is_symlink() or not apps.is_dir():
        raise SystemExit(f"--apps-dir must be an absolute, non-symlink directory: {apps}")

    for relative in RELATIVE_CONFIGS:
        target = apps / relative
        if target.is_symlink() or not target.is_file():
            raise SystemExit(f"MV3DT VST config is missing or is a symlink: {target}")
        document = json.loads(target.read_text(encoding="utf-8"))
        network = document.get("network")
        if not isinstance(network, dict) or "stunurl_list" not in network:
            raise SystemExit(f"MV3DT VST config has no network.stunurl_list: {target}")
        # An empty array is not offline-safe: VST inserts its compiled public
        # DEFAULT_STUN_URL when no server is configured. A non-empty loopback
        # sentinel prevents that fallback without creating network egress.
        network["stunurl_list"] = ["127.0.0.1:3478"]
        network["use_twilio_stun_turn"] = False

        descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2)
                handle.write("\n")
            os.chmod(temporary, target.stat().st_mode & 0o777)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(f"offline STUN override: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
