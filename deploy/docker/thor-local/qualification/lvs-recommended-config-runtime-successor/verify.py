#!/usr/bin/env python3
"""Verify the retained LVS recommended-configuration receipt."""

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
    assert receipt["official_indices"] == [303]
    assert not UUID_PATTERN.search(receipt_path.read_text(encoding="utf-8"))

    ledger_path = REPO / contract["official_source"]["path"]
    assert sha(ledger_path) == contract["official_source"]["ledger_sha256"]
    row = json.loads(ledger_path.read_text(encoding="utf-8"))["capabilities"][303]
    assert row["id"] == contract["capability_ids"][0]
    assert row["runtime_state"] == "not_qualified"
    assert hashlib.sha256(canonical(row)).hexdigest() == (
        contract["official_source"]["row_canonical_sha256_by_index"]["303"]
    )
    for lock in contract["source_locks"]:
        assert sha(REPO / lock["path"]) == lock["sha256"]

    api = receipt["authoritative_api"]
    assert api["request_fields"] == contract["authoritative_release_contract"]["request_fields"]
    assert api["response_fields"] == contract["authoritative_release_contract"]["response_fields"]
    assert api["frame_setting_advertised_by_api"] is False
    assert api["token_setting_advertised_by_api"] is False
    assert api["model_context_field_advertised_by_api"] is False
    assert api["generated_ledger_semantics_overstate_frame_token_and_model_context"] is True
    recommendation = receipt["recommendation"]
    assert set(recommendation["lower_bound_negative_statuses"].values()) == {422}
    assert recommendation["within_declared_bounds"] is True
    follow_on = receipt["follow_on"]
    assert follow_on["recommended_chunk_size"] == follow_on["submitted_chunk_duration"]
    assert follow_on["accepted_unchanged"] is True
    assert follow_on["response_content_nonempty"] is True
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
