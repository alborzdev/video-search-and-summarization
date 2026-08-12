#!/usr/bin/env python3
"""Verify the retained LVS file-caption and summary receipt."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


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
    assert receipt["capability_ids"] == contract["capability_ids"]
    assert receipt["official_indices"] == [296, 297]
    assert not UUID_PATTERN.search(receipt_path.read_text(encoding="utf-8"))

    ledger_path = REPO / contract["official_source"]["path"]
    assert sha(ledger_path) == contract["official_source"]["ledger_sha256"]
    rows = json.loads(ledger_path.read_text(encoding="utf-8"))["capabilities"]
    for index, capability_id in zip(contract["official_indices"], contract["capability_ids"]):
        row = rows[index]
        assert row["id"] == capability_id
        assert row["runtime_state"] == "not_qualified"
        assert hashlib.sha256(canonical(row)).hexdigest() == (
            contract["official_source"]["row_canonical_sha256_by_index"][str(index)]
        )
    for lock in contract["source_locks"]:
        assert sha(REPO / lock["path"]) == lock["sha256"]

    captions = receipt["chunked_dense_captions"]
    assert captions["intervals"] == [[0.0, 3.0], [3.0, 6.0], [6.0, 9.0], [9.0, 10.0]]
    assert captions["first_event_carrying_box"] is True
    assert captions["last_event_on_ladder_at_shelf"] is True
    assert captions["absent_forklift_excluded"] is True
    summary = receipt["file_summarization"]
    assert summary["beginning_box_event_present"] is True
    assert summary["ending_ladder_event_present"] is True
    assert summary["absent_forklift_excluded"] is True
    assert summary["summary_requests"] == 1
    assert receipt["cleanup"]["file_catalog_restored_exactly"] is True
    assert receipt["cleanup"]["graph_restored_exactly"] is True

    print(json.dumps({
        "official_indices": contract["official_indices"],
        "package_id": contract["package_id"],
        "receipt_sha256": sha(receipt_path),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
