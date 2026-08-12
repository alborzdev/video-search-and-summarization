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


def test_uninstantiated_multiprocess_counter_means_zero() -> None:
    harness = load("harness")
    metric = "alert_bridge_async_external_io_fallback_total"
    labels = {"operation": "dispatch_message", "reason": "submit_error"}
    assert harness.metric_sum_or_zero("", metric, labels) == 0.0
    text = (
        f'{metric}{{operation="dispatch_message",reason="submit_error"}} 2\n'
        f'{metric}{{operation="dispatch_message",reason="submit_error"}} 3\n'
    )
    assert harness.metric_sum_or_zero(text, metric, labels) == 5.0


def test_retained_receipt_validates() -> None:
    value = receipt()
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def test_full_verifier_passes() -> None:
    assert load("verify").main() == 0


def test_slowest_call_does_not_block_ingestion_or_fast_candidates() -> None:
    value = receipt()
    concurrency = value["concurrency"]
    assert concurrency["maximum_parallel_vlm_calls"] >= 3
    assert len(concurrency["dispatch_threads"]) >= 3
    assert concurrency["queue_events_total"] == 6
    assert concurrency["queue_events_before_slowest_completed"] >= 6
    assert concurrency["fast_candidates_completed_before_slow"] == [1, 2, 3, 4, 5]
    assert concurrency["completion_order"][-1] == 0
    assert concurrency["all_independent_fast_candidates_overtook_slow"] is True
    assert concurrency["inline_fallbacks"] == 0


def test_per_candidate_state_and_terminal_metrics_are_preserved() -> None:
    value = receipt()
    candidates = value["candidates"]
    assert candidates["count"] == 6
    assert candidates["confirmed_count"] == 3
    assert candidates["rejected_count"] == 3
    assert candidates["all_media_correlated"] is True
    assert candidates["all_parser_schemas_conformant"] is True
    assert candidates["all_categories_preserved"] is True
    assert [item["candidate"] for item in candidates["records"]] == list(range(6))
    for item in candidates["records"]:
        assert item["event_metric_count"] == 1.0
        assert item["after_dedup_metric_count"] == 1.0
        assert set(item["terminal_metric_counts"].values()) == {1.0}


def test_exact_cleanup_and_local_policy_are_proven() -> None:
    value = receipt()
    cleanup = value["cleanup"]
    assert cleanup["before_sha256"] == cleanup["after_sha256"]
    assert cleanup["exact_main_runtime_restored"] is True
    assert cleanup["running_container_set_preserved"] is True
    assert cleanup["owned_container_absent"] is True
    assert cleanup["owned_indices_absent"] is True
    assert cleanup["owned_redis_keys_absent"] is True
    assert cleanup["owned_kafka_topics_absent"] is True
    assert value["policy"] == {
        "network": "loopback-only",
        "external_requests": 0,
        "agent_generate_calls": 0,
        "warehouse_sample_bundle": "excluded",
        "main_alert_mutations": 0,
        "main_rtvlm_mutations": 0,
    }
