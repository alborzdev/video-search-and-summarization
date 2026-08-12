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


def test_authoritative_api_mapping_is_explicit() -> None:
    value = receipt()["authoritative_api_mapping"]
    assert value["ledger_endpoint_semantics_reversed"] is True
    assert value["source_declares_original_plural"] is True
    assert value["source_declares_cv_compatible_singular"] is True
    assert value["stream_route_set_exact"] is True
    assert all(path.startswith("/v1/streams/") for path in value["original_routes"])
    assert all(path.startswith("/v1/stream/") for path in value["cv_compatible_routes"])


def test_both_api_families_and_negatives_are_proven() -> None:
    value = receipt()
    assert value["original_api"]["metadata_round_trip_exact"] is True
    assert value["original_api"]["batch_per_item_outcomes_exact"] is True
    assert value["cv_compatible_api"]["identity_round_trip_exact"] is True
    assert value["cv_compatible_api"]["duplicate_status"] == 409
    assert value["cv_compatible_api"]["missing_remove_status"] == 404


def test_exact_cleanup_and_local_policy_are_proven() -> None:
    value = receipt()
    assert value["cleanup"]["before_sha256"] == value["cleanup"]["after_sha256"]
    assert value["cleanup"]["catalogs_restored_exactly"] is True
    assert value["cleanup"]["owned_streams_absent"] is True
    assert value["cleanup"]["support_container_absent"] is True
    assert value["cleanup"]["publisher_stopped"] is True
    assert value["cleanup"]["running_container_set_preserved"] is True
    assert value["policy"] == {
        "external_requests": 0,
        "agent_generate_calls": 0,
        "model_inference_requests": 0,
        "main_vios_mutations": 0,
        "core_service_lifecycle_actions": 0,
        "warehouse_sample_bundle": "excluded",
        "raw_resource_ids_retained": False,
        "credentials_retained": False,
    }
