#!/usr/bin/env python3
"""Offline fail-closed verifier for the retained LVS REST receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return raw, value


def verify() -> dict[str, Any]:
    contract_raw, contract = _load(HERE / "contract.json")
    receipt_raw, receipt = _load(HERE / "runtime-receipt.json")
    _, schema = _load(HERE / "receipt.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(receipt)
    if receipt_raw != _canonical(receipt) + b"\n":
        raise ValueError("runtime receipt is not canonical JSON")
    if receipt["contract_sha256"] != _sha(contract_raw):
        raise ValueError("contract digest mismatch")
    for key in ("package_id", "capability_id", "oracle_id", "target_commit"):
        if receipt[key] != contract[key]:
            raise ValueError(f"contract/receipt {key} mismatch")

    expected_sources = {row["path"]: row["sha256"] for row in contract["source_locks"]}
    if receipt["source_hashes"] != expected_sources:
        raise ValueError("source lock set mismatch")
    for relative, digest in expected_sources.items():
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or _sha(path.read_bytes()) != digest:
            raise ValueError(f"current source lock mismatch: {relative}")

    expected_operations = sorted(
        contract["expected_operations"], key=lambda row: (row["method"], row["path"])
    )
    observed_operations = [
        {"method": row["method"], "path": row["path"]} for row in receipt["operations"]
    ]
    if observed_operations != expected_operations:
        raise ValueError("operation coverage does not equal the exact contract")
    if receipt["discovery"]["operation_set_sha256"] != _sha(_canonical(expected_operations)):
        raise ValueError("operation set digest mismatch")
    if (
        receipt["discovery"]["expected_manifest_sha256"]
        != contract["expected_manifest_sha256"]
        or receipt["discovery"]["operation_count"] != len(expected_operations)
    ):
        raise ValueError("manifest or operation count mismatch")

    expected_negatives = {
        "recommended_config_schema": 422,
        "file_info_uuid_schema": 422,
        "caption_model_identity": 400,
        "chat_required_messages": 422,
        "live_caption_uuid_schema": 422,
        "file_delete_uuid_schema": 422,
    }
    if {row["case"]: row["status"] for row in receipt["negatives"]} != expected_negatives:
        raise ValueError("adjacent-negative set mismatch")
    if receipt["runtime"]["pre"] != receipt["runtime"]["post"]:
        raise ValueError("runtime identity changed")
    if not all(receipt["cleanup"].values()):
        raise ValueError("cleanup postcondition failed")

    lifecycle = receipt["file_lifecycle"]
    if (
        lifecycle["graph_asset_mid_count"] < 1
        or lifecycle["graph_mid"]["nodes"] <= lifecycle["graph_before"]["nodes"]
        or lifecycle["graph_mid"]["relationships"] <= lifecycle["graph_before"]["relationships"]
    ):
        raise ValueError("Q&A graph was not materially exercised")
    if receipt["live"]["caption_documents"] < 1:
        raise ValueError("no live caption reached local storage")
    if receipt["counts"]["requests"] > contract["bounds"]["max_requests"]:
        raise ValueError("request bound exceeded")
    if receipt["counts"]["actions"] > contract["bounds"]["max_actions"]:
        raise ValueError("action bound exceeded")
    if receipt["duration_seconds"] > contract["bounds"]["max_duration_seconds"]:
        raise ValueError("duration bound exceeded")

    forbidden = [
        rb"nvapi-[A-Za-z0-9_-]+",
        rb"(?i)authorization\s*:",
        rb"(?i)bearer\s+[A-Za-z0-9._-]+",
        rb'"(request_id|session_id|sdp|ice_candidate|raw_prompt|raw_response|semantic_output)"\s*:',
        rb"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    ]
    if any(re.search(pattern, receipt_raw) for pattern in forbidden):
        raise ValueError("forbidden sensitive field or value in retained receipt")

    return {
        "package_id": receipt["package_id"],
        "status": "passed",
        "operation_count": len(receipt["operations"]),
        "requests": receipt["counts"]["requests"],
        "actions": receipt["counts"]["actions"],
        "promotion_eligible": receipt["promotion_eligible"],
        "warehouse_sample_bundle": receipt["warehouse_sample_bundle"],
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
