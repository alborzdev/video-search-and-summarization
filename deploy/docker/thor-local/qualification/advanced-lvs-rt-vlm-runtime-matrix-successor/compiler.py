#!/usr/bin/env python3
"""Compile a source-locked current-Thor runtime evidence overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
MATRIX_PATH = HERE / "matrix.json"
MATRIX_SCHEMA_PATH = HERE / "matrix.schema.json"
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


class MatrixError(RuntimeError):
    """The source-locked runtime matrix could not be proven."""


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MatrixError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                MatrixError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError(f"cannot read strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MatrixError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locked(path_value: str, digest: str) -> Path:
    path = REPO / path_value
    if not path.is_file() or path.is_symlink():
        raise MatrixError(f"locked source is not a regular file: {path_value}")
    if _sha256(path) != digest:
        raise MatrixError(f"locked source drifted: {path_value}")
    return path


def _pointer(value: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise MatrixError(f"invalid JSON pointer: {pointer}")
    current = value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise MatrixError(f"missing receipt assertion pointer: {pointer}")
        current = current[token]
    return current


def _validate_receipt(entry: dict[str, Any]) -> dict[str, Any]:
    package_contract_path = _locked(entry["contract_path"], entry["contract_sha256"])
    receipt_path = _locked(entry["receipt_path"], entry["receipt_sha256"])
    schema_path = _locked(entry["receipt_schema_path"], entry["receipt_schema_sha256"])
    package_contract = _load_json(package_contract_path)
    receipt = _load_json(receipt_path)
    schema = _load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda e: list(e.path))
    if errors:
        raise MatrixError(f"receipt schema validation failed: {entry['package_id']}")
    if package_contract.get("package_id") != entry["package_id"]:
        raise MatrixError("package contract identity mismatch")
    if package_contract.get("capability_id") != entry["capability_id"]:
        raise MatrixError("package capability identity mismatch")
    if receipt.get("package_id") != entry["package_id"]:
        raise MatrixError("receipt package identity mismatch")
    receipt_capability = receipt.get("capability_id")
    if receipt_capability not in (None, entry["capability_id"]):
        raise MatrixError("receipt capability identity mismatch")
    if receipt.get("status") != entry["receipt_status"]:
        raise MatrixError("receipt status mismatch")
    if receipt.get("contract_sha256") != entry["contract_sha256"]:
        raise MatrixError("receipt is not bound to its exact package contract")
    for pointer, expected in entry["required_assertions"].items():
        if _pointer(receipt, pointer) != expected:
            raise MatrixError(f"receipt assertion failed: {entry['package_id']} {pointer}")
    raw = receipt_path.read_text(encoding="utf-8")
    if UUID_PATTERN.search(raw):
        raise MatrixError(f"receipt retained a raw UUID: {entry['package_id']}")
    return receipt


def build_matrix() -> dict[str, Any]:
    contract = _load_json(CONTRACT_PATH)
    selected = contract["selected_metadata"]
    selector_path = _locked(selected["selector_path"], selected["selector_sha256"])
    ledger_path = _locked(selected["ledger_path"], selected["ledger_sha256"])
    selector = _load_json(selector_path)
    ledger = _load_json(ledger_path)
    if selector.get("selected_set") != selected["selected_set"]:
        raise MatrixError("selected Metadata500 identity drifted")
    capabilities = ledger.get("capabilities")
    if not isinstance(capabilities, list) or len(capabilities) != 500:
        raise MatrixError("selected Metadata500 ledger is not exactly 500 rows")

    rows: list[dict[str, Any]] = []
    for entry in contract["entries"]:
        index = entry["official_index"]
        canonical = capabilities[index]
        if not isinstance(canonical, dict) or canonical.get("id") != entry["capability_id"]:
            raise MatrixError("official capability index/identity drifted")
        if canonical.get("runtime_state") != selected["canonical_candidate_runtime_state"]:
            raise MatrixError("canonical candidate state unexpectedly changed")
        if canonical.get("acceptance_class") != "required_local":
            raise MatrixError("runtime overlay may only contain required-local capabilities")
        if canonical.get("contract", {}).get("advertised_literal") != entry["advertised_literal"]:
            raise MatrixError("advertised literal drifted")
        _validate_receipt(entry)
        rows.append(
            {
                "official_index": index,
                "capability_id": entry["capability_id"],
                "feature_id": canonical["feature_id"],
                "advertised_literal": entry["advertised_literal"],
                "acceptance_class": canonical["acceptance_class"],
                "canonical_runtime_state": canonical["runtime_state"],
                "overlay_runtime_state": "passed_current_thor",
                "admission_state": "runtime_evidence_available_not_canonically_admitted",
                "canonical_state_advanced": False,
                "runtime_evidence": {
                    "package_id": entry["package_id"],
                    "contract_path": entry["contract_path"],
                    "contract_sha256": entry["contract_sha256"],
                    "receipt_path": entry["receipt_path"],
                    "receipt_sha256": entry["receipt_sha256"],
                    "receipt_schema_path": entry["receipt_schema_path"],
                    "receipt_schema_sha256": entry["receipt_schema_sha256"],
                    "receipt_status": entry["receipt_status"],
                },
                "warehouse_sample_bundle": "excluded",
            }
        )
    if [row["official_index"] for row in rows] != sorted(
        row["official_index"] for row in rows
    ):
        raise MatrixError("overlay rows are not in official ledger order")
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "matrix_id": contract["matrix_id"],
        "selected_metadata_set": selected["selected_set"],
        "selected_ledger_path": selected["ledger_path"],
        "selected_ledger_sha256": selected["ledger_sha256"],
        "matrix_semantics": {
            "overlay_only": True,
            "canonical_admission_claimed": False,
            "canonical_state_advanced": False,
            "meaning": (
                "Live current-Thor evidence is available and schema-valid; the separate "
                "canonical candidate admission system has not admitted these rows."
            ),
        },
        "summary": {
            "row_count": len(rows),
            "passed_current_thor": len(rows),
            "canonical_promotions": 0,
            "agent_generate_calls": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "rows": rows,
    }


def _render(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("compile", "check"), nargs="?", default="check")
    args = parser.parse_args(argv)
    try:
        value = build_matrix()
        schema = _load_json(MATRIX_SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
        rendered = _render(value)
        if args.mode == "compile":
            sys.stdout.buffer.write(rendered)
        elif not MATRIX_PATH.is_file() or MATRIX_PATH.read_bytes() != rendered:
            raise MatrixError("checked matrix.json drifted; run compile and review the result")
        return 0
    except MatrixError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
