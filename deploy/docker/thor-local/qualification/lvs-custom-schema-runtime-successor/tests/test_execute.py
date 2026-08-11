from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lvs_custom_schema_runtime", HERE / "execute.py")
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def _contract() -> dict:
    return json.loads((HERE / "contract.json").read_text(encoding="utf-8"))


def _response(status: int, value: object):
    return SimpleNamespace(
        status=status,
        content_type="application/json",
        body=json.dumps(value, sort_keys=True).encode(),
    )


def _envelope(identifier: str, model: str, events: list[dict]) -> object:
    content = json.dumps({"video_summary": "", "events": events})
    return _response(
        200,
        {
            "id": str(uuid4()),
            "video_id": identifier,
            "model": model,
            "object": "summarization.completion",
            "media_info": {"type": "offset", "start_offset": None, "end_offset": None},
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"total_chunks_processed": 1},
        },
    )


def _event() -> dict:
    return {
        "start_time": 0.0,
        "end_time": 10.0,
        "description": "An amber crate moves across the frame.",
        "type": "visible object movement",
        "schema_marker": "thor-local-schema",
    }


def test_plan_is_static_bounded_and_non_mutating() -> None:
    result = executor.plan()
    assert result["status"] == "passed"
    assert result["max_actions"] == 10
    assert result["writes_or_lifecycle_actions"] is False
    assert result["warehouse_sample_bundle"] == "excluded"


def test_schema_pair_is_valid_and_has_possible_vs_impossible_marker_enum() -> None:
    positive = json.loads(executor._schema(["thor-local-schema"]))
    negative = json.loads(executor._schema([]))
    marker_path = positive["properties"]["events"]["items"]["properties"]["schema_marker"]
    negative_marker = negative["properties"]["events"]["items"]["properties"]["schema_marker"]
    assert marker_path["enum"] == ["thor-local-schema"]
    assert negative_marker["enum"] == []
    assert set(positive["properties"]["events"]["items"]["required"]) == {
        "start_time", "end_time", "description", "type", "schema_marker"
    }


def test_request_selects_schema_aware_plain_caption_mode() -> None:
    value = json.loads(executor._request(str(uuid4()), "local-model", executor._schema(["thor-local-schema"])))
    assert value["batch_response_method"] == "json_schema"
    assert value["auto_generate_prompt"] is False
    assert value["enable_vlm_structured_output"] is False
    assert value["override_vlm_prompt"] is False
    assert value["events"] == ["visible object movement"]
    assert value["objects_of_interest"] == ["amber crate"]


def test_positive_validator_requires_exact_custom_event_shape() -> None:
    contract = _contract()
    identifier = str(uuid4())
    result = executor._validate_positive(
        _envelope(identifier, contract["model_id"], [_event()]), identifier, contract
    )
    assert result["event_count"] == 1
    assert result["event_keys_exact"] is True
    assert result["schema_markers_exact"] is True
    assert result["fixture_grounded"] is True


@pytest.mark.parametrize("field", ["schema_marker", "type"])
def test_positive_validator_fails_closed_on_custom_field_drift(field: str) -> None:
    contract = _contract()
    identifier = str(uuid4())
    event = _event()
    event[field] = "wrong"
    with pytest.raises(executor.QualificationError, match="oracle_failed"):
        executor._validate_positive(
            _envelope(identifier, contract["model_id"], [event]), identifier, contract
        )


def test_impossible_schema_allows_only_parseable_empty_success() -> None:
    contract = _contract()
    identifier = str(uuid4())
    result = executor._validate_negative(
        _envelope(identifier, contract["model_id"], []), identifier, contract
    )
    assert result["http_status"] == 200
    assert result["json_parseable"] is True
    assert result["event_count"] == 0
    with pytest.raises(executor.QualificationError, match="oracle_failed"):
        executor._validate_negative(
            _envelope(identifier, contract["model_id"], [_event()]), identifier, contract
        )


def test_impossible_schema_accepts_parseable_non_success_error() -> None:
    contract = _contract()
    result = executor._validate_negative(
        _response(422, {"code": "BadParameters"}), str(uuid4()), contract
    )
    assert result["http_status"] == 422
    assert result["event_count"] is None
    assert result["malformed_success_rejected"] is True


def test_authorization_precedes_runtime_and_transport(monkeypatch) -> None:
    called = False

    def fail_snapshot(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(executor, "_container_snapshot", fail_snapshot)
    with pytest.raises(executor.QualificationError, match="authorization_required"):
        executor.execute("wrong")
    assert called is False


def test_contract_mutation_fails_closed() -> None:
    contract = copy.deepcopy(_contract())
    contract["execution_bounds"]["max_http_requests"] = 11
    with pytest.raises(executor.QualificationError, match="configuration_error"):
        executor._verify_static(contract)


@pytest.mark.parametrize(
    "value",
    [
        {"id": "raw"},
        {"prompt": "raw"},
        {"path": "/tmp/raw"},
        {"safe": "http://127.0.0.1:38111"},
        {"safe": "Bearer secret"},
    ],
)
def test_privacy_filter_rejects_raw_identity_prompt_and_endpoint(value: object) -> None:
    with pytest.raises(executor.QualificationError, match="configuration_error"):
        executor._privacy_walk(value)


def test_privacy_filter_accepts_hashed_receipt_fields() -> None:
    executor._privacy_walk(
        {
            "package_id": "lvs-custom-schema-runtime-successor",
            "capability_id": "manifest-entry.video-summarization-file.03-structured-output",
            "owned_id_sha256": "a" * 64,
            "response_sha256": "b" * 64,
            "event_count": 1,
        }
    )
