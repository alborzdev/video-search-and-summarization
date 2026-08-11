#!/usr/bin/env python3
"""Bounded direct RT-VLM reasoning qualification for Thor.

The default command is an inert source-locked plan.  The acknowledged execute
mode generates two tiny mirrored clips in a temporary directory and sends the
same temporal question to the local RT-VLM endpoint with reasoning enabled.
Only hashes, counts, and semantic booleans are emitted; prompts, response text,
reasoning text, and raw identifiers are never written to the receipt.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[5]
CONTRACT_PATH = PACKAGE_DIR / "contract.json"
RECEIPT_SCHEMA_PATH = PACKAGE_DIR / "receipt.schema.json"


class QualificationError(RuntimeError):
    """A bounded qualification assertion failed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _validate_source_locks(contract: dict[str, Any]) -> None:
    for lock in contract["source_locks"]:
        path = REPO_ROOT / lock["path"]
        if not path.is_file():
            raise QualificationError(f"source lock is missing: {lock['path']}")
        actual = _sha256_file(path)
        if actual != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")


def _validate_endpoint(endpoint: str, contract: dict[str, Any]) -> str:
    expected = contract["execution"]["endpoint"].rstrip("/")
    actual = endpoint.rstrip("/")
    parsed = urllib.parse.urlparse(actual)
    if actual != expected or parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise QualificationError("execution endpoint must be the frozen loopback RT-VLM endpoint")
    if parsed.port != 8018 or parsed.path not in ("", "/"):
        raise QualificationError("execution endpoint must be exactly http://127.0.0.1:8018")
    return actual


def _http_json(
    endpoint: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> tuple[int, bytes, dict[str, Any]]:
    data = None if payload is None else _canonical_bytes(payload)
    request = urllib.request.Request(
        endpoint + path,
        data=data,
        method="GET" if data is None else "POST",
        headers={} if data is None else {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("local RT-VLM request failed") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"RT-VLM returned non-JSON HTTP {status}") from exc
    if not isinstance(value, dict):
        raise QualificationError("RT-VLM response is not a JSON object")
    return status, raw, value


def _make_fixture(path: Path, moving_color: str) -> None:
    if moving_color not in {"blue", "red"}:
        raise QualificationError("unsupported fixture case")
    if moving_color == "blue":
        filter_graph = (
            "drawbox=x=40+60*t:y=120:w=100:h=100:color=blue:t=fill,"
            "drawbox=x=500:y=120:w=100:h=100:color=red:t=fill"
        )
    else:
        filter_graph = (
            "drawbox=x=500:y=120:w=100:h=100:color=blue:t=fill,"
            "drawbox=x=40+60*t:y=120:w=100:h=100:color=red:t=fill"
        )
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=white:s=640x360:r=4:d=6",
        "-vf",
        filter_graph,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(path),
    ]
    try:
        subprocess.run(command, check=True, timeout=60)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("deterministic ffmpeg fixture generation failed") from exc


def _question() -> str:
    return (
        "Compare the beginning and end of this video. Which colored square moves "
        "from the left toward the center while the other square stays still? Answer "
        "with exactly one lowercase color word: blue or red."
    )


def _request(model: str, video: bytes) -> dict[str, Any]:
    video_url = "data:video/mp4;base64," + base64.b64encode(video).decode("ascii")
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _question()},
                    {"type": "video_url", "video_url": {"url": video_url}},
                ],
            }
        ],
        "enable_reasoning": True,
        "chunk_duration": 0,
        "num_frames_per_second_or_fixed_frames_chunk": 12,
        "use_fps_for_chunking": False,
        "temperature": 0.0,
        # Reasoning-capable Cosmos responses can spend more than 512 tokens in
        # the private thinking block even for a tiny clip.  The RT-VLM docs
        # explicitly recommend increasing this cap when reasoning is
        # incomplete; 1024 remains bounded while allowing the final answer.
        "max_tokens": 1024,
        "seed": 1,
    }


def _strip_reasoning(content: str) -> tuple[str, bool]:
    lowered = content.lower()
    has_open = "<think>" in lowered
    has_close = "</think>" in lowered
    if has_open != has_close:
        raise QualificationError("response contained an incomplete reasoning block")
    cleaned = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.I | re.S)
    cleaned = re.sub(r"</?answer>", "", cleaned, flags=re.I).strip().lower()
    cleaned = cleaned.strip(" .\n\t")
    if "<think>" in cleaned or "</think>" in cleaned:
        raise QualificationError("reasoning leaked into the final semantic answer")
    return cleaned, has_open and has_close


def _validate_models(value: dict[str, Any], expected_model: str) -> str:
    data = value.get("data")
    if not isinstance(data, list):
        raise QualificationError("/v1/models omitted data list")
    ids = [row.get("id") for row in data if isinstance(row, dict)]
    if expected_model not in ids:
        raise QualificationError("frozen local reasoning model is not advertised")
    return _sha256_bytes(_canonical_bytes(sorted(ids)))


def _validate_case_response(
    value: dict[str, Any],
    *,
    expected_model: str,
    expected_answer: str,
) -> dict[str, Any]:
    if value.get("model") != expected_model:
        raise QualificationError("RT-VLM response substituted the model")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise QualificationError("RT-VLM response did not contain exactly one choice")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise QualificationError("RT-VLM response omitted assistant content")
    content = message["content"]
    final_answer, tagged_reasoning = _strip_reasoning(content)
    separate_reasoning = message.get("reasoning_description")
    separate_present = isinstance(separate_reasoning, str) and bool(separate_reasoning.strip())
    if not (tagged_reasoning or separate_present):
        raise QualificationError("reasoning-enabled request produced no reasoning signal")
    color_conclusions = re.findall(r"\b(?:blue|red)\b", final_answer)
    if not color_conclusions or color_conclusions[0] != expected_answer:
        raise QualificationError("temporal conclusion was incorrect")
    response_id = value.get("id")
    return {
        "correct_final_conclusion": True,
        "expected_answer_sha256": _sha256_bytes(expected_answer.encode("utf-8")),
        "final_answer_sha256": _sha256_bytes(final_answer.encode("utf-8")),
        "hidden_reasoning_excluded_from_semantic_oracle": True,
        "reasoning_signal_present": True,
        "response_id_sha256": (
            _sha256_bytes(response_id.encode("utf-8"))
            if isinstance(response_id, str) and response_id
            else None
        ),
        "response_model_exact": True,
    }


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _validate_source_locks(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "status": "inert_reasoning_plan_valid",
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "http_requests": 0,
        "model_requests": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    _validate_source_locks(contract)
    endpoint = _validate_endpoint(endpoint, contract)
    expected_model = contract["model"]["id"]
    request_count = 0
    model_request_count = 0

    pre_status, pre_raw, pre_models = _http_json(endpoint, "/v1/models", timeout=15)
    request_count += 1
    if pre_status != 200:
        raise QualificationError("preflight /v1/models was not HTTP 200")
    pre_models_sha = _validate_models(pre_models, expected_model)

    cases: list[dict[str, Any]] = []
    temp_root_absent = False
    with tempfile.TemporaryDirectory(prefix="rt-vlm-reasoning-runtime-") as temp_dir:
        temp_root = Path(temp_dir)
        for case_id, expected_answer, fixture_key in (
            ("target", "blue", "target_sha256"),
            ("adjacent_negative", "red", "adjacent_negative_sha256"),
        ):
            fixture_path = temp_root / f"{case_id}.mp4"
            _make_fixture(fixture_path, expected_answer)
            fixture = fixture_path.read_bytes()
            fixture_sha = _sha256_bytes(fixture)
            if fixture_sha != contract["fixture"][fixture_key]:
                raise QualificationError(f"deterministic fixture digest drifted: {case_id}")
            payload = _request(expected_model, fixture)
            status, raw, value = _http_json(
                endpoint,
                "/v1/chat/completions",
                payload=payload,
                timeout=300,
            )
            request_count += 1
            model_request_count += 1
            if status != 200:
                raise QualificationError(f"reasoning case returned HTTP {status}: {case_id}")
            assertions = _validate_case_response(
                value,
                expected_model=expected_model,
                expected_answer=expected_answer,
            )
            cases.append(
                {
                    "case_id": case_id,
                    "fixture_bytes": len(fixture),
                    "fixture_sha256": fixture_sha,
                    "http_status": status,
                    "request_sha256": _sha256_bytes(_canonical_bytes(payload)),
                    "response_sha256": _sha256_bytes(raw),
                    **assertions,
                }
            )
    temp_root_absent = not temp_root.exists()

    post_status, post_raw, post_models = _http_json(endpoint, "/v1/models", timeout=15)
    request_count += 1
    if post_status != 200:
        raise QualificationError("postflight /v1/models was not HTTP 200")
    post_models_sha = _validate_models(post_models, expected_model)
    if pre_models_sha != post_models_sha:
        raise QualificationError("RT-VLM model set changed during qualification")
    if request_count != contract["execution"]["max_http_requests"]:
        raise QualificationError("HTTP request budget was not exact")
    if model_request_count != contract["execution"]["max_model_requests"]:
        raise QualificationError("model request budget was not exact")
    if not temp_root_absent:
        raise QualificationError("temporary fixture root was not cleaned")

    answers = [case["final_answer_sha256"] for case in cases]
    if len(set(answers)) != 2:
        raise QualificationError("mirrored fixtures did not produce opposite conclusions")
    duration = round(time.monotonic() - started, 6)
    if duration > contract["execution"]["max_duration_seconds"]:
        raise QualificationError("qualification exceeded its duration budget")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "status": "passed",
        "contract_sha256": _sha256_file(CONTRACT_PATH),
        "duration_seconds": duration,
        "budget": {
            "http_requests": request_count,
            "max_http_requests": contract["execution"]["max_http_requests"],
            "model_requests": model_request_count,
            "max_model_requests": contract["execution"]["max_model_requests"],
        },
        "runtime": {
            "endpoint_sha256": _sha256_bytes(endpoint.encode("utf-8")),
            "model_id_sha256": _sha256_bytes(expected_model.encode("utf-8")),
            "models_before_sha256": pre_models_sha,
            "models_after_sha256": post_models_sha,
            "models_unchanged": True,
            "models_pre_response_sha256": _sha256_bytes(pre_raw),
            "models_post_response_sha256": _sha256_bytes(post_raw),
        },
        "cases": cases,
        "oracle": {
            "same_question": True,
            "opposite_correct_conclusions": True,
            "reasoning_enabled_for_all_cases": True,
            "reasoning_signal_present_for_all_cases": True,
            "hidden_reasoning_excluded_from_all_semantic_oracles": True,
        },
        "cleanup": {
            "temporary_fixture_root_absent": True,
            "persistent_resources_created": 0,
            "persistent_resources_deleted": 0,
        },
        "policy": {
            "agent_generate_calls": 0,
            "stream_mutations": 0,
            "service_lifecycle_actions": 0,
            "raw_prompt_retained": False,
            "raw_response_retained": False,
            "reasoning_text_retained": False,
            "raw_response_ids_retained": False,
            "warehouse_sample_bundle": "excluded",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode")
    subparsers.add_parser("plan")
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--ack", required=True)
    execute_parser.add_argument("--endpoint", default="http://127.0.0.1:8018")
    args = parser.parse_args()
    mode = args.mode or "plan"
    contract = _load_json(CONTRACT_PATH)
    try:
        if mode == "plan":
            receipt = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            receipt = _execute(contract, args.endpoint)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "package_id": contract.get("package_id"),
                    "status": "failed",
                    "failure": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
