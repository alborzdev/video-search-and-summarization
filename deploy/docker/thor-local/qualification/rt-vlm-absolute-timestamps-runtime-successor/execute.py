#!/usr/bin/env python3
"""Bounded direct RT-VLM absolute-timestamp qualification for Thor.

The default command is inert. Acknowledged execution generates one tiny local
clip, proves source timestamp readback and absolute response metadata, exercises
one malformed-timestamp negative, exact-deletes the owned asset, and restores
the pre-existing catalog. Raw prompts, captions, and identifiers are not emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
        if _sha256_file(path) != lock["sha256"]:
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


def _http(
    endpoint: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[int, bytes, Any]:
    request = urllib.request.Request(
        endpoint + path,
        data=body,
        method=method,
        headers=headers or {},
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
    return status, raw, value


def _json_request(
    endpoint: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout: float,
) -> tuple[int, bytes, Any]:
    return _http(
        endpoint,
        path,
        method="POST",
        body=_canonical_bytes(payload),
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )


def _multipart_upload_body(
    fixture: bytes,
    *,
    creation_time: str,
) -> tuple[bytes, str]:
    boundary = "----thor-absolute-timestamp-runtime"
    parts: list[bytes] = []
    fields = (
        ("purpose", "vision"),
        ("media_type", "video"),
        ("creation_time", creation_time),
        ("sensor_name", "thor-absolute-timestamp-runtime"),
    )
    for name, value in fields:
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
            b'Content-Disposition: form-data; name="file"; filename="absolute_timestamp_fixture.mp4"\r\n',
            b"Content-Type: video/mp4\r\n\r\n",
            fixture,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _make_fixture(path: Path) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=green:s=320x240:r=4:d=8",
        "-vf",
        (
            "drawtext=text=UTC_2026-08-11T12-00-00.000Z:fontcolor=white:"
            "fontsize=18:x=10:y=105:box=1:boxcolor=black@0.7"
        ),
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


def _validate_models(value: Any, expected_model: str) -> str:
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise QualificationError("/v1/models omitted data list")
    ids = [row.get("id") for row in value["data"] if isinstance(row, dict)]
    if expected_model not in ids:
        raise QualificationError("frozen local RT-VLM model is not advertised")
    return _sha256_bytes(_canonical_bytes(sorted(ids)))


def _catalog_fingerprint(value: Any) -> tuple[int, str]:
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise QualificationError("/v1/files omitted data list")
    rows = value["data"]
    return len(rows), _sha256_bytes(_canonical_bytes(rows))


def _request_payload(resource_id: str, model: str, contract: dict[str, Any]) -> dict[str, Any]:
    selection = contract["selection"]
    return {
        "id": resource_id,
        "model": model,
        "prompt": "Describe the visible color and timestamp overlay concisely.",
        "stream": False,
        "chunk_duration": selection["chunk_duration"],
        "media_info": {
            "type": "offset",
            "start_offset": selection["start_offset"],
            "end_offset": selection["end_offset"],
        },
        "num_frames_per_second_or_fixed_frames_chunk": selection[
            "expected_frame_count_per_chunk"
        ],
        "use_fps_for_chunking": False,
        "max_tokens": 128,
        "temperature": 0.0,
        "seed": 1,
    }


def _validate_positive_response(
    value: Any,
    *,
    expected_model: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise QualificationError("caption response was not an object")
    if value.get("model") != expected_model:
        raise QualificationError("caption response substituted the model")
    selection = contract["selection"]
    expected_media = {
        "type": "timestamp",
        "start_timestamp": selection["expected_media_start"],
        "end_timestamp": selection["expected_media_end"],
    }
    if value.get("media_info") != expected_media:
        raise QualificationError("absolute media_info did not match the selected source interval")
    chunks = value.get("chunk_responses")
    if not isinstance(chunks, list) or len(chunks) != len(selection["expected_chunk_windows"]):
        raise QualificationError("caption response returned the wrong chunk count")
    observed_windows: list[list[str]] = []
    metric_fields = (
        "decode_latency_ms",
        "vlm_latency_ms",
        "chunk_latency_ms",
        "queue_time_s",
        "processing_latency_s",
    )
    semantic_parts: list[str] = []
    metric_capture: list[dict[str, float]] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict) or chunk.get("chunk_id") != index:
            raise QualificationError("chunk ordering metadata was invalid")
        window = [chunk.get("start_time"), chunk.get("end_time")]
        observed_windows.append(window)
        if window != selection["expected_chunk_windows"][index]:
            raise QualificationError("chunk absolute timestamps did not align with source frames")
        if chunk.get("frame_count") != selection["expected_frame_count_per_chunk"]:
            raise QualificationError("selected frame count did not match the bounded request")
        content = chunk.get("content")
        if not isinstance(content, str) or not content.strip():
            raise QualificationError("chunk inference content was empty")
        semantic_parts.append(content)
        captured: dict[str, float] = {}
        for field in metric_fields:
            metric = chunk.get(field)
            if not isinstance(metric, (int, float)) or metric < 0:
                raise QualificationError(f"chunk metric was absent or invalid: {field}")
            captured[field] = round(float(metric), 3)
        metric_capture.append(captured)
    return {
        "media_info": expected_media,
        "chunk_count": len(chunks),
        "chunk_windows": observed_windows,
        "frame_counts": [chunk["frame_count"] for chunk in chunks],
        "metrics": metric_capture,
        "all_inference_content_nonempty": True,
        "semantic_response_sha256": _sha256_bytes("\n".join(semantic_parts).encode()),
        "response_model_exact": True,
    }


def _validate_malformed_response(status: int, value: Any) -> dict[str, Any]:
    if status != 422 or not isinstance(value, dict):
        raise QualificationError("malformed absolute timestamp was not rejected as JSON HTTP 422")
    if not isinstance(value.get("code"), str) or not isinstance(value.get("message"), str):
        raise QualificationError("malformed timestamp error omitted code/message")
    return {
        "http_status": status,
        "structured_error": True,
        "error_code_sha256": _sha256_bytes(value["code"].encode()),
        "error_message_sha256": _sha256_bytes(value["message"].encode()),
    }


def _plan(contract: dict[str, Any]) -> dict[str, Any]:
    _validate_source_locks(contract)
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_id": contract["capability_id"],
        "status": "inert_absolute_timestamp_plan_valid",
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
    resource_id: str | None = None
    resource_deleted = False

    pre_model_status, pre_model_raw, pre_models = _http(
        endpoint, "/v1/models", timeout=15
    )
    request_count += 1
    if pre_model_status != 200:
        raise QualificationError("preflight /v1/models was not HTTP 200")
    pre_models_sha = _validate_models(pre_models, expected_model)

    pre_catalog_status, pre_catalog_raw, pre_catalog = _http(
        endpoint, "/v1/files?purpose=vision", timeout=15
    )
    request_count += 1
    if pre_catalog_status != 200:
        raise QualificationError("preflight /v1/files was not HTTP 200")
    pre_catalog_count, pre_catalog_sha = _catalog_fingerprint(pre_catalog)

    temp_root_absent = False
    try:
        with tempfile.TemporaryDirectory(prefix="rt-vlm-absolute-timestamps-") as temp_dir:
            temp_root = Path(temp_dir)
            fixture_path = temp_root / "absolute_timestamp_fixture.mp4"
            _make_fixture(fixture_path)
            fixture = fixture_path.read_bytes()
            if len(fixture) != contract["fixture"]["bytes"]:
                raise QualificationError("deterministic fixture byte count drifted")
            fixture_sha = _sha256_bytes(fixture)
            if fixture_sha != contract["fixture"]["sha256"]:
                raise QualificationError("deterministic fixture digest drifted")

            malformed_body, malformed_type = _multipart_upload_body(
                fixture,
                creation_time=contract["fixture"]["malformed_creation_time"],
            )
            malformed_status, malformed_raw, malformed_value = _http(
                endpoint,
                "/v1/files",
                method="POST",
                body=malformed_body,
                headers={"Content-Type": malformed_type},
                timeout=30,
            )
            request_count += 1
            malformed_assertions = _validate_malformed_response(
                malformed_status, malformed_value
            )

            upload_body, upload_type = _multipart_upload_body(
                fixture,
                creation_time=contract["fixture"]["creation_time"],
            )
            upload_status, upload_raw, upload_value = _http(
                endpoint,
                "/v1/files",
                method="POST",
                body=upload_body,
                headers={"Content-Type": upload_type},
                timeout=30,
            )
            request_count += 1
            if upload_status != 200 or not isinstance(upload_value, dict):
                raise QualificationError("valid timestamp upload was not HTTP 200 JSON")
            resource_id = upload_value.get("id")
            if not isinstance(resource_id, str) or not resource_id:
                raise QualificationError("valid upload omitted its resource identifier")
            if upload_value.get("creation_time") != contract["fixture"]["creation_time"]:
                raise QualificationError("upload response did not preserve creation_time")
            if upload_value.get("bytes") != len(fixture):
                raise QualificationError("upload response byte count drifted")

            read_status, read_raw, read_value = _http(
                endpoint, f"/v1/files/{resource_id}", timeout=15
            )
            request_count += 1
            if read_status != 200 or not isinstance(read_value, dict):
                raise QualificationError("uploaded asset readback failed")
            if read_value.get("creation_time") != contract["fixture"]["creation_time"]:
                raise QualificationError("asset readback did not preserve source timestamp")
            if read_value.get("bytes") != len(fixture):
                raise QualificationError("asset readback byte count drifted")

            payload = _request_payload(resource_id, expected_model, contract)
            response_status, response_raw, response_value = _json_request(
                endpoint,
                "/v1/generate_captions",
                payload,
                timeout=180,
            )
            request_count += 1
            model_request_count += 1
            if response_status != 200:
                raise QualificationError("absolute timestamp inference was not HTTP 200")
            positive = _validate_positive_response(
                response_value,
                expected_model=expected_model,
                contract=contract,
            )

            delete_status, delete_raw, delete_value = _http(
                endpoint,
                f"/v1/files/{resource_id}",
                method="DELETE",
                timeout=30,
            )
            request_count += 1
            if (
                delete_status != 200
                or not isinstance(delete_value, dict)
                or delete_value.get("deleted") is not True
            ):
                raise QualificationError("exact owned-asset deletion failed")
            resource_deleted = True
        temp_root_absent = not temp_root.exists()
    finally:
        if resource_id and not resource_deleted:
            try:
                _http(
                    endpoint,
                    f"/v1/files/{resource_id}",
                    method="DELETE",
                    timeout=30,
                )
            except QualificationError:
                pass

    post_catalog_status, post_catalog_raw, post_catalog = _http(
        endpoint, "/v1/files?purpose=vision", timeout=15
    )
    request_count += 1
    if post_catalog_status != 200:
        raise QualificationError("postflight /v1/files was not HTTP 200")
    post_catalog_count, post_catalog_sha = _catalog_fingerprint(post_catalog)
    if (pre_catalog_count, pre_catalog_sha) != (post_catalog_count, post_catalog_sha):
        raise QualificationError("RT-VLM file catalog was not restored exactly")

    post_model_status, post_model_raw, post_models = _http(
        endpoint, "/v1/models", timeout=15
    )
    request_count += 1
    if post_model_status != 200:
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
            "endpoint_sha256": _sha256_bytes(endpoint.encode()),
            "model_id_sha256": _sha256_bytes(expected_model.encode()),
            "models_before_sha256": pre_models_sha,
            "models_after_sha256": post_models_sha,
            "models_unchanged": True,
            "models_pre_response_sha256": _sha256_bytes(pre_model_raw),
            "models_post_response_sha256": _sha256_bytes(post_model_raw),
        },
        "fixture": {
            "bytes": len(fixture),
            "sha256": fixture_sha,
            "creation_time": contract["fixture"]["creation_time"],
            "timestamp_burned_into_pixels": True,
        },
        "negative": {
            **malformed_assertions,
            "request_sha256": _sha256_bytes(malformed_body),
            "response_sha256": _sha256_bytes(malformed_raw),
            "catalog_resource_created": False,
        },
        "positive": {
            "upload_http_status": upload_status,
            "upload_request_sha256": _sha256_bytes(upload_body),
            "upload_response_sha256": _sha256_bytes(upload_raw),
            "readback_http_status": read_status,
            "readback_response_sha256": _sha256_bytes(read_raw),
            "request_sha256": _sha256_bytes(_canonical_bytes(payload)),
            "response_sha256": _sha256_bytes(response_raw),
            "http_status": response_status,
            **positive,
        },
        "oracle": {
            "source_timestamp_preserved_on_upload_and_readback": True,
            "source_instant_normalized_to_utc": True,
            "bounded_interval_preserved_as_absolute_media_info": True,
            "chunk_metadata_aligned_with_known_frame_times": True,
            "inference_executed": True,
            "malformed_absolute_timestamp_rejected_before_asset_creation": True,
        },
        "cleanup": {
            "owned_asset_exact_deleted": True,
            "temporary_fixture_root_absent": True,
            "catalog_before_count": pre_catalog_count,
            "catalog_after_count": post_catalog_count,
            "catalog_before_sha256": pre_catalog_sha,
            "catalog_after_sha256": post_catalog_sha,
            "catalog_restored_exactly": True,
            "delete_response_sha256": _sha256_bytes(delete_raw),
        },
        "policy": {
            "agent_generate_calls": 0,
            "stream_mutations": 0,
            "service_lifecycle_actions": 0,
            "raw_prompt_retained": False,
            "raw_response_retained": False,
            "raw_resource_ids_retained": False,
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
