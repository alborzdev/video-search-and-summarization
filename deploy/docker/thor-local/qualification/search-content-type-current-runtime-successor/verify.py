#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Offline fail-closed verifier for the retained Search Content-Type receipt."""

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


def _strict(raw: bytes) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    value = _strict(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be an object")
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
        if not path.is_file() or _sha(path.read_bytes()) != digest:
            raise ValueError(f"current source lock mismatch: {relative}")

    if receipt["runtime"]["pre"] != receipt["runtime"]["post"]:
        raise ValueError("runtime identities changed")
    expected_images = contract["runtime"]["images"]
    observed_images = {
        row["name"]: row["image"] for row in receipt["runtime"]["pre"]["containers"]
    }
    if observed_images != expected_images:
        raise ValueError("runtime image set mismatch")

    cases = receipt["fixture"]["cases"]
    if [(row["media_type"], row["extension"]) for row in cases] != [
        ("video/mp4", "mp4"),
        ("video/x-matroska", "mkv"),
    ]:
        raise ValueError("positive media cases drifted")
    if any(
        row["status"] != 200
        or row["chunks_processed"] < 1
        or row["embed_document_count"] < 1
        or row["bytes"] > contract["fixture"]["maximum_bytes_per_file"]
        for row in cases
    ):
        raise ValueError("positive media semantics failed")
    if receipt["negative_cases"] != [
        {"case": "missing", "status": 400},
        {
            "case": "unsupported",
            "media_type": "application/octet-stream",
            "status": 400,
        },
    ]:
        raise ValueError("negative media semantics drifted")

    observations = receipt["observations"]
    if [row["sequence"] for row in observations] != list(
        range(1, len(observations) + 1)
    ):
        raise ValueError("observation sequence is not contiguous")
    if len(observations) != receipt["counts"]["http_requests"]:
        raise ValueError("HTTP request count mismatch")
    if (
        sum(1 for row in observations if row["mutation"])
        != receipt["counts"]["persistent_mutations"]
    ):
        raise ValueError("persistent mutation count mismatch")
    if receipt["counts"]["http_requests"] > contract["bounds"]["max_http_requests"]:
        raise ValueError("HTTP request bound exceeded")
    if (
        receipt["counts"]["persistent_mutations"]
        > contract["bounds"]["max_persistent_mutations"]
    ):
        raise ValueError("mutation bound exceeded")

    positive_hashes = {row["sensor_id_sha256"] for row in cases}
    cleanup_hashes = {
        row["sensor_id_sha256"] for row in receipt["cleanup"]["delete_results"]
    }
    if positive_hashes != cleanup_hashes or len(cleanup_hashes) != 2:
        raise ValueError("cleanup does not cover the exact positive sensor set")
    if not all(HEX64.fullmatch(value) for value in positive_hashes):
        raise ValueError("invalid retained identity digest")
    if receipt["cleanup"] != {
        "delete_results": receipt["cleanup"]["delete_results"],
        "exact_owned_resources_only": True,
        "exact_sensor_and_file_inventory_restored": True,
        "namespace_absent": True,
        "service_lifecycle_mutations": 0,
    }:
        raise ValueError("cleanup postconditions drifted")

    forbidden = [
        rb"nvapi-[A-Za-z0-9_-]+",
        rb"(?i)authorization\s*:",
        rb"(?i)bearer\s+[A-Za-z0-9._-]+",
        rb'"sensor_id"\s*:',
        rb'"request_id"\s*:',
        rb'"session_id"\s*:',
        rb'"sdp"\s*:',
        rb'"ice_candidate"\s*:',
        rb'"raw_prompt"\s*:',
        rb'"semantic_output"\s*:',
    ]
    if any(re.search(pattern, receipt_raw) for pattern in forbidden):
        raise ValueError("forbidden sensitive field or value in retained receipt")

    return {
        "package_id": receipt["package_id"],
        "status": "passed",
        "http_requests": receipt["counts"]["http_requests"],
        "persistent_mutations": receipt["counts"]["persistent_mutations"],
        "positive_cases": receipt["counts"]["positive_cases"],
        "negative_cases": receipt["counts"]["negative_cases"],
        "promotion_eligible": receipt["promotion_eligible"],
        "warehouse_sample_bundle": receipt["warehouse_sample_bundle"],
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
