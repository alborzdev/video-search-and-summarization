from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _module("lvs_custom_model_prompt_executor_evidence", HERE / "execute.py")
builder = _module(
    "lvs_custom_model_prompt_builder_evidence", HERE / "build_official_evidence.py"
)
verifier = _module("lvs_custom_model_prompt_verifier_evidence", HERE / "verify.py")


def test_retained_evidence_and_projection_verify() -> None:
    result = verifier.verify()
    assert result["status"] == "passed"
    assert result["capability_id"] == "configuration.lvs.custom-model-prompt"
    assert result["http_request_count"] == 19
    assert result["semantic_action_count"] == 2
    assert result["custom_prompt_event_count"] == 1
    assert result["warehouse_sample_bundle"] is False


def test_official_projection_is_reproducible() -> None:
    retained = json.loads(builder.OUTPUT.read_text(encoding="utf-8"))
    assert retained == builder.build()


def test_retained_receipt_prevents_accidental_rerun_before_commands() -> None:
    with mock.patch.object(executor.subprocess, "run") as command:
        with pytest.raises(executor.QualificationError) as caught:
            executor.execute(executor.ACK, retain=False)
    command.assert_not_called()
    assert caught.value.code == "evidence_already_retained"


@pytest.mark.parametrize(
    "value",
    [
        {"request_id": "redacted"},
        {"safe": "00000000-0000-4000-8000-000000000099"},
        {"safe": "http://127.0.0.1:38111"},
        {"safe": "Bearer secret"},
        {"prompt": "redacted"},
    ],
)
def test_verifier_privacy_guard_rejects_sensitive_values(value: object) -> None:
    with pytest.raises(verifier.LvsCustomModelPromptEvidenceError):
        verifier._privacy_walk(value)


def test_verifier_privacy_guard_allows_only_the_fixed_owned_id() -> None:
    verifier._privacy_walk(
        {"target": "00000000-0000-4000-8000-000000000041"},
        allowed_fixed_ids={"00000000-0000-4000-8000-000000000041"},
    )
