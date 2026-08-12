#!/usr/bin/env python3
"""Verify the retained CV -> Behavior Analytics -> VLM receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def main() -> int:
    contract_path = HERE / "contract.json"
    receipt_path = HERE / "runtime-receipt.json"
    schema_path = HERE / "receipt.schema.json"
    contract = json.loads(contract_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)

    assert receipt["contract_sha256"] == sha(contract_path)
    assert contract["official_indices"] == [321, 322]
    ledger_path = REPO / contract["official_source"]["path"]
    assert sha(ledger_path) == contract["official_source"]["ledger_sha256"]
    rows = json.loads(ledger_path.read_text())["capabilities"]
    for index, capability_id in zip(
        contract["official_indices"], contract["capability_ids"], strict=True,
    ):
        row = rows[index]
        assert hashlib.sha256(canonical(row)).hexdigest() == (
            contract["official_source"]["row_canonical_sha256_by_index"][str(index)]
        )
        assert row["id"] == capability_id
        assert row["runtime_state"] == "not_qualified"
    assert receipt["capability_ids"] == contract["capability_ids"]

    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        assert path.is_file() and not path.is_symlink()
        assert sha(path) == lock["sha256"]

    observations = receipt["pipeline"]["observation_ms"]
    assert observations == sorted(observations)
    assert receipt["pipeline"]["same_candidate_document_id"] is True
    assert receipt["pipeline"]["sensor_identity_preserved"] is True
    assert receipt["pipeline"]["evidence_interval_preserved"] is True
    assert receipt["pipeline"]["object_ids_preserved"] is True
    assert receipt["pipeline"]["object_timeline_preserved"] is True
    assert receipt["pipeline"]["final_verdict"] == "confirmed"
    assert receipt["transport"]["rtvlm_data_url_logged"] is True
    assert receipt["transport"]["local_chat_completion_200"] is True
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["cleanup"]["exact_live_state_restored"] is True
    assert receipt["policy"]["agent_generate_request_count"] == 0
    assert receipt["policy"]["external_network_requests"] == 0

    print(json.dumps({
        "official_indices": [321, 322],
        "package_id": contract["package_id"],
        "receipt_sha256": sha(receipt_path),
        "status": "passed",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
