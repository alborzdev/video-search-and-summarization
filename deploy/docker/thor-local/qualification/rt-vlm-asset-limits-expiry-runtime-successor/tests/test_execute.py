from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator
import pytest


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
CONTRACT = HERE / "contract.json"
SCHEMA = HERE / "receipt.schema.json"
RECEIPT = HERE / "runtime-receipt.json"
EXECUTOR = HERE / "execute.py"
LEDGER = (
    REPO
    / "deploy/docker/thor-local/qualification/metadata-500-current-lvs-rest-runtime-successor/post-state-official-capabilities.json"
)
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rt_vlm_asset_limits_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "a44b25ce563ba4dfda57550efa5fe659cc640eec718947da545fbc306c056628"
    assert _sha(SCHEMA) == "c5b16e10974539b5a85ba258fef2d0016e1a8b68dcedaf8962694d3710afe821"
    assert _sha(RECEIPT) == "90dccd8ef4151d2a495e58403052267bcb53d194e1c348a8bbf9b88102efd2a8"
    assert _sha(EXECUTOR) == "132fd15ea2726febe9a632103bb07315968914f8f540c3c798004c322ed5c580"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == _sha(CONTRACT)


def test_default_command_is_inert_and_wrong_ack_is_rejected() -> None:
    plan = subprocess.run(
        [sys.executable, str(EXECUTOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    plan_value = json.loads(plan.stdout)
    assert plan_value["status"] == "inert_asset_limits_expiry_plan_valid"
    assert plan_value["writes_or_lifecycle_actions"] is False
    assert plan_value["docker_commands"] == 0
    denied = subprocess.run(
        [sys.executable, str(EXECUTOR), "execute", "--ack", "wrong"],
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["status"] == "failed"


def test_source_locks_overlay_and_exact_advertised_row() -> None:
    contract = _load(CONTRACT)
    module = _module()
    module._verify_static(contract)
    ledger = _load(LEDGER)
    row = ledger["capabilities"][364]
    assert row["id"] == contract["capability_ids"][0]
    assert row["title"] == "asset limits and expiry"
    assert row["contract"]["advertised_literal"] == "asset limits and expiry"


def test_endpoint_is_frozen_to_loopback() -> None:
    module = _module()
    contract = _load(CONTRACT)
    assert module._validate_endpoint("http://127.0.0.1:8018", contract).endswith(":8018")
    for endpoint in ("http://localhost:8018", "https://127.0.0.1:8018", "http://127.0.0.1:8000"):
        with pytest.raises(module.QualificationError):
            module._validate_endpoint(endpoint, contract)


def test_runtime_semantics_and_exact_cleanup() -> None:
    receipt = _load(RECEIPT)
    assert receipt["status"] == "passed"
    assert receipt["budget"]["model_requests"] == 0
    assert receipt["runtime_identity"]["asset_manager_overlay_read_only"] is True
    pressure = receipt["storage_limit"]["pressure_eviction"]
    assert pressure["oldest_evicted"] is True
    assert pressure["newest_preserved"] is True
    assert pressure["aged_out_count"] == 1
    hard = receipt["storage_limit"]["hard_limit"]
    assert hard["busy_asset_preserved"] is True
    assert hard["blocked_asset_absent"] is True
    assert hard["error"] == {"code": "ServerBusy", "status_code": 503}
    ttl = receipt["ttl_expiry"]["ttl"]
    assert ttl["old_expired"] is True
    assert ttl["busy_expired_asset_preserved"] is True
    assert ttl["fresh_asset_preserved"] is True
    assert all(receipt["cleanup"].values())


def test_retained_receipt_is_privacy_safe() -> None:
    raw = RECEIPT.read_text()
    lowered = raw.casefold()
    assert UUID_PATTERN.search(raw) is None
    assert "nvapi-" not in lowered
    assert "bearer " not in lowered
    for forbidden in ('"prompt"', '"semantic_output"', '"resource_id"', '"session_id"'):
        assert forbidden not in lowered
