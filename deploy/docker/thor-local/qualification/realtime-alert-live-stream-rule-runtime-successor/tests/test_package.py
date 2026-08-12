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


def test_cyclic_contiguous_oracle_handles_arbitrary_join_phase() -> None:
    harness = load("harness")
    assert harness.cyclically_contiguous([4, 5, 6], 9)
    assert harness.cyclically_contiguous([8, 0, 1], 9)
    assert not harness.cyclically_contiguous([1, 3, 5], 9)


def test_boolean_answer_oracle_is_exact() -> None:
    harness = load("harness")
    assert harness.answer_is_match("Yes") is True
    assert harness.answer_is_match("No.") is False
    assert harness.answer_is_match("Yesterday") is None


def test_window_and_incident_sets_are_exact() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    oracle = receipt["window_oracle"]
    assert oracle["positive_window_indices"] == [4, 5, 6]
    assert oracle["negative_window_indices"] == [0, 1, 2, 3, 7, 8]
    assert oracle["incident_window_indices"] == oracle["positive_window_indices"]


def test_cleanup_is_exact_and_local_policy_was_respected() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["run"]["numeric_local_endpoints_only"] is True
    assert receipt["run"]["agent_generate_request_count"] == 0
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["cleanup"]["owned_artifacts_absent"] is True
    assert receipt["cleanup"]["running_container_set_preserved"] is True
