#!/usr/bin/env python3
"""Offline validation for the retained Thor Dashboard runtime receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    value = json.loads((HERE / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name}: root must be an object")
    return value


def verify() -> None:
    contract = load("contract.json")
    fixture = load("fixture.json")
    schema = load("receipt.schema.json")
    receipt = load("runtime-receipt.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        raise ValueError(f"receipt schema: {errors[0].message}")
    expected = {
        "contract_sha256": digest(HERE / "contract.json"),
        "fixture_sha256": digest(HERE / "fixture.json"),
        "harness_sha256": digest(HERE / "harness.mjs"),
    }
    for key, value in expected.items():
        if receipt[key] != value:
            raise ValueError(f"{key}: digest mismatch")
    if contract["fixture"]["sha256"] != expected["fixture_sha256"]:
        raise ValueError("contract fixture lock mismatch")
    if fixture["capability_id"] != contract["capability_id"]:
        raise ValueError("fixture capability mismatch")
    if receipt["identity"]["source_locks"] != contract["source_locks"]:
        raise ValueError("receipt source lock set mismatch")
    for lock in contract["source_locks"]:
        path = Path(lock["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe source lock path")
        full = (ROOT / path).resolve(strict=True)
        full.relative_to(ROOT)
        if digest(full) != lock["sha256"]:
            raise ValueError(f"source lock drift: {lock['path']}")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", receipt["target_commit"], "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if ancestor.returncode != 0:
        raise ValueError("runtime target is not an ancestor of the current checkout")
    if receipt["bounds"]["direct_api_requests"] != contract["bounds"]["max_direct_api_requests"]:
        raise ValueError("direct API boundary was not fully exercised")
    if receipt["diagnostics"]["unknown_404_paths"]:
        raise ValueError("unknown browser 404 remains")
    if receipt["cleanup"] != {
        "mutation": "none_read_only",
        "persistent_resources_created": 0,
        "persistent_resources_deleted": 0,
        "persistent_state_unchanged": True,
        "temporary_screenshots_only": True,
    }:
        raise ValueError("read-only postcondition mismatch")


if __name__ == "__main__":
    try:
        verify()
    except Exception as exc:
        print(f"ui-dashboard-runtime evidence: failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("ui-dashboard-runtime evidence: passed")
