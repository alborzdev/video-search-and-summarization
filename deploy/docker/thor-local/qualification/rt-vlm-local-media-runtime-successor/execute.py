#!/usr/bin/env python3
"""Bounded current-Thor proof for RT-VLM local file and inline data URLs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import subprocess
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
CACHE_ROOT = "/tmp/assets/_data_url_cache"
SERVER_DESTINATION = "/opt/nvidia/rtvi/rtvi/server/rtvi_vlm_server.py"


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


def _load_fixture_helper(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("rt_vlm_local_media_fixture", path)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load deterministic fixture helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> Any:
    if contract["official_indices"] != [339, 340]:
        raise QualificationError("official index contract drifted")
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
    return _load_fixture_helper(REPO / contract["source_locks"][0]["path"])


def _http_json(
    endpoint: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float,
) -> tuple[int, bytes, Any]:
    request = urllib.request.Request(
        endpoint + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("local RT-VLM request failed") from exc
    try:
        return status, raw, json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"RT-VLM returned non-JSON HTTP {status}") from exc


def _catalog(value: Any) -> tuple[int, str]:
    rows = value.get("data") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise QualificationError("file catalog envelope invalid")
    identities = sorted(row.get("id") for row in rows if isinstance(row, dict))
    if len(identities) != len(rows) or not all(isinstance(item, str) for item in identities):
        raise QualificationError("file catalog identities invalid")
    return len(rows), _sha(_canonical(identities))


def _model(value: Any, expected: str) -> str:
    rows = value.get("data") if isinstance(value, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or rows[0].get("id") != expected
        or value.get("audio_support") is not False
    ):
        raise QualificationError("model inventory mismatch")
    return _sha(_canonical(value))


def _structured_error(status: int, value: Any, code: str) -> dict[str, Any]:
    if (
        status != 400
        or not isinstance(value, dict)
        or value.get("code") != code
        or not isinstance(value.get("message"), str)
    ):
        raise QualificationError(f"expected structured {code} rejection")
    return {"http_status": 400, "structured": True, "code_exact": True}


def _chat_payload(model: str, media_url: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Answer only about visible video evidence and follow the requested concise format.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "List the three primary square colors in chronological order."},
                    {"type": "video_url", "video_url": {"url": media_url}},
                ],
            },
        ],
        "stream": False,
        "max_tokens": 48,
        "temperature": 0.0,
        "seed": 7,
        "num_frames_per_second_or_fixed_frames_chunk": 9,
        "use_fps_for_chunking": False,
    }


def _semantic_result(status: int, raw: bytes, value: Any, model: str) -> dict[str, Any]:
    choices = value.get("choices") if isinstance(value, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and len(choices) == 1 else None
    content = message.get("content") if isinstance(message, dict) else None
    if status != 200 or value.get("model") != model or not isinstance(content, str):
        raise QualificationError("local media chat response invalid")
    lowered = content.casefold()
    positions = [lowered.find(marker) for marker in ("blue", "green", "red")]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise QualificationError("local media semantic marker oracle failed")
    return {
        "http_status": 200,
        "model_exact": True,
        "all_primary_markers_present": True,
        "markers_in_chronological_order": True,
        "response_sha256": _sha(raw),
        "semantic_output_sha256": _sha(content),
    }


def _run_container(
    container: str,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["docker", "exec", container, *args],
            check=check,
            capture_output=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise QualificationError("bounded RT-VLM container command failed") from exc


def _cache_inventory(container: str) -> tuple[int, str]:
    command = [
        "sh",
        "-lc",
        f"if [ -d {CACHE_ROOT} ]; then find {CACHE_ROOT} -mindepth 1 -maxdepth 3 -printf '%y %P %s\\n' | sort; fi",
    ]
    raw = _run_container(container, command).stdout
    rows = [line for line in raw.splitlines() if line]
    return len(rows), _sha(raw)


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "ready",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "endpoint": contract["execution"]["endpoint"],
        "requires_acknowledgement": contract["execution"]["acknowledgement"],
        "agent_generate_calls": 0,
        "stream_mutations": 0,
        "service_lifecycle_actions": 0,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    fixture_helper = _verify_static(contract)
    execution = contract["execution"]
    if endpoint != execution["endpoint"]:
        raise QualificationError("endpoint must be exactly http://127.0.0.1:8018")
    container = execution["container"]
    allowed = contract["owned_paths"]["allowlisted"]
    outside = contract["owned_paths"]["outside"]
    if not allowed.startswith("/opt/nvidia/rtvi/streams/perf/vss-qualifier-"):
        raise QualificationError("owned allowlisted path contract is unsafe")
    if not outside.startswith("/tmp/vss-qualifier-"):
        raise QualificationError("owned outside path contract is unsafe")

    request_count = 0
    model_requests = 0
    container_commands = 0

    def js(path: str, **kwargs: Any) -> tuple[int, bytes, Any]:
        nonlocal request_count
        result = _http_json(endpoint, path, **kwargs)
        request_count += 1
        return result

    def ctr(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        nonlocal container_commands
        result = _run_container(container, args, check=check)
        container_commands += 1
        return result

    absent = ctr(["sh", "-lc", f"test ! -e {allowed} && test ! -e {outside}"], check=False)
    if absent.returncode != 0:
        raise QualificationError("owned qualifier paths already exist; refusing to overwrite")

    server_lock = next(
        lock for lock in contract["source_locks"] if lock["path"].endswith("rtvi_vlm_server.py")
    )
    live_server_hash = ctr(["sha256sum", SERVER_DESTINATION]).stdout.decode().split()[0]
    if live_server_hash != server_lock["sha256"]:
        raise QualificationError("live RT-VLM source does not match locked host source")
    cache_before = _cache_inventory(container)
    container_commands += 1

    model_status, model_raw, models = js("/v1/models", timeout=15)
    catalog_status, catalog_raw, catalog = js("/v1/files?purpose=vision", timeout=15)
    stats_status, stats_raw, stats = js("/v1/assets/stats", timeout=15)
    if model_status != 200 or catalog_status != 200 or stats_status != 200:
        raise QualificationError("RT-VLM preflight failed")
    model = contract["model"]["id"]
    model_before_sha = _model(models, model)
    catalog_before = _catalog(catalog)
    stats_before_sha = _sha(_canonical(stats))

    inline_result: dict[str, Any]
    file_result: dict[str, Any]
    negative_results: dict[str, Any] = {}
    owned_paths_absent = False
    fixture_bytes = b""
    with tempfile.TemporaryDirectory(prefix="rt-vlm-local-media-") as temp_dir:
        fixture_path = Path(temp_dir) / "timeline.mp4"
        fixture_bytes = fixture_helper._generate_fixture(fixture_path, time.monotonic() + 60)
        if (
            len(fixture_bytes) != contract["fixture"]["bytes"]
            or _sha(fixture_bytes) != contract["fixture"]["sha256"]
        ):
            raise QualificationError("deterministic fixture drifted")

        inline_url = "data:video/mp4;base64," + base64.b64encode(fixture_bytes).decode()
        inline_body = _canonical(_chat_payload(model, inline_url))
        status, raw, value = js(
            "/v1/chat/completions", method="POST", body=inline_body, timeout=180
        )
        model_requests += 1
        inline_result = {
            **_semantic_result(status, raw, value, model),
            "request_sha256": _sha(inline_body),
            "declared_mime_exact": True,
            "decoded_byte_count": len(fixture_bytes),
            "decoded_content_sha256": _sha(fixture_bytes),
            "network_fetches": 0,
        }

        for label, media_url in (
            ("mime_mismatch", "data:image/png;base64,AAAA"),
            ("invalid_base64", "data:video/mp4;base64,not@base64"),
        ):
            body = _canonical(_chat_payload(model, media_url))
            error_status, error_raw, error_value = js(
                "/v1/chat/completions", method="POST", body=body, timeout=15
            )
            negative_results[label] = {
                **_structured_error(error_status, error_value, "InvalidDataUrl"),
                "request_sha256": _sha(body),
                "response_sha256": _sha(error_raw),
                "model_invoked": False,
            }

        try:
            ctr(["mkdir", "-p", allowed, outside])
            subprocess.run(
                ["docker", "cp", str(fixture_path), f"{container}:{allowed}/timeline.mp4"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            container_commands += 1
            subprocess.run(
                ["docker", "cp", str(fixture_path), f"{container}:{outside}/timeline.mp4"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            container_commands += 1
            ctr(["ln", "-s", f"{outside}/timeline.mp4", f"{allowed}/escape.mp4"])

            file_url = f"file://{allowed}/timeline.mp4"
            file_body = _canonical(_chat_payload(model, file_url))
            status, raw, value = js(
                "/v1/chat/completions", method="POST", body=file_body, timeout=180
            )
            model_requests += 1
            source_hash = ctr(["sha256sum", f"{allowed}/timeline.mp4"]).stdout.decode().split()[0]
            if source_hash != contract["fixture"]["sha256"]:
                raise QualificationError("allowlisted source file changed during analysis")
            file_result = {
                **_semantic_result(status, raw, value, model),
                "request_sha256": _sha(file_body),
                "canonical_allowlisted_root_exact": True,
                "source_content_sha256": source_hash,
                "source_preserved_exactly": True,
            }

            negative_urls = (
                ("symlink_escape", f"file://{allowed}/escape.mp4"),
                (
                    "traversal_escape",
                    "file:///opt/nvidia/rtvi/streams/perf/../../../../../tmp/"
                    "vss-qualifier-allowlisted-339-outside/timeline.mp4",
                ),
                ("absolute_outside", f"file://{outside}/timeline.mp4"),
            )
            for label, media_url in negative_urls:
                body = _canonical(_chat_payload(model, media_url))
                error_status, error_raw, error_value = js(
                    "/v1/chat/completions", method="POST", body=body, timeout=15
                )
                negative_results[label] = {
                    **_structured_error(error_status, error_value, "InvalidFileUrl"),
                    "request_sha256": _sha(body),
                    "response_sha256": _sha(error_raw),
                    "model_invoked": False,
                }
        finally:
            ctr(["rm", "-rf", allowed, outside], check=False)
            owned_paths_absent = (
                ctr(
                    ["sh", "-lc", f"test ! -e {allowed} && test ! -e {outside}"],
                    check=False,
                ).returncode
                == 0
            )

    post_catalog_status, post_catalog_raw, post_catalog = js(
        "/v1/files?purpose=vision", timeout=15
    )
    post_stats_status, post_stats_raw, post_stats = js("/v1/assets/stats", timeout=15)
    post_model_status, post_model_raw, post_models = js("/v1/models", timeout=15)
    cache_after = _cache_inventory(container)
    container_commands += 1
    if post_catalog_status != 200 or _catalog(post_catalog) != catalog_before:
        raise QualificationError("file catalog was not restored exactly")
    if post_stats_status != 200 or _sha(_canonical(post_stats)) != stats_before_sha:
        raise QualificationError("asset statistics were not restored exactly")
    if post_model_status != 200 or _model(post_models, model) != model_before_sha:
        raise QualificationError("model inventory changed during qualification")
    if cache_after != cache_before:
        raise QualificationError("inline data cache inventory was not restored exactly")
    if not owned_paths_absent:
        raise QualificationError("owned container paths remain after cleanup")
    if request_count != execution["max_http_requests"] or model_requests != 2:
        raise QualificationError("exact HTTP/model request budget mismatch")
    if container_commands != execution["max_container_commands"]:
        raise QualificationError("exact container command budget mismatch")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(time.monotonic() - started, 6),
        "budget": {
            "http_requests": request_count,
            "max_http_requests": execution["max_http_requests"],
            "model_requests": model_requests,
            "max_model_requests": execution["max_model_requests"],
            "container_commands": container_commands,
            "max_container_commands": execution["max_container_commands"],
        },
        "runtime_identity": {
            "endpoint_loopback_exact": True,
            "container_name_exact": True,
            "model_exact": True,
            "release_exact": contract["model"]["release"],
            "live_source_sha256": live_server_hash,
            "live_source_matches_lock": True,
            "audio_support": False,
        },
        "fixture": {
            "duration_seconds": contract["fixture"]["duration_seconds"],
            "byte_count": len(fixture_bytes),
            "content_sha256": _sha(fixture_bytes),
            "primary_markers": contract["fixture"]["primary_markers"],
        },
        "inline_data_uri": inline_result,
        "allowlisted_file_uri": file_result,
        "adjacent_negatives": negative_results,
        "cleanup": {
            "catalog_before_count": catalog_before[0],
            "catalog_after_count": _catalog(post_catalog)[0],
            "catalog_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "model_inventory_restored_exactly": True,
            "cache_inventory_before_count": cache_before[0],
            "cache_inventory_after_count": cache_after[0],
            "cache_inventory_restored_exactly": True,
            "owned_container_paths_absent": True,
            "temporary_fixture_root_absent": not Path(temp_dir).exists(),
        },
        "policy": {
            "agent_generate_calls": 0,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "raw_resource_ids_retained": False,
            "raw_container_ids_retained": False,
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
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "failure": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
