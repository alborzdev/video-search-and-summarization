#!/usr/bin/env python3
"""Verify retained Behavior Analytics space-utilization evidence."""

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
    if receipt["input"]["config_sha256"] != locks["oracle-config.json"]:
        raise EvidenceError("config identity drifted")
    if receipt["input"]["calibration_sha256"] != locks["calibration.json"]:
        raise EvidenceError("calibration identity drifted")
    if receipt["input"]["fixture_sha256"] != locks["warehouse_3d_playback_data.txt"]:
        raise EvidenceError("fixture identity drifted")

    outputs = receipt["outputs"]
    if set(outputs["positive_records"]) != {
        "occupied", "free", "total", "ratio", "extra_pallets", "utilizable_free_space"
    }:
        raise EvidenceError("metric family identity drifted")
    if not all(value > 0 for value in outputs["positive_records"].values()):
        raise EvidenceError("not every advertised metric was positive")
    if not all(value[1] > 0 for value in outputs["ranges"].values()):
        raise EvidenceError("metric range lacks a positive observation")
    if outputs["free_plus_occupied_max_error"] > 0.02 or outputs["ratio_max_error"] > 0.02:
        raise EvidenceError("metric arithmetic drifted")
    if outputs["free_layout_records"] != outputs["output_count"]:
        raise EvidenceError("free-space layouts drifted")
    if outputs["utilizable_layout_records"] != outputs["output_count"]:
        raise EvidenceError("utilizable layouts drifted")
    if receipt["container"] != {"exit_code": 0, "oom_killed": False, "restart_count": 0}:
        raise EvidenceError("container exit integrity drifted")
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
