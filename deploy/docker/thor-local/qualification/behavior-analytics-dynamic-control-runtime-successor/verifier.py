#!/usr/bin/env python3
"""Verify retained Thor Behavior Analytics dynamic-control runtime evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"


class EvidenceError(RuntimeError):
    pass


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


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
        raise EvidenceError(f"expected JSON object: {path}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    receipt = _load(RECEIPT_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt),
        key=lambda error: list(error.path),
    )
    if errors:
        path = ".".join(str(item) for item in errors[0].path)
        raise EvidenceError(f"receipt schema violation at {path}: {errors[0].message}")
    if receipt["contract_sha256"] != _sha(CONTRACT_PATH):
        raise EvidenceError("receipt contract binding drifted")
    for key in ("capability_ids", "official_indices", "policy"):
        if receipt[key] != contract[key]:
            raise EvidenceError(f"{key} drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")

    config = receipt["dynamic_configuration"]
    if len(config["scenario_names"]) != config["official_driver_scenarios"]:
        raise EvidenceError("dynamic-config scenario total does not reconcile")
    if config["passed"] + config["failed"] != config["official_driver_scenarios"]:
        raise EvidenceError("dynamic-config results do not reconcile")
    calibration = receipt["dynamic_calibration"]
    if len(calibration["scenario_names"]) != calibration["official_driver_scenarios"]:
        raise EvidenceError("dynamic-calibration scenario total does not reconcile")
    if calibration["passed"] + calibration["failed"] != calibration["official_driver_scenarios"]:
        raise EvidenceError("dynamic-calibration results do not reconcile")
    if set(calibration["type_selection"]) != set(contract["required_assertions"]["dynamic_calibration"]["types"]):
        raise EvidenceError("calibration type coverage drifted")
    observation = receipt["topic_observation"]
    if sum(observation["key_counts"].values()) != observation["record_count"]:
        raise EvidenceError("topic key totals do not reconcile")
    if sum(sum(events.values()) for events in observation["event_counts"].values()) != observation["record_count"]:
        raise EvidenceError("topic event totals do not reconcile")
    if not all(value for key, value in receipt["cleanup"].items() if key != "failures") or receipt["cleanup"]["failures"]:
        raise EvidenceError("qualification cleanup was not exact")
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
