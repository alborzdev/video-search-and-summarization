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


def test_live_parser_identity_config_and_schema_are_proven() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["parser"]["worker_loader_observed"] is True
    assert receipt["parser"]["api_loader_observed"] is True
    assert receipt["parser"]["identity_exposed"] is True
    assert receipt["parser"]["config_exposed"] is True
    assert receipt["output"]["normalized_verdict"] == "confirmed"
    assert receipt["output"]["normalized_reasoning_present"] is True
    assert receipt["output"]["outer_verdict_empty"] is True
    assert receipt["output"]["vlm_response_json_present"] is True
    assert receipt["output"]["default_reasoning_field_absent"] is True
    assert receipt["output"]["service_response_schema_conformant"] is True


def test_invalid_import_and_exact_cleanup_are_proven() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["negative"]["startup_rejected"] is True
    assert receipt["negative"]["health_never_reachable"] is True
    assert receipt["negative"]["import_failure_observed"] is True
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["cleanup"]["exact_main_runtime_restored"] is True
    assert receipt["cleanup"]["owned_indices_absent"] is True
    assert receipt["cleanup"]["owned_rtvlm_documents_absent"] is True
    assert receipt["cleanup"]["running_container_set_preserved"] is True
