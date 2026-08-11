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
    spec = importlib.util.spec_from_file_location("rt_embed_live_api_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "c0cc20019d047ac90e8ca772bb3bede6722f15d0ff58788e84973458e55b7c6c"
    assert _sha(EXECUTOR) == "dac5a99b62666f1f82cb3b6c79f4cd3cd14498b226ffc0de4561a843fba37614"
    assert _sha(SCHEMA) == "962d788c5aef6c2852c9177624ba3d1ae00f4bee667297c5bc648789ebe37248"
    assert _sha(RECEIPT) == "0c9732edb1aa2242c0bb3ad1bbc8fd513cf86c1f424be623fd7c4a0a472c7ba6"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == _sha(CONTRACT)


def test_default_is_inert_and_wrong_ack_is_rejected() -> None:
    plan = subprocess.run(
        [sys.executable, str(EXECUTOR)], check=True, capture_output=True, text=True
    )
    assert json.loads(plan.stdout)["status"] == "inert_rt_embed_live_api_plan_valid"
    denied = subprocess.run(
        [sys.executable, str(EXECUTOR), "execute", "--ack", "wrong"],
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["status"] == "failed"


def test_only_current_compose_and_capture_date_are_overlaid() -> None:
    contract = _load(CONTRACT)
    adapted, _raw = _module()._verify_static(contract)
    base = _load(REPO / contract["reused_qualifier"]["contract_path"])
    base["target"]["captured_on"] = contract["captured_on"]
    overlay = contract["reused_qualifier"]["allowed_overlay"]
    row = next(
        row for row in base["source_anchors"] if row["path"] == overlay["compose_path"]
    )
    row["bytes"] = overlay["compose_bytes"]
    row["sha256"] = overlay["compose_sha256"]
    assert adapted == base


def test_exact_advertised_rows_and_live_semantics() -> None:
    contract = _load(CONTRACT)
    ledger = _load(LEDGER)["capabilities"]
    assert [ledger[index]["id"] for index in (369, 373, 374)] == contract["capability_ids"]
    receipt = _load(RECEIPT)
    assert receipt["live_rtsp"]["sse_embedding_chunk_count"] == 1
    assert receipt["live_rtsp"]["embedding_dimension"] == 768
    assert receipt["stream_apis"]["all_operations_exercised"] is True
    assert receipt["stream_apis"]["complete_operation_count"] == 24
    assert receipt["health_metadata_models_metrics"]["metrics_http_200_and_prometheus"] is True
    assert all(receipt["cleanup"].values())


def test_retained_receipt_is_privacy_safe() -> None:
    raw = RECEIPT.read_text().casefold()
    uuid_pattern = re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
    )
    assert uuid_pattern.search(raw) is None
    for forbidden in (
        "nvapi-",
        "bearer ",
        "rtsp://",
        '"embeddings"',
        '"prompt"',
        '"session_id"',
        '"request_id"',
        '"resource_id"',
    ):
        assert forbidden not in raw
