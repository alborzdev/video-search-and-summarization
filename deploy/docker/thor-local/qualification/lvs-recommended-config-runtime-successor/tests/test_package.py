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


def receipt() -> dict:
    return json.loads((HERE / "runtime-receipt.json").read_text())


def test_retained_receipt_validates() -> None:
    value = receipt()
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def test_full_verifier_passes() -> None:
    assert load("verify").main() == 0


def test_released_api_contract_and_metadata_discrepancy_are_explicit() -> None:
    api = receipt()["authoritative_api"]
    assert api["request_fields"] == [
        "target_response_time", "usecase_event_duration", "video_length",
    ]
    assert api["response_fields"] == ["chunk_size", "text"]
    assert api["frame_setting_advertised_by_api"] is False
    assert api["token_setting_advertised_by_api"] is False
    assert api["model_context_field_advertised_by_api"] is False
    assert api["generated_ledger_semantics_overstate_frame_token_and_model_context"] is True


def test_recommendation_is_bounded_and_accepted_unchanged() -> None:
    value = receipt()
    recommendation = value["recommendation"]
    follow_on = value["follow_on"]
    assert recommendation["http_status"] == 200
    assert recommendation["within_declared_bounds"] is True
    assert set(recommendation["lower_bound_negative_statuses"].values()) == {422}
    assert follow_on["http_status"] == 200
    assert follow_on["recommended_chunk_size"] == follow_on["submitted_chunk_duration"]
    assert follow_on["accepted_unchanged"] is True
    assert follow_on["chunk_count"] >= 1
    assert follow_on["response_content_nonempty"] is True


def test_exact_cleanup_and_local_policy_are_proven() -> None:
    value = receipt()
    cleanup = value["cleanup"]
    assert cleanup["file_catalog_before_sha256"] == cleanup["file_catalog_after_sha256"]
    assert cleanup["file_catalog_restored_exactly"] is True
    assert cleanup["graph_before"] == cleanup["graph_after"]
    assert cleanup["graph_restored_exactly"] is True
    assert cleanup["owned_graph_nodes_absent"] is True
    assert cleanup["running_container_set_preserved"] is True
    assert cleanup["runtime_state_preserved"] is True
    assert value["policy"]["agent_generate_calls"] == 0
    assert value["policy"]["external_requests"] == 0
    assert value["policy"]["warehouse_sample_bundle"] == "excluded"
