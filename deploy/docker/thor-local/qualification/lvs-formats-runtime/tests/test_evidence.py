from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _module("lvs_formats_runtime_executor", HERE / "execute.py")
verifier = _module("lvs_formats_runtime_verifier", HERE / "verify.py")
builder = _module(
    "lvs_formats_runtime_builder", HERE / "build_official_evidence.py"
)


def test_retained_evidence_and_projection_verify() -> None:
    result = verifier.verify()
    assert result["status"] == "passed"
    assert result["capability_id"] == "runtime.lvs.supported-formats"
    assert result["format_count"] == 5
    assert result["http_request_count"] == 37
    assert result["semantic_action_count"] == 9


def test_official_projection_is_reproducible() -> None:
    retained = json.loads(builder.OUTPUT.read_text(encoding="utf-8"))
    assert retained == builder.build()


def test_plan_is_inert_and_exactly_bounded() -> None:
    with (
        mock.patch.object(executor.subprocess, "run") as command,
        mock.patch.object(executor.http.client, "HTTPConnection") as connection,
    ):
        result = executor.plan()
    command.assert_not_called()
    connection.assert_not_called()
    assert result["status"] == "passed"
    assert result["format_names"] == ["MP4", "AVI", "MOV", "MKV", "WebM"]
    assert result["execution_bounds"]["max_http_requests"] == 37
    assert result["execution_bounds"]["max_semantic_actions"] == 9
    assert result["execution_bounds"]["min_free_bytes"] == 10 * 1024**3
    assert result["writes_or_lifecycle_actions"] is False
    assert result["warehouse_sample_bundle"] is False


def test_retained_receipt_prevents_accidental_rerun_before_commands() -> None:
    with mock.patch.object(executor.subprocess, "run") as command:
        with pytest.raises(executor.QualificationError) as raised:
            executor.execute(executor.ACK)
    command.assert_not_called()
    assert raised.value.code == "evidence_already_retained"


def test_static_contract_rejects_format_or_boundary_drift() -> None:
    contract, _ = executor._load(executor.CONTRACT_PATH)
    drifted = copy.deepcopy(contract)
    drifted["formats"][0]["name"] = "MPEG-4"
    with pytest.raises(executor.QualificationError) as raised:
        executor._verify_static(drifted)
    assert raised.value.code == "configuration_error"


def test_multipart_is_fixed_owned_and_contains_no_authorization() -> None:
    identifier = "00000000-0000-4000-8000-000000000021"
    body, content_type = executor._multipart(
        identifier=identifier,
        filename="vss-lvs-format.mp4",
        mime_type="video/mp4",
        sensor_name="vss-lvs-formats-mp4",
        media=b"media",
        boundary_suffix="mp4",
    )
    assert content_type == "multipart/form-data; boundary=vss-lvs-formats-mp4"
    assert identifier.encode() in body
    assert b'filename="vss-lvs-format.mp4"' in body
    assert b"video/mp4" in body
    assert b"Authorization" not in body


def _summary_response(*, summary: str, events: list[dict[str, object]]):
    content = json.dumps(
        {
            "video_summary": summary,
            "events": events,
            "total_events": len(events),
        }
    )
    value = {
        "id": "00000000-0000-4000-8000-000000000099",
        "video_id": "00000000-0000-4000-8000-000000000021",
        "model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        "object": "summarization.completion",
        "created": 1,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"total_chunks_processed": 1},
    }
    return executor.Response(
        200,
        {"content-type": "application/json"},
        json.dumps(value).encode(),
    )


def test_summary_validator_requires_real_semantic_output() -> None:
    accepted = executor._validate_summary(
        _summary_response(summary="worker moves a container", events=[]),
        identifier="00000000-0000-4000-8000-000000000021",
        model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        expected_chunks=1,
    )
    assert accepted["video_summary_nonempty"] is True
    assert accepted["chunks_processed"] == 1
    with pytest.raises(executor.QualificationError):
        executor._validate_summary(
            _summary_response(summary=" ", events=[]),
            identifier="00000000-0000-4000-8000-000000000021",
            model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            expected_chunks=1,
        )


def test_privacy_guard_rejects_dynamic_identity_url_and_credentials() -> None:
    with pytest.raises(verifier.LvsFormatsEvidenceError):
        verifier._privacy_walk(
            {"safe": "00000000-0000-4000-8000-000000000099"}
        )
    with pytest.raises(verifier.LvsFormatsEvidenceError):
        verifier._privacy_walk({"safe": "http://127.0.0.1:38111"})
    with pytest.raises(verifier.LvsFormatsEvidenceError):
        verifier._privacy_walk({"safe": "Bearer secret"})
