from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
CONTRACT = HERE / "contract.json"
EXECUTOR = HERE / "execute.py"
SCHEMA = HERE / "receipt.schema.json"
RECEIPT = HERE / "runtime-receipt.json"
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
    spec = importlib.util.spec_from_file_location("rt_vlm_incident_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "c889d05c1cdb4fab370f1f23e8ec78b50f8c4d0046a84044d0e0a24c5ccbf14d"
    assert _sha(EXECUTOR) == "107ebd490524839d1e9236563f56c2e45ffea4bf02946a831e6bc24b78f10ee1"
    assert _sha(SCHEMA) == "e57095b065fd37455a1495fe71a04ea7a1bf9cb2084fcb7b05aff6f64f224ae4"
    assert _sha(RECEIPT) == "86d482b08c38f52af244bb86622d0343354fb17e76322539e912c61b74e4644f"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == _sha(CONTRACT)


def test_source_locks_and_plan_are_current() -> None:
    contract = _load(CONTRACT)
    for lock in contract["source_locks"]:
        assert _sha(REPO / lock["path"]) == lock["sha256"]
    plan = _module()._plan(contract)
    assert plan["status"] == "ready"
    assert plan["official_indices"] == [343, 344]
    assert plan["append_only_kafka_records"] == 1
    assert plan["agent_generate_calls"] == 0
    assert plan["stream_mutations"] == 0


def test_exact_advertised_rows_are_bound() -> None:
    ledger = _load(LEDGER)
    expected = {
        343: ("manifest-entry.rt-vlm-media.07-incidents", "incidents"),
        344: ("manifest-entry.rt-vlm-media.08-categories", "categories"),
    }
    for index, (capability_id, title) in expected.items():
        row = ledger["capabilities"][index]
        assert row["id"] == capability_id
        assert row["title"] == title
        assert row["contract"]["advertised_literal"] == title


def test_runtime_incident_category_semantics_and_cleanup() -> None:
    receipt = _load(RECEIPT)
    assert receipt["caption"]["primary_markers_present"] == [True, True, True]
    incident = receipt["kafka_incident"]
    assert incident["protobuf_decoded"] is True
    assert incident["category_exact"] is True
    assert incident["alert_category_info_exact"] is True
    assert incident["is_anomaly"] is True
    assert incident["verdict_confirmed"] is True
    assert incident["owned_matching_records"] == 1
    assert incident["append_only_record_retained"] is True
    assert incident["individual_record_deletion_supported"] is False
    cleanup = receipt["cleanup"]
    assert cleanup["append_only_kafka_record_count"] == 1
    assert all(
        cleanup[key] is True
        for key in (
            "owned_file_deleted",
            "file_catalog_restored_exactly",
            "asset_statistics_restored_exactly",
            "model_inventory_restored_exactly",
            "health_contract_restored_exactly",
            "observer_stopped",
            "temporary_fixture_root_absent",
        )
    )


def test_retained_receipt_is_privacy_safe() -> None:
    raw = RECEIPT.read_text()
    lowered = raw.casefold()
    assert UUID_PATTERN.search(raw) is None
    for forbidden in (
        "nvapi-",
        "bearer ",
        "rtsp://",
        '"prompt"',
        '"semantic_output"',
        '"incident_payload"',
        '"request_id"',
        '"session_id"',
        '"sdp"',
        '"ice"',
    ):
        assert forbidden not in lowered
