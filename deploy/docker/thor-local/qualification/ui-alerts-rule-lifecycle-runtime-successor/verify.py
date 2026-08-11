#!/usr/bin/env python3
"""Verify the retained Thor Alerts UI lifecycle receipt and source locks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    contract = json.loads((HERE / "contract.json").read_text())
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)

    assert contract["official_indices"] == [169]
    assert contract["capability_id"] == "runtime.ui.alerts-tab"
    assert contract["execution"]["agent_generate_allowed"] is False
    assert contract["execution"]["external_network_allowed"] is False
    assert contract["execution"]["exact_cleanup_required"] is True
    for lock in contract["source_locks"]:
        target = REPO / lock["path"]
        assert target.is_file() and not target.is_symlink()
        assert sha256(target) == lock["sha256"], lock["path"]

    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    serialized = json.dumps(receipt, sort_keys=True)
    assert "http://" not in serialized and "https://" not in serialized
    assert "rtsp://" not in serialized
    assert re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        serialized,
        re.IGNORECASE,
    ) is None

    print(json.dumps({
        "status": "passed",
        "package_id": contract["package_id"],
        "official_indices": contract["official_indices"],
        "receipt_sha256": sha256(HERE / "runtime-receipt.json"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
