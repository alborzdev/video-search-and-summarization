#!/usr/bin/env python3
"""Verify the retained Thor Behavior Analytics 2D runtime evidence."""

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
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    if receipt["contract_sha256"] != _sha(CONTRACT_PATH):
        raise EvidenceError("receipt contract binding drifted")
    if receipt["capability_ids"] != contract["capability_ids"]:
        raise EvidenceError("capability identities drifted")
    if receipt["official_indices"] != contract["official_indices"]:
        raise EvidenceError("official indices drifted")
    if receipt["policy"] != contract["policy"]:
        raise EvidenceError("policy drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path) != lock["sha256"]:
            raise EvidenceError(f"source lock drifted: {lock['path']}")

    outputs = receipt["outputs"]
    if sum(outputs["events"]["types"].values()) != outputs["events"]["total"]:
        raise EvidenceError("event type totals do not reconcile")
    if sum(outputs["incidents"]["categories"].values()) != outputs["incidents"]["total"]:
        raise EvidenceError("incident category totals do not reconcile")
    if outputs["topic_counts"]["vss-oracle-ba-events"] != outputs["events"]["total"]:
        raise EvidenceError("event topic total does not reconcile")
    if outputs["topic_counts"]["vss-oracle-ba-incidents"] != outputs["incidents"]["total"]:
        raise EvidenceError("incident topic total does not reconcile")
    if receipt["input"]["playback_frames"] != outputs["topic_counts"]["vss-oracle-ba-frames"]:
        raise EvidenceError("frame input/output totals do not reconcile")
    if receipt["input"]["playback_objects"] != outputs["occupancy"]["frame_objects"]:
        raise EvidenceError("object input/output totals do not reconcile")
    if not all(receipt["cleanup"][key] for key in (
        "disposable_containers_absent",
        "qualification_topics_absent",
        "normal_behavior_containers_running",
    )) or receipt["cleanup"]["failures"]:
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
