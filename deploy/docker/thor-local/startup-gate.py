#!/usr/bin/env python3
"""Apply a host admission check, wait for one dependency, then exec a process.

Docker restart policies do not replay Compose ``depends_on`` ordering after a
host reboot. The Thor appliance therefore uses this tiny PID 1 gate for the
two order-sensitive model services: Cosmos waits for Kafka, and Nemotron waits
for Cosmos. Exact dual-model lanes can additionally require host memory before
the second model starts. Any failed gate exits without executing the workload.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
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


def _mem_available_kib(path: Path) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read memory information {path}: {exc}") from exc
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "MemAvailable:":
            try:
                available = int(fields[1])
            except ValueError as exc:
                raise ValueError(
                    f"invalid MemAvailable value in {path}: {line}"
                ) from exc
            if available < 0:
                raise ValueError(f"invalid MemAvailable value in {path}: {line}")
            return available
    raise ValueError(f"{path} lacks MemAvailable")


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
    parser.add_argument("--min-available-kib", type=int, default=0)
    parser.add_argument("--meminfo-path", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.min_available_kib < 0:
        parser.error("--min-available-kib cannot be negative")
    return args


def _memory_admitted(args: argparse.Namespace) -> bool:
    if not args.min_available_kib:
        return True
    try:
        available_kib = _mem_available_kib(args.meminfo_path)
    except ValueError as exc:
        print(
            f"[thor-startup-gate] memory admission unavailable: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return False
    if available_kib < args.min_available_kib:
        print(
            "[thor-startup-gate] memory admission blocked: "
            f"MemAvailable={available_kib} KiB, required>={args.min_available_kib} KiB",
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not _memory_admitted(args):
        return 78
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
            # The dependency itself can consume unified memory while this gate
            # waits. Recheck at the only point that matters: immediately before
            # replacing PID 1 with the second model.
            if not _memory_admitted(args):
                return 78
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
