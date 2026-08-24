#!/usr/bin/env python3
"""Wait for one local Thor dependency, then replace this process.

Docker restart policies do not replay Compose ``depends_on`` ordering after a
host reboot.  The Thor appliance therefore uses this tiny PID 1 gate for the
two order-sensitive model services: Cosmos waits for Kafka, and Nemotron waits
for Cosmos.  A timeout exits non-zero so ``restart: unless-stopped`` retries the
whole gate instead of starting a permanently degraded service.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
import urllib.request


def _tcp_ready(authority: str, timeout: float = 2.0) -> bool:
    host, separator, port_text = authority.rpartition(":")
    if not separator or not host or not port_text.isdigit():
        raise ValueError(f"invalid TCP authority: {authority!r}")
    with socket.create_connection((host, int(port_text)), timeout=timeout):
        return True


def _http_ready(url: str, timeout: float = 3.0) -> bool:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return 200 <= response.status < 300


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--tcp")
    target.add_argument("--http")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("THOR_STARTUP_GATE_TIMEOUT_SECONDS", "900")),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    description = f"tcp://{args.tcp}" if args.tcp else args.http
    deadline = time.monotonic() + args.timeout_seconds
    next_progress_log = 0.0

    while True:
        now = time.monotonic()
        try:
            ready = _tcp_ready(args.tcp) if args.tcp else _http_ready(args.http)
        except (OSError, ValueError):
            ready = False

        if ready:
            print(
                f"[thor-startup-gate] {description} is ready; starting {args.command[0]}",
                flush=True,
            )
            os.execvp(args.command[0], args.command)

        if now >= deadline:
            print(
                f"[thor-startup-gate] timed out waiting for {description}",
                file=sys.stderr,
                flush=True,
            )
            return 75

        if now >= next_progress_log:
            remaining = max(0, int(deadline - now))
            print(
                f"[thor-startup-gate] waiting for {description} "
                f"({remaining}s remaining)",
                flush=True,
            )
            next_progress_log = now + 30
        time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
