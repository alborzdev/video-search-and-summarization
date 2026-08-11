import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("rt_vlm_local_media_execute", HERE / "execute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_is_inert_and_exact():
    module = _module()
    contract = json.loads((HERE / "contract.json").read_text())
    plan = module._plan(contract)
    assert plan["status"] == "ready"
    assert plan["official_indices"] == [339, 340]
    assert plan["agent_generate_calls"] == 0
    assert plan["stream_mutations"] == 0
    assert plan["service_lifecycle_actions"] == 0


def test_wrong_endpoint_is_rejected_before_live_work(monkeypatch):
    module = _module()
    contract = json.loads((HERE / "contract.json").read_text())
    monkeypatch.setattr(module, "_verify_static", lambda value: object())
    with pytest.raises(module.QualificationError, match="endpoint must be exactly"):
        module._execute(contract, "http://127.0.0.1:9999")


def test_contract_has_exact_budgets_and_forbidden_call_guards():
    contract = json.loads((HERE / "contract.json").read_text())
    execution = contract["execution"]
    assert execution["max_http_requests"] == 13
    assert execution["max_model_requests"] == 2
    assert execution["max_container_commands"] == 11
    assert execution["agent_generate_calls"] == 0
    assert execution["stream_mutations"] == 0
    assert execution["service_lifecycle_actions"] == 0
    source = (HERE / "execute.py").read_text()
    assert '"/generate"' not in source
    assert "/v1/streams/add" not in source
    assert "docker restart" not in source


def test_receipt_schema_is_valid():
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)


def test_retained_receipt_validates_when_present():
    receipt_path = HERE / "runtime-receipt.json"
    if not receipt_path.exists():
        pytest.skip("live receipt not retained yet")
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    receipt = json.loads(receipt_path.read_text())
    Draft202012Validator(schema).validate(receipt)
    serialized = receipt_path.read_text().casefold()
    for forbidden in (
        '"authorization"',
        '"api_key"',
        '"request_id"',
        '"container_id"',
        '"prompt"',
        '"semantic_output"',
    ):
        assert forbidden not in serialized
    assert receipt["policy"]["raw_prompt_retained"] is False
    assert receipt["policy"]["raw_semantic_output_retained"] is False
