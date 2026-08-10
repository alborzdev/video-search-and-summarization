from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "thor_lvs_single_request_queue_runtime", HERE / "execute.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def _contract() -> dict:
    return json.loads((HERE / "contract.json").read_text(encoding="utf-8"))


def test_plan_is_static_fail_closed_and_non_mutating() -> None:
    result = executor.plan()
    assert result["status"] == "passed"
    assert result["capability_id"] == "runtime.lvs.single-request-queue"
    assert result["acknowledgement_required"] is True
    assert result["writes_or_lifecycle_actions"] is False
    assert result["warehouse_sample_bundle"] is False
    assert result["execution_bounds"]["max_semantic_actions"] == 2


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), 2),
        (("execution_bounds", "max_http_requests"), 751),
        (("metrics", "poll_interval_seconds"), 0.5),
        (("metrics", "required_pending_transition"), [1, 0]),
        (("media", "expected_bytes"), 1),
        (("assets", 0, "asset_id"), "00000000-0000-4000-8000-000000000032"),
        (("base_dependency", "executor", "sha256"), "0" * 64),
    ],
)
def test_static_contract_mutations_fail_closed(
    path: tuple[object, ...], replacement: object
) -> None:
    contract = copy.deepcopy(_contract())
    current: object = contract
    for key in path[:-1]:
        current = current[key]  # type: ignore[index]
    current[path[-1]] = replacement  # type: ignore[index]
    with pytest.raises(executor.QualificationError) as caught:
        executor._verify_static(contract)
    assert caught.value.code == "configuration_error"


def test_transition_requires_two_then_one_then_zero_with_processed_steps() -> None:
    samples = [
        {"pending": 0, "processed": 18, "offset_seconds": 0.01},
        {"pending": 2, "processed": 18, "offset_seconds": 0.25},
        {"pending": 2, "processed": 18, "offset_seconds": 1.0},
        {"pending": 1, "processed": 19, "offset_seconds": 12.0},
        {"pending": 0, "processed": 20, "offset_seconds": 24.0},
    ]
    transition = executor._find_transition(samples, 18)
    assert [row["pending"] for row in transition] == [2, 1, 0]
    assert [row["processed"] for row in transition] == [18, 19, 20]
    assert [row["sample_index"] for row in transition] == [1, 3, 4]

    with pytest.raises(executor.QualificationError) as caught:
        executor._find_transition(samples[:3] + samples[4:], 18)
    assert caught.value.code == "oracle_failed"


class _MetricClient:
    def __init__(self, body: bytes, content_type: str = "text/plain; version=0.0.4"):
        self.body = body
        self.content_type = content_type

    def request(self, *_args, **_kwargs):
        return executor.Response(
            status=200,
            headers={"content-type": self.content_type},
            body=self.body,
        )


def _metrics_body() -> bytes:
    return b"\n".join(
        [
            b"# HELP video_file_queries_processed Number of video file queries whose processing is complete",
            b"# TYPE video_file_queries_processed gauge",
            b"video_file_queries_processed 18.0",
            b"# HELP video_file_queries_pending Number of video file queries which are queued and yet to be processed",
            b"# TYPE video_file_queries_pending gauge",
            b"video_file_queries_pending 2.0",
            b"# HELP vlm_queue_time_seconds Time a chunk waited in RTVI's VLM queue before processing",
            b"# TYPE vlm_queue_time_seconds histogram",
            b"vlm_queue_time_seconds_count 18.0",
            b"vlm_queue_time_seconds_sum 0.02",
            b"",
        ]
    )


def test_metric_parser_binds_exact_prometheus_contract() -> None:
    result = executor._metric_snapshot(
        _MetricClient(_metrics_body()), _contract(), "unit-metrics"
    )
    assert result == {
        "pending": 2,
        "processed": 18,
        "queue_count": 18,
        "queue_sum_seconds": 0.02,
    }

    bad = _metrics_body().replace(b"pending 2.0", b"pending NaN")
    with pytest.raises(executor.QualificationError) as caught:
        executor._metric_snapshot(_MetricClient(bad), _contract(), "bad-metrics")
    assert caught.value.code == "invalid_response"


@pytest.mark.parametrize(
    "value",
    [
        {"request_id": "redacted"},
        {"safe": "00000000-0000-4000-8000-000000000031"},
        {"safe": "http://127.0.0.1:38111"},
        {"safe": "Bearer secret"},
        {"safe": "nvapi-secret"},
    ],
)
def test_privacy_filter_rejects_identifiers_endpoints_and_credentials(value) -> None:
    with pytest.raises(executor.QualificationError) as caught:
        executor._privacy_walk(value)
    assert caught.value.code == "configuration_error"


def test_privacy_filter_accepts_only_redacted_semantic_measurements() -> None:
    executor._privacy_walk(
        {
            "pending_transition": [2, 1, 0],
            "response_sha256": "a" * 64,
            "summary_nonempty": True,
            "queue_sum_delta_seconds": 12.5,
        }
    )


def test_exclusive_receipt_retention_never_overwrites(
    monkeypatch, tmp_path: Path
) -> None:
    receipt_path = tmp_path / "runtime-receipt.json"
    monkeypatch.setattr(executor, "HERE", tmp_path)
    monkeypatch.setattr(executor, "RECEIPT_PATH", receipt_path)
    executor._retain_receipt({"status": "passed"})
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {"status": "passed"}
    with pytest.raises(executor.QualificationError) as caught:
        executor._retain_receipt({"status": "different"})
    assert caught.value.code == "evidence_already_retained"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {"status": "passed"}
