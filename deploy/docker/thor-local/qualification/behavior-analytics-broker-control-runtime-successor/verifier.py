#!/usr/bin/env python3
"""Verify retained three-broker Behavior Analytics control/runtime evidence."""

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
            parse_constant=lambda token: (_ for _ in ()).throw(EvidenceError(f"non-finite JSON: {token}")),
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
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt), key=lambda error: list(error.path))
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    if receipt["contract_sha256"] != _sha(CONTRACT_PATH):
        raise EvidenceError("receipt contract binding drifted")
    for key in ("capability_ids", "official_indices", "policy"):
        if receipt[key] != contract[key]:
            raise EvidenceError(f"{key} drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")

    expected_sensors = receipt["fixture"]["sensor_names"]
    baseline_calibration = receipt["fixture"]["baseline_calibration_sha256"]
    source_hashes = {
        lock["path"].rsplit("/", 1)[-1].removesuffix("-config.json"): lock["sha256"]
        for lock in contract["source_locks"]
        if lock["path"].endswith(("kafka-config.json", "redis-config.json", "mqtt-config.json"))
    }
    for name, backend in receipt["backends"].items():
        if backend["source_config_sha256"] != source_hashes[name]:
            raise EvidenceError(f"{name} source config identity drifted")
        configs = backend["checkpoint"]["config"]
        if [item["behavior_max_points"] for item in configs] != ["200", "3"]:
            raise EvidenceError(f"{name} prior/new config identity drifted")
        if configs[0]["content_sha256"] == configs[1]["content_sha256"] or configs[0]["name_sha256"] == configs[1]["name_sha256"]:
            raise EvidenceError(f"{name} config checkpoints are not distinct")
        calibration = backend["checkpoint"]["calibration"]
        if calibration["content_sha256"] != backend["dynamic_calibration_sha256"]:
            raise EvidenceError(f"{name} dynamic calibration checkpoint drifted")
        if calibration["content_sha256"] == baseline_calibration or calibration["version"] != backend["dynamic_calibration_version"]:
            raise EvidenceError(f"{name} prior/new calibration identity drifted")
        output = backend["post_update"]
        if output["sensors"] != expected_sensors or output["max_behavior_points"] != 3:
            raise EvidenceError(f"{name} post-update config semantics drifted")
        if output["frames_with_fov_metrics"] != output["enhanced_frames"] or output["frames_with_roi_metrics"] != output["enhanced_frames"]:
            raise EvidenceError(f"{name} post-update calibration semantics drifted")
        if backend["request_reference_sha256"] == backend["ack_reference_sha256"]:
            raise EvidenceError(f"{name} request/ack identity is not auditable")
    if not all(value for key, value in receipt["cleanup"].items() if key != "failures") or receipt["cleanup"]["failures"]:
        raise EvidenceError("cleanup was not exact")
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
            print(json.dumps({"status": "passed", "official_indices": receipt["official_indices"], "receipt_sha256": _sha(RECEIPT_PATH), "writes_or_lifecycle_actions": False}, sort_keys=True))
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
