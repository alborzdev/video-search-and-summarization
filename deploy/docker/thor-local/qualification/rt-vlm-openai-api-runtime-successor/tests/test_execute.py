from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rt_vlm_openai_api_execute", HERE / "execute.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def contract() -> dict:
    return json.loads((HERE / "contract.json").read_text())


def test_plan_is_inert_and_source_locked() -> None:
    value = MODULE._plan(contract())
    assert value["status"] == "inert_openai_api_plan_valid"
    assert value["http_requests"] == 0
    assert value["model_requests"] == 0
    assert value["writes_or_lifecycle_actions"] is False


def test_receipt_schema_is_valid() -> None:
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)


def test_exact_capability_and_index_set() -> None:
    value = contract()
    assert len(value["capability_ids"]) == 6
    assert value["official_indices"] == [347, 348, 349, 350, 353, 354]


def test_chat_payload_is_openai_shaped() -> None:
    messages = [{"role": "user", "content": "x"}]
    value = MODULE._chat_payload("model", messages, stream=True)
    assert value["model"] == "model"
    assert value["messages"] == messages
    assert value["stream"] is True
    assert value["stream_options"]["include_usage"] is True


def test_chat_content_accepts_exact_assistant_envelope() -> None:
    value = {
        "model": "m",
        "choices": [{"message": {"role": "assistant", "content": "EDGE42"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    content, result = MODULE._chat_content(value, "m")
    assert content == "EDGE42"
    assert result["model_exact"] is True
    assert result["usage_positive"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(model="wrong"),
        lambda x: x.update(choices=[]),
        lambda x: x["choices"][0].update(finish_reason="length"),
        lambda x: x.update(usage={}),
    ],
)
def test_chat_content_rejects_bad_envelopes(mutation) -> None:
    value = {
        "model": "m",
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    mutation(value)
    with pytest.raises(MODULE.QualificationError):
        MODULE._chat_content(value, "m")


def test_metrics_parser_requires_and_hashes_expected_families() -> None:
    raw = b"""# HELP system_uptime_seconds x
system_uptime_seconds 1
video_file_queries_processed 2
vlm_latency_seconds_count 3
"""
    value = MODULE._metrics(raw)
    assert value["required_families_present"] is True
    assert value["video_file_queries_processed"] == 2
    assert len(value["sample_names_sha256"]) == 64


def test_metrics_parser_rejects_missing_family() -> None:
    with pytest.raises(MODULE.QualificationError):
        MODULE._metrics(b"system_uptime_seconds 1\n")


def test_header_lookup_is_case_insensitive() -> None:
    assert MODULE._header({"content-type": "text/plain"}, "Content-Type") == "text/plain"
    assert MODULE._header({"Content-Type": "text/plain"}, "content-type") == "text/plain"


def test_policy_is_loopback_bounded_and_non_agent() -> None:
    value = contract()["execution"]
    assert value["endpoint"] == "http://127.0.0.1:8018"
    assert value["network_scope"] == "loopback_only"
    assert value["agent_generate_calls"] == 0
    assert value["stream_mutations"] == 0
    assert value["service_lifecycle_actions"] == 0
    assert value["warehouse_sample_bundle"] == "excluded"
