#!/usr/bin/env python3
"""Verify retained Behavior Analytics custom Sink runtime evidence."""

from __future__ import annotations

import argparse
import ast
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


def _custom_sink_ast() -> tuple[str, set[str]]:
    tree = ast.parse((HERE / "custom_sink.py").read_text(encoding="utf-8"))
    node = next(
        (value for value in tree.body if isinstance(value, ast.ClassDef) and value.name == "JsonlFileSink"),
        None,
    )
    if node is None:
        raise EvidenceError("JsonlFileSink class is absent")
    bases = {base.id for base in node.bases if isinstance(base, ast.Name)}
    methods = {value.name for value in node.body if isinstance(value, ast.FunctionDef)}
    if "Sink" not in bases:
        raise EvidenceError("JsonlFileSink no longer subclasses Sink")
    return "Sink", methods


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

    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")

    base_class, methods = _custom_sink_ast()
    interface = receipt["interface"]
    required = contract["required_assertions"]
    if base_class != interface["base_class"] or base_class != required["base_class"]:
        raise EvidenceError("Sink base interface drifted")
    if set(interface["implemented_methods"]) != {"write", "write_msg", "close"}:
        raise EvidenceError("custom Sink method surface drifted")
    if not set(interface["implemented_methods"]).issubset(methods):
        raise EvidenceError("custom Sink implementation is incomplete")
    if not interface["concrete"]:
        raise EvidenceError("custom Sink remained abstract at runtime")

    if receipt["batch_write"]["records"] != len(receipt["batch_write"]["event_ids"]):
        raise EvidenceError("batch record arithmetic drifted")
    if receipt["batch_write"]["event_ids"] != receipt["batch_write"]["keys"]:
        raise EvidenceError("batch key extraction drifted")
    if not receipt["batch_write"]["json_bytes_serializer"]:
        raise EvidenceError("JSON serializer path was not exercised")
    if not receipt["batch_write"]["binary_header_preserved"]:
        raise EvidenceError("binary header was not preserved")
    if not receipt["single_write"]["opaque_bytes_preserved"]:
        raise EvidenceError("single-message opaque bytes drifted")
    if not receipt["protobuf_write"]["proto_bytes_serializer"]:
        raise EvidenceError("protobuf serializer path was not exercised")
    if receipt["outputs"]["event_records"] != (
        receipt["batch_write"]["records"] + receipt["single_write"]["records"]
    ):
        raise EvidenceError("event destination routing arithmetic drifted")
    if receipt["outputs"]["incident_records"] != receipt["protobuf_write"]["records"]:
        raise EvidenceError("incident destination routing arithmetic drifted")
    if receipt["outputs"]["destinations"] != required["destination_routing"]:
        raise EvidenceError("destination routing drifted")
    if not receipt["outputs"]["double_close_safe"]:
        raise EvidenceError("close lifecycle drifted")

    if receipt["integration_boundary"]["factory_registration_claimed"]:
        raise EvidenceError("unsupported built-in factory registration was claimed")
    if receipt["runtime"]["container"] != {"exit_code": 0, "oom_killed": False, "restart_count": 0}:
        raise EvidenceError("container exit integrity drifted")
    if not receipt["cleanup"]["disposable_container_absent"]:
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
                "receipt_sha256": _sha(RECEIPT_PATH),
                "writes_or_lifecycle_actions": False,
            }, sort_keys=True))
        return 0
    except (EvidenceError, OSError, SyntaxError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
