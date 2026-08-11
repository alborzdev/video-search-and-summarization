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
HEX_ID_PATTERN = re.compile(r'"(?:trace_id|span_id)"\s*:')


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rt_vlm_prometheus_otel_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "261ac30d44027cd35cee0b261aa65b884fcfcffb72103a56b1e2a111f2fc2b60"
    assert _sha(SCHEMA) == "53014bb0a5d24621fa1b400c73b250d4379b6be357b1b32d67a1d5ba4926f235"
    assert _sha(RECEIPT) == "d0139d612d3d7a397c601ba7a0cbe15ecede635992631a5e15bef7b1d6928f4a"
    assert _sha(EXECUTOR) == "6e44990710a4ec6f84ded142add61275881b60cc53b9e4bb09e6d7bf7f29c7ca"
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
    assert value["status"] == "inert_prometheus_otel_plan_valid"
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
    row = _load(LEDGER)["capabilities"][366]
    assert row["id"] == contract["capability_ids"][0]
    assert row["title"] == "Prometheus and OpenTelemetry"
    assert row["contract"]["advertised_literal"] == "Prometheus and OpenTelemetry"


def test_endpoints_are_frozen_to_loopback() -> None:
    module = _module()
    assert module._endpoint("http://127.0.0.1:8018", "http://127.0.0.1:8018").endswith(":8018")
    for endpoint in ("http://localhost:8018", "https://127.0.0.1:8018"):
        with pytest.raises(module.QualificationError):
            module._endpoint(endpoint, "http://127.0.0.1:8018")


def test_runtime_semantics_and_cleanup() -> None:
    receipt = _load(RECEIPT)
    assert receipt["status"] == "passed"
    assert receipt["budget"]["model_requests"] == 0
    assert receipt["prometheus_endpoint"]["required_metric_families_present"] is True
    assert receipt["prometheus_endpoint"]["otel_sdk_label_present"] is True
    assert receipt["prometheus_scrape"]["target_up"] is True
    assert receipt["prometheus_query"]["up_value"] == 1
    assert receipt["opentelemetry"]["console_span_export_present"] is True
    assert receipt["opentelemetry"]["console_metric_export_present"] is True
    assert receipt["opentelemetry"]["trace_flushed"] is True
    assert receipt["opentelemetry"]["metrics_flushed"] is True
    assert all(receipt["cleanup"].values())


def test_retained_receipt_is_privacy_safe() -> None:
    raw = RECEIPT.read_text()
    lowered = raw.casefold()
    assert HEX_ID_PATTERN.search(raw) is None
    assert "nvapi-" not in lowered
    assert "bearer " not in lowered
    for forbidden in ('"prompt"', '"semantic_output"', '"request_id"', '"session_id"'):
        assert forbidden not in lowered
