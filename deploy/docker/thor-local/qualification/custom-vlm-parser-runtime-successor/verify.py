#!/usr/bin/env python3
"""Verify the retained Thor custom-VLM-parser receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def main() -> int:
    contract_path = HERE / "contract.json"
    receipt_path = HERE / "runtime-receipt.json"
    schema_path = HERE / "receipt.schema.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == sha(contract_path)
    assert contract["official_indices"] == [326]
    assert receipt["capability_ids"] == contract["capability_ids"]

    ledger_path = REPO / contract["official_source"]["path"]
    assert sha(ledger_path) == contract["official_source"]["ledger_sha256"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    row = ledger["capabilities"][326]
    assert hashlib.sha256(canonical(row)).hexdigest() == (
        contract["official_source"]["row_canonical_sha256_by_index"]["326"]
    )
    assert row["id"] == contract["capability_ids"][0]
    assert row["runtime_state"] == "not_qualified"

    for lock in contract["source_locks"]:
        source = REPO / lock["path"]
        assert source.is_file() and not source.is_symlink()
        assert sha(source) == lock["sha256"]

    assert receipt["parser"]["dotted_path"] == contract["parser"]["dotted_path"]
    assert receipt["parser"]["parser_id"] == contract["parser"]["parser_id"]
    assert receipt["parser"]["module_sha256"] == contract["parser"]["module_sha256"]
    assert receipt["api"]["terminal_state"] == "completed"
    assert receipt["output"]["normalized_verdict"] == "confirmed"
    assert receipt["output"]["default_reasoning_field_absent"] is True
    assert receipt["negative"]["startup_rejected"] is True
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]

    print(json.dumps({
        "official_indices": contract["official_indices"],
        "package_id": contract["package_id"],
        "receipt_sha256": sha(receipt_path),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
