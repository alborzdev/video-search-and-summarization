#!/usr/bin/env python3
"""Verify retained Behavior Analytics embedding-downsampling evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"


class EvidenceError(RuntimeError):
    pass


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                EvidenceError(f"non-finite JSON: {token}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    receipt = _load(RECEIPT_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda error: list(error.path))
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    if receipt["contract_sha256"] != _sha(CONTRACT_PATH):
        raise EvidenceError("receipt contract binding drifted")
    for key in ("capability_ids", "official_indices", "policy"):
        if receipt[key] != contract[key]:
            raise EvidenceError(f"{key} drifted")

    locks: dict[str, str] = {}
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")
        locks[path.name] = lock["sha256"]
    if receipt["modes"]["sdt"]["config_sha256"] != locks["sdt-config.json"]:
        raise EvidenceError("SDT config identity drifted")
    if receipt["modes"]["window"]["config_sha256"] != locks["window-config.json"]:
        raise EvidenceError("window config identity drifted")

    expected_ids = {"sdt": ["0", "11", "12"], "window": ["0", "1", "2", "12"]}
    for mode, value in receipt["modes"].items():
        if value["output_frame_ids"] != expected_ids[mode]:
            raise EvidenceError(f"{mode} retained output identity drifted")
        if value["output_count"] != len(value["output_frame_ids"]):
            raise EvidenceError(f"{mode} output count drifted")
        if value["output_count"] >= value["input_count"]:
            raise EvidenceError(f"{mode} compression is not proven")
        if value["output_frame_ids"][0] != "0" or value["output_frame_ids"][-1] != "12":
            raise EvidenceError(f"{mode} boundary preservation drifted")
        if value["container"] != {"exit_code": 0, "oom_killed": False, "restart_count": 0}:
            raise EvidenceError(f"{mode} exit integrity drifted")
    if not all(value for key, value in receipt["cleanup"].items() if key != "failures"):
        raise EvidenceError("cleanup was not exact")
    if receipt["cleanup"]["failures"]:
        raise EvidenceError("cleanup recorded failures")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "show"), nargs="?", default="check")
    args = parser.parse_args(argv)
    try:
        receipt = verify()
        if args.mode == "show":
            print(json.dumps(receipt, indent=2, sort_keys=True))
        else:
            print(json.dumps({
                "status": "passed",
                "official_indices": receipt["official_indices"],
                "receipt_sha256": _sha(RECEIPT_PATH),
                "writes_or_lifecycle_actions": False,
            }, sort_keys=True))
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
