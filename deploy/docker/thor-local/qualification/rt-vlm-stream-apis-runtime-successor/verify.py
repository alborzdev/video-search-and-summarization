#!/usr/bin/env python3
"""Verify the retained RT-VLM stream-API qualification receipt."""

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
    assert receipt["official_indices"] == [351, 352]
    assert not UUID_PATTERN.search(receipt_path.read_text(encoding="utf-8"))

    ledger_path = REPO / contract["official_source"]["path"]
    assert sha(ledger_path) == contract["official_source"]["ledger_sha256"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for index, capability_id in zip(contract["official_indices"], contract["capability_ids"]):
        row = ledger["capabilities"][index]
        assert row["id"] == capability_id
        assert row["runtime_state"] == "not_qualified"
        assert hashlib.sha256(canonical(row)).hexdigest() == (
            contract["official_source"]["row_canonical_sha256_by_index"][str(index)]
        )
    for lock in contract["source_locks"]:
        assert sha(REPO / lock["path"]) == lock["sha256"]

    mapping = receipt["authoritative_api_mapping"]
    assert mapping["ledger_endpoint_semantics_reversed"] is True
    assert mapping["source_declares_original_plural"] is True
    assert mapping["source_declares_cv_compatible_singular"] is True
    assert mapping["stream_route_set_exact"] is True
    assert receipt["original_api"]["metadata_round_trip_exact"] is True
    assert receipt["original_api"]["batch_per_item_outcomes_exact"] is True
    assert receipt["cv_compatible_api"]["identity_round_trip_exact"] is True
    assert receipt["cv_compatible_api"]["duplicate_status"] == 409
    assert receipt["cv_compatible_api"]["missing_remove_status"] == 404
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["cleanup"]["catalogs_restored_exactly"] is True
    assert receipt["cleanup"]["running_container_set_preserved"] is True

    print(json.dumps({
        "official_indices": contract["official_indices"],
        "package_id": contract["package_id"],
        "receipt_sha256": sha(receipt_path),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
