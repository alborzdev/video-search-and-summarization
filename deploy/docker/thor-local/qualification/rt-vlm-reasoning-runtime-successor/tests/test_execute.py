import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


PACKAGE_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rt_vlm_reasoning_execute", PACKAGE_DIR / "execute.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _response(answer="blue", model="nim_nvidia_cosmos3-nano-reasoner_bf16-final"):
    return {
        "id": "opaque-runtime-id",
        "model": model,
        "choices": [
            {
                "message": {
                    "content": f"<think>private reasoning</think>\n\n<answer>{answer}</answer>"
                }
            }
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
    assert receipt["status"] == "inert_reasoning_plan_valid"
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
    contract = MODULE._load_json(PACKAGE_DIR / "contract.json")
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_endpoint("http://localhost:8018", contract)
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_endpoint("https://127.0.0.1:8018", contract)
    assert MODULE._validate_endpoint("http://127.0.0.1:8018", contract) == "http://127.0.0.1:8018"


def test_source_locks_are_current():
    contract = MODULE._load_json(PACKAGE_DIR / "contract.json")
    MODULE._validate_source_locks(contract)


def test_question_is_temporal_and_fixed():
    assert "beginning and end" in MODULE._question()
    assert MODULE._question() == MODULE._question()


def test_request_enables_reasoning_and_uses_inline_video():
    request = MODULE._request("model", b"video")
    assert request["enable_reasoning"] is True
    assert request["max_tokens"] == 1024
    assert request["messages"][0]["content"][1]["video_url"]["url"].startswith(
        "data:video/mp4;base64,"
    )


def test_strip_reasoning_returns_only_final_answer():
    answer, signaled = MODULE._strip_reasoning(
        "<think>do not retain this</think>\n<answer>blue</answer>"
    )
    assert answer == "blue"
    assert signaled is True


def test_incomplete_reasoning_block_is_rejected():
    with pytest.raises(MODULE.QualificationError):
        MODULE._strip_reasoning("<think>unfinished blue")


def test_correct_temporal_conclusion_passes_without_raw_text():
    result = MODULE._validate_case_response(
        _response(),
        expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        expected_answer="blue",
    )
    assert result["correct_final_conclusion"] is True
    assert result["hidden_reasoning_excluded_from_semantic_oracle"] is True
    assert "content" not in result
    assert "reasoning" not in result


def test_sentence_framing_preserves_correct_conclusion():
    response = _response(answer="The blue square is the moving square; the red square stays still.")
    result = MODULE._validate_case_response(
        response,
        expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
        expected_answer="blue",
    )
    assert result["correct_final_conclusion"] is True


def test_wrong_conclusion_is_rejected():
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_case_response(
            _response(answer="red"),
            expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            expected_answer="blue",
        )


def test_model_substitution_is_rejected():
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_case_response(
            _response(model="substitute"),
            expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            expected_answer="blue",
        )


def test_missing_reasoning_signal_is_rejected():
    response = _response()
    response["choices"][0]["message"]["content"] = "blue"
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_case_response(
            response,
            expected_model="nim_nvidia_cosmos3-nano-reasoner_bf16-final",
            expected_answer="blue",
        )
