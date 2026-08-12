#!/usr/bin/env python3
"""Verify the retained Thor Alert concurrency receipt."""

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


def ast_sha(path: Path) -> str:
    import ast
    source = path.read_text(encoding="utf-8")
    return hashlib.sha256(
        ast.dump(ast.parse(source), include_attributes=False).encode()
    ).hexdigest()


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
    assert contract["official_indices"] == [327]
    assert receipt["capability_ids"] == contract["capability_ids"]

    ledger_path = REPO / contract["official_source"]["path"]
    assert sha(ledger_path) == contract["official_source"]["ledger_sha256"]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    row = ledger["capabilities"][327]
    assert hashlib.sha256(canonical(row)).hexdigest() == (
        contract["official_source"]["row_canonical_sha256_by_index"]["327"]
    )
    assert row["id"] == contract["capability_ids"][0]
    assert row["runtime_state"] == "not_qualified"

    for lock in contract["source_locks"]:
        source = REPO / lock["path"]
        assert source.is_file() and not source.is_symlink()
        assert sha(source) == lock["sha256"]
        if lock.get("semantic_ast_sha256"):
            assert ast_sha(source) == lock["semantic_ast_sha256"]

    concurrency = receipt["concurrency"]
    assert concurrency["maximum_parallel_vlm_calls"] >= 3
    assert concurrency["queue_events_before_slowest_completed"] >= 6
    assert concurrency["fast_candidates_completed_before_slow"] == [1, 2, 3, 4, 5]
    assert concurrency["completion_order"][-1] == 0
    assert concurrency["inline_fallbacks"] == 0
    assert receipt["candidates"]["count"] == 6
    assert receipt["metrics"]["per_candidate_terminal_metrics"] is True
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
