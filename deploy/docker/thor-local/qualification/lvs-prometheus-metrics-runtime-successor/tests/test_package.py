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


def test_one_request_advances_intended_series_once() -> None:
    value = receipt()
    assert value["request"]["http_status"] == 200
    assert value["request"]["chunk_count"] == 1
    assert value["prometheus"]["processed_query_delta"] == 1.0
    assert set(value["prometheus"]["histogram_count_deltas"].values()) == {1.0}
    assert value["prometheus"]["pending_before"] == 0.0
    assert value["prometheus"]["pending_after"] == 0.0
    assert value["prometheus"]["latest_latencies_positive"] is True


def test_prometheus_is_parseable_without_resource_id_cardinality() -> None:
    value = receipt()["prometheus"]
    assert value["parseable_before"] is True
    assert value["parseable_after"] is True
    assert value["content_type_text_plain"] is True
    assert value["forbidden_resource_labels"] == []
    assert value["resource_id_cardinality_absent"] is True


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
