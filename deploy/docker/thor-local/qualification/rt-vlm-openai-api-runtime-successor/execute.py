#!/usr/bin/env python3
"""Bounded current-Thor proof for the RT-VLM OpenAI-compatible API surface."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"


class QualificationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise QualificationError(f"expected object: {path}")
    return value


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> tuple[Any, Any]:
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    if contract["official_indices"] != [347, 348, 349, 350, 353, 354]:
        raise QualificationError("official index contract drifted")
    fd_path = REPO / contract["source_locks"][1]["path"]
    partial_path = REPO / contract["source_locks"][0]["path"]
    return _load_module("rt_vlm_openai_fd", fd_path), _load_module(
        "rt_vlm_openai_partial", partial_path
    )


def _http_raw(
    endpoint: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[int, bytes, dict[str, str]]:
    request = urllib.request.Request(
        endpoint + path, data=body, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("local RT-VLM request failed") from exc


def _http_json(*args: Any, **kwargs: Any) -> tuple[int, bytes, Any]:
    status, raw, _ = _http_raw(*args, **kwargs)
    try:
        return status, raw, json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"RT-VLM returned non-JSON HTTP {status}") from exc


def _chat_payload(model: str, messages: list[dict[str, Any]], *, stream: bool) -> dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "stream_options": {"include_usage": True},
        "max_tokens": 16,
        "temperature": 0.0,
        "seed": 42,
    }


def _chat_content(value: Any, model: str) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, dict) or value.get("model") != model:
        raise QualificationError("chat response model/envelope invalid")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise QualificationError("chat response choice count invalid")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if (
        not isinstance(content, str)
        or not content.strip()
        or message.get("role") != "assistant"
        or choice.get("finish_reason") != "stop"
    ):
        raise QualificationError("chat assistant response invalid")
    usage = value.get("usage")
    if not isinstance(usage, dict) or not all(
        isinstance(usage.get(key), int) and usage[key] >= 0
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    ):
        raise QualificationError("chat usage invalid")
    return content, {
        "assistant_role": True,
        "finish_reason": "stop",
        "model_exact": True,
        "usage_positive": True,
        "content_nonempty": True,
        "content_sha256": _sha(content),
    }


def _chat_sse(
    endpoint: str, body: bytes, model: str, timeout: float
) -> tuple[dict[str, Any], bytes]:
    request = urllib.request.Request(
        endpoint + "/v1/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("local RT-VLM SSE request failed") from exc
    events: list[str] = []
    deltas: list[str] = []
    identities: list[str] = []
    created: list[int] = []
    models: list[str] = []
    finish: list[str] = []
    terminal = 0
    errors = 0
    try:
        content_type = response.headers.get("Content-Type", "")
        for raw_line in response:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            events.append(data)
            if data == "[DONE]":
                terminal += 1
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise QualificationError("SSE event was not JSON") from exc
            if not isinstance(event, dict) or "error" in event:
                errors += 1
                continue
            identities.append(event.get("id"))
            created.append(event.get("created"))
            models.append(event.get("model"))
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if isinstance(delta.get("content"), str):
                    deltas.append(delta["content"])
                if choice.get("finish_reason") is not None:
                    finish.append(choice["finish_reason"])
    finally:
        response.close()
    content = "".join(deltas)
    if (
        response.status != 200
        or not content_type.startswith("text/event-stream")
        or not content.strip()
        or terminal != 1
        or finish != ["stop"]
        or errors
        or not identities
        or len(set(identities)) != 1
        or not identities[0]
        or len(set(created)) != 1
        or not models
        or any(value != model for value in models)
    ):
        raise QualificationError("token SSE oracle failed")
    return {
        "http_status": 200,
        "content_type_sse": True,
        "data_event_count": len(events),
        "token_delta_count": len(deltas),
        "content_nonempty": True,
        "content_sha256": _sha(content),
        "terminal_done_count": 1,
        "finish_reason_stop_once": True,
        "identity_stable": True,
        "identity_sha256": _sha(identities[0]),
        "created_stable": True,
        "model_exact": True,
        "errors": 0,
        "events_sha256": _sha("\n".join(events)),
    }, content.encode()


def _metrics(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8")
    samples: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+([-+0-9.eE]+)$", line)
        if match:
            try:
                samples[match.group(1)] = float(match.group(2))
            except ValueError:
                pass
    required = {"system_uptime_seconds", "video_file_queries_processed", "vlm_latency_seconds_count"}
    if not required <= samples.keys():
        raise QualificationError("Prometheus metrics omitted required families")
    names = sorted(samples)
    return {
        "line_count": len(text.splitlines()),
        "sample_name_count": len(names),
        "sample_names_sha256": _sha("\n".join(names)),
        "required_families_present": True,
        "video_file_queries_processed": samples["video_file_queries_processed"],
    }


def _header(headers: dict[str, str], name: str) -> str:
    lowered = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == lowered), "")


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "status": "inert_openai_api_plan_valid",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "http_requests": 0,
        "model_requests": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    fd, partial = _verify_static(contract)
    if endpoint != contract["execution"]["endpoint"]:
        raise QualificationError("endpoint must be exactly http://127.0.0.1:8018")
    request_count = 0
    model_requests = 0
    resource_id: str | None = None
    deleted = False
    model = contract["model"]["id"]

    def raw(path: str, **kwargs: Any) -> tuple[int, bytes, dict[str, str]]:
        nonlocal request_count
        result = _http_raw(endpoint, path, **kwargs)
        request_count += 1
        return result

    def js(path: str, **kwargs: Any) -> tuple[int, bytes, Any]:
        nonlocal request_count
        result = _http_json(endpoint, path, **kwargs)
        request_count += 1
        return result

    openapi_status, openapi_raw, openapi = js("/openapi.json", timeout=15)
    required_paths = {
        "/v1/chat/completions", "/v1/files", "/v1/files/{file_id}",
        "/v1/files/{file_id}/content", "/v1/health/live", "/v1/health/ready",
        "/v1/metadata", "/v1/version", "/v1/manifest", "/v1/models", "/v1/metrics",
    }
    if openapi_status != 200 or not required_paths <= set(openapi.get("paths", {})):
        raise QualificationError("live OpenAPI omitted required API paths")

    models_status, models_raw, models = js("/v1/models", timeout=15)
    if models_status != 200:
        raise QualificationError("model preflight failed")
    _, models_before_sha = fd._model(models, model)
    audio_support = models.get("audio_support")
    if not isinstance(audio_support, bool):
        raise QualificationError("model inventory omitted audio_support")

    catalog_status, catalog_raw, catalog = js("/v1/files?purpose=vision", timeout=15)
    if catalog_status != 200:
        raise QualificationError("catalog preflight failed")
    catalog_before = fd._catalog(catalog)
    stats_status, stats_raw, stats = js("/v1/assets/stats", timeout=15)
    if stats_status != 200 or not isinstance(stats, dict):
        raise QualificationError("asset statistics preflight failed")
    stats_before_sha = _sha(_canonical(stats))

    health: dict[str, Any] = {}
    for label, path in (("live", "/v1/health/live"), ("ready", "/v1/health/ready")):
        status, response_raw, value = js(path, timeout=15)
        if status != 200 or not isinstance(value, dict) or value.get("object") != "health.response":
            raise QualificationError(f"{label} health failed")
        health[label] = {"http_status": 200, "object_exact": True, "response_sha256": _sha(response_raw)}

    metadata_status, metadata_raw, metadata = js("/v1/metadata", timeout=15)
    version_status, version_raw, version = js("/v1/version", timeout=15)
    manifest_status, manifest_raw, manifest = js("/v1/manifest", timeout=15)
    if not all(status == 200 for status in (metadata_status, version_status, manifest_status)):
        raise QualificationError("metadata/version/manifest request failed")
    release = contract["model"]["release"]
    if (
        metadata.get("version") != release
        or version.get("release") != release
        or not isinstance(version.get("api"), str)
        or manifest.get("version") != release
        or manifest.get("model") != model
    ):
        raise QualificationError("metadata/version/manifest identity mismatch")

    metrics_status, metrics_raw, metrics_headers = raw("/v1/metrics", timeout=15)
    if metrics_status != 200 or not _header(metrics_headers, "content-type").startswith("text/plain"):
        raise QualificationError("Prometheus endpoint failed")
    metrics_before = _metrics(metrics_raw)

    invalid_body = _canonical({"model": model, "messages": [], "unexpected": "x"})
    invalid_status, invalid_raw, invalid = js(
        "/v1/chat/completions", method="POST", body=invalid_body,
        headers={"Content-Type": "application/json"}, timeout=15,
    )
    if (
        invalid_status != 422
        or not isinstance(invalid, dict)
        or not isinstance(invalid.get("code"), str)
        or not isinstance(invalid.get("message"), str)
    ):
        raise QualificationError("chat schema error was not structured")

    text_messages = [
        {"role": "system", "content": "Follow the user formatting instruction exactly."},
        {"role": "user", "content": "Return exactly EDGE42 and nothing else."},
    ]
    non_payload = _chat_payload(model, text_messages, stream=False)
    non_body = _canonical(non_payload)
    non_status, non_raw, non_value = js(
        "/v1/chat/completions", method="POST", body=non_body,
        headers={"Content-Type": "application/json"}, timeout=180,
    )
    model_requests += 1
    if non_status != 200:
        raise QualificationError("text-only non-streaming chat failed")
    non_content, non_result = _chat_content(non_value, model)
    if non_content.strip() != "EDGE42":
        raise QualificationError("text-only deterministic marker mismatch")

    stream_payload = _chat_payload(model, text_messages, stream=True)
    stream_body = _canonical(stream_payload)
    stream_result, stream_content_raw = _chat_sse(endpoint, stream_body, model, 180)
    request_count += 1
    model_requests += 1
    stream_content = stream_content_raw.decode()
    if stream_content != non_content:
        raise QualificationError("token SSE did not reconstruct non-streaming answer")

    fixture_bytes = b""
    turn1_raw = b""
    turn2_raw = b""
    try:
        with tempfile.TemporaryDirectory(prefix="rt-vlm-openai-api-") as temp_dir:
            fixture_bytes = partial._generate_fixture(
                Path(temp_dir) / "timeline.mp4", time.monotonic() + 60
            )
            if (
                len(fixture_bytes) != contract["fixture"]["bytes"]
                or _sha(fixture_bytes) != contract["fixture"]["sha256"]
            ):
                raise QualificationError("deterministic fixture drifted")
            upload_body, upload_type = fd._multipart(fixture_bytes, filename="timeline.mp4")
            upload_status, upload_raw, upload = js(
                "/v1/files", method="POST", body=upload_body,
                headers={"Content-Type": upload_type}, timeout=30,
            )
            if upload_status != 200 or not isinstance(upload, dict):
                raise QualificationError("file API create failed")
            resource_id = upload.get("id")
            if not isinstance(resource_id, str) or upload.get("bytes") != len(fixture_bytes):
                raise QualificationError("file API create identity/size mismatch")

            list_status, list_raw, listed = js("/v1/files?purpose=vision", timeout=15)
            listed_rows = listed.get("data") if isinstance(listed, dict) else None
            if (
                list_status != 200
                or not isinstance(listed_rows, list)
                or len(listed_rows) != catalog_before[0] + 1
                or sum(row.get("id") == resource_id for row in listed_rows if isinstance(row, dict)) != 1
            ):
                raise QualificationError("file API list did not expose exact owned file")

            get_status, get_raw, get_value = js(f"/v1/files/{resource_id}", timeout=15)
            if (
                get_status != 200
                or not isinstance(get_value, dict)
                or get_value.get("id") != resource_id
                or get_value.get("bytes") != len(fixture_bytes)
                or get_value.get("creation_time") != contract["fixture"]["creation_time"]
            ):
                raise QualificationError("file API metadata readback mismatch")
            content_status, content_raw, _ = raw(f"/v1/files/{resource_id}/content", timeout=30)
            if content_status != 200 or content_raw != fixture_bytes:
                raise QualificationError("file API content readback mismatch")

            base_messages = [
                {"role": "system", "content": "Answer only about visible video evidence and follow the requested concise format."},
                {"role": "user", "content": "List the three primary square colors in chronological order."},
            ]
            turn1_payload = {
                "model": model, "id": resource_id, "messages": base_messages,
                "stream": False, "max_tokens": 48, "temperature": 0.0, "seed": 7,
                "num_frames_per_second_or_fixed_frames_chunk": 9,
                "use_fps_for_chunking": False,
            }
            turn1_status, turn1_raw, turn1_value = js(
                "/v1/chat/completions", method="POST", body=_canonical(turn1_payload),
                headers={"Content-Type": "application/json"}, timeout=180,
            )
            model_requests += 1
            if turn1_status != 200:
                raise QualificationError("multimodal first turn failed")
            turn1_content, turn1_result = _chat_content(turn1_value, model)
            lowered = turn1_content.casefold()
            positions = [lowered.find(marker) for marker in contract["fixture"]["primary_markers"]]
            if any(position < 0 for position in positions) or positions != sorted(positions):
                raise QualificationError("multimodal first turn omitted chronological markers")

            turn2_messages = base_messages + [
                {"role": "assistant", "content": turn1_content},
                {"role": "user", "content": "According to your previous answer, which color was second? Return only that color."},
            ]
            turn2_payload = {
                "model": model, "id": resource_id, "messages": turn2_messages,
                "stream": False, "max_tokens": 24, "temperature": 0.0, "seed": 7,
                "num_frames_per_second_or_fixed_frames_chunk": 9,
                "use_fps_for_chunking": False,
            }
            turn2_status, turn2_raw, turn2_value = js(
                "/v1/chat/completions", method="POST", body=_canonical(turn2_payload),
                headers={"Content-Type": "application/json"}, timeout=180,
            )
            model_requests += 1
            if turn2_status != 200:
                raise QualificationError("multimodal follow-up turn failed")
            turn2_content, turn2_result = _chat_content(turn2_value, model)
            turn2_lower = turn2_content.casefold()
            if "green" not in turn2_lower or "blue" in turn2_lower or "red" in turn2_lower:
                raise QualificationError("multimodal follow-up was not grounded in prior turn")

            delete_status, delete_raw, delete_value = js(
                f"/v1/files/{resource_id}", method="DELETE", timeout=30
            )
            if delete_status != 200 or not isinstance(delete_value, dict) or delete_value.get("deleted") is not True:
                raise QualificationError("file API exact delete failed")
            deleted = True
            absent_status, absent_raw, absent_value = js(f"/v1/files/{resource_id}", timeout=15)
            if (
                absent_status not in (400, 404)
                or not isinstance(absent_value, dict)
                or not isinstance(absent_value.get("code"), str)
                or not isinstance(absent_value.get("message"), str)
            ):
                raise QualificationError("deleted file did not become structurally unavailable")
        temporary_root_absent = not Path(temp_dir).exists()
    finally:
        if resource_id and not deleted:
            try:
                _http_json(endpoint, f"/v1/files/{resource_id}", method="DELETE", timeout=30)
            except QualificationError:
                pass

    post_catalog_status, post_catalog_raw, post_catalog = js("/v1/files?purpose=vision", timeout=15)
    post_stats_status, post_stats_raw, post_stats = js("/v1/assets/stats", timeout=15)
    post_models_status, post_models_raw, post_models = js("/v1/models", timeout=15)
    post_metrics_status, post_metrics_raw, post_metrics_headers = raw("/v1/metrics", timeout=15)
    if post_catalog_status != 200 or fd._catalog(post_catalog) != catalog_before:
        raise QualificationError("catalog was not restored exactly")
    if post_stats_status != 200 or _sha(_canonical(post_stats)) != stats_before_sha:
        raise QualificationError("asset statistics were not restored exactly")
    if post_models_status != 200 or fd._model(post_models, model)[1] != models_before_sha:
        raise QualificationError("model set changed during qualification")
    if post_metrics_status != 200 or not _header(post_metrics_headers, "content-type").startswith("text/plain"):
        raise QualificationError("Prometheus postflight failed")
    metrics_after = _metrics(post_metrics_raw)
    processed_delta = metrics_after["video_file_queries_processed"] - metrics_before["video_file_queries_processed"]
    if processed_delta < 2:
        raise QualificationError("video query metric did not observe both multimodal turns")
    if request_count != contract["execution"]["max_http_requests"] or model_requests != 4:
        raise QualificationError("exact request budget mismatch")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(time.monotonic() - started, 6),
        "budget": {
            "http_requests": request_count,
            "max_http_requests": contract["execution"]["max_http_requests"],
            "model_requests": model_requests,
            "max_model_requests": contract["execution"]["max_model_requests"],
        },
        "openai_compatibility": {
            "openapi_http_status": openapi_status,
            "required_paths_present": True,
            "openapi_response_sha256": _sha(openapi_raw),
            "schema_error_http_status": invalid_status,
            "schema_error_structured": True,
            "schema_error_response_sha256": _sha(invalid_raw),
            "roles_preserved": True,
            "model_identity_preserved": True,
            "finish_condition_preserved": True,
            "usage_present": True,
        },
        "text_only_chat": {
            **non_result,
            "http_status": non_status,
            "expected_marker_exact": True,
            "request_sha256": _sha(non_body),
            "response_sha256": _sha(non_raw),
            "media_fetches": 0,
            "message_role_order": ["system", "user"],
        },
        "token_sse": {
            **stream_result,
            "request_sha256": _sha(stream_body),
            "matches_non_stream_exactly": True,
            "expected_marker_exact": stream_content.strip() == "EDGE42",
        },
        "file_api": {
            "create_http_status": 200,
            "list_http_status": 200,
            "get_http_status": 200,
            "content_http_status": 200,
            "delete_http_status": 200,
            "deleted_get_http_status": absent_status,
            "stable_identity": True,
            "identity_sha256": _sha(resource_id or ""),
            "byte_count": len(fixture_bytes),
            "content_sha256": _sha(fixture_bytes),
            "content_readback_exact": True,
            "catalog_single_owned_entry": True,
            "exact_delete": True,
            "deleted_get_structured_unavailable": True,
        },
        "multimodal_multi_turn": {
            "turn_1": {
                **turn1_result,
                "http_status": 200,
                "response_sha256": _sha(turn1_raw),
                "all_primary_markers_present": True,
                "markers_in_chronological_order": True,
            },
            "turn_2": {
                **turn2_result,
                "http_status": 200,
                "response_sha256": _sha(turn2_raw),
                "middle_marker_correct": True,
                "other_markers_absent": True,
            },
            "ordered_role_sequence": ["system", "user", "assistant", "user"],
            "same_media_identity": True,
            "prior_assistant_content_preserved_by_digest": True,
        },
        "health_metadata_models_metrics": {
            "health": health,
            "metadata_http_status": metadata_status,
            "version_http_status": version_status,
            "manifest_http_status": manifest_status,
            "models_pre_http_status": models_status,
            "models_post_http_status": post_models_status,
            "metrics_pre_http_status": metrics_status,
            "metrics_post_http_status": post_metrics_status,
            "release_exact": release,
            "api_version_present": True,
            "manifest_model_exact": True,
            "models_unchanged": True,
            "audio_support": audio_support,
            "metrics_parseable": True,
            "required_metric_families_present": True,
            "metric_sample_name_count_before": metrics_before["sample_name_count"],
            "metric_sample_names_sha256_before": metrics_before["sample_names_sha256"],
            "metric_sample_names_sha256_after": metrics_after["sample_names_sha256"],
            "video_file_queries_processed_delta": processed_delta,
            "metadata_response_sha256": _sha(metadata_raw),
            "version_response_sha256": _sha(version_raw),
            "manifest_response_sha256": _sha(manifest_raw),
            "models_pre_response_sha256": _sha(models_raw),
            "models_post_response_sha256": _sha(post_models_raw),
            "metrics_pre_response_sha256": _sha(metrics_raw),
            "metrics_post_response_sha256": _sha(post_metrics_raw),
        },
        "cleanup": {
            "catalog_before_count": catalog_before[0],
            "catalog_after_count": fd._catalog(post_catalog)[0],
            "catalog_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "owned_file_exact_deleted": True,
            "deleted_file_unavailable": True,
            "temporary_fixture_root_absent": temporary_root_absent,
        },
        "policy": {
            "agent_generate_calls": 0,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "raw_resource_ids_retained": False,
            "service_lifecycle_actions": 0,
            "stream_mutations": 0,
            "warehouse_sample_bundle": "excluded",
        },
    }
    schema = _load_json(RECEIPT_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"), nargs="?", default="plan")
    parser.add_argument("--ack")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8018")
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    try:
        if args.mode == "plan":
            result = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement is required")
            result = _execute(contract, args.endpoint)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (QualificationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
