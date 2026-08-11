#!/usr/bin/env python3
"""Qualify RT-VLM file upload and ordered multi-chunk dense captions on Thor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"


class QualificationError(RuntimeError):
    """A bounded qualification assertion failed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError(f"expected JSON object: {path}")
    return value


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load source-locked helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_static(contract: dict[str, Any]) -> tuple[Any, Any]:
    if contract.get("package_id") != "rt-vlm-file-dense-captions-runtime-successor":
        raise QualificationError("package identity drifted")
    if contract.get("capability_ids") != [
        "manifest-entry.rt-vlm-media.00-file-upload",
        "manifest-entry.rt-vlm-media.06-dense-captions",
    ]:
        raise QualificationError("capability identity drifted")
    if contract.get("execution", {}).get("max_http_requests") != 13:
        raise QualificationError("request envelope drifted")
    locked: dict[str, Path] = {}
    for lock in contract["source_locks"]:
        path = REPO / lock["path"]
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != lock["sha256"]:
            raise QualificationError(f"source lock drifted: {lock['path']}")
        locked[lock["path"]] = path
    absolute = _load_module(
        "_dense_absolute_helper",
        locked[
            "deploy/docker/thor-local/qualification/"
            "rt-vlm-absolute-timestamps-runtime-successor/execute.py"
        ],
    )
    partial = _load_module(
        "_dense_fixture_helper",
        locked[
            "deploy/docker/thor-local/qualification/"
            "lvs-partial-offsets-runtime-successor/execute.py"
        ],
    )
    Draft202012Validator.check_schema(_load_json(RECEIPT_SCHEMA_PATH))
    return absolute, partial


def _validate_endpoint(endpoint: str, contract: dict[str, Any]) -> str:
    expected = contract["execution"]["endpoint"]
    parsed = urllib.parse.urlparse(endpoint)
    if (
        endpoint != expected
        or parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 8018
        or parsed.path not in ("", "/")
    ):
        raise QualificationError("endpoint must be exactly http://127.0.0.1:8018")
    return endpoint


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
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QualificationError(f"RT-VLM returned non-JSON HTTP {status}") from exc
    return status, raw, value


def _multipart(media: bytes, *, filename: str) -> tuple[bytes, str]:
    boundary = "----thor-rt-vlm-file-dense-runtime"
    parts: list[bytes] = []
    for name, value in (
        ("purpose", "vision"),
        ("media_type", "video"),
        ("creation_time", "2026-08-11T12:00:00.000Z"),
        ("sensor_name", "thor-file-dense-runtime"),
    ):
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: video/mp4\r\n\r\n",
            media,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _catalog(value: Any) -> tuple[int, str]:
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise QualificationError("file catalog shape invalid")
    return len(value["data"]), _sha(_canonical(value["data"]))


def _model(value: Any, expected: str) -> tuple[str, str]:
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise QualificationError("model list shape invalid")
    ids = [row.get("id") for row in value["data"] if isinstance(row, dict)]
    if expected not in ids:
        raise QualificationError("exact local model is absent")
    return expected, _sha(_canonical(sorted(ids)))


def _caption_payload(resource_id: str, model: str, chunk_duration: int) -> dict[str, Any]:
    return {
        "id": resource_id,
        "model": model,
        "prompt": (
            "For each video chunk, state the visible all-caps phase label and "
            "colored moving square. Be concise."
        ),
        "stream": False,
        "chunk_duration": chunk_duration,
        "num_frames_per_second_or_fixed_frames_chunk": 4,
        "use_fps_for_chunking": False,
        "max_tokens": 128,
        "temperature": 0.0,
        "seed": 1,
    }


def _validate_dense(value: Any, contract: dict[str, Any], expected_model: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("model") != expected_model:
        raise QualificationError("dense response model/envelope invalid")
    chunks = value.get("chunk_responses")
    expected_windows = contract["dense"]["expected_windows"]
    expected_markers = contract["dense"]["expected_primary_markers"]
    if not isinstance(chunks, list) or len(chunks) != 3:
        raise QualificationError("dense mode did not return three chunks")
    marker_matrix: list[dict[str, bool]] = []
    contents: list[str] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict) or chunk.get("chunk_id") != index:
            raise QualificationError("dense chunk ordering invalid")
        if [chunk.get("start_time"), chunk.get("end_time")] != expected_windows[index]:
            raise QualificationError("dense chunk timestamps invalid")
        if chunk.get("frame_count") != contract["dense"]["fixed_frames_per_chunk"]:
            raise QualificationError("dense chunk frame count invalid")
        content = chunk.get("content")
        if not isinstance(content, str) or not content.strip():
            raise QualificationError("dense chunk content empty")
        lowered = content.casefold()
        flags = {color: color in lowered for color in expected_markers}
        if not flags[expected_markers[index]]:
            raise QualificationError("dense chunk omitted its planted phase marker")
        marker_matrix.append(flags)
        contents.append(content)
    usage = value.get("usage")
    if not isinstance(usage, dict) or usage.get("total_chunks_processed") != 3:
        raise QualificationError("dense usage did not correlate to three chunks")
    return {
        "chunk_count": 3,
        "chunk_ids": [0, 1, 2],
        "chunk_windows": expected_windows,
        "frame_counts": [4, 4, 4],
        "primary_phase_markers_present": [True, True, True],
        "marker_matrix": marker_matrix,
        "all_content_nonempty": True,
        "usage_chunks": 3,
        "semantic_response_sha256": _sha("\n".join(contents)),
        "response_model_exact": True,
    }


def _validate_non_dense(value: Any, contract: dict[str, Any], expected_model: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("model") != expected_model:
        raise QualificationError("non-dense control model/envelope invalid")
    chunks = value.get("chunk_responses")
    if not isinstance(chunks, list) or len(chunks) != 1:
        raise QualificationError("non-dense control did not return exactly one chunk")
    chunk = chunks[0]
    if (
        not isinstance(chunk, dict)
        or chunk.get("chunk_id") != 0
        or [chunk.get("start_time"), chunk.get("end_time")]
        != contract["non_dense_control"]["expected_window"]
        or not isinstance(chunk.get("content"), str)
        or not chunk["content"].strip()
    ):
        raise QualificationError("non-dense control metadata invalid")
    usage = value.get("usage")
    if not isinstance(usage, dict) or usage.get("total_chunks_processed") != 1:
        raise QualificationError("non-dense control usage invalid")
    return {
        "chunk_count": 1,
        "chunk_ids": [0],
        "chunk_windows": [contract["non_dense_control"]["expected_window"]],
        "multi_chunk_dense_payload_absent": True,
        "content_nonempty": True,
        "usage_chunks": 1,
        "semantic_response_sha256": _sha(chunk["content"]),
    }


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _verify_static(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "status": "inert_file_dense_plan_valid",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "http_requests": 0,
        "model_requests": 0,
        "writes_or_lifecycle_actions": False,
    }


def _execute(contract: dict[str, Any], endpoint: str) -> dict[str, Any]:
    started = time.monotonic()
    absolute, partial = _verify_static(contract)
    endpoint = _validate_endpoint(endpoint, contract)
    request_count = 0
    model_request_count = 0
    resource_id: str | None = None
    deleted = False

    openapi_status, openapi_raw, openapi = _http_json(endpoint, "/openapi.json", timeout=15)
    request_count += 1
    required_paths = {"/v1/files", "/v1/files/{file_id}/content", "/v1/generate_captions", "/v1/models"}
    if openapi_status != 200 or not isinstance(openapi, dict) or not required_paths <= set(openapi.get("paths", {})):
        raise QualificationError("live OpenAPI omitted required dense-caption paths")

    models_status, models_raw, models = _http_json(endpoint, "/v1/models", timeout=15)
    request_count += 1
    if models_status != 200:
        raise QualificationError("model preflight failed")
    expected_model, models_before_sha = _model(models, contract["model"]["id"])

    catalog_status, catalog_raw, catalog = _http_json(endpoint, "/v1/files?purpose=vision", timeout=15)
    request_count += 1
    if catalog_status != 200:
        raise QualificationError("catalog preflight failed")
    catalog_before_count, catalog_before_sha = _catalog(catalog)

    with tempfile.TemporaryDirectory(prefix="rt-vlm-file-dense-") as temp_dir:
        fixture = partial._generate_fixture(Path(temp_dir) / "dense.mp4", time.monotonic() + 60)
        fixture_sha = _sha(fixture)
        if len(fixture) != contract["fixture"]["bytes"] or fixture_sha != contract["fixture"]["sha256"]:
            raise QualificationError("deterministic fixture drifted")
        invalid = b"not-a-valid-video"
        if _sha(invalid) != contract["fixture"]["invalid_bytes_sha256"]:
            raise QualificationError("invalid fixture drifted")

        invalid_body, invalid_type = _multipart(invalid, filename="corrupt.mp4")
        invalid_status, invalid_raw, invalid_value = _http_json(
            endpoint, "/v1/files", method="POST", body=invalid_body,
            headers={"Content-Type": invalid_type}, timeout=30,
        )
        request_count += 1
        if invalid_status not in (400, 422) or not isinstance(invalid_value, dict):
            raise QualificationError("corrupt upload was not rejected structurally")
        if not isinstance(invalid_value.get("code"), str) or not isinstance(invalid_value.get("message"), str):
            raise QualificationError("corrupt upload error omitted code/message")

        negative_catalog_status, negative_catalog_raw, negative_catalog = _http_json(
            endpoint, "/v1/files?purpose=vision", timeout=15
        )
        request_count += 1
        if negative_catalog_status != 200 or _catalog(negative_catalog) != (catalog_before_count, catalog_before_sha):
            raise QualificationError("corrupt upload allocated a catalog asset")

        try:
            upload_body, upload_type = _multipart(fixture, filename="dense_timeline.mp4")
            upload_status, upload_raw, upload_value = _http_json(
                endpoint, "/v1/files", method="POST", body=upload_body,
                headers={"Content-Type": upload_type}, timeout=30,
            )
            request_count += 1
            if upload_status != 200 or not isinstance(upload_value, dict):
                raise QualificationError("valid file upload failed")
            resource_id = upload_value.get("id")
            if not isinstance(resource_id, str) or not resource_id:
                raise QualificationError("valid upload omitted resource identity")
            if upload_value.get("bytes") != len(fixture):
                raise QualificationError("upload byte count mismatch")

            read_status, read_raw, read_value = _http_json(
                endpoint, f"/v1/files/{resource_id}", timeout=15
            )
            request_count += 1
            if (
                read_status != 200
                or not isinstance(read_value, dict)
                or read_value.get("id") != resource_id
                or read_value.get("bytes") != len(fixture)
                or read_value.get("creation_time") != contract["fixture"]["creation_time"]
            ):
                raise QualificationError("uploaded metadata readback mismatch")

            content_status, content_raw, _ = _http_raw(
                endpoint, f"/v1/files/{resource_id}/content", timeout=30
            )
            request_count += 1
            if content_status != 200 or len(content_raw) != len(fixture) or _sha(content_raw) != fixture_sha:
                raise QualificationError("uploaded file content digest mismatch")

            dense_payload = _caption_payload(resource_id, expected_model, 3)
            dense_status, dense_raw, dense_value = _http_json(
                endpoint, "/v1/generate_captions", method="POST",
                body=_canonical(dense_payload), headers={"Content-Type": "application/json"}, timeout=180,
            )
            request_count += 1
            model_request_count += 1
            if dense_status != 200:
                raise QualificationError("dense-caption request failed")
            dense_result = _validate_dense(dense_value, contract, expected_model)

            control_payload = _caption_payload(resource_id, expected_model, 0)
            control_status, control_raw, control_value = _http_json(
                endpoint, "/v1/generate_captions", method="POST",
                body=_canonical(control_payload), headers={"Content-Type": "application/json"}, timeout=180,
            )
            request_count += 1
            model_request_count += 1
            if control_status != 200:
                raise QualificationError("non-dense control failed")
            control_result = _validate_non_dense(control_value, contract, expected_model)

            delete_status, delete_raw, delete_value = _http_json(
                endpoint, f"/v1/files/{resource_id}", method="DELETE", timeout=30
            )
            request_count += 1
            if delete_status != 200 or not isinstance(delete_value, dict) or delete_value.get("deleted") is not True:
                raise QualificationError("exact owned file deletion failed")
            deleted = True
        finally:
            if resource_id and not deleted:
                try:
                    _http_json(endpoint, f"/v1/files/{resource_id}", method="DELETE", timeout=30)
                except QualificationError:
                    pass
    temp_root_absent = not Path(temp_dir).exists()

    post_catalog_status, post_catalog_raw, post_catalog = _http_json(
        endpoint, "/v1/files?purpose=vision", timeout=15
    )
    request_count += 1
    if post_catalog_status != 200:
        raise QualificationError("catalog postflight failed")
    catalog_after_count, catalog_after_sha = _catalog(post_catalog)
    if (catalog_after_count, catalog_after_sha) != (catalog_before_count, catalog_before_sha):
        raise QualificationError("file catalog was not restored exactly")

    post_models_status, post_models_raw, post_models = _http_json(endpoint, "/v1/models", timeout=15)
    request_count += 1
    if post_models_status != 200:
        raise QualificationError("model postflight failed")
    _, models_after_sha = _model(post_models, expected_model)
    if models_after_sha != models_before_sha:
        raise QualificationError("model set changed during qualification")
    if request_count != 13 or model_request_count != 2:
        raise QualificationError("exact request budget mismatch")
    duration = round(time.monotonic() - started, 6)
    if duration > contract["execution"]["max_duration_seconds"]:
        raise QualificationError("qualification exceeded duration budget")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH.read_bytes()),
        "duration_seconds": duration,
        "budget": {"http_requests": request_count, "max_http_requests": 13, "model_requests": model_request_count, "max_model_requests": 2},
        "runtime": {
            "endpoint_sha256": _sha(endpoint), "openapi_http_status": openapi_status,
            "openapi_response_sha256": _sha(openapi_raw), "required_openapi_paths_present": True,
            "model_id_sha256": _sha(expected_model), "models_before_sha256": models_before_sha,
            "models_after_sha256": models_after_sha, "models_unchanged": True,
            "models_pre_response_sha256": _sha(models_raw), "models_post_response_sha256": _sha(post_models_raw),
        },
        "fixture": {"bytes": len(fixture), "sha256": fixture_sha, "creation_time": contract["fixture"]["creation_time"]},
        "invalid_upload": {
            "http_status": invalid_status, "structured_error": True,
            "request_sha256": _sha(invalid_body), "response_sha256": _sha(invalid_raw),
            "error_code_sha256": _sha(invalid_value["code"]), "error_message_sha256": _sha(invalid_value["message"]),
            "catalog_unchanged": True, "catalog_response_sha256": _sha(negative_catalog_raw),
        },
        "file_upload": {
            "http_status": upload_status, "request_sha256": _sha(upload_body), "response_sha256": _sha(upload_raw),
            "stable_file_identity_returned": True, "resource_id_sha256": _sha(resource_id),
            "metadata_readback_http_status": read_status, "metadata_readback_response_sha256": _sha(read_raw),
            "content_readback_http_status": content_status, "content_bytes": len(content_raw),
            "content_sha256": _sha(content_raw), "content_digest_matches_fixture": True,
        },
        "dense_captions": {
            "http_status": dense_status, "request_sha256": _sha(_canonical(dense_payload)), "response_sha256": _sha(dense_raw),
            **dense_result,
        },
        "non_dense_control": {
            "http_status": control_status, "request_sha256": _sha(_canonical(control_payload)), "response_sha256": _sha(control_raw),
            **control_result,
        },
        "cleanup": {
            "owned_file_exact_deleted": True, "temporary_fixture_root_absent": temp_root_absent,
            "catalog_before_count": catalog_before_count, "catalog_after_count": catalog_after_count,
            "catalog_before_sha256": catalog_before_sha, "catalog_after_sha256": catalog_after_sha,
            "catalog_restored_exactly": True, "delete_response_sha256": _sha(delete_raw),
        },
        "policy": {
            "agent_generate_calls": 0, "stream_mutations": 0, "service_lifecycle_actions": 0,
            "raw_prompt_retained": False, "raw_semantic_output_retained": False,
            "raw_resource_ids_retained": False, "warehouse_sample_bundle": "excluded",
        },
    }
    schema = _load_json(RECEIPT_SCHEMA_PATH)
    errors = list(Draft202012Validator(schema).iter_errors(receipt))
    if errors:
        raise QualificationError("generated receipt failed schema")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode")
    subparsers.add_parser("plan")
    execute = subparsers.add_parser("execute")
    execute.add_argument("--ack", required=True)
    execute.add_argument("--endpoint", default="http://127.0.0.1:8018")
    args = parser.parse_args()
    contract = _load_json(CONTRACT_PATH)
    try:
        if (args.mode or "plan") == "plan":
            receipt = _plan(contract)
        else:
            if args.ack != contract["execution"]["acknowledgement"]:
                raise QualificationError("exact acknowledgement required")
            receipt = _execute(contract, args.endpoint)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(json.dumps({"schema_version": 1, "package_id": contract.get("package_id"), "status": "failed", "failure": str(exc)}, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
