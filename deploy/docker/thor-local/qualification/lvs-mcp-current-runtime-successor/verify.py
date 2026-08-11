#!/usr/bin/env python3
"""Offline fail-closed verifier for the retained LVS MCP runtime receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    value = json.loads(raw.decode(), object_pairs_hook=pairs)
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
    if receipt["runtime"]["pre"] != receipt["runtime"]["post"]:
        raise ValueError("runtime identity changed")
    if receipt["lifecycle"]["catalog_before"] != receipt["lifecycle"]["catalog_after"]:
        raise ValueError("MCP catalog was not restored")
    cleanup = receipt["cleanup"]
    if (
        cleanup["rest_catalog_before"] != cleanup["rest_catalog_after"]
        or cleanup["media_root_before"] != cleanup["media_root_after"]
    ):
        raise ValueError("external catalog or media root was not restored")
    expected_calls = [
        {"name": name, "result": "passed"}
        for name in contract["expected_success_calls"][:6]
    ]
    expected_calls += [
        {"name": "add_file", "result": "expected_error"},
        {"name": "delete_file", "result": "expected_error"},
    ]
    expected_calls += [
        {"name": name, "result": "passed"}
        for name in contract["expected_success_calls"][6:]
    ]
    if receipt["tool_calls"] != expected_calls:
        raise ValueError("tool call sequence drifted")
    for key in ("sha256", "filename_sha256", "sensor_name_sha256", "file_id_sha256"):
        if not HEX64.fullmatch(receipt["fixture"][key]):
            raise ValueError("fixture identity digest is invalid")
    forbidden = [
        rb"nvapi-[A-Za-z0-9_-]+",
        rb"(?i)authorization\s*:",
        rb"(?i)bearer\s+[A-Za-z0-9._-]+",
        rb'"(file_id|request_id|session_id|sdp|ice_candidate|raw_prompt|raw_response|semantic_output)"\s*:',
        rb"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    ]
    if any(re.search(pattern, receipt_raw) for pattern in forbidden):
        raise ValueError("forbidden sensitive field or value in retained receipt")
    return {
        "package_id": receipt["package_id"],
        "status": "passed",
        "tool_count": receipt["transport"]["tool_count"],
        "tool_calls": receipt["counts"]["tool_calls"],
        "persistent_mutations": receipt["counts"]["persistent_mutations"],
        "promotion_eligible": receipt["promotion_eligible"],
        "warehouse_sample_bundle": receipt["warehouse_sample_bundle"],
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
