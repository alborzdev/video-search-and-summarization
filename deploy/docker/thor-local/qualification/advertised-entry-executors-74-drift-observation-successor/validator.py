#!/usr/bin/env python3
"""Validate the immutable 74-successor identity without replaying stale sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
HISTORICAL = (
    "deploy/docker/thor-local/qualification/advertised-entry-executors-74-successor"
)
INVENTORY_PATH = f"{HISTORICAL}/inventory.json"
RECEIPT_PATH = f"{HISTORICAL}/execution-receipt.json"
PINNED = {
    INVENTORY_PATH: "a9774af207f612e6c07936637d1141f5bc8e77df607363cfbac33aa447e19cb7",
    RECEIPT_PATH: "acfe8215c0666a990109e2e1d34a531ba5c2b3c2fa415f7cf901c5e7bddec99c",
    f"{HISTORICAL}/compiler.py": "3d6a84a0f53380809a8e992be6deff1d58c27b3abf73038439be5b3c8b8481eb",
    f"{HISTORICAL}/executor.py": "0edbe9bb5e29ffe1bd1a72439dd97ed861a14147b20939d514c96bd721af0198",
    f"{HISTORICAL}/inventory.schema.json": "e0bad7baa44b288b49bc46118dc1aef92a7d809278b68e88f46e95234c6a8422",
    f"{HISTORICAL}/result.schema.json": "9776016ef702a0437e1926d28a243a5a6e1a135dfd83226c2a9718546c584a43",
}
MAX_BYTES = 32_000_000


class ObservationError(RuntimeError):
    """An immutable identity or observation boundary drifted."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _repo_file(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ObservationError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise ObservationError(f"repository input unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ObservationError(f"repository path contains a symlink: {relative}")
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
        raise ObservationError(
            f"repository input is not bounded regular file: {relative}"
        )
    return path


def _read(relative: str) -> bytes:
    payload = _repo_file(relative).read_bytes()
    if len(payload) > MAX_BYTES:
        raise ObservationError(f"repository input exceeds bound: {relative}")
    return payload


def _json(payload: bytes, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ObservationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise ObservationError(f"JSON root is not an object: {label}")
    return value


def observe() -> dict[str, Any]:
    for path, expected in PINNED.items():
        if _sha(_read(path)) != expected:
            raise ObservationError(f"immutable 74-successor identity drift: {path}")

    inventory = _json(_read(INVENTORY_PATH), "immutable inventory")
    receipt = _json(_read(RECEIPT_PATH), "immutable execution receipt")
    waves = inventory.get("historical_waves")
    if not isinstance(waves, list) or [row.get("wave") for row in waves] != list(
        range(1, 8)
    ):
        raise ObservationError("historical Wave 1-7 denominator drift")
    for row in waves:
        for path_key, hash_key in (
            ("inventory_path", "inventory_sha256"),
            ("executor_path", "executor_sha256"),
        ):
            if _sha(_read(row[path_key])) != row[hash_key]:
                raise ObservationError(
                    f"immutable Wave {row['wave']} identity drift: {row[path_key]}"
                )

    if (
        receipt.get("candidate_only") is not True
        or receipt.get("can_mark_passed_current") is not False
        or receipt.get("runtime_evidence") != []
        or receipt.get("official_capability_effect") != "none_candidate_only"
        or receipt.get("inventory_payload_sha256")
        != inventory.get("inventory_payload_sha256")
    ):
        raise ObservationError("immutable receipt non-promotion boundary drift")

    source_rows = inventory.get("source_files")
    if not isinstance(source_rows, list) or len(source_rows) != 88:
        raise ObservationError("immutable 88-source denominator drift")
    locked: dict[str, str] = {}
    for row in source_rows:
        path, digest = row.get("path"), row.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str) or path in locked:
            raise ObservationError("malformed or duplicate immutable source lock")
        locked[path] = digest

    current = {path: _sha(_read(path)) for path in sorted(locked)}
    drifted = [path for path in current if current[path] != locked[path]]
    return {
        "schema_version": 1,
        "status": "pass_immutable_snapshot_not_replayed",
        "guarded_observer_receipt_raw_sha256": PINNED[RECEIPT_PATH],
        "historical_waves_verified": 7,
        "immutable_source_locks": len(locked),
        "currently_matching_sources": len(locked) - len(drifted),
        "currently_drifted_sources": len(drifted),
        "drifted_paths": drifted,
        "historical_dispatch_executed": False,
        "current_source_match_required": False,
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate and summarize")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    try:
        result = observe()
    except (ObservationError, KeyError, TypeError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "PASS: immutable 74 receipt preserved; historical dispatch suppressed; "
            f"current source drift={result['currently_drifted_sources']}/88"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
