#!/usr/bin/env python3
"""Verify retained Behavior Analytics events-and-incidents evidence."""

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
BASE_DIR = REPO / "deploy/docker/thor-local/qualification/behavior-analytics-2d-runtime-successor"


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


def _sha_json(value: Any) -> str:
    rendered = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(rendered).hexdigest()


def verify() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    receipt = _load(RECEIPT_PATH)
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(receipt), key=lambda error: list(error.path)
    )
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    if receipt["contract_sha256"] != _sha(CONTRACT_PATH):
        raise EvidenceError("receipt contract binding drifted")
    for key in ("capability_ids", "official_indices", "policy"):
        if receipt[key] != contract[key]:
            raise EvidenceError(f"{key} drifted")

    locked: dict[str, Path] = {}
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")
        locked[lock["path"]] = path

    base_contract_path = BASE_DIR / "contract.json"
    base_receipt_path = BASE_DIR / "runtime-receipt.json"
    base_schema_path = BASE_DIR / "receipt.schema.json"
    base_contract = _load(base_contract_path)
    base_receipt = _load(base_receipt_path)
    base_schema = _load(base_schema_path)
    Draft202012Validator.check_schema(base_schema)
    base_errors = sorted(
        Draft202012Validator(base_schema).iter_errors(base_receipt),
        key=lambda error: list(error.path),
    )
    if base_errors:
        raise EvidenceError(f"base 2D receipt schema violation: {base_errors[0].message}")
    if base_receipt["contract_sha256"] != _sha(base_contract_path):
        raise EvidenceError("base 2D receipt contract binding drifted")
    if base_contract["package_id"] != "behavior-analytics-2d-runtime-successor":
        raise EvidenceError("base 2D package identity drifted")

    base = receipt["base_2d_evidence"]
    expected_base_identity = {
        "package_id": base_contract["package_id"],
        "contract_sha256": _sha(base_contract_path),
        "receipt_sha256": _sha(base_receipt_path),
        "receipt_schema_sha256": _sha(base_schema_path),
    }
    if {key: base[key] for key in expected_base_identity} != expected_base_identity:
        raise EvidenceError("base 2D evidence identity drifted")
    if base["events"] != base_receipt["outputs"]["events"]:
        raise EvidenceError("base directional event evidence drifted")
    if base["incidents"] != base_receipt["outputs"]["incidents"]:
        raise EvidenceError("base incident evidence drifted")
    if sum(base["events"]["types"].values()) != base["events"]["total"]:
        raise EvidenceError("base event count arithmetic drifted")
    if sum(base["incidents"]["categories"].values()) != base["incidents"]["total"]:
        raise EvidenceError("base incident count arithmetic drifted")

    required_event_types = set(contract["required_assertions"]["event_types"])
    if set(base["events"]["types"]) != required_event_types:
        raise EvidenceError("tripwire/ROI directional event coverage drifted")
    if not all(value > 0 for value in base["events"]["types"].values()):
        raise EvidenceError("a tripwire/ROI directional event was not observed")

    fov = receipt["fov_runtime"]
    config_path = BASE_DIR / "oracle-config.json"
    runtime_config = json.loads(json.dumps(_load(config_path)))
    by_name = {item["name"]: item for item in runtime_config["app"]}
    for item in fov["config"]["app"]:
        by_name[item["name"]] = item
    runtime_config["app"] = list(by_name.values())
    if fov["runtime_config_sha256"] != _sha_json(runtime_config):
        raise EvidenceError("derived FOV runtime configuration drifted")
    if fov["baseline_config_sha256"] != _sha(config_path):
        raise EvidenceError("FOV baseline configuration drifted")

    incidents = fov["incidents"]
    if incidents["count"] != len(incidents["object_id_counts"]):
        raise EvidenceError("FOV incident/object identity count drifted")
    if not all(value > 0 for value in incidents["object_id_counts"]):
        raise EvidenceError("FOV incident omitted its contributing object identity")
    if not incidents["all_start_before_or_equal_end"] or not incidents["positive_time_bounds"]:
        raise EvidenceError("FOV incident time identity drifted")
    if incidents["complete_count"] != 0 or incidents["observation_state"] != "ongoing_at_capture":
        raise EvidenceError("FOV observation completion claim drifted")
    if fov["container"] != {"exit_code": 0, "oom_killed": False, "restart_count": 0}:
        raise EvidenceError("FOV container exit integrity drifted")

    observed_categories = set(base["incidents"]["categories"]) | set(incidents["categories"])
    if observed_categories != set(contract["required_assertions"]["incident_categories"]):
        raise EvidenceError("four-class violation coverage drifted")
    if receipt["coverage"] != contract["advertised_contract"]:
        raise EvidenceError("advertised event/violation coverage drifted")
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
