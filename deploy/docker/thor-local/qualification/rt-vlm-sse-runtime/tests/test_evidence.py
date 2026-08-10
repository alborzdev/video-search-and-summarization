from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _module("rt_vlm_sse_runtime_executor", HERE / "execute.py")
verifier = _module("rt_vlm_sse_runtime_verifier", HERE / "verify.py")


def test_retained_evidence_and_six_projections_verify() -> None:
    result = verifier.verify()
    assert result["status"] == "passed"
    assert result["capability_count"] == 6
    assert result["capability_ids"] == verifier.CAPABILITY_IDS


def test_inert_plan_names_exact_bounds_and_forbidden_actions() -> None:
    contract, _ = executor._load(executor.CONTRACT_PATH)
    plan = executor._plan(contract)
    assert plan["mode"] == "inert_plan"
    assert plan["network_scope"] == "loopback_only"
    assert plan["warehouse_sample_bundle"] is False
    assert len(plan["semantic_actions"]) == contract["max_semantic_actions"] == 8
    assert "VSS Agent /generate" in plan["forbidden_actions"]
    assert "RTSP stream registration or deletion" in plan["forbidden_actions"]


def test_multipart_is_exactly_owned_and_contains_no_authorization() -> None:
    contract, _ = executor._load(executor.CONTRACT_PATH)
    body, media_type = executor._multipart(contract)
    fixture = contract["fixture"]
    assert media_type == "multipart/form-data; boundary=vss-rt-vlm-sse-runtime"
    assert fixture["asset_id"].encode() in body
    assert fixture["sensor_name"].encode() in body
    assert fixture["filename"].encode() in body
    assert b'filename="vss-protocol-case-rt-vlm.mp4"' in body
    assert b"Authorization" not in body
    assert len(body) <= contract["max_request_bytes"]


def _sse_frame(value: object) -> bytes:
    payload = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    return f"data: {payload}\n\n".encode()


def test_sse_parser_accepts_schema_empty_chunk_but_requires_real_output() -> None:
    contract, _ = executor._load(executor.CONTRACT_PATH)
    request_id = "00000000-0000-4000-8000-000000000099"
    common = {
        "id": request_id,
        "model": contract["runtime"]["served_model_id"],
        "created": 1,
        "media_info": {"start_offset": 0, "end_offset": 2},
        "usage": None,
    }
    raw = b"".join(
        (
            _sse_frame(
                {
                    **common,
                    "chunk_responses": [
                        {"chunk_id": 0, "start_time": "0.0", "end_time": "1.0", "content": ""}
                    ],
                }
            ),
            _sse_frame(
                {
                    **common,
                    "chunk_responses": [
                        {"chunk_id": 1, "start_time": "1.0", "end_time": "2.0", "content": "worker carries a box"}
                    ],
                }
            ),
            _sse_frame(
                {
                    **common,
                    "media_info": None,
                    "usage": {
                        "query_processing_time": 1,
                        "total_chunks_processed": 2,
                        "prompt_tokens": 2,
                        "completion_tokens": 2,
                        "total_tokens": 4,
                    },
                    "chunk_responses": [],
                }
            ),
            _sse_frame("[DONE]"),
        )
    )
    result = executor._parse_sse(
        raw,
        contract,
        {"content-type": "text/event-stream", "x-request-id": request_id},
    )
    assert result["caption_chunk_count"] == 2
    assert result["usage_event_count"] == 1
    assert result["terminal_event_last"] is True
    assert [row["content_nonblank"] for row in result["caption_chunks"]] == [
        False,
        True,
    ]


def test_sse_parser_rejects_no_real_caption_output() -> None:
    contract, _ = executor._load(executor.CONTRACT_PATH)
    request_id = "00000000-0000-4000-8000-000000000099"
    event = {
        "id": request_id,
        "model": contract["runtime"]["served_model_id"],
        "created": 1,
        "media_info": {"start_offset": 0, "end_offset": 1},
        "usage": None,
        "chunk_responses": [
            {"chunk_id": 0, "start_time": "0.0", "end_time": "1.0", "content": " "}
        ],
    }
    usage = {
        "id": request_id,
        "model": contract["runtime"]["served_model_id"],
        "created": 1,
        "media_info": None,
        "usage": {"query_processing_time": 1, "total_chunks_processed": 1},
        "chunk_responses": [],
    }
    raw = _sse_frame(event) + _sse_frame(usage) + _sse_frame("[DONE]")
    with pytest.raises(executor.QualificationError, match="captions plus"):
        executor._parse_sse(
            raw,
            contract,
            {"content-type": "text/event-stream", "x-request-id": request_id},
        )


def test_privacy_guard_rejects_dynamic_request_id_and_credentials() -> None:
    with pytest.raises(verifier.RtVlmEvidenceError, match="forbidden retained field"):
        verifier._privacy_walk({"request_id": "dynamic"})
    with pytest.raises(verifier.RtVlmEvidenceError, match="credential-like"):
        verifier._privacy_walk({"safe": "Bearer secret"})
