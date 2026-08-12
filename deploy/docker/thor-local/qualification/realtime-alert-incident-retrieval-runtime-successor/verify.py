#!/usr/bin/env python3
"""Verify retained incident-retrieval evidence and its official binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    contract_path = HERE / "contract.json"
    schema_path = HERE / "receipt.schema.json"
    receipt_path = HERE / "runtime-receipt.json"
    contract = json.loads(contract_path.read_text())
    schema = json.loads(schema_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)

    assert contract["official_indices"] == [332]
    assert contract["capability_id"] == "manifest-entry.realtime-alerts.04-incident-retrieval"
    assert contract["execution"]["agent_generate_allowed"] is False
    assert contract["execution"]["external_network_allowed"] is False
    assert contract["execution"]["preexisting_rules_allowed"] is False
    assert contract["execution"]["exact_cleanup_required"] is True
    assert receipt["contract_sha256"] == sha256(contract_path)

    ledger_path = REPO / contract["official_source"]["path"]
    assert sha256(ledger_path) == contract["official_source"]["ledger_sha256"]
    ledger = json.loads(ledger_path.read_text())
    row = ledger["capabilities"][332]
    row_raw = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(row_raw).hexdigest() == contract["official_source"]["row_canonical_sha256"]
    assert row["id"] == contract["capability_id"]
    assert row["runtime_state"] == "not_qualified"

    for lock in contract["source_locks"]:
        target = REPO / lock["path"]
        assert target.is_file() and not target.is_symlink()
        assert sha256(target) == lock["sha256"], lock["path"]

    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["retrieval"]["control_incident_count"] == 4
    assert receipt["retrieval"]["unknown_rule_returns_empty"] is True
    raw = receipt_path.read_text()
    assert "http://" not in raw and "https://" not in raw and "rtsp://" not in raw
    assert UUID_PATTERN.search(raw) is None

    print(json.dumps({
        "status": "passed",
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "receipt_sha256": sha256(receipt_path),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
