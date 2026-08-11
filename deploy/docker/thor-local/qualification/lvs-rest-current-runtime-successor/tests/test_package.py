from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


PACKAGE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("lvs_rest_verify", PACKAGE / "verify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sealed_receipt_verifies() -> None:
    result = _module().verify()
    assert result == {
        "actions": 4,
        "operation_count": 18,
        "package_id": "thor-lvs-rest-current-runtime-successor-v1",
        "promotion_eligible": True,
        "requests": 41,
        "status": "passed",
        "warehouse_sample_bundle": "excluded",
    }


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda value: value["operations"].pop(), "operation"),
        (lambda value: value["cleanup"].update({"relay_absent": False}), "cleanup"),
        (
            lambda value: value["fixture"].update(
                {"raw_prompt": "not permitted in retained evidence"}
            ),
            "Additional properties",
        ),
    ],
)
def test_verifier_fails_closed_on_receipt_drift(tmp_path, monkeypatch, mutation, match) -> None:
    for name in ("contract.json", "receipt.schema.json", "runtime-receipt.json"):
        shutil.copy2(PACKAGE / name, tmp_path / name)
    receipt_path = tmp_path / "runtime-receipt.json"
    value = json.loads(receipt_path.read_text())
    mutation(value)
    receipt_path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    )
    module = _module()
    monkeypatch.setattr(module, "HERE", tmp_path)
    with pytest.raises(Exception, match=match):
        module.verify()


def test_contract_excludes_forbidden_mutations() -> None:
    contract = json.loads((PACKAGE / "contract.json").read_text())
    assert len(contract["expected_operations"]) == 18
    assert contract["policy"] == {
        "agent_generate_calls": 0,
        "auth_boundary": "trusted-loopback-local-development",
        "retain_raw_ids": False,
        "retain_raw_prompts": False,
        "retain_raw_semantic_output": False,
        "vios_or_rt_cv_stream_mutations": 0,
        "warehouse_sample_bundle": "excluded",
    }
    assert contract["bounds"]["max_requests"] == 69
    assert contract["bounds"]["max_duration_seconds"] == 900
