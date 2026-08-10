#!/usr/bin/env python3
"""Qualify current Thor RT-VLM SSE and boundary contracts with one owned clip."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import http.client
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
from uuid import UUID


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
ACK = "I_ACK_RT_VLM_OWNED_FILE_UPLOAD_AND_EXACT_DELETE"


class QualificationError(RuntimeError):
    """The bounded RT-VLM qualification failed closed."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=_reject_duplicates)
    if not isinstance(value, dict):
        raise QualificationError(f"{path} is not a JSON object")
    return value, raw


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label} did not return strict JSON") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{label} did not return a JSON object")
    return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _command(args: list[str], *, timeout: float = 30) -> str:
    completed = subprocess.run(
        args,
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise QualificationError(f"command failed ({args[0]}): {detail[-800:]}")
    return completed.stdout


def _docker_object(kind: str, reference: str) -> dict[str, Any]:
    if kind == "container":
        raw = _command(["docker", "inspect", reference])
    elif kind == "image":
        raw = _command(["docker", "image", "inspect", reference])
    else:
        raise QualificationError("invalid Docker object kind")
    rows = json.loads(raw, object_pairs_hook=_reject_duplicates)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise QualificationError(f"could not inspect exact {kind} {reference}")
    return rows[0]


class LoopbackClient:
    """Small direct HTTP client with hard request, byte, host, and time bounds."""

    def __init__(self, contract: dict[str, Any], started: float) -> None:
        runtime = contract["runtime"]
        if runtime["host"] != "127.0.0.1":
            raise QualificationError("runtime host is not exact loopback")
        self.host = runtime["host"]
        self.port = runtime["host_port"]
        self.maximum_requests = contract["max_http_requests"]
        self.maximum_request_bytes = contract["max_request_bytes"]
        self.maximum_response_bytes = contract["max_response_bytes"]
        self.deadline = started + contract["max_duration_seconds"]
        self.request_count = 0

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: set[int] | None = None,
        timeout: float = 10,
        cleanup: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        if not path.startswith("/") or path.startswith("//"):
            raise QualificationError("HTTP path must be origin-relative")
        if body is not None and len(body) > self.maximum_request_bytes:
            raise QualificationError("HTTP request exceeded the byte bound")
        self.request_count += 1
        if self.request_count > self.maximum_requests:
            raise QualificationError("HTTP request count exceeded the contract")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 and not cleanup:
            raise QualificationError("qualification duration bound expired")
        actual_timeout = timeout if cleanup else min(timeout, max(0.1, remaining))
        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=actual_timeout
        )
        response: http.client.HTTPResponse | None = None
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            raw = response.read(self.maximum_response_bytes + 1)
            if len(raw) > self.maximum_response_bytes:
                raise QualificationError("HTTP response exceeded the byte bound")
            response_headers = {
                key.lower(): value for key, value in response.getheaders()
            }
            if 300 <= response.status < 400:
                raise QualificationError("redirects are forbidden in loopback qualification")
            if expected is not None and response.status not in expected:
                raise QualificationError(
                    f"unexpected HTTP status for {method} {path}: {response.status}"
                )
            return response.status, response_headers, raw
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError(
                f"loopback HTTP transport failed for {method} {path}"
            ) from exc
        finally:
            if response is not None:
                response.close()
            connection.close()

    def json_get(
        self, path: str, *, expected: set[int] = {200}, cleanup: bool = False
    ) -> tuple[int, dict[str, str], dict[str, Any], bytes]:
        status, headers, raw = self.request(
            "GET",
            path,
            headers={"Accept": "application/json"},
            expected=expected,
            cleanup=cleanup,
        )
        return status, headers, _json_object(raw, path), raw

    def json_post(
        self,
        path: str,
        value: dict[str, Any],
        *,
        expected: set[int] | None,
        accept: str = "application/json",
        timeout: float = 10,
    ) -> tuple[int, dict[str, str], bytes]:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return self.request(
            "POST",
            path,
            body=raw,
            headers={
                "Accept": accept,
                "Content-Type": "application/json",
                "Content-Length": str(len(raw)),
            },
            expected=expected,
            timeout=timeout,
        )


def _media_type(headers: dict[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _safe_repo_file(relative: str, expected_sha: str) -> Path:
    if not relative or relative.startswith("/"):
        raise QualificationError("source path must be repository-relative")
    path = (REPO / relative).resolve()
    try:
        path.relative_to(REPO.resolve())
    except ValueError as exc:
        raise QualificationError(f"source path escaped repository: {relative}") from exc
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"source is not a regular file: {relative}")
    if _sha(path.read_bytes()) != expected_sha:
        raise QualificationError(f"source digest drifted: {relative}")
    return path


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("schema_version") != 1
        or contract.get("tool_id") != "thor-rt-vlm-sse-runtime"
        or contract.get("network_scope") != "loopback_only"
        or contract.get("warehouse_sample_bundle") is not False
        or contract.get("target_release") != "VSS 3.2.1"
        or contract.get("target_commit")
        != "ae0fceee78a117a418fb4afb73209156a00a32fc"
        or contract.get("max_semantic_actions") != 8
    ):
        raise QualificationError("qualification contract identity drifted")

    source_hashes: dict[str, str] = {}
    for lock in contract["source_locks"]:
        _safe_repo_file(lock["path"], lock["sha256"])
        source_hashes[lock["path"]] = lock["sha256"]

    protocol_lock = contract["protocol_case"]
    protocol, protocol_raw = _load(REPO / protocol_lock["path"])
    if (
        _sha(protocol_raw) != protocol_lock["file_sha256"]
        or protocol.get("contract_set_sha256")
        != protocol_lock["contract_set_sha256"]
        or protocol.get("target_commit") != contract["target_commit"]
    ):
        raise QualificationError("protocol-case document binding drifted")
    case = next(
        row for row in protocol["cases"] if row["case_id"] == protocol_lock["case_id"]
    )
    if (
        _canonical_sha(case) != protocol_lock["case_sha256"]
        or case.get("capability_id") != "protocol.rt-vlm.sse"
        or case["positive_vector"]["id"] != protocol_lock["positive_vector_id"]
        or [row["id"] for row in case["adjacent_negative_vectors"]]
        != [protocol_lock["negative_vector_id"]]
    ):
        raise QualificationError("RT-VLM protocol case/vector binding drifted")
    positive = case["positive_vector"]
    fixture = contract["fixture"]
    expected_fixture = {
        "id": fixture["asset_id"],
        "prompt": contract["positive"]["prompt"],
        "model": "<loaded-local-model-id>",
        "stream": True,
        "stream_options": {"include_usage": True},
        "chunk_duration": contract["positive"]["chunk_duration"],
        "max_tokens": contract["positive"]["max_tokens"],
    }
    if (
        positive["fixture"] != expected_fixture
        or positive["deadline_seconds"] != contract["positive"]["deadline_seconds"]
        or positive["max_events"] != contract["positive"]["max_events"]
    ):
        raise QualificationError("positive SSE fixture differs from protocol case")

    fixture_path = _safe_repo_file(fixture["path"], fixture["sha256"])
    if fixture_path.stat().st_size != fixture["bytes"]:
        raise QualificationError("video fixture byte length drifted")

    runtime = contract["runtime"]
    cache_root = Path(runtime["model_cache_path"])
    allowed_root = Path("/home/nvidia/vss-official-edge-artifacts/ngc/model-cache")
    if cache_root.parent.resolve() != allowed_root.resolve() or not cache_root.is_dir():
        raise QualificationError("exact local model cache directory is unavailable")
    index_path = cache_root / "model.safetensors.index.json"
    config_path = cache_root / "config.json"
    if (
        _sha(index_path.read_bytes()) != runtime["model_index_sha256"]
        or _sha(config_path.read_bytes()) != runtime["model_config_sha256"]
    ):
        raise QualificationError("local model metadata digest drifted")
    index, _ = _load(index_path)
    weight_map = index.get("weight_map")
    if not isinstance(weight_map, dict):
        raise QualificationError("local model index has no weight map")
    indexed_shards = sorted(set(weight_map.values()))
    if indexed_shards != sorted(runtime["model_shards"]):
        raise QualificationError("local model index shard set drifted")
    for name, size in runtime["model_shards"].items():
        shard = cache_root / name
        if not shard.is_file() or shard.is_symlink() or shard.stat().st_size != size:
            raise QualificationError(f"local model shard identity drifted: {name}")

    compose = (REPO / "deploy/docker/thor-local/official-edge/compose.yml").read_text()
    for literal in (
        "VLM_MODEL_TO_USE: cosmos-reason3",
        "MODEL_PATH: ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final",
    ):
        if literal not in compose:
            raise QualificationError(f"official-edge compose declaration missing: {literal}")

    return {
        "source_hashes": source_hashes,
        "protocol_case_sha256": protocol_lock["case_sha256"],
        "protocol_positive_vector": protocol_lock["positive_vector_id"],
        "protocol_negative_vector": protocol_lock["negative_vector_id"],
        "fixture_sha256": fixture["sha256"],
        "fixture_bytes": fixture["bytes"],
        "model_index_sha256": runtime["model_index_sha256"],
        "model_config_sha256": runtime["model_config_sha256"],
        "model_shards_present": len(runtime["model_shards"]),
        "warehouse_sample_bundle": False,
    }


def _parse_env(rows: Any) -> dict[str, str]:
    if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
        raise QualificationError("container environment is not a string list")
    result: dict[str, str] = {}
    for row in rows:
        name, separator, value = row.partition("=")
        if not separator or name in result:
            raise QualificationError("container environment contains malformed entries")
        result[name] = value
    return result


def _runtime_identity(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = contract["runtime"]
    container = _docker_object("container", runtime["container"])
    image = _docker_object("image", runtime["image"])
    labels = container.get("Config", {}).get("Labels", {})
    state = container.get("State", {})
    port_bindings = container.get("HostConfig", {}).get("PortBindings", {})
    expected_binding = [
        {"HostIp": runtime["host"], "HostPort": str(runtime["host_port"])}
    ]
    if (
        container.get("Image") != runtime["image_id"]
        or container.get("Config", {}).get("Image") != runtime["image"]
        or state.get("Running") is not True
        or state.get("Status") != "running"
        or state.get("Health", {}).get("Status") != "healthy"
        or state.get("OOMKilled") is not False
        or container.get("RestartCount") != 0
        or labels.get("com.docker.compose.project") != runtime["compose_project"]
        or labels.get("com.docker.compose.service") != runtime["compose_service"]
        or port_bindings.get(runtime["container_port"]) != expected_binding
        or image.get("Id") != runtime["image_id"]
        or image.get("Architecture") != runtime["architecture"]
        or runtime["image"] not in image.get("RepoDigests", [])
    ):
        raise QualificationError("RT-VLM container/image/loopback identity drifted")

    env = _parse_env(container.get("Config", {}).get("Env", []))
    expected_env = {
        "VLM_MODEL_TO_USE": runtime["model_selector"],
        "MODEL_PATH": runtime["model_artifact_id"],
        "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME": runtime["served_model_id"],
        "VLM_MAX_GENERATION_TOKENS": str(
            contract["api_contract"]["generation_token_cap"]["default"]
        ),
        "VLM_PROMPT_MAX_LENGTH": str(
            contract["api_contract"]["user_prompt_cap"]["default"]
        ),
    }
    if any(env.get(name) != value for name, value in expected_env.items()):
        raise QualificationError("selected RT-VLM model/limit environment drifted")
    if "VLM_SYSTEM_PROMPT_MAX_LENGTH" in env:
        raise QualificationError("system-prompt default is no longer using its default")

    mounts = container.get("Mounts", [])
    container_hashes: dict[str, str] = {}
    hash_targets = [lock["container_path"] for lock in contract["source_locks"] if lock["container_path"]]
    raw_hashes = _command(
        ["docker", "exec", runtime["container"], "sha256sum", *hash_targets]
    )
    for line in raw_hashes.splitlines():
        digest, separator, path = line.partition("  ")
        if not separator:
            raise QualificationError("container sha256sum output was malformed")
        container_hashes[path] = digest
    for lock in contract["source_locks"]:
        destination = lock["container_path"]
        if destination is None:
            continue
        if container_hashes.get(destination) != lock["sha256"]:
            raise QualificationError(f"running source digest drifted: {destination}")
        if lock["mounted_read_only"]:
            expected_source = str((REPO / lock["path"]).resolve())
            matches = [
                mount
                for mount in mounts
                if mount.get("Destination") == destination
                and mount.get("Source") == expected_source
                and mount.get("RW") is False
            ]
            if len(matches) != 1:
                raise QualificationError(f"read-only source mount drifted: {destination}")
        elif any(mount.get("Destination") == destination for mount in mounts):
            raise QualificationError(f"stock image source unexpectedly mounted: {destination}")

    return {
        "container": runtime["container"],
        "image": runtime["image"],
        "image_id": runtime["image_id"],
        "architecture": runtime["architecture"],
        "running": True,
        "health": "healthy",
        "restart_count": 0,
        "oom_killed": False,
        "compose_project": runtime["compose_project"],
        "compose_service": runtime["compose_service"],
        "loopback_binding": f"127.0.0.1:{runtime['host_port']}->{runtime['container_port']}",
        "model_selector": expected_env["VLM_MODEL_TO_USE"],
        "model_artifact_id": expected_env["MODEL_PATH"],
        "served_model_id": expected_env["VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME"],
        "generation_token_limit": int(expected_env["VLM_MAX_GENERATION_TOKENS"]),
        "user_prompt_limit": int(expected_env["VLM_PROMPT_MAX_LENGTH"]),
        "system_prompt_limit_source": "schema_default",
        "container_source_hashes": container_hashes,
    }


def _readiness(client: LoopbackClient, *, cleanup: bool = False) -> dict[str, Any]:
    _, headers, value, _ = client.json_get(
        "/v1/health/ready", cleanup=cleanup
    )
    if (
        _media_type(headers) != "application/json"
        or value.get("object") != "health.response"
        or value.get("message") != "Service is ready."
    ):
        raise QualificationError("RT-VLM readiness contract drifted")
    return {"http_status": 200, "object": "health.response", "ready": True}


def _openapi_contract(
    client: LoopbackClient, contract: dict[str, Any]
) -> dict[str, Any]:
    _, headers, document, raw = client.json_get("/openapi.json")
    if _media_type(headers) != "application/json":
        raise QualificationError("OpenAPI media type drifted")
    paths = document.get("paths")
    schemas = document.get("components", {}).get("schemas", {})
    api = contract["api_contract"]
    if not isinstance(paths, dict) or not isinstance(schemas, dict):
        raise QualificationError("OpenAPI paths/schemas are unavailable")
    current = paths.get(api["current_path"])
    if (
        not isinstance(current, dict)
        or "post" not in current
        or api["removed_legacy_path"] in paths
    ):
        raise QualificationError("generate-captions route rename contract drifted")
    operation = current["post"]
    if operation.get("security") not in (None, []):
        raise QualificationError("generate-captions unexpectedly declares auth")
    schema = schemas.get("VlmQuery")
    if not isinstance(schema, dict) or schema.get("additionalProperties") is not False:
        raise QualificationError("VlmQuery closed schema contract drifted")
    properties = schema.get("properties", {})
    required = schema.get("required")
    if required != ["id", "prompt", "model"]:
        raise QualificationError("VlmQuery required fields drifted")
    for cap_name in (
        "generation_token_cap",
        "user_prompt_cap",
        "system_prompt_cap",
    ):
        cap = api[cap_name]
        field = properties.get(cap["field"], {})
        limit_key = "maximum" if cap_name == "generation_token_cap" else "maxLength"
        if (
            field.get(limit_key) != cap["default"]
            or field.get("x-env-override") != cap["environment"]
        ):
            raise QualificationError(f"OpenAPI limit drifted: {cap_name}")
    return {
        "document_sha256": _sha(raw),
        "path_count": len(paths),
        "operation_count": sum(
            1
            for path in paths.values()
            if isinstance(path, dict)
            for key in path
            if key.lower()
            in {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
        ),
        "current_path_present": True,
        "current_method_present": "POST",
        "removed_legacy_path_absent": True,
        "authorization_dependency_declared": False,
        "additional_properties_rejected": True,
        "required_fields": required,
        "generation_token_maximum": properties["max_tokens"]["maximum"],
        "generation_token_environment": properties["max_tokens"]["x-env-override"],
        "user_prompt_maximum": properties["prompt"]["maxLength"],
        "user_prompt_environment": properties["prompt"]["x-env-override"],
        "system_prompt_maximum": properties["system_prompt"]["maxLength"],
        "system_prompt_environment": properties["system_prompt"]["x-env-override"],
    }


def _model_contract(
    client: LoopbackClient, contract: dict[str, Any], *, cleanup: bool = False
) -> dict[str, Any]:
    _, headers, value, _ = client.json_get("/v1/models", cleanup=cleanup)
    rows = value.get("data")
    runtime = contract["runtime"]
    if (
        _media_type(headers) != "application/json"
        or value.get("object") != "list"
        or value.get("audio_support") is not False
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("id") != runtime["served_model_id"]
        or rows[0].get("object") != "model"
        or rows[0].get("owned_by") != "custom"
        or rows[0].get("api_type") != "internal"
        or not isinstance(rows[0].get("created"), int)
    ):
        raise QualificationError("exact served RT-VLM model contract drifted")
    return {
        "http_status": 200,
        "model_count": 1,
        "served_model_id": runtime["served_model_id"],
        "model_object": "model",
        "owned_by": "custom",
        "api_type": "internal",
        "audio_support": False,
    }


def _asset_stats(client: LoopbackClient, *, cleanup: bool = False) -> dict[str, Any]:
    _, headers, value, _ = client.json_get("/v1/assets/stats", cleanup=cleanup)
    if _media_type(headers) != "application/json":
        raise QualificationError("asset statistics media type drifted")
    expected_keys = {
        "asset_count",
        "asset_count_with_storage",
        "aged_out_count",
        "oldest_asset_age_hours",
        "max_storage_usage_gb",
        "max_asset_age_hours",
    }
    if set(value) != expected_keys:
        raise QualificationError("asset statistics fields drifted")
    if any(
        not isinstance(value[key], int)
        for key in ("asset_count", "asset_count_with_storage", "aged_out_count")
    ):
        raise QualificationError("asset statistics counters are not integers")
    return value


def _assert_absent(
    client: LoopbackClient,
    asset_id: str,
    contract: dict[str, Any],
    *,
    cleanup: bool = False,
) -> dict[str, Any]:
    status, headers, raw = client.request(
        "GET",
        f"/v1/files/{asset_id}",
        headers={"Accept": "application/json"},
        expected={contract["boundary_oracles"]["absent_asset_http_status"]},
        cleanup=cleanup,
    )
    value = _json_object(raw, "asset absence")
    if _media_type(headers) != "application/json" or value.get("code") != "BadParameter":
        raise QualificationError("exact asset absence response drifted")
    return {"http_status": status, "error_code": "BadParameter", "absent": True}


def _multipart(contract: dict[str, Any]) -> tuple[bytes, str]:
    fixture = contract["fixture"]
    media = (REPO / fixture["path"]).read_bytes()
    if len(media) != fixture["bytes"] or _sha(media) != fixture["sha256"]:
        raise QualificationError("fixture drifted before multipart creation")
    boundary = "vss-rt-vlm-sse-runtime"
    fields = {
        "purpose": "vision",
        "media_type": "video",
        "id": fixture["asset_id"],
        "sensor_name": fixture["sensor_name"],
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fixture["filename"]}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
    )
    chunks.extend((media, b"\r\n", f"--{boundary}--\r\n".encode()))
    body = b"".join(chunks)
    if len(body) > contract["max_request_bytes"]:
        raise QualificationError("multipart request exceeds contract")
    return body, f"multipart/form-data; boundary={boundary}"


def _upload(client: LoopbackClient, contract: dict[str, Any]) -> dict[str, Any]:
    body, content_type = _multipart(contract)
    status, headers, raw = client.request(
        "POST",
        "/v1/files",
        body=body,
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        },
        expected={200},
        timeout=30,
    )
    value = _json_object(raw, "file upload")
    fixture = contract["fixture"]
    if (
        _media_type(headers) != "application/json"
        or value.get("id") != fixture["asset_id"]
        or value.get("bytes") != fixture["bytes"]
        or value.get("filename") != fixture["filename"]
        or value.get("purpose") != "vision"
        or value.get("media_type") != "video"
        or value.get("sensor_name") != fixture["sensor_name"]
    ):
        raise QualificationError("owned file upload response drifted")
    _, read_headers, readback, _ = client.json_get(
        f"/v1/files/{fixture['asset_id']}"
    )
    if (
        _media_type(read_headers) != "application/json"
        or readback.get("id") != fixture["asset_id"]
        or readback.get("bytes") != fixture["bytes"]
        or readback.get("filename") != fixture["filename"]
        or readback.get("purpose") != "vision"
        or readback.get("sensor_name") != fixture["sensor_name"]
    ):
        raise QualificationError("owned file readback drifted")
    stats = _asset_stats(client)
    if (
        stats["asset_count"] != 1
        or stats["asset_count_with_storage"] != 1
        or stats["aged_out_count"] != 0
    ):
        raise QualificationError("owned upload did not create exactly one stored asset")
    return {
        "http_status": status,
        "owned_asset_id_match": True,
        "fixture_sha256": fixture["sha256"],
        "bytes": fixture["bytes"],
        "filename": fixture["filename"],
        "purpose": "vision",
        "media_type": "video",
        "sensor_name": fixture["sensor_name"],
        "readback_exact": True,
        "asset_count_after_upload": 1,
        "asset_count_with_storage_after_upload": 1,
    }


def _boundary_requests(
    client: LoopbackClient, contract: dict[str, Any]
) -> dict[str, Any]:
    runtime = contract["runtime"]
    fixture = contract["fixture"]
    api = contract["api_contract"]
    base = {
        "id": fixture["absent_boundary_asset_id"],
        "prompt": "ok",
        "model": runtime["served_model_id"],
        "stream": True,
        "max_tokens": contract["positive"]["max_tokens"],
    }
    generation_limit = api["generation_token_cap"]["default"]
    user_limit = api["user_prompt_cap"]["default"]
    system_limit = api["system_prompt_cap"]["default"]
    cases = [
        ("blank_prompt", {**base, "prompt": " "}, "rejected"),
        ("generation_at_limit", {**base, "max_tokens": generation_limit}, "accepted"),
        ("generation_above_limit", {**base, "max_tokens": generation_limit + 1}, "rejected"),
        ("user_prompt_at_limit", {**base, "prompt": "a" * user_limit}, "accepted"),
        ("user_prompt_above_limit", {**base, "prompt": "a" * (user_limit + 1)}, "rejected"),
        ("system_prompt_at_limit", {**base, "system_prompt": "b" * system_limit}, "accepted"),
        ("system_prompt_above_limit", {**base, "system_prompt": "b" * (system_limit + 1)}, "rejected"),
    ]
    results: dict[str, Any] = {}
    for name, payload, outcome in cases:
        expected_status = (
            contract["boundary_oracles"]["at_limit_http_status"]
            if outcome == "accepted"
            else contract["boundary_oracles"]["above_limit_http_status"]
        )
        if name == "blank_prompt":
            expected_status = contract["boundary_oracles"]["blank_prompt_http_status"]
        status, headers, raw = client.json_post(
            contract["api_contract"]["current_path"],
            payload,
            expected={expected_status},
        )
        value = _json_object(raw, name)
        expected_code = "BadParameter" if outcome == "accepted" else "InvalidParameters"
        if (
            _media_type(headers) != "application/json"
            or value.get("code") != expected_code
            or not isinstance(value.get("message"), str)
            or not value["message"]
        ):
            raise QualificationError(f"boundary response semantics drifted: {name}")
        results[name] = {
            "http_status": status,
            "schema_outcome": outcome,
            "error_code": expected_code,
            "response_sha256": _sha(raw),
            "response_bytes": len(raw),
        }
    return results


def _parse_sse(
    raw: bytes, contract: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    if "text/event-stream" not in headers.get("content-type", "").lower():
        raise QualificationError("positive caption response was not SSE")
    text = raw.decode("utf-8")
    frames = re.split(r"\r?\n\r?\n", text)
    events: list[str] = []
    ping_comments = 0
    for frame in frames:
        if not frame.strip():
            continue
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line.startswith(":"):
                ping_comments += 1
            elif line.strip():
                raise QualificationError("SSE frame used a non-data application field")
        if data_lines:
            events.append("\n".join(data_lines))
    if len(events) > contract["positive"]["max_events"]:
        raise QualificationError("SSE event count exceeded the vector bound")
    if not events or events[-1] != "[DONE]" or events.count("[DONE]") != 1:
        raise QualificationError("SSE terminal [DONE] contract drifted")

    served_model = contract["runtime"]["served_model_id"]
    shared_request_id: str | None = None
    shared_created: int | None = None
    last_chunk_id = -1
    caption_event_count = 0
    caption_chunks: list[dict[str, Any]] = []
    usage_event_count = 0
    usage_seen = False
    usage_numbers: dict[str, int | float] = {}
    for index, event in enumerate(events[:-1]):
        value = _json_object(event.encode(), f"SSE event {index}")
        request_id = value.get("id")
        try:
            UUID(str(request_id))
        except (ValueError, TypeError) as exc:
            raise QualificationError("SSE request id was not a UUID") from exc
        if shared_request_id is None:
            shared_request_id = str(request_id)
        if str(request_id) != shared_request_id:
            raise QualificationError("SSE request id changed between events")
        if value.get("model") != served_model:
            raise QualificationError("SSE model identity drifted")
        created = value.get("created")
        if not isinstance(created, int):
            raise QualificationError("SSE created timestamp was not an integer")
        if shared_created is None:
            shared_created = created
        if created != shared_created:
            raise QualificationError("SSE created timestamp changed between events")

        usage = value.get("usage")
        chunks = value.get("chunk_responses") or []
        if not isinstance(chunks, list):
            raise QualificationError("SSE chunk_responses was not an array")
        if usage is not None:
            if not isinstance(usage, dict) or usage_event_count:
                raise QualificationError("SSE usage event contract drifted")
            usage_event_count += 1
            usage_seen = True
            for key, item in usage.items():
                if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0:
                    raise QualificationError("SSE usage values were not non-negative numbers")
                usage_numbers[key] = item
        if chunks:
            if usage_seen:
                raise QualificationError("SSE caption chunk followed usage")
            caption_event_count += 1
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise QualificationError("SSE caption chunk was not an object")
            chunk_id = chunk.get("chunk_id")
            content = chunk.get("content")
            start_time = chunk.get("start_time")
            end_time = chunk.get("end_time")
            if (
                not isinstance(chunk_id, int)
                or not 0 <= chunk_id <= 100000
                or chunk_id < last_chunk_id
                or not isinstance(start_time, str)
                or not start_time
                or not isinstance(end_time, str)
                or not end_time
                or not isinstance(content, str)
                or len(content) > 100000
            ):
                raise QualificationError("SSE caption chunk schema/order drifted")
            last_chunk_id = chunk_id
            caption_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "content_characters": len(content),
                    "content_nonblank": bool(content.strip()),
                    "content_sha256": _sha(content.encode()),
                }
            )
    if (
        not caption_chunks
        or not any(chunk["content_nonblank"] for chunk in caption_chunks)
        or caption_event_count < 1
        or usage_event_count != 1
    ):
        raise QualificationError("SSE did not return captions plus exactly one usage event")
    header_request_id = headers.get("x-request-id")
    if header_request_id is not None and header_request_id != shared_request_id:
        raise QualificationError("SSE response header request id differed from events")
    return {
        "http_status": 200,
        "content_type": "text/event-stream",
        "positive_vector_id": contract["protocol_case"]["positive_vector_id"],
        "data_event_count": len(events),
        "caption_event_count": caption_event_count,
        "caption_chunk_count": len(caption_chunks),
        "caption_chunks": caption_chunks,
        "usage_event_count": usage_event_count,
        "usage_numbers": usage_numbers,
        "terminal_event": "[DONE]",
        "terminal_event_last": True,
        "request_id_well_formed": True,
        "request_identity_stable": True,
        "response_header_identity_match": header_request_id is not None,
        "model_identity_stable": True,
        "created_timestamp_stable": True,
        "chunk_ids_nondecreasing": True,
        "usage_after_captions": True,
        "ping_comment_count": ping_comments,
    }


def _positive_sse(client: LoopbackClient, contract: dict[str, Any]) -> dict[str, Any]:
    positive = contract["positive"]
    payload = {
        "id": contract["fixture"]["asset_id"],
        "prompt": positive["prompt"],
        "model": contract["runtime"]["served_model_id"],
        "stream": True,
        "stream_options": {"include_usage": positive["include_usage"]},
        "chunk_duration": positive["chunk_duration"],
        "max_tokens": positive["max_tokens"],
    }
    status, headers, raw = client.json_post(
        contract["api_contract"]["current_path"],
        payload,
        expected={200},
        accept="text/event-stream",
        timeout=positive["deadline_seconds"],
    )
    if status != 200:
        raise QualificationError("positive SSE request did not return HTTP 200")
    return _parse_sse(raw, contract, headers)


def _cleanup_asset(
    client: LoopbackClient,
    contract: dict[str, Any],
    *,
    creation_intended: bool,
    pre_stats: dict[str, Any] | None,
    runtime_before: dict[str, Any] | None,
) -> dict[str, Any]:
    fixture = contract["fixture"]
    failures: list[str] = []
    delete_status: int | None = None
    if creation_intended:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                status, headers, raw = client.request(
                    "DELETE",
                    f"/v1/files/{fixture['asset_id']}",
                    headers={"Accept": "application/json"},
                    expected=None,
                    timeout=5,
                    cleanup=True,
                )
                delete_status = status
                if status == 200:
                    value = _json_object(raw, "owned asset delete")
                    if (
                        _media_type(headers) != "application/json"
                        or value.get("id") != fixture["asset_id"]
                        or value.get("object") != "file"
                        or value.get("deleted") is not True
                    ):
                        failures.append("owned_asset_delete_response_drifted")
                    break
                if status in {400, 404}:
                    break
                if status != 409:
                    failures.append(f"owned_asset_delete_http_{status}")
                    break
            except QualificationError:
                failures.append("owned_asset_delete_transport_failed")
                break
            time.sleep(0.5)
        else:
            failures.append("owned_asset_delete_timed_out")

    absence: dict[str, Any] | None = None
    stats_after: dict[str, Any] | None = None
    ready_after: dict[str, Any] | None = None
    model_after: dict[str, Any] | None = None
    runtime_after: dict[str, Any] | None = None
    try:
        absence = _assert_absent(
            client, fixture["asset_id"], contract, cleanup=True
        )
    except QualificationError:
        failures.append("owned_asset_not_absent")
    try:
        stats_after = _asset_stats(client, cleanup=True)
        if pre_stats is None or stats_after != pre_stats:
            failures.append("asset_statistics_not_restored")
    except QualificationError:
        failures.append("asset_statistics_probe_failed")
    try:
        ready_after = _readiness(client, cleanup=True)
    except QualificationError:
        failures.append("readiness_not_restored")
    try:
        model_after = _model_contract(client, contract, cleanup=True)
    except QualificationError:
        failures.append("model_identity_not_restored")
    try:
        runtime_after = _runtime_identity(contract)
        if runtime_before is None or runtime_after != runtime_before:
            failures.append("container_runtime_identity_not_restored")
    except QualificationError:
        failures.append("container_runtime_identity_probe_failed")
    return {
        "attempted": creation_intended,
        "delete_http_status": delete_status,
        "owned_asset_absent": absence is not None,
        "asset_statistics_exact": stats_after == pre_stats if stats_after is not None else False,
        "asset_count_after": stats_after.get("asset_count") if stats_after else None,
        "asset_count_with_storage_after": stats_after.get("asset_count_with_storage") if stats_after else None,
        "readiness_after": ready_after.get("ready") if ready_after else False,
        "model_identity_after": model_after == _model_contract_record(contract) if model_after else False,
        "container_identity_exact": runtime_after == runtime_before if runtime_after else False,
        "failures": failures,
    }


def _model_contract_record(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "http_status": 200,
        "model_count": 1,
        "served_model_id": contract["runtime"]["served_model_id"],
        "model_object": "model",
        "owned_by": "custom",
        "api_type": "internal",
        "audio_support": False,
    }


def execute() -> dict[str, Any]:
    started = time.monotonic()
    captured = _utc_now()
    contract, contract_raw = _load(CONTRACT_PATH)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "tool_id": contract.get("tool_id"),
        "status": "failed",
        "failure": None,
        "blockers": [],
        "captured_at": captured,
        "contract_sha256": _sha(contract_raw),
        "target_release": contract.get("target_release"),
        "target_commit": contract.get("target_commit"),
        "capability_ids": contract.get("capability_ids"),
        "network_scope": contract.get("network_scope"),
        "warehouse_sample_bundle": False,
        "semantic_action_count": 0,
        "forbidden_actions_observed": [],
        "writes_or_lifecycle_actions": False,
    }
    client: LoopbackClient | None = None
    creation_intended = False
    pre_stats: dict[str, Any] | None = None
    runtime_before: dict[str, Any] | None = None
    try:
        receipt["static_contract"] = _verify_static(contract)
        runtime_before = _runtime_identity(contract)
        receipt["runtime_identity"] = runtime_before
        client = LoopbackClient(contract, started)
        receipt["readiness"] = _readiness(client)
        receipt["api_contract"] = _openapi_contract(client, contract)
        receipt["model_contract"] = _model_contract(client, contract)
        pre_stats = _asset_stats(client)
        fixture = contract["fixture"]
        owned_absence = _assert_absent(client, fixture["asset_id"], contract)
        boundary_absence = _assert_absent(
            client, fixture["absent_boundary_asset_id"], contract
        )
        blockers: list[str] = []
        if (
            pre_stats["asset_count"] != 0
            or pre_stats["asset_count_with_storage"] != 0
            or pre_stats["aged_out_count"] != 0
        ):
            blockers.append("RT-VLM asset store was not empty at pre-state")
        if blockers:
            receipt["blockers"] = blockers
            receipt["failure"] = "precondition_failed"
            return receipt
        receipt["pre_state"] = {
            "asset_statistics": pre_stats,
            "owned_asset": owned_absence,
            "boundary_asset": boundary_absence,
            "container_healthy": True,
            "container_restart_count": 0,
            "container_oom_killed": False,
        }

        creation_intended = True
        receipt["writes_or_lifecycle_actions"] = True
        receipt["owned_upload"] = _upload(client, contract)
        receipt["boundaries"] = _boundary_requests(client, contract)
        receipt["semantic_action_count"] = 7
        receipt["sse"] = _positive_sse(client, contract)
        receipt["semantic_action_count"] = 8
        receipt["endpoint_rename"] = {
            "current_path_discovered": True,
            "current_path_called": True,
            "current_http_status": 200,
            "removed_legacy_path_absent": True,
        }
    except (
        QualificationError,
        OSError,
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        receipt["failure"] = type(exc).__name__
        print(f"[rt-vlm-sse] {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if client is not None:
            try:
                cleanup = _cleanup_asset(
                    client,
                    contract,
                    creation_intended=creation_intended,
                    pre_stats=pre_stats,
                    runtime_before=runtime_before,
                )
            except Exception as exc:  # cleanup must always yield a retained result
                cleanup = {
                    "attempted": creation_intended,
                    "failures": [f"cleanup_collector_failed:{type(exc).__name__}"],
                }
            receipt["cleanup"] = cleanup
            receipt["http_request_count"] = client.request_count
            if cleanup["failures"] and receipt["failure"] is None:
                receipt["failure"] = "cleanup_failed"
        else:
            receipt["cleanup"] = {
                "attempted": False,
                "failures": ["HTTP client was not initialized"],
            }
            receipt["http_request_count"] = 0
        duration = time.monotonic() - started
        receipt["duration_seconds"] = round(duration, 3)
        if duration > contract.get("max_duration_seconds", 0) and receipt["failure"] is None:
            receipt["failure"] = "duration_bound_exceeded"
        if (
            receipt["failure"] is None
            and receipt["blockers"] == []
            and receipt["semantic_action_count"] == contract["max_semantic_actions"]
            and receipt["http_request_count"] <= contract["max_http_requests"]
            and receipt["cleanup"]["failures"] == []
        ):
            receipt["status"] = "passed"
    return receipt


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "inert_plan",
        "network_scope": contract["network_scope"],
        "warehouse_sample_bundle": contract["warehouse_sample_bundle"],
        "semantic_actions": [
            "blank-prompt rejection",
            "generation-token at-limit acceptance",
            "generation-token above-limit rejection",
            "user-prompt at-limit acceptance",
            "user-prompt above-limit rejection",
            "system-prompt at-limit acceptance",
            "system-prompt above-limit rejection",
            "one caption SSE through usage and terminal [DONE]",
        ],
        "mutation": "upload and exact-delete one fixed qualifier-owned file UUID",
        "forbidden_actions": contract["forbidden_actions"],
        "execute_acknowledgement": ACK,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan", help="print the inert bounded plan")
    execute_parser = subparsers.add_parser("execute", help="run the acknowledged qualifier")
    execute_parser.add_argument("--ack", required=True)
    execute_parser.add_argument("--write", action="store_true", required=True)
    args = parser.parse_args(argv)
    contract, _ = _load(CONTRACT_PATH)
    if args.command in (None, "plan"):
        print(json.dumps(_plan(contract), indent=2, sort_keys=True))
        return 0
    if args.ack != ACK:
        print("FAIL: exact lifecycle acknowledgement is required", file=sys.stderr)
        return 2
    if RECEIPT_PATH.exists():
        print(f"FAIL: refusing to overwrite {RECEIPT_PATH}", file=sys.stderr)
        return 2
    receipt = execute()
    RECEIPT_PATH.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
