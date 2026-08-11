import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("file_dense_execute", HERE / "execute.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def contract():
    return MODULE._load_json(HERE / "contract.json")


def dense_response():
    windows = contract()["dense"]["expected_windows"]
    colors = ["blue", "green", "red"]
    return {
        "model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        "chunk_responses": [
            {"chunk_id": i, "start_time": window[0], "end_time": window[1], "content": f"{colors[i]} phase", "frame_count": 4}
            for i, window in enumerate(windows)
        ],
        "usage": {"total_chunks_processed": 3},
    }


def test_default_is_inert():
    result = subprocess.run([sys.executable, str(HERE / "execute.py")], check=True, capture_output=True, text=True)
    value = json.loads(result.stdout)
    assert value["status"] == "inert_file_dense_plan_valid"
    assert value["http_requests"] == 0


def test_wrong_ack_fails():
    result = subprocess.run([sys.executable, str(HERE / "execute.py"), "execute", "--ack", "wrong"], capture_output=True, text=True)
    assert result.returncode == 1


def test_static_locks_are_current():
    MODULE._verify_static(contract())


def test_endpoint_is_exact_loopback():
    assert MODULE._validate_endpoint("http://127.0.0.1:8018", contract()).endswith("8018")
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_endpoint("http://localhost:8018", contract())


def test_payload_controls_chunking():
    dense = MODULE._caption_payload("id", "model", 3)
    flat = MODULE._caption_payload("id", "model", 0)
    assert dense["chunk_duration"] == 3
    assert flat["chunk_duration"] == 0
    assert dense["num_frames_per_second_or_fixed_frames_chunk"] == 4


def test_dense_oracle_accepts_ordered_marked_chunks():
    result = MODULE._validate_dense(dense_response(), contract(), "nim_nvidia_cosmos3-nano-reasoner_bf16-final")
    assert result["chunk_count"] == 3
    assert result["primary_phase_markers_present"] == [True, True, True]
    assert "content" not in result


def test_dense_oracle_rejects_reordered_window():
    value = dense_response()
    value["chunk_responses"][1]["start_time"] = "0.0"
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_dense(value, contract(), "nim_nvidia_cosmos3-nano-reasoner_bf16-final")


def test_dense_oracle_rejects_missing_phase_marker():
    value = dense_response()
    value["chunk_responses"][2]["content"] = "unknown phase"
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_dense(value, contract(), "nim_nvidia_cosmos3-nano-reasoner_bf16-final")


def test_non_dense_control_requires_one_full_window():
    value = {"model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final", "chunk_responses": [{"chunk_id": 0, "start_time": "2026-08-11T12:00:00.000Z", "end_time": "2026-08-11T12:00:09.000Z", "content": "one result"}], "usage": {"total_chunks_processed": 1}}
    result = MODULE._validate_non_dense(value, contract(), "nim_nvidia_cosmos3-nano-reasoner_bf16-final")
    assert result["multi_chunk_dense_payload_absent"] is True


def test_non_dense_control_rejects_multiple_chunks():
    value = {"model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final", "chunk_responses": [{}, {}], "usage": {"total_chunks_processed": 2}}
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_non_dense(value, contract(), "nim_nvidia_cosmos3-nano-reasoner_bf16-final")


def test_catalog_fingerprint_hides_identity():
    count, digest = MODULE._catalog({"data": [{"id": "opaque-id"}]})
    assert count == 1 and len(digest) == 64 and "opaque" not in digest
