#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run bounded, read-only Search route/schema/fixture readiness checks."""

from __future__ import annotations

import ast
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[4].resolve(strict=True)
MAX_JSON_BYTES = 131_072


class ContractError(RuntimeError):
    """A static readiness invariant failed closed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path, maximum: int = MAX_JSON_BYTES) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ContractError(f"cannot stat {path}") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not (0 < metadata.st_size <= maximum)
    ):
        raise ContractError(f"not a bounded regular file: {path}")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if not hasattr(os, "O_NOFOLLOW"):
        raise ContractError("O_NOFOLLOW is required")
    descriptor = os.open(path, flags | os.O_NOFOLLOW)
    try:
        raw = os.read(descriptor, maximum + 1)
        if len(raw) != metadata.st_size:
            raise ContractError(f"short or unstable read: {path}")
        return raw
    finally:
        os.close(descriptor)


def _json(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ContractError(f"duplicate key {key} in {path}")
            result[key] = value
        return result

    try:
        value = json.loads(_read_regular(path), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON: {path}") from exc
    if type(value) is not dict:
        raise ContractError(f"JSON root is not an object: {path}")
    return value


def _repo_path(relative: str) -> Path:
    path = (REPO_ROOT / relative).resolve(strict=True)
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ContractError(f"path escapes repository: {relative}") from exc
    return path


def _endpoint_bindings(relative: str) -> dict[str, str]:
    source = _read_regular(_repo_path(relative), 2_000_000).decode("utf-8")
    matches = re.findall(
        r"^\s*- path:\s*(\S+)\s*$\n"
        r"^\s*method:\s*POST\s*$\n"
        r"^\s*description:\s*.*$\n"
        r"^\s*function_name:\s*(\S+)\s*$",
        source,
        flags=re.MULTILINE,
    )
    bindings = dict(matches)
    if len(bindings) != len(matches):
        raise ContractError(f"duplicate endpoint path: {relative}")
    return bindings


def _model_fields(relative: str, class_name: str) -> set[str]:
    source = _read_regular(_repo_path(relative), 2_000_000).decode("utf-8")
    tree = ast.parse(source, filename=relative)
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(matches) != 1:
        raise ContractError(f"expected exactly one {class_name}")
    return {
        node.target.id
        for node in matches[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def execute() -> dict[str, Any]:
    contract = _json(PACKAGE_DIR / "contract.json")
    locks = contract["source_locks"]
    if type(locks) is not list or len(locks) != 22:
        raise ContractError("source-lock inventory is not exact-twenty-two")
    seen: set[str] = set()
    for lock in locks:
        relative = lock["path"]
        if relative in seen:
            raise ContractError(f"duplicate source lock: {relative}")
        seen.add(relative)
        if _sha256(_read_regular(_repo_path(relative), 2_000_000)) != lock["sha256"]:
            raise ContractError(f"source lock mismatch: {relative}")

    predecessor = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/"
            "lvs-rtvi-current-contract-source-claim-layered-successor/"
            "layered-current-contract.json"
        )
    )
    predecessor_api_rows = [
        row
        for row in predecessor["current_contract_inputs"]
        if row["path"] == "deploy/docker/thor-local/qualification/api_inventory.json"
    ]
    if len(predecessor_api_rows) != 1 or predecessor_api_rows[0]["raw_sha256"] != (
        "e621f0b8a9e8be6fa04535965bdefc17910c6d88284779fc95daafeb4f66c482"
    ):
        raise ContractError("layered current-contract predecessor identity drift")
    if predecessor["summary"]["rt_vlm_operation_count"] != 28:
        raise ContractError("predecessor RT-VLM contract drift")
    if predecessor["summary"]["lvs_operation_count"] != 18:
        raise ContractError("predecessor LVS contract drift")
    if predecessor["summary"]["lvs_mcp_tool_count"] != 13:
        raise ContractError("predecessor LVS MCP contract drift")
    inventory = _json(
        _repo_path("deploy/docker/thor-local/qualification/api_inventory.json")
    )
    if inventory["expected_totals"] != {
        "declared_rest_operations": 350,
        "normalized_unique_rest_operations": 349,
        "official_declared_rest_operations": 346,
        "official_normalized_unique_rest_operations": 345,
        "thor_local_extension_operations": 4,
        "mcp_tools": 42,
        "mcp_prompts": 5,
    }:
        raise ContractError("successor aggregate API totals drift")
    expected_inventory_result = {
        "agent_declared_operations": 64,
        "agent_normalized_unique_operations": 64,
        "aggregate_declared_rest_operations": 350,
        "aggregate_normalized_unique_rest_operations": 349,
        "aggregate_official_declared_rest_operations": 346,
        "aggregate_official_normalized_unique_rest_operations": 345,
        "aggregate_thor_local_extension_operations": 4,
        "derivation": (
            "the current Agent exposes 64 live routes after recognizing "
            "path-converter routes and the released evaluation and asynchronous "
            "workflow endpoints"
        ),
    }
    if contract["api_inventory_result"] != expected_inventory_result:
        raise ContractError("successor API inventory result drift")

    route_results: dict[str, bool] = {}
    for profile in contract["profile_paths"]:
        bindings = _endpoint_bindings(profile)
        for route, function_name in contract["required_route_bindings"].items():
            if bindings.get(route) != function_name:
                raise ContractError(f"route binding mismatch: {profile}:{route}")
            route_results[f"{profile}:{route}"] = True
        for route, function_name in contract["legacy_route_bindings"].items():
            if bindings.get(route) != function_name:
                raise ContractError(f"legacy route drift: {profile}:{route}")

    model_contracts = {
        "AttributeSearchInput": sorted(
            _model_fields(
                "services/agent/src/vss_agents/tools/attribute_search.py",
                "AttributeSearchInput",
            )
        ),
        "SearchInput": sorted(
            _model_fields(
                "services/agent/src/vss_agents/tools/search.py", "SearchInput"
            )
        ),
        "ReferenceObject": sorted(
            _model_fields(
                "services/agent/src/vss_agents/tools/search.py", "ReferenceObject"
            )
        ),
    }
    required_sets = {
        "AttributeSearchInput": set(
            contract["input_contract"]["attribute_route_required_fields"]
        ),
        "SearchInput": set(contract["input_contract"]["search_required_fields"]),
        "ReferenceObject": set(
            contract["input_contract"]["reference_object_required_fields"]
        ),
    }
    for name, required in required_sets.items():
        missing = required - set(model_contracts[name])
        if missing:
            raise ContractError(f"{name} missing fields: {sorted(missing)}")
    if {"image", "image_bytes", "bbox", "image_base64"}.intersection(
        model_contracts["SearchInput"]
    ):
        raise ContractError(
            "SearchInput raw-image semantics changed; re-review required"
        )

    fixture_raw = _read_regular(_repo_path(contract["fixture_path"]))
    if _sha256(fixture_raw) != contract["fixture_sha256"]:
        raise ContractError("successor fixture digest mismatch")
    fixture = _json(_repo_path(contract["fixture_path"]))
    try:
        image = base64.b64decode(fixture["image_base64"], validate=True)
    except (KeyError, binascii.Error, ValueError) as exc:
        raise ContractError("fixture image is not strict base64") from exc
    if not image or len(image) > 8192 or _sha256(image) != fixture["image_sha256"]:
        raise ContractError("fixture image bytes/digest mismatch")
    bbox = fixture["bbox_xyxy_normalized"]
    if (
        type(bbox) is not list
        or len(bbox) != 4
        or not (bbox[0] < bbox[2] and bbox[1] < bbox[3])
    ):
        raise ContractError("fixture selected bbox is invalid")

    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "static_contract_verified_non_promoting",
        "valid": True,
        "promotion_eligible": False,
        "runtime_requests": 0,
        "runtime_actions": 0,
        "route_bindings": route_results,
        "input_contracts": model_contracts,
        "selected_bbox_fixture": {
            "fixture_sha256": contract["fixture_sha256"],
            "image_bytes": len(image),
            "image_sha256": fixture["image_sha256"],
            "request_semantics": "reference_object_metadata_not_raw_image",
        },
        "predecessor_current_contract_preserved": True,
        "runtime_executor_boundary": contract["runtime_executor_boundary"],
        "source_locks_verified": len(locks),
        "remaining_blockers": contract["remaining_blockers"],
    }
    schema = _json(PACKAGE_DIR / "result.schema.json")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(result),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ContractError(f"result schema violation: {errors[0].message}")
    return result


def main() -> int:
    try:
        result = execute()
    except ContractError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
