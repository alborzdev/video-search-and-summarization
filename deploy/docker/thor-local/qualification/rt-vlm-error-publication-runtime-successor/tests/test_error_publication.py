from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator


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


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rt_vlm_error_publication_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "d99880e8500c1b53c9a856d1f319770f1d6170ff6c87e0a46ce6687b83dfd796"
    assert _sha(EXECUTOR) == "a45eca30b9bef051dfc5ff40319f05bf165c02a8785453bae192303753fa0c03"
    assert _sha(SCHEMA) == "eaf129ca1afd33a2cebd64e23295560fe5273e0b33921967e69c5eb2140490a9"
    assert _sha(RECEIPT) == "49b1b9af485bc7ff33b243d18dec617d14def6ca8932c2ffcf3c8462910b750d"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == _sha(CONTRACT)


def test_default_is_inert_and_wrong_ack_is_rejected() -> None:
    plan = subprocess.run(
        [sys.executable, str(EXECUTOR)], check=True, capture_output=True, text=True
    )
    value = json.loads(plan.stdout)
    assert value["status"] == "inert_error_publication_plan_valid"
    assert value["writes_or_lifecycle_actions"] is False
    denied = subprocess.run(
        [sys.executable, str(EXECUTOR), "execute", "--ack", "wrong"],
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["status"] == "failed"


def test_source_locks_and_exact_advertised_row() -> None:
    contract = _load(CONTRACT)
    _module()._verify_static(contract)
    row = _load(LEDGER)["capabilities"][365]
    assert row["id"] == contract["capability_ids"][0]
    assert row["title"] == "Kafka/Redis error publication"
    assert row["contract"]["advertised_literal"] == "Kafka/Redis error publication"


def test_production_backends_have_equal_schema_and_cleanup() -> None:
    receipt = _load(RECEIPT)
    assert receipt["status"] == "passed"
    assert receipt["budget"]["model_requests"] == 0
    assert receipt["kafka"]["record_count"] == 1
    assert receipt["kafka"]["message_type_header_exact"] is True
    assert receipt["redis"]["message_count"] == 1
    assert receipt["redis"]["backend_switch_routed_to_redis"] is True
    assert receipt["schema_equal_between_backends"] is True
    assert receipt["cleanup"] == {
        "kafka_topic_absent": True,
        "redis_persistent_key_absent": True,
        "redis_subscriber_count": 0,
        "sender_threads_stopped": True,
    }


def test_retained_receipt_is_privacy_safe() -> None:
    raw = RECEIPT.read_text().casefold()
    for forbidden in (
        "nvapi-",
        "bearer ",
        "vss-rt-vlm-error-qual-365-",
        '"prompt"',
        '"semantic_output"',
        '"request_id"',
        '"session_id"',
        '"payload"',
        '"topic"',
        '"channel"',
    ):
        assert forbidden not in raw
