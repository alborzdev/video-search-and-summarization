from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
from unittest import mock

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "thor_lvs_custom_model_prompt_runtime", HERE / "execute.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def _contract() -> dict:
    return json.loads((HERE / "contract.json").read_text(encoding="utf-8"))


def _base():
    return executor._verify_static(_contract())["base"]


def test_plan_is_static_bounded_and_non_mutating() -> None:
    with mock.patch.object(executor.subprocess, "run") as command:
        result = executor.plan()
    command.assert_not_called()
    assert result["status"] == "passed"
    assert result["capability_id"] == "configuration.lvs.custom-model-prompt"
    assert result["acknowledgement_required"] is True
    assert result["execution_bounds"]["max_http_requests"] == 19
    assert result["execution_bounds"]["max_semantic_actions"] == 2
    assert result["execution_bounds"]["model_staging"] == "forbidden"
    assert result["execution_bounds"]["service_lifecycle"] == "forbidden"
    assert result["writes_or_lifecycle_actions"] is False
    assert result["warehouse_sample_bundle"] is False


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), 2),
        (("prompt_contract", "custom_prompt_sha256"), "0" * 64),
        (("execution_bounds", "max_http_requests"), 20),
        (("render_probe", "model_selector"), "openai-compat"),
        (("live_model_configuration", "model_root_mount", "read_only"), False),
        (("source_anchors", 4, "sha256"), "0" * 64),
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


def test_compose_render_proves_same_path_read_only_rt_vlm_mount() -> None:
    contract = _contract()
    proof = executor._render_custom_model(contract, deadline=time.monotonic() + 120)
    assert proof["model_selector_exact"] is True
    assert proof["model_path_below_model_root"] is True
    assert proof["lvs_model_root_mount_exact"] is True
    assert proof["rt_vlm_model_root_mount_exact"] is True
    assert proof["rt_vlm_model_root_mount_read_only"] is True


def _summary_response(*, event: dict[str, object]):
    base = _base()
    content = json.dumps(
        {
            "video_summary": "A worker performs notable activity.",
            "events": [event],
            "total_events": 1,
            "uuids": ["00000000-0000-4000-8000-000000000041"],
        }
    )
    envelope = {
        "id": "00000000-0000-4000-8000-000000000099",
        "video_id": "00000000-0000-4000-8000-000000000041",
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
    return base, base.Response(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(envelope).encode(),
    )


def test_custom_summary_requires_compatible_caption_shape() -> None:
    event = {
        "start_time": 0.0,
        "end_time": 10.0,
        "type": "notable activity",
        "description": "A worker moves through the scene.",
    }
    base, response = _summary_response(event=event)
    result = executor._validate_custom_summary(base, response, _contract())
    assert result["summary_shape_exact"] is True
    assert result["caption_event_shape_compatible"] is True
    assert result["event_count"] == 1

    missing_type = dict(event)
    missing_type.pop("type")
    base, response = _summary_response(event=missing_type)
    with pytest.raises(executor.QualificationError) as caught:
        executor._validate_custom_summary(base, response, _contract())
    assert caught.value.code == "oracle_failed"


@pytest.mark.parametrize(
    "value",
    [
        {"request_id": "redacted"},
        {"safe": "00000000-0000-4000-8000-000000000041"},
        {"safe": "http://127.0.0.1:38111"},
        {"safe": "Bearer secret"},
        {"safe": "nvapi-secret"},
        {"prompt": "redacted"},
        {"content": "redacted"},
    ],
)
def test_privacy_filter_rejects_identifiers_urls_credentials_and_content(
    value: object,
) -> None:
    with pytest.raises(executor.QualificationError) as caught:
        executor._privacy_walk(value)
    assert caught.value.code == "configuration_error"


def test_privacy_filter_accepts_only_sanitized_measurements() -> None:
    executor._privacy_walk(
        {
            "custom_prompt_sha256": "a" * 64,
            "summary_shape_exact": True,
            "event_count": 1,
            "duration_seconds": 17.1,
        }
    )


def test_exclusive_receipt_retention_never_overwrites(
    monkeypatch, tmp_path: Path
) -> None:
    receipt_path = tmp_path / "runtime-receipt.json"
    monkeypatch.setattr(executor, "HERE", tmp_path)
    monkeypatch.setattr(executor, "RECEIPT_PATH", receipt_path)
    executor._retain_receipt({"status": "passed"})
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {
        "status": "passed"
    }
    with pytest.raises(executor.QualificationError) as caught:
        executor._retain_receipt({"status": "different"})
    assert caught.value.code == "evidence_already_retained"
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {
        "status": "passed"
    }
