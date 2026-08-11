#!/usr/bin/env python3
"""Bounded current-Thor proof for RT-VLM HTTP and HTTPS media URLs."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
SERVER_DESTINATION = "/opt/nvidia/rtvi/rtvi/server/rtvi_vlm_server.py"
ASSET_MANAGER_DESTINATION = "/opt/nvidia/rtvi/rtvi/utils/asset_manager.py"


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
    spec = importlib.util.spec_from_file_location("rt_vlm_http_s_fixture", path)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load deterministic fixture helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> Any:
    if contract["official_indices"] != [337]:
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


def _chat_payload(model: str, media_url: str, *, mode: str) -> dict[str, Any]:
    if mode == "timeline":
        prompt = "List the three primary square colors in chronological order."
        fixed_frames = 9
    elif mode == "sintel":
        prompt = (
            "Inspect the clip and return exactly three classifications: "
            "animation=yes/no; woman=yes/no; mountains=yes/no."
        )
        fixed_frames = 8
    else:
        prompt = "Describe visible evidence."
        fixed_frames = 1
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"url": media_url}},
                ],
            }
        ],
        "stream": False,
        "max_tokens": 48,
        "temperature": 0.0,
        "seed": 7,
        "num_frames_per_second_or_fixed_frames_chunk": fixed_frames,
        "use_fps_for_chunking": False,
    }


def _semantic_content(status: int, value: Any, model: str) -> str:
    choices = value.get("choices") if isinstance(value, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and len(choices) == 1 else None
    content = message.get("content") if isinstance(message, dict) else None
    if status != 200 or value.get("model") != model or not isinstance(content, str):
        raise QualificationError("HTTP/S media chat response invalid")
    return content


def _timeline_result(status: int, raw: bytes, value: Any, model: str) -> dict[str, Any]:
    content = _semantic_content(status, value, model)
    lowered = content.casefold()
    positions = [lowered.find(marker) for marker in ("blue", "green", "red")]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise QualificationError("HTTP timeline semantic marker oracle failed")
    return {
        "http_status": 200,
        "model_exact": True,
        "all_primary_markers_present": True,
        "markers_in_chronological_order": True,
        "response_sha256": _sha(raw),
        "semantic_output_sha256": _sha(content),
    }


def _https_result(status: int, raw: bytes, value: Any, model: str) -> dict[str, Any]:
    content = _semantic_content(status, value, model)
    compact = "".join(content.casefold().split())
    required = ("animation=yes",)
    if not all(marker in compact for marker in required):
        raise QualificationError("HTTPS semantic classification oracle failed")
    return {
        "http_status": 200,
        "model_exact": True,
        "animation_classification_positive": True,
        "response_sha256": _sha(raw),
        "semantic_output_sha256": _sha(content),
    }


def _structured_error(status: int, value: Any, code: str) -> dict[str, Any]:
    if (
        status != 422
        or not isinstance(value, dict)
        or value.get("code") != code
        or not isinstance(value.get("message"), str)
    ):
        raise QualificationError(f"expected structured {code} rejection")
    return {"http_status": 422, "structured": True, "code_exact": True}


def _run_container(container: str, args: list[str]) -> bytes:
    try:
        return subprocess.run(
            ["docker", *args, container] if args[0] == "inspect" else ["docker", "exec", container, *args],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise QualificationError("bounded RT-VLM container command failed") from exc


def _runtime_identity(contract: dict[str, Any]) -> tuple[dict[str, Any], int]:
    container = contract["execution"]["container"]
    try:
        raw = subprocess.run(
            ["docker", "inspect", container],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        inspected = json.loads(raw)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
        raise QualificationError("cannot inspect RT-VLM runtime") from exc
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise QualificationError("RT-VLM inspect envelope invalid")
    row = inspected[0]
    state = row.get("State", {})
    network = row.get("NetworkSettings", {}).get("Networks", {}).get(
        contract["http_fixture"]["bridge_network"], {}
    )
    if (
        state.get("Status") != "running"
        or state.get("Health", {}).get("Status") != "healthy"
        or state.get("OOMKilled") is not False
        or row.get("RestartCount") != 0
        or row.get("Image") != contract["model"]["image_id"]
        or network.get("Gateway") != contract["http_fixture"]["bridge_gateway"]
    ):
        raise QualificationError("RT-VLM runtime identity drifted")
    locks = {lock["path"]: lock["sha256"] for lock in contract["source_locks"]}
    server_hash = _run_container(container, ["sha256sum", SERVER_DESTINATION]).decode().split()[0]
    asset_hash = _run_container(container, ["sha256sum", ASSET_MANAGER_DESTINATION]).decode().split()[0]
    if (
        server_hash != locks["services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py"]
        or asset_hash != locks["services/rtvi/rt-vlm/src/utils/asset_manager.py"]
    ):
        raise QualificationError("live RT-VLM source does not match host locks")
    return {
        "container_name_exact": True,
        "image_id_exact": True,
        "healthy": True,
        "restart_count": 0,
        "oom_killed": False,
        "bridge_network_exact": True,
        "bridge_gateway_exact": True,
        "server_source_sha256": server_hash,
        "asset_manager_source_sha256": asset_hash,
        "live_sources_match_locks": True,
    }, 3


def _fetch_https_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        fixture["url"], headers={"User-Agent": "VSS-Thor-Qualification/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(fixture["bytes"] + 1)
            status = response.status
            content_type = response.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise QualificationError("HTTPS fixture verification failed") from exc
    if (
        status != 200
        or len(raw) != fixture["bytes"]
        or _sha(raw) != fixture["sha256"]
        or content_type != fixture["content_type"]
    ):
        raise QualificationError("HTTPS fixture bytes or media type drifted")
    return {
        "host_exact": True,
        "tls_verification_enabled": True,
        "http_status": 200,
        "content_type_exact": True,
        "byte_count": len(raw),
        "content_sha256": _sha(raw),
    }


@contextmanager
def _fixture_server(
    fixture: dict[str, Any], payload: bytes
) -> Iterator[tuple[str, dict[str, int], threading.Thread]]:
    counts = {"timeline": 0, "redirect": 0, "other": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == fixture["path"]:
                counts["timeline"] += 1
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("ETag", f'"{_sha(payload)}"')
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/redirect.mp4":
                counts["redirect"] += 1
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9/blocked.mp4")
                self.end_headers()
            else:
                counts["other"] += 1
                self.send_error(404)

        def log_message(self, *_args: Any) -> None:
            return

    try:
        server = ThreadingHTTPServer(
            (fixture["bridge_gateway"], fixture["port"]), Handler
        )
    except OSError as exc:
        raise QualificationError("fixed qualifier HTTP port is unavailable") from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"http://{fixture['bridge_gateway']}:{fixture['port']}",
            counts,
            thread,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "ready",
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "requires_acknowledgement": contract["execution"]["acknowledgement"],
        "agent_generate_calls": 0,
        "stream_mutations": 0,
        "service_lifecycle_actions": 0,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    helper = _verify_static(contract)
    execution = contract["execution"]
    if endpoint != execution["endpoint"]:
        raise QualificationError("endpoint must be exactly http://127.0.0.1:8018")
    runtime, container_commands = _runtime_identity(contract)
    request_count = 0
    model_requests = 0

    def js(path: str, **kwargs: Any) -> tuple[int, bytes, Any]:
        nonlocal request_count
        result = _http_json(endpoint, path, **kwargs)
        request_count += 1
        return result

    model = contract["model"]["id"]
    model_status, _, models = js("/v1/models", timeout=15)
    catalog_status, _, catalog = js("/v1/files?purpose=vision", timeout=15)
    stats_status, _, stats = js("/v1/assets/stats", timeout=15)
    if model_status != 200 or catalog_status != 200 or stats_status != 200:
        raise QualificationError("RT-VLM preflight failed")
    model_before_sha = _model(models, model)
    catalog_before = _catalog(catalog)
    stats_before_sha = _sha(_canonical(stats))
    https_fixture = _fetch_https_fixture(contract["https_fixture"])

    fixture_bytes = b""
    http_result: dict[str, Any]
    https_result: dict[str, Any]
    negatives: dict[str, Any] = {}
    server_counts: dict[str, int] = {}
    server_stopped = False
    temp_root_absent = False
    with tempfile.TemporaryDirectory(prefix="rt-vlm-http-s-") as temp_dir:
        fixture_path = Path(temp_dir) / "timeline.mp4"
        fixture_bytes = helper._generate_fixture(fixture_path, time.monotonic() + 60)
        if (
            len(fixture_bytes) != contract["http_fixture"]["bytes"]
            or _sha(fixture_bytes) != contract["http_fixture"]["sha256"]
        ):
            raise QualificationError("deterministic HTTP fixture drifted")
        with _fixture_server(contract["http_fixture"], fixture_bytes) as (
            base_url,
            server_counts,
            server_thread,
        ):
            http_body = _canonical(
                _chat_payload(
                    model,
                    base_url + contract["http_fixture"]["path"],
                    mode="timeline",
                )
            )
            status, raw, value = js(
                "/v1/chat/completions", method="POST", body=http_body, timeout=180
            )
            model_requests += 1
            http_result = {
                **_timeline_result(status, raw, value, model),
                "request_sha256": _sha(http_body),
                "transport_plain_http": True,
                "served_from_existing_docker_bridge": True,
                "downloaded_content_sha256": _sha(fixture_bytes),
                "downloaded_byte_count": len(fixture_bytes),
            }

            https_body = _canonical(
                _chat_payload(
                    model, contract["https_fixture"]["url"], mode="sintel"
                )
            )
            status, raw, value = js(
                "/v1/chat/completions", method="POST", body=https_body, timeout=180
            )
            model_requests += 1
            https_result = {
                **_https_result(status, raw, value, model),
                "request_sha256": _sha(https_body),
                "transport_https": True,
                "tls_verification_default": True,
                "fixture_content_sha256": contract["https_fixture"]["sha256"],
                "fixture_byte_count": contract["https_fixture"]["bytes"],
            }

            for label, media_url, code in (
                ("loopback_ssrf", "http://127.0.0.1:9/blocked.mp4", "InvalidParameters"),
                (
                    "redirect_disabled",
                    base_url + "/redirect.mp4",
                    "RedirectNotAllowed",
                ),
            ):
                body = _canonical(_chat_payload(model, media_url, mode="negative"))
                error_status, error_raw, error_value = js(
                    "/v1/chat/completions", method="POST", body=body, timeout=20
                )
                negatives[label] = {
                    **_structured_error(error_status, error_value, code),
                    "request_sha256": _sha(body),
                    "response_sha256": _sha(error_raw),
                    "model_invoked": False,
                }
        server_stopped = not server_thread.is_alive()
    temp_root_absent = not Path(temp_dir).exists()

    post_catalog_status, _, post_catalog = js("/v1/files?purpose=vision", timeout=15)
    post_stats_status, _, post_stats = js("/v1/assets/stats", timeout=15)
    post_model_status, _, post_models = js("/v1/models", timeout=15)
    if post_catalog_status != 200 or _catalog(post_catalog) != catalog_before:
        raise QualificationError("file catalog was not restored exactly")
    if post_stats_status != 200 or _sha(_canonical(post_stats)) != stats_before_sha:
        raise QualificationError("asset statistics were not restored exactly")
    if post_model_status != 200 or _model(post_models, model) != model_before_sha:
        raise QualificationError("model inventory changed during qualification")
    if server_counts != {"timeline": 1, "redirect": 1, "other": 0}:
        raise QualificationError("local fixture server request budget drifted")
    if not server_stopped or not temp_root_absent:
        raise QualificationError("qualifier-owned HTTP resources remain")
    if (
        request_count != execution["max_rt_vlm_http_requests"]
        or model_requests != execution["max_model_requests"]
        or container_commands != execution["max_container_commands"]
    ):
        raise QualificationError("exact request/action budget mismatch")
    duration = time.monotonic() - started
    if not 0 < duration <= execution["max_duration_seconds"]:
        raise QualificationError("runtime duration bound exceeded")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": round(duration, 6),
        "budget": {
            "rt_vlm_http_requests": request_count,
            "max_rt_vlm_http_requests": execution["max_rt_vlm_http_requests"],
            "model_requests": model_requests,
            "max_model_requests": execution["max_model_requests"],
            "external_fixture_verification_fetches": 1,
            "max_external_fixture_verification_fetches": execution[
                "max_external_fixture_fetches"
            ],
            "local_fixture_requests": sum(server_counts.values()),
            "max_local_fixture_requests": execution["max_local_fixture_requests"],
            "container_commands": container_commands,
            "max_container_commands": execution["max_container_commands"],
        },
        "runtime_identity": {
            **runtime,
            "endpoint_loopback_exact": True,
            "model_exact": True,
            "release_exact": contract["model"]["release"],
            "audio_support": False,
        },
        "http_fixture": {
            "duration_seconds": contract["http_fixture"]["duration_seconds"],
            "byte_count": len(fixture_bytes),
            "content_sha256": _sha(fixture_bytes),
            "primary_markers": contract["http_fixture"]["primary_markers"],
        },
        "https_fixture": https_fixture,
        "plain_http": http_result,
        "https": https_result,
        "adjacent_negatives": negatives,
        "cleanup": {
            "catalog_before_count": catalog_before[0],
            "catalog_after_count": _catalog(post_catalog)[0],
            "catalog_restored_exactly": True,
            "asset_statistics_restored_exactly": True,
            "model_inventory_restored_exactly": True,
            "local_fixture_server_stopped": True,
            "temporary_fixture_root_absent": True,
            "owned_assets_absent": True,
        },
        "policy": {
            "agent_generate_calls": 0,
            "raw_prompt_retained": False,
            "raw_semantic_output_retained": False,
            "raw_resource_ids_retained": False,
            "credentials_retained": False,
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
