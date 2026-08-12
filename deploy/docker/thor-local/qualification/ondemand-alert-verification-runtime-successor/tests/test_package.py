from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_receipt_validates() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)


def test_full_verifier_passes() -> None:
    assert load("verify").main() == 0


def test_receipt_proves_job_verdict_sink_and_cancellation() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["positive"]["server_generated_job_id"] is True
    assert receipt["positive"]["verdict"] == "confirmed"
    assert receipt["positive"]["sink_outcome"] == "acknowledged"
    assert receipt["cancellation"]["cancellation_accepted"] is True
    assert receipt["cancellation"]["sink_hit_count"] == 0


def test_exact_external_state_cleanup_and_local_boundary() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["run"]["numeric_local_endpoints_only"] is True
    assert receipt["run"]["agent_generate_request_count"] == 0
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["cleanup"]["owned_config_absent"] is True
    assert receipt["cleanup"]["owned_sink_documents_absent"] is True
    assert receipt["cleanup"]["owned_rtvlm_documents_deleted"] >= 1
    assert receipt["cleanup"]["running_container_set_preserved"] is True
