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


def test_four_chronological_chunks_cover_endpoint_events() -> None:
    value = receipt()["chunked_dense_captions"]
    assert value["intervals"] == [[0.0, 3.0], [3.0, 6.0], [6.0, 9.0], [9.0, 10.0]]
    assert value["chunk_count"] == value["usage_total_chunks_processed"] == 4
    assert value["chronological_and_contiguous"] is True
    assert value["first_event_carrying_box"] is True
    assert value["last_event_on_ladder_at_shelf"] is True
    assert value["absent_forklift_excluded"] is True


def test_file_summary_aggregates_both_events_without_control() -> None:
    value = receipt()["file_summarization"]
    assert value["http_status"] == 200
    assert value["event_count"] == 2
    assert value["beginning_box_event_present"] is True
    assert value["ending_ladder_event_present"] is True
    assert value["absent_forklift_excluded"] is True
    assert value["chronological"] is True
    assert value["summary_requests"] == 1
    assert value["summary_tokens_positive"] is True
    assert value["aggregation_tokens_positive"] is True


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
