#!/usr/bin/env python3
"""Verify retained complete Behavior Analytics pipeline evidence."""

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

    advertised = contract["advertised_contract"]
    expected_coverage = set(advertised["inputs"]) | set(advertised["stages"])
    if set(receipt["stage_coverage"]) != expected_coverage:
        raise EvidenceError("advertised pipeline stage identity drifted")
    if not all(receipt["stage_coverage"].values()):
        raise EvidenceError("an advertised pipeline stage was not exercised")

    pipeline_input = receipt["input"]
    if not all(
        pipeline_input[name] == pipeline_input["objects"]
        for name in ("bbox_objects", "tracking_id_objects", "embedded_objects")
    ):
        raise EvidenceError("not every input object carried bbox/tracking/embedding")
    if pipeline_input["embedding_dimensions"] != [4] or not pipeline_input["embedding_finite"]:
        raise EvidenceError("input embedding identity drifted")

    control = receipt["control"]
    if control["baseline_behavior_max_points"] == control["updated_behavior_max_points"]:
        raise EvidenceError("dynamic configuration did not change the runtime value")
    if control["baseline_config_checkpoint_sha256"] == control["updated_config_checkpoint_sha256"]:
        raise EvidenceError("dynamic configuration checkpoints are not distinct")
    if control["ack_status"] != "success":
        raise EvidenceError("dynamic configuration was not acknowledged")

    outputs = receipt["outputs"]
    if outputs["frames"] != pipeline_input["frames"]:
        raise EvidenceError("enhanced frame count drifted")
    if outputs["enhanced_frame_objects"] != pipeline_input["objects"]:
        raise EvidenceError("enhanced object count drifted")
    if outputs["behaviors"] <= 0 or outputs["behavior_identity_count"] <= 0:
        raise EvidenceError("behavior state produced no identities")
    if outputs["behaviors_with_locations"] != outputs["behaviors"]:
        raise EvidenceError("coordinate transform did not reach every behavior output")
    if outputs["behaviors_with_embeddings"] != outputs["behaviors"]:
        raise EvidenceError("embedding did not reach every behavior output")
    if outputs["behavior_embedding_dimensions"] != [4] or not outputs["behavior_embeddings_finite"]:
        raise EvidenceError("behavior embedding identity drifted")
    if outputs["max_behavior_points"] != control["updated_behavior_max_points"]:
        raise EvidenceError("dynamic behavior limit was not reflected in output")
    if outputs["positive_fov_metric_entries"] <= 0 or outputs["positive_roi_metric_entries"] <= 0:
        raise EvidenceError("positive ROI/FOV metrics were absent")

    if receipt["runtime"]["container"] != {"exit_code": 0, "oom_killed": False, "restart_count": 0}:
        raise EvidenceError("container exit integrity drifted")
    if not receipt["cleanup"]["container_absent"] or not receipt["cleanup"]["backend_records_absent"]:
        raise EvidenceError("qualification cleanup was not exact")
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
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
