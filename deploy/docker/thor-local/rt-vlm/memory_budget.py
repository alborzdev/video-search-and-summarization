#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed Thor unified-memory admission with a fixed 20% reserve."""

from __future__ import annotations

import argparse
import decimal
import sys
from pathlib import Path


RESERVE = decimal.Decimal("0.20")
KIB_PER_GIB = 1024 * 1024


class BudgetError(RuntimeError):
    """The requested vLLM fraction cannot preserve the fixed reserve."""


def parse_fraction(value: str) -> decimal.Decimal:
    try:
        fraction = decimal.Decimal(value)
    except decimal.InvalidOperation as exc:
        raise BudgetError(f"invalid utilization fraction: {value!r}") from exc
    if not fraction.is_finite() or fraction <= 0 or fraction > decimal.Decimal("0.80"):
        raise BudgetError("utilization must be greater than 0 and at most 0.80")
    return fraction


def required_available_kib(
    total_kib: int, utilization: decimal.Decimal, minimum_gib: int
) -> int:
    if total_kib <= 0 or minimum_gib < 0:
        raise BudgetError("memory totals and minimum must be non-negative")
    fractional = (
        decimal.Decimal(total_kib) * (utilization + RESERVE)
    ).to_integral_value(rounding=decimal.ROUND_CEILING)
    return max(int(fractional), minimum_gib * KIB_PER_GIB)


def read_meminfo(path: Path = Path("/proc/meminfo")) -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] in {"MemTotal:", "MemAvailable:"}:
                values[fields[0]] = int(fields[1])
    except (OSError, ValueError) as exc:
        raise BudgetError(
            f"cannot read memory availability from {path}: {exc}"
        ) from exc
    if set(values) != {"MemTotal:", "MemAvailable:"}:
        raise BudgetError(f"{path} lacks MemTotal or MemAvailable")
    return values["MemTotal:"], values["MemAvailable:"]


def check(
    total_kib: int, available_kib: int, utilization: decimal.Decimal, minimum_gib: int
) -> int:
    required = required_available_kib(total_kib, utilization, minimum_gib)
    if available_kib < required:
        raise BudgetError(
            "available unified memory is "
            f"{available_kib / KIB_PER_GIB:.1f} GiB; "
            f"{required / KIB_PER_GIB:.1f} GiB is required for utilization "
            f"{utilization} plus the fixed {RESERVE} reserve"
        )
    return required


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utilization", required=True)
    parser.add_argument("--minimum-gib", type=int, default=0)
    parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        utilization = parse_fraction(args.utilization)
        total_kib, available_kib = read_meminfo(args.meminfo)
        required = check(total_kib, available_kib, utilization, args.minimum_gib)
        print(
            f"[OK] available={available_kib / KIB_PER_GIB:.1f} GiB "
            f"required={required / KIB_PER_GIB:.1f} GiB "
            f"utilization={utilization} reserve={RESERVE}"
        )
    except BudgetError as exc:
        print(f"[BLOCK] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
