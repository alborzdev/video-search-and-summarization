import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


PACKAGE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "rt_vlm_absolute_timestamps_execute", PACKAGE_DIR / "execute.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _contract():
    return MODULE._load_json(PACKAGE_DIR / "contract.json")


def _response():
    return {
        "model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        "media_info": {
            "type": "timestamp",
            "start_timestamp": "2026-08-11T12:00:02.000Z",
            "end_timestamp": "2026-08-11T12:00:06.000Z",
        },
        "chunk_responses": [
            {
                "chunk_id": index,
                "start_time": start,
                "end_time": end,
                "content": "nonempty caption",
                "frame_count": 2,
                "decode_latency_ms": 1.0,
                "vlm_latency_ms": 2.0,
                "chunk_latency_ms": 3.0,
                "queue_time_s": 0.1,
                "processing_latency_s": 3.1,
            }
            for index, (start, end) in enumerate(
                [
                    ("2026-08-11T12:00:02.000Z", "2026-08-11T12:00:04.000Z"),
                    ("2026-08-11T12:00:04.000Z", "2026-08-11T12:00:06.000Z"),
                ]
            )
        ],
    }


def test_default_command_is_inert_plan():
    result = subprocess.run(
        [sys.executable, str(PACKAGE_DIR / "execute.py")],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "inert_absolute_timestamp_plan_valid"
    assert receipt["http_requests"] == 0
    assert receipt["writes_or_lifecycle_actions"] is False


def test_wrong_ack_fails_before_runtime():
    result = subprocess.run(
        [sys.executable, str(PACKAGE_DIR / "execute.py"), "execute", "--ack", "wrong"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "failed"


def test_endpoint_must_be_exact_loopback():
    contract = _contract()
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_endpoint("http://localhost:8018", contract)
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_endpoint("https://127.0.0.1:8018", contract)
    assert MODULE._validate_endpoint("http://127.0.0.1:8018", contract).endswith(":8018")


def test_source_locks_are_current():
    MODULE._validate_source_locks(_contract())


def test_fixture_is_deterministic(tmp_path):
    path = tmp_path / "fixture.mp4"
    MODULE._make_fixture(path)
    contract = _contract()
    assert path.stat().st_size == contract["fixture"]["bytes"]
    assert MODULE._sha256_file(path) == contract["fixture"]["sha256"]


def test_payload_selects_bounded_offset_window():
    payload = MODULE._request_payload("opaque-id", "model", _contract())
    assert payload["media_info"] == {"type": "offset", "start_offset": 2, "end_offset": 6}
    assert payload["chunk_duration"] == 2
    assert payload["stream"] is False


def test_positive_oracle_accepts_exact_absolute_windows():
    result = MODULE._validate_positive_response(
        _response(),
        expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        contract=_contract(),
    )
    assert result["chunk_count"] == 2
    assert result["all_inference_content_nonempty"] is True
    assert "content" not in result


def test_positive_oracle_rejects_relative_chunk_time():
    response = _response()
    response["chunk_responses"][0]["start_time"] = "2.0"
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_positive_response(
            response,
            expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            contract=_contract(),
        )


def test_positive_oracle_rejects_empty_inference():
    response = _response()
    response["chunk_responses"][0]["content"] = ""
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_positive_response(
            response,
            expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            contract=_contract(),
        )


def test_positive_oracle_rejects_missing_metric():
    response = _response()
    response["chunk_responses"][0].pop("vlm_latency_ms")
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_positive_response(
            response,
            expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            contract=_contract(),
        )


def test_malformed_timestamp_requires_structured_422():
    result = MODULE._validate_malformed_response(
        422, {"code": "InvalidParameters", "message": "invalid timestamp"}
    )
    assert result["structured_error"] is True
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_malformed_response(200, {})


def test_catalog_fingerprint_is_order_sensitive_and_private():
    count, digest = MODULE._catalog_fingerprint({"data": [{"id": "opaque"}]})
    assert count == 1
    assert len(digest) == 64
    assert "opaque" not in digest
