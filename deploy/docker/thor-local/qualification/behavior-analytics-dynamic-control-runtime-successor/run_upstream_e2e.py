#!/usr/bin/env python3
"""Run NVIDIA's dynamic-control E2E driver on an isolated notification topic."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
DRIVERS = {
    "config": REPO / "services/analytics/behavior-analytics/tests/integration/dynamic_config/dynamic_config_e2e.py",
    "calibration": REPO / "services/analytics/behavior-analytics/tests/integration/dynamic_calibration/dynamic_calibration_e2e.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=sorted(DRIVERS))
    parser.add_argument("--notification-topic", required=True)
    parser.add_argument("--only-scenario")
    args, remainder = parser.parse_known_args()
    path = DRIVERS[args.mode]
    spec = importlib.util.spec_from_file_location(f"upstream_dynamic_{args.mode}_e2e", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load upstream driver: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.NOTIFICATION_TOPIC = args.notification_topic

    # The released container can replay a busy notification topic immediately
    # after restart. Docker's relative ``--since 30s`` query occasionally
    # misses the just-emitted bootstrap line during that burst. Use a bounded
    # tail of the same container log; scenario filenames/references remain
    # unique, so this changes transport reliability, not pass semantics.
    def _bounded_container_logs(container: str, since: str) -> str:
        if len(since) == 19 and since[10] == "T":
            since = f"{since}Z"
        proc = subprocess.run(
            ["docker", "logs", "--since", since, "--tail", "20000", container],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return proc.stdout + proc.stderr

    module._container_logs_since = _bounded_container_logs
    if args.only_scenario is not None:
        if args.mode != "config":
            raise ValueError("--only-scenario is supported only by the config driver")
        selected = [item for item in module.SCENARIOS if item[0] == args.only_scenario]
        if len(selected) != 1:
            raise ValueError(f"unknown config scenario: {args.only_scenario}")
        module.SCENARIOS = selected
    sys.argv = [str(path), *remainder]
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
