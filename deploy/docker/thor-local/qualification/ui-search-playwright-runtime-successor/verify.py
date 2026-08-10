#!/usr/bin/env python3
"""Offline validation for the retained partial Thor Search UI runtime receipt."""

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
    schema = load("receipt.schema.json")
    receipt = load("runtime-receipt.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        raise ValueError(f"receipt schema: {errors[0].message}")
    if receipt["contract_sha256"] != digest(HERE / "contract.json"):
        raise ValueError("contract digest mismatch")
    if receipt["harness_sha256"] != digest(HERE / "harness.mjs"):
        raise ValueError("harness digest mismatch")
    if contract["evidence_scope"] != {
        "status": "partial_current_candidate",
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "reason": "The current local video corpus has searchable embeddings and VST frames but no stored tracked-object bbox documents, so the selected-object image-KNN path cannot be exercised without provisioning a detection stream.",
    }:
        raise ValueError("partial-evidence boundary drift")
    if set(contract["open_facets"]) != {
        "selected-object-bbox-selection",
        "selected-object-image-knn",
        "attribute-merge-and-fusion-route-runtime-semantics",
    }:
        raise ValueError("open-facet inventory drift")
    for lock in contract["source_locks"]:
        path = Path(lock["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe source-lock path")
        full = (ROOT / path).resolve(strict=True)
        full.relative_to(ROOT)
        if digest(full) != lock["sha256"]:
            raise ValueError(f"source-lock drift: {lock['path']}")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", receipt["target_commit"], "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if ancestor.returncode != 0:
        raise ValueError("runtime target is not an ancestor of current checkout")
    if not any(card["label"] == "Confirmed" for card in receipt["critic"]["cards"]):
        raise ValueError("confirmed critic card missing")
    mobile = receipt["direct"]["mobile"]["overflow"]
    if mobile["document"] > mobile["viewport"] or mobile["body"] > mobile["viewport"]:
        raise ValueError("mobile horizontal overflow")
    if receipt["corpus_boundary"]["selected_object_knn_exercised"]:
        raise ValueError("receipt falsely claims selected-object KNN")
    serialized = json.dumps(receipt, sort_keys=True).lower()
    for forbidden in (
        "request_id",
        "session_id",
        "conversation_id",
        "sensor_id",
        "screenshot_url",
        "assistant_response",
        "raw_prompt",
        "raw_query",
        "description",
        "http://",
        "https://",
        "ws://",
        "wss://",
    ):
        if forbidden in serialized:
            raise ValueError(f"forbidden retained field or value: {forbidden}")


if __name__ == "__main__":
    try:
        verify()
    except Exception as exc:
        print(f"ui-search-runtime evidence: failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("ui-search-runtime evidence: passed (partial; bbox/image-KNN remains open)")
