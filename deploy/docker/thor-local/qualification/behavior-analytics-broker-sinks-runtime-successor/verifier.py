#!/usr/bin/env python3
"""Verify retained Behavior Analytics output-family x broker-sink evidence."""

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
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt),
        key=lambda error: list(error.path),
    )
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

    outputs = contract["advertised_contract"]["outputs"]
    backends = contract["advertised_contract"]["sink_types"]
    required = contract["required_assertions"]
    if list(receipt["payload_catalog"]) != outputs:
        raise EvidenceError("advertised output-family order drifted")
    if list(receipt["backends"]) != backends:
        raise EvidenceError("advertised broker order drifted")

    expected_identities = {
        "frames": {"id": "frame-1", "sensor": "sink-matrix-camera", "objects": 1},
        "behaviors": {"id": "behavior-1", "sensor": "sink-matrix-camera", "object": "track-1"},
        "events": {"id": "event-1", "sensor": "sink-matrix-camera", "object": "track-1", "event": "roi:ENTRY"},
        "incidents": {"sensor": "sink-matrix-camera", "category": "FOV Count Violation", "objects": 1},
        "anomalies": {"id": "anomaly-1", "sensor": "sink-matrix-camera", "object": "track-1", "anomaly_type": "qualification"},
        "cluster": {"id": "cluster-1", "sensor": "sink-matrix-camera", "object": "track-1", "cluster_index": "7"},
        "space-utilization": {"id": "zone-1", "sensors": ["sink-matrix-camera"], "total_space": 3.0},
    }
    for family, payload in receipt["payload_catalog"].items():
        if payload["decoded_identity"] != expected_identities[family]:
            raise EvidenceError(f"decoded protobuf identity drifted: {family}")

    route_count = 0
    for backend_name, backend in receipt["backends"].items():
        if backend["factory_class"] != required["sink_factory_classes"][backend_name]:
            raise EvidenceError(f"sink factory class drifted: {backend_name}")
        if list(backend["routes"]) != outputs or backend["family_count"] != len(outputs):
            raise EvidenceError(f"output-family coverage drifted: {backend_name}")
        for family, route in backend["routes"].items():
            payload = receipt["payload_catalog"][family]
            if route["destination_key"] != required["destination_keys"][family]:
                raise EvidenceError(f"destination key drifted: {backend_name}/{family}")
            if route["payload_sha256"] != payload["payload_sha256"]:
                raise EvidenceError(f"payload identity drifted: {backend_name}/{family}")
            if route["message_key"] != payload["message_key"]:
                raise EvidenceError(f"message key drifted: {backend_name}/{family}")
            if route["record_count"] != 1 or not route["headers_preserved"]:
                raise EvidenceError(f"record/header evidence drifted: {backend_name}/{family}")
            if backend_name == "mqtt":
                expected_destination = f"vss/sink/matrix/{route['destination_key']}"
            else:
                expected_destination = (
                    f"vss-sink-matrix-{backend_name}-{route['destination_key']}"
                )
            if route["broker_destination"] != expected_destination:
                raise EvidenceError(f"broker destination drifted: {backend_name}/{family}")
            route_count += 1

    if route_count != required["routes"] or route_count != receipt["cross_backend"]["route_count"]:
        raise EvidenceError("broker/output route count drifted")
    if not all(receipt["cross_backend"].values()):
        raise EvidenceError("cross-backend invariant drifted")
    behavior_image_id = receipt["runtime"]["behavior_image"]["image_id"]
    expected_container = {
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": 0,
        "image_id": behavior_image_id,
    }
    if not all(value["runtime"]["container"] == expected_container for value in receipt["backends"].values()):
        raise EvidenceError("released-image container integrity drifted")
    if not all(receipt["cleanup"]["broker_records_absent"].values()):
        raise EvidenceError("qualification broker records remain")
    if not receipt["cleanup"]["probe_containers_absent"] or not receipt["cleanup"]["mqtt_broker_absent"]:
        raise EvidenceError("disposable container cleanup drifted")
    expected_normal = {"running": True, "oom_killed": False, "restart_count": 0}
    if not all(value == expected_normal for value in receipt["cleanup"]["normal_behavior_containers"].values()):
        raise EvidenceError("normal Behavior Analytics containers drifted")
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
                "route_count": receipt["cross_backend"]["route_count"],
                "receipt_sha256": _sha(RECEIPT_PATH),
                "writes_or_lifecycle_actions": False,
            }, sort_keys=True))
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
