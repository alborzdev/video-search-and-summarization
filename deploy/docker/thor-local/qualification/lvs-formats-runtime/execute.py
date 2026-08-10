#!/usr/bin/env python3
"""Qualify all five VSS LVS file formats with bounded local inference."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
from typing import Any
from uuid import UUID


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
ACK = "I_ACK_LVS_FIVE_FORMAT_SUMMARIZATION_AND_EXACT_CLEANUP"
MAX_STATIC_BYTES = 128 * 1024 * 1024
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class QualificationError(RuntimeError):
    """Stable fail-closed error code for the qualification boundary."""

    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "evidence_already_retained",
        "invalid_response",
        "oracle_failed",
        "runtime_unavailable",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise QualificationError("configuration_error")
        value[key] = item
    return value


def _decode_json(
    raw: bytes, *, code: str = "invalid_response", object_only: bool = True
) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                QualificationError(code)
            ),
        )
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(code) from exc
    if object_only and not isinstance(value, dict):
        raise QualificationError(code)
    return value


def _read_regular(path: Path, maximum: int = MAX_STATIC_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise QualificationError("configuration_error")
        pieces: list[bytes] = []
        total = 0
        while total <= maximum:
            piece = os.read(descriptor, min(131072, maximum + 1 - total))
            if not piece:
                break
            pieces.append(piece)
            total += len(piece)
        raw = b"".join(pieces)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in stable
        ):
            raise QualificationError("configuration_error")
        return raw
    finally:
        os.close(descriptor)


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path)
    value = _decode_json(raw, code="configuration_error")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationError("invalid_response") from exc


def _canonical_sha(value: Any) -> str:
    return _sha(_canonical(value))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_repo_file(relative: str, expected_sha: str, expected_bytes: int) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise QualificationError("configuration_error")
    current = REPO
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise QualificationError("configuration_error")
        except QualificationError:
            raise
        except OSError as exc:
            raise QualificationError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(REPO.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise QualificationError("configuration_error") from exc
    raw = _read_regular(current)
    if len(raw) != expected_bytes or _sha(raw) != expected_sha:
        raise QualificationError("configuration_error")
    return current


def _exact_derivation() -> dict[str, list[str]]:
    common = ["-hide_banner", "-loglevel", "error", "-y", "-i"]
    return {
        "normalized_mp4": common
        + [
            "<source>",
            "-vf",
            "scale=640:-2,fps=5",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "<mp4>",
        ],
        "avi": common
        + ["<mp4>", "-an", "-c:v", "mpeg4", "-q:v", "8", "<avi>"],
        "mov": common + ["<mp4>", "-c", "copy", "<mov>"],
        "mkv": common + ["<mp4>", "-c", "copy", "<mkv>"],
        "webm": common
        + [
            "<mp4>",
            "-an",
            "-c:v",
            "libvpx",
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-b:v",
            "500k",
            "<webm>",
        ],
    }


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    if (
        contract.get("schema_version") != 1
        or contract.get("tool_id") != "thor-lvs-formats-runtime"
        or contract.get("capability_id") != "runtime.lvs.supported-formats"
        or contract.get("acknowledgement") != ACK
        or contract.get("default_execution_enabled") is not False
        or contract.get("target")
        != {
            "product_version": "3.2.1",
            "ga_commit": "7640d917047cf7b0fd3085eefb8282754b56bc94",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "captured_on": "2026-07-31",
        }
        or contract.get("endpoints")
        != {
            "lvs_origin": "http://127.0.0.1:38111",
            "rt_vlm_origin": "http://127.0.0.1:8018",
        }
        or contract.get("model_id")
        != "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
        or contract.get("service_contract")
        != {
            "lvs_metadata_version": "3.0.0",
            "lvs_metadata_sub_version": "d16a216",
            "lvs_metadata_port": "38111",
            "lvs_model_count": 1,
        }
        or contract.get("autonomous_hitl_defaults")
        != {
            "scenario": "activity monitoring",
            "events": ["notable activity"],
        }
        or contract.get("media_semantics")
        != {
            "width": 640,
            "height": 360,
            "frame_rate": "5/1",
            "duration_seconds": 10.0,
            "video_stream_count": 1,
            "audio_stream_count": 0,
        }
        or contract.get("summarization")
        != {
            "chunk_duration": 10,
            "fixed_frames_per_chunk": 8,
            "use_fps_for_chunking": False,
            "seed": 1,
            "max_tokens": 256,
            "expected_chunks_processed": 1,
        }
        or contract.get("execution_bounds")
        != {
            "max_duration_seconds": 900,
            "max_http_requests": 37,
            "max_semantic_actions": 9,
            "min_free_bytes": 10737418240,
            "network_scope": "numeric-loopback-only",
            "model_staging": "forbidden",
            "service_lifecycle": "forbidden",
            "warehouse_sample_bundle": "excluded",
        }
        or contract.get("transport")
        != {
            "max_request_bytes": 4194304,
            "max_response_bytes": 16777216,
            "short_timeout_seconds": 15,
            "summarize_timeout_seconds": 180,
            "tool_timeout_seconds": 120,
        }
        or contract.get("derivation") != _exact_derivation()
    ):
        raise QualificationError("configuration_error")

    source = contract.get("source_fixture", {})
    source_path = _safe_repo_file(
        source.get("path", ""),
        source.get("sha256", ""),
        source.get("bytes", -1),
    )
    if (
        source.get("duration_seconds") != 10.0
        or source.get("warehouse_sample_bundle") is not False
    ):
        raise QualificationError("configuration_error")

    tools = contract.get("tools", {})
    expected_tools = {
        "ffmpeg": (
            "/usr/bin/ffmpeg",
            "dbb8cc21c4b4e0e9bbb750cf74f7af6b023199e1b311eb2f6aec31c9722ceb88",
            "ffmpeg version 6.1.1-3ubuntu5",
        ),
        "ffprobe": (
            "/usr/bin/ffprobe",
            "94aeaba8eb9cd72e48310674718fef2a71d0c57c1f592612e90e252c515d9d6c",
            "ffprobe version 6.1.1-3ubuntu5",
        ),
    }
    tool_hashes: dict[str, str] = {}
    for name, (path_text, digest, version_prefix) in expected_tools.items():
        row = tools.get(name)
        if row != {
            "path": path_text,
            "sha256": digest,
            "version_prefix": version_prefix,
        }:
            raise QualificationError("configuration_error")
        path = Path(path_text)
        if path.is_symlink() or _sha(_read_regular(path)) != digest:
            raise QualificationError("configuration_error")
        tool_hashes[name] = digest

    formats = contract.get("formats")
    if not isinstance(formats, list) or len(formats) != 5:
        raise QualificationError("configuration_error")
    expected_names = ["MP4", "AVI", "MOV", "MKV", "WebM"]
    expected_extensions = ["mp4", "avi", "mov", "mkv", "webm"]
    ids: list[str] = []
    for row, name, extension in zip(formats, expected_names, expected_extensions):
        if (
            not isinstance(row, dict)
            or row.get("name") != name
            or row.get("extension") != extension
            or row.get("raw_hash_policy")
            not in {"deterministic_exact", "runtime_mux_uid"}
            or type(row.get("expected_bytes")) is not int
            or row["expected_bytes"] <= 0
        ):
            raise QualificationError("configuration_error")
        try:
            identifier = UUID(str(row["asset_id"]))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise QualificationError("configuration_error") from exc
        if identifier.version != 4:
            raise QualificationError("configuration_error")
        ids.append(str(identifier))
        expected_sha = row.get("expected_sha256")
        if row["raw_hash_policy"] == "deterministic_exact":
            if not isinstance(expected_sha, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_sha
            ):
                raise QualificationError("configuration_error")
        elif expected_sha is not None:
            raise QualificationError("configuration_error")

    negative = contract.get("adjacent_negative", {})
    try:
        negative_id = str(UUID(str(negative["asset_id"])))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("configuration_error") from exc
    if (
        negative_id in ids
        or len(ids) != len(set(ids))
        or negative.get("filename") != "vss-lvs-invalid.mp4"
        or negative.get("payload_sha256")
        != "3b73878fc46d17d46fed2a8fa14607b6ee5811011933a4975b17530734979180"
        or negative.get("expected_http_status") != 400
        or negative.get("expected_error_code") != "InvalidFile"
    ):
        raise QualificationError("configuration_error")

    cleanup = contract.get("cleanup", {})
    if (
        cleanup.get("logical_namespace")
        != "vss-oracle-runtime-lvs-supported-formats"
        or cleanup.get("target_ids") != ids + [negative_id]
        or len(cleanup.get("postconditions", [])) != 4
    ):
        raise QualificationError("configuration_error")

    return {
        "source_path": source_path,
        "source_sha256": source["sha256"],
        "source_bytes": source["bytes"],
        "tool_hashes": tool_hashes,
        "format_names": expected_names,
        "target_ids": ids + [negative_id],
    }


def plan() -> dict[str, Any]:
    contract, raw = _load(CONTRACT_PATH)
    static = _verify_static(contract)
    return {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "plan",
        "status": "passed",
        "contract_sha256": _sha(raw),
        "capability_id": contract["capability_id"],
        "format_names": static["format_names"],
        "source_fixture_sha256": static["source_sha256"],
        "execution_bounds": contract["execution_bounds"],
        "acknowledgement_required": True,
        "writes_or_lifecycle_actions": False,
        "warehouse_sample_bundle": False,
    }


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
    deadline: float,
) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise QualificationError("oracle_failed")
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=min(timeout, max(0.1, remaining)),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("runtime_unavailable") from exc
    if completed.returncode != 0:
        raise QualificationError("runtime_unavailable")
    if len(completed.stdout) > 16 * 1024 * 1024:
        raise QualificationError("runtime_unavailable")
    return completed.stdout


def _tool_versions(
    contract: dict[str, Any], *, deadline: float
) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in ("ffmpeg", "ffprobe"):
        row = contract["tools"][name]
        raw = _run_command(
            [row["path"], "-version"],
            cwd=REPO,
            timeout=15,
            deadline=deadline,
        )
        first = raw.decode("utf-8", errors="strict").splitlines()[0]
        if not first.startswith(row["version_prefix"]):
            raise QualificationError("runtime_unavailable")
        versions[name] = first
    return versions


def _container_identity(
    contract: dict[str, Any], *, deadline: float
) -> dict[str, dict[str, Any]]:
    delimiter = "|vss-identity-field|"
    template = (
        f"{{{{json .Config.Image}}}}{delimiter}{{{{json .Image}}}}{delimiter}"
        f"{{{{json .State.Status}}}}{delimiter}"
        "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}"
        f"{delimiter}{{{{json .RestartCount}}}}{delimiter}"
        "{{json .State.OOMKilled}}"
    )
    result: dict[str, dict[str, Any]] = {}
    for logical_name in ("lvs", "rt_vlm"):
        expected = contract["containers"][logical_name]
        raw = _run_command(
            ["/usr/bin/docker", "inspect", "--format", template, expected["name"]],
            cwd=REPO,
            timeout=30,
            deadline=deadline,
        )
        parts = raw.decode("utf-8", errors="strict").strip().split(delimiter)
        if len(parts) != 6:
            raise QualificationError("runtime_unavailable")
        try:
            image, image_id, status, health, restarts, oom = [
                json.loads(part) for part in parts
            ]
        except json.JSONDecodeError as exc:
            raise QualificationError("runtime_unavailable") from exc
        if (
            image != expected["image"]
            or image_id != expected["image_id"]
            or status != "running"
            or health != "healthy"
            or restarts != 0
            or oom is not False
        ):
            raise QualificationError("runtime_unavailable")
        result[logical_name] = {
            "container": expected["name"],
            "image": image,
            "image_id": image_id,
            "status": status,
            "health": health,
            "restart_count": restarts,
            "oom_killed": oom,
        }
    return result


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class LoopbackBudget:
    """Direct HTTP transport with exact hosts and shared duration/request bounds."""

    def __init__(self, contract: dict[str, Any], started: float) -> None:
        self._origins = {
            "lvs": ("127.0.0.1", 38111),
            "rt_vlm": ("127.0.0.1", 8018),
        }
        if contract["endpoints"] != {
            "lvs_origin": "http://127.0.0.1:38111",
            "rt_vlm_origin": "http://127.0.0.1:8018",
        }:
            raise QualificationError("configuration_error")
        self._transport = contract["transport"]
        self._maximum = contract["execution_bounds"]["max_http_requests"]
        self._deadline = started + contract["execution_bounds"][
            "max_duration_seconds"
        ]
        self.request_count = 0
        self.observations: list[dict[str, Any]] = []

    def request(
        self,
        service: str,
        action_id: str,
        method: str,
        path: str,
        *,
        path_template: str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: float | None = None,
        cleanup: bool = False,
    ) -> Response:
        if service not in self._origins:
            raise QualificationError("configuration_error")
        if not path.startswith("/") or path.startswith("//"):
            raise QualificationError("configuration_error")
        if body is not None and len(body) > self._transport["max_request_bytes"]:
            raise QualificationError("configuration_error")
        self.request_count += 1
        if self.request_count > self._maximum:
            raise QualificationError("oracle_failed")
        remaining = self._deadline - time.monotonic()
        if remaining <= 0 and not cleanup:
            raise QualificationError("oracle_failed")
        requested_timeout = float(
            timeout or self._transport["short_timeout_seconds"]
        )
        actual_timeout = (
            requested_timeout
            if cleanup
            else min(requested_timeout, max(0.1, remaining))
        )
        host, port = self._origins[service]
        connection = http.client.HTTPConnection(host, port, timeout=actual_timeout)
        response: http.client.HTTPResponse | None = None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Length"] = str(len(body))
        if content_type is not None:
            headers["Content-Type"] = content_type
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(self._transport["max_response_bytes"] + 1)
            if len(raw) > self._transport["max_response_bytes"]:
                raise QualificationError("invalid_response")
            response_headers = {
                key.lower(): value for key, value in response.getheaders()
            }
            if 300 <= response.status < 400:
                raise QualificationError("transport_error")
            self.observations.append(
                {
                    "order": self.request_count,
                    "action_id": action_id,
                    "service": service,
                    "method": method,
                    "path_template": path_template or path,
                    "http_status": response.status,
                    "response_bytes": len(raw),
                    "response_sha256": _sha(raw),
                    "cleanup": cleanup,
                }
            )
            return Response(response.status, response_headers, raw)
        except QualificationError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError("transport_error") from exc
        finally:
            if response is not None:
                response.close()
            connection.close()


def _media_type(headers: dict[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _json_response(response: Response) -> dict[str, Any]:
    if _media_type(response.headers) != "application/json":
        raise QualificationError("invalid_response")
    return _decode_json(response.body)


def _file_row(value: Any, *, require_media_type: bool) -> dict[str, Any]:
    required = {"id", "bytes", "filename", "purpose", "sensor_name"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise QualificationError("invalid_response")
    try:
        UUID(str(value["id"]))
    except (TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("invalid_response") from exc
    if (
        type(value["bytes"]) is not int
        or value["bytes"] < 0
        or not isinstance(value["filename"], str)
        or not isinstance(value["sensor_name"], str)
        or value["purpose"] != "vision"
        or (require_media_type and value.get("media_type") != "video")
    ):
        raise QualificationError("invalid_response")
    return value


def _file_list(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or value.get("object") != "list"
        or not isinstance(value.get("data"), list)
    ):
        raise QualificationError("invalid_response")
    rows = [_file_row(row, require_media_type=True) for row in value["data"]]
    identifiers = [str(row["id"]) for row in rows]
    if len(identifiers) != len(set(identifiers)) or len(rows) > 1_000_000:
        raise QualificationError("invalid_response")
    return sorted(rows, key=lambda row: str(row["id"]))


def _service_snapshot(
    client: LoopbackBudget,
    contract: dict[str, Any],
    *,
    phase: str,
    cleanup: bool = False,
) -> dict[str, Any]:
    ready = client.request(
        "lvs", f"{phase}-lvs-ready", "GET", "/v1/ready", cleanup=cleanup
    )
    if ready.status != 200:
        raise QualificationError("runtime_unavailable")

    models_response = client.request(
        "lvs", f"{phase}-lvs-models", "GET", "/models", cleanup=cleanup
    )
    models = _json_response(models_response)
    data = models.get("data")
    if (
        models_response.status != 200
        or models.get("object") != "list"
        or not isinstance(data, list)
        or len(data) != contract["service_contract"]["lvs_model_count"]
        or len(data) != 1
        or not isinstance(data[0], dict)
        or data[0].get("id") != contract["model_id"]
    ):
        raise QualificationError("runtime_unavailable")

    metadata_response = client.request(
        "lvs", f"{phase}-lvs-metadata", "GET", "/v1/metadata", cleanup=cleanup
    )
    metadata = _json_response(metadata_response)
    expected_service = contract["service_contract"]
    if (
        metadata_response.status != 200
        or metadata.get("version") != expected_service["lvs_metadata_version"]
        or metadata.get("sub_version")
        != expected_service["lvs_metadata_sub_version"]
        or metadata.get("port") != expected_service["lvs_metadata_port"]
    ):
        raise QualificationError("runtime_unavailable")

    assets_response = client.request(
        "rt_vlm",
        f"{phase}-rt-vlm-assets",
        "GET",
        "/v1/assets/stats",
        cleanup=cleanup,
    )
    assets = _json_response(assets_response)
    if assets_response.status != 200 or set(assets) != {
        "asset_count",
        "asset_count_with_storage",
        "aged_out_count",
        "oldest_asset_age_hours",
        "max_storage_usage_gb",
        "max_asset_age_hours",
    }:
        raise QualificationError("runtime_unavailable")
    for key in ("asset_count", "asset_count_with_storage", "aged_out_count"):
        if type(assets[key]) is not int or assets[key] < 0:
            raise QualificationError("runtime_unavailable")

    files_response = client.request(
        "lvs",
        f"{phase}-lvs-file-list",
        "GET",
        "/files?purpose=vision",
        path_template="/files?purpose=vision",
        cleanup=cleanup,
    )
    files_value = _json_response(files_response)
    if files_response.status != 200:
        raise QualificationError("runtime_unavailable")
    files = _file_list(files_value)
    return {
        "ready": {"http_status": ready.status, "body_sha256": _sha(ready.body)},
        "models": models,
        "metadata": metadata,
        "assets": assets,
        "files": files,
    }


def _snapshot_public(snapshot: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    assets = snapshot["assets"]
    return {
        "lvs_ready_http_status": snapshot["ready"]["http_status"],
        "lvs_ready_body_sha256": snapshot["ready"]["body_sha256"],
        "lvs_models_sha256": _canonical_sha(snapshot["models"]),
        "lvs_model_count": len(snapshot["models"]["data"]),
        "lvs_model_id": contract["model_id"],
        "lvs_metadata_sha256": _canonical_sha(snapshot["metadata"]),
        "lvs_metadata_version": snapshot["metadata"]["version"],
        "lvs_metadata_sub_version": snapshot["metadata"]["sub_version"],
        "rt_vlm_asset_statistics_sha256": _canonical_sha(assets),
        "rt_vlm_asset_count": assets["asset_count"],
        "rt_vlm_asset_count_with_storage": assets["asset_count_with_storage"],
        "lvs_file_list_sha256": _canonical_sha(snapshot["files"]),
        "lvs_file_count": len(snapshot["files"]),
    }


def _snapshot_exact(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return all(
        _canonical(before[key]) == _canonical(after[key])
        for key in ("ready", "models", "metadata", "assets", "files")
    )


def _render_derivation(
    values: list[str], *, source: Path, outputs: dict[str, Path]
) -> list[str]:
    replacements = {"<source>": str(source)} | {
        f"<{extension}>": str(path) for extension, path in outputs.items()
    }
    try:
        return [replacements.get(value, value) for value in values]
    except KeyError as exc:
        raise QualificationError("configuration_error") from exc


def _probe_media(
    contract: dict[str, Any], row: dict[str, Any], path: Path, *, deadline: float
) -> dict[str, Any]:
    ffprobe = contract["tools"]["ffprobe"]["path"]
    raw = _run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        cwd=path.parent,
        timeout=contract["transport"]["tool_timeout_seconds"],
        deadline=deadline,
    )
    value = _decode_json(raw, code="runtime_unavailable")
    streams = value.get("streams")
    media_format = value.get("format")
    if not isinstance(streams, list) or not isinstance(media_format, dict):
        raise QualificationError("runtime_unavailable")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    semantics = contract["media_semantics"]
    try:
        duration = float(media_format["duration"])
        probed_size = int(media_format["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QualificationError("runtime_unavailable") from exc
    if (
        len(videos) != semantics["video_stream_count"]
        or len(audios) != semantics["audio_stream_count"]
        or len(videos) != 1
        or videos[0].get("codec_name") != row["codec"]
        or videos[0].get("width") != semantics["width"]
        or videos[0].get("height") != semantics["height"]
        or videos[0].get("r_frame_rate") != semantics["frame_rate"]
        or media_format.get("format_name") != row["format_name"]
        or abs(duration - semantics["duration_seconds"]) > 0.001
        or probed_size != row["expected_bytes"]
        or path.stat().st_size != row["expected_bytes"]
    ):
        raise QualificationError("runtime_unavailable")
    digest = _sha(_read_regular(path, contract["transport"]["max_request_bytes"]))
    if (
        row["raw_hash_policy"] == "deterministic_exact"
        and digest != row["expected_sha256"]
    ):
        raise QualificationError("runtime_unavailable")
    return {
        "codec": videos[0]["codec_name"],
        "format_name": media_format["format_name"],
        "width": videos[0]["width"],
        "height": videos[0]["height"],
        "frame_rate": videos[0]["r_frame_rate"],
        "duration_seconds": duration,
        "video_stream_count": len(videos),
        "audio_stream_count": len(audios),
        "bytes": probed_size,
        "sha256": digest,
        "raw_hash_policy": row["raw_hash_policy"],
    }


def _derive_formats(
    contract: dict[str, Any], source: Path, root: Path, *, deadline: float
) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    outputs = {extension: root / f"vss-lvs-format.{extension}" for extension in (
        "mp4",
        "avi",
        "mov",
        "mkv",
        "webm",
    )}
    for key in ("normalized_mp4", "avi", "mov", "mkv", "webm"):
        args = _render_derivation(
            contract["derivation"][key], source=source, outputs=outputs
        )
        _run_command(
            [contract["tools"]["ffmpeg"]["path"], *args],
            cwd=root,
            timeout=contract["transport"]["tool_timeout_seconds"],
            deadline=deadline,
        )
    probes: dict[str, dict[str, Any]] = {}
    for row in contract["formats"]:
        path = outputs[row["extension"]]
        if path.is_symlink() or not path.is_file():
            raise QualificationError("runtime_unavailable")
        probes[row["extension"]] = _probe_media(
            contract, row, path, deadline=deadline
        )
    return outputs, probes


def _multipart(
    *,
    identifier: str,
    filename: str,
    mime_type: str,
    sensor_name: str,
    media: bytes,
    boundary_suffix: str,
) -> tuple[bytes, str]:
    boundary = f"vss-lvs-formats-{boundary_suffix}"
    fields = {
        "purpose": "vision",
        "media_type": "video",
        "id": identifier,
        "sensor_name": sensor_name,
    }
    pieces: list[bytes] = []
    for name, value in fields.items():
        pieces.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    pieces.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            media,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(pieces), f"multipart/form-data; boundary={boundary}"


def _validate_uploaded_file(
    response: Response,
    *,
    identifier: str,
    filename: str,
    sensor_name: str,
    size: int,
    require_media_type: bool,
) -> dict[str, Any]:
    if response.status != 200:
        raise QualificationError("oracle_failed")
    value = _file_row(
        _json_response(response), require_media_type=require_media_type
    )
    if (
        str(value["id"]) != identifier
        or value["bytes"] != size
        or value["filename"] != filename
        or value["sensor_name"] != sensor_name
    ):
        raise QualificationError("oracle_failed")
    return value


def _validate_summary(
    response: Response,
    *,
    identifier: str,
    model: str,
    expected_chunks: int,
) -> dict[str, Any]:
    if response.status != 200:
        raise QualificationError("oracle_failed")
    value = _json_response(response)
    try:
        UUID(str(value["id"]))
        choices = value["choices"]
        usage = value["usage"]
        choice = choices[0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise QualificationError("invalid_response") from exc
    if (
        value.get("video_id") != identifier
        or value.get("model") != model
        or value.get("object") != "summarization.completion"
        or not isinstance(value.get("created"), int)
        or not isinstance(choices, list)
        or len(choices) != 1
        or choice.get("index") != 0
        or choice.get("finish_reason") != "stop"
        or not isinstance(choice.get("message"), dict)
        or choice["message"].get("role") != "assistant"
        or not isinstance(content, str)
        or not content.strip()
        or not isinstance(usage, dict)
        or usage.get("total_chunks_processed") != expected_chunks
    ):
        raise QualificationError("oracle_failed")
    structured = _decode_json(content.encode("utf-8"), code="invalid_response")
    summary = structured.get("video_summary")
    events = structured.get("events")
    total_events = structured.get("total_events")
    summary_nonempty = isinstance(summary, str) and bool(summary.strip())
    if (
        not isinstance(events, list)
        or any(not isinstance(event, dict) for event in events)
        or type(total_events) is not int
        or total_events != len(events)
        or not (summary_nonempty or events)
    ):
        raise QualificationError("oracle_failed")
    return {
        "http_status": response.status,
        "response_bytes": len(response.body),
        "response_sha256": _sha(response.body),
        "content_bytes": len(content.encode("utf-8")),
        "content_sha256": _sha(content.encode("utf-8")),
        "request_id_well_formed": True,
        "model_exact": True,
        "video_identity_exact": True,
        "finish_reason": "stop",
        "video_summary_nonempty": summary_nonempty,
        "event_count": len(events),
        "chunks_processed": usage["total_chunks_processed"],
    }


def _delete_owned(
    client: LoopbackBudget,
    identifier: str,
    label: str,
    *,
    cleanup: bool = False,
) -> None:
    response = client.request(
        "lvs",
        f"delete-{label}",
        "DELETE",
        f"/files/{identifier}",
        path_template="/files/{qualifier-owned-id}",
        cleanup=cleanup,
    )
    value = _json_response(response)
    if response.status != 200 or value != {
        "id": identifier,
        "object": "file",
        "deleted": True,
    }:
        raise QualificationError("cleanup_failed")


def _read_file_list(
    client: LoopbackBudget, action_id: str, *, cleanup: bool = False
) -> list[dict[str, Any]]:
    response = client.request(
        "lvs",
        action_id,
        "GET",
        "/files?purpose=vision",
        path_template="/files?purpose=vision",
        cleanup=cleanup,
    )
    if response.status != 200:
        raise QualificationError("cleanup_failed" if cleanup else "oracle_failed")
    return _file_list(_json_response(response))


def _privacy_walk(value: Any, path: str = "$") -> None:
    forbidden_keys = {
        "request_id",
        "video_id",
        "asset_id",
        "prompt",
        "system_prompt",
        "summary",
        "content",
        "authorization",
        "access_token",
        "refresh_token",
        "sdp",
        "ice",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in forbidden_keys:
                raise QualificationError("configuration_error")
            _privacy_walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _privacy_walk(item, f"{path}/{index}")
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            UUID_RE.search(value)
            or "nvapi-" in lowered
            or "bearer " in lowered
            or "http://" in lowered
            or "https://" in lowered
        ):
            raise QualificationError("configuration_error")


def execute(acknowledgement: str) -> dict[str, Any]:
    contract, contract_raw = _load(CONTRACT_PATH)
    static = _verify_static(contract)
    if acknowledgement != ACK:
        raise QualificationError("authorization_required")
    if RECEIPT_PATH.exists():
        raise QualificationError("evidence_already_retained")
    if shutil.disk_usage(REPO).free < contract["execution_bounds"]["min_free_bytes"]:
        raise QualificationError("runtime_unavailable")

    started_at = _utc_now()
    started = time.monotonic()
    deadline = started + contract["execution_bounds"]["max_duration_seconds"]
    versions = _tool_versions(contract, deadline=deadline)
    containers_before = _container_identity(contract, deadline=deadline)
    client = LoopbackBudget(contract, started)
    active_id: str | None = None
    active_confirmed = False
    active_label = "unknown-owned-file"
    pre_snapshot: dict[str, Any] | None = None
    cleanup_failures: list[str] = []
    primary: QualificationError | None = None
    formats_result: list[dict[str, Any]] = []
    negative_result: dict[str, Any] | None = None
    post_snapshot: dict[str, Any] | None = None
    containers_after: dict[str, dict[str, Any]] | None = None

    with tempfile.TemporaryDirectory(prefix="vss-lvs-formats-") as temporary:
        root = Path(temporary)
        outputs, probes = _derive_formats(
            contract, static["source_path"], root, deadline=deadline
        )
        try:
            pre_snapshot = _service_snapshot(client, contract, phase="pre")
            pre_ids = {str(row["id"]) for row in pre_snapshot["files"]}
            if pre_ids.intersection(static["target_ids"]):
                raise QualificationError("oracle_failed")
            pre_files = pre_snapshot["files"]

            for row in contract["formats"]:
                extension = row["extension"]
                identifier = row["asset_id"]
                filename = f"vss-lvs-format.{extension}"
                sensor_name = f"vss-lvs-formats-{extension}"
                media = _read_regular(
                    outputs[extension], contract["transport"]["max_request_bytes"]
                )
                body, content_type = _multipart(
                    identifier=identifier,
                    filename=filename,
                    mime_type=row["mime_type"],
                    sensor_name=sensor_name,
                    media=media,
                    boundary_suffix=extension,
                )
                active_id = identifier
                active_confirmed = False
                active_label = extension
                upload = client.request(
                    "lvs",
                    f"upload-{extension}",
                    "POST",
                    "/files",
                    body=body,
                    content_type=content_type,
                )
                _validate_uploaded_file(
                    upload,
                    identifier=identifier,
                    filename=filename,
                    sensor_name=sensor_name,
                    size=len(media),
                    require_media_type=True,
                )
                active_confirmed = True

                metadata = client.request(
                    "lvs",
                    f"readback-{extension}",
                    "GET",
                    f"/files/{identifier}",
                    path_template="/files/{qualifier-owned-id}",
                )
                _validate_uploaded_file(
                    metadata,
                    identifier=identifier,
                    filename=filename,
                    sensor_name=sensor_name,
                    size=len(media),
                    require_media_type=False,
                )

                summary_request = {
                    "id": identifier,
                    "model": contract["model_id"],
                    "scenario": contract["autonomous_hitl_defaults"]["scenario"],
                    "events": contract["autonomous_hitl_defaults"]["events"],
                    "chunk_duration": contract["summarization"]["chunk_duration"],
                    "num_frames_per_second_or_fixed_frames_chunk": contract[
                        "summarization"
                    ]["fixed_frames_per_chunk"],
                    "use_fps_for_chunking": contract["summarization"][
                        "use_fps_for_chunking"
                    ],
                    "seed": contract["summarization"]["seed"],
                    "max_tokens": contract["summarization"]["max_tokens"],
                }
                summary_started = time.monotonic()
                summary = client.request(
                    "lvs",
                    f"summarize-{extension}",
                    "POST",
                    "/v1/summarize",
                    body=_canonical(summary_request),
                    content_type="application/json",
                    timeout=contract["transport"]["summarize_timeout_seconds"],
                )
                summary_result = _validate_summary(
                    summary,
                    identifier=identifier,
                    model=contract["model_id"],
                    expected_chunks=contract["summarization"][
                        "expected_chunks_processed"
                    ],
                )
                summary_result["duration_seconds"] = round(
                    time.monotonic() - summary_started, 6
                )

                _delete_owned(client, identifier, extension)
                active_id = None
                active_confirmed = False
                after_delete = _read_file_list(
                    client, f"verify-{extension}-exact-cleanup"
                )
                if _canonical(after_delete) != _canonical(pre_files):
                    raise QualificationError("cleanup_failed")
                formats_result.append(
                    {
                        "name": row["name"],
                        "extension": extension,
                        "media": probes[extension],
                        "upload_http_status": upload.status,
                        "readback_http_status": metadata.status,
                        "summarization": summary_result,
                        "delete_http_status": 200,
                        "exact_cleanup_after": True,
                    }
                )

            negative = contract["adjacent_negative"]
            invalid_media = b"not a video fixture\n"
            if _sha(invalid_media) != negative["payload_sha256"]:
                raise QualificationError("configuration_error")
            body, content_type = _multipart(
                identifier=negative["asset_id"],
                filename=negative["filename"],
                mime_type="video/mp4",
                sensor_name="vss-lvs-formats-invalid",
                media=invalid_media,
                boundary_suffix="invalid",
            )
            active_id = negative["asset_id"]
            active_confirmed = False
            active_label = "invalid"
            rejected = client.request(
                "lvs",
                "reject-invalid-media",
                "POST",
                "/files",
                body=body,
                content_type=content_type,
            )
            rejection = _json_response(rejected)
            after_negative = _read_file_list(
                client, "verify-invalid-media-absence"
            )
            after_negative_ids = {str(row["id"]) for row in after_negative}
            active_confirmed = negative["asset_id"] in after_negative_ids
            if not active_confirmed:
                active_id = None
            if (
                rejected.status != negative["expected_http_status"]
                or rejection.get("code") != negative["expected_error_code"]
                or active_confirmed
                or _canonical(after_negative) != _canonical(pre_files)
            ):
                raise QualificationError("oracle_failed")
            negative_result = {
                "http_status": rejected.status,
                "error_code": rejection["code"],
                "response_bytes": len(rejected.body),
                "response_sha256": _sha(rejected.body),
                "asset_absent": True,
                "file_list_exact_after": True,
            }

            post_snapshot = _service_snapshot(
                client, contract, phase="post", cleanup=True
            )
            containers_after = _container_identity(contract, deadline=deadline)
            if (
                not _snapshot_exact(pre_snapshot, post_snapshot)
                or containers_after != containers_before
                or {str(row["id"]) for row in post_snapshot["files"]}.intersection(
                    static["target_ids"]
                )
            ):
                raise QualificationError("cleanup_failed")
        except QualificationError as exc:
            primary = exc
        except BaseException as exc:
            primary = QualificationError("oracle_failed")
            primary.__cause__ = exc
        finally:
            if active_id is not None:
                try:
                    current = _read_file_list(
                        client, "cleanup-discover-active-owned-file", cleanup=True
                    )
                    present = active_id in {str(row["id"]) for row in current}
                    if present:
                        _delete_owned(
                            client,
                            active_id,
                            f"recovery-{active_label}",
                            cleanup=True,
                        )
                    restored = _read_file_list(
                        client, "cleanup-verify-active-owned-file", cleanup=True
                    )
                    if (
                        active_id in {str(row["id"]) for row in restored}
                        or pre_snapshot is None
                        or _canonical(restored)
                        != _canonical(pre_snapshot["files"])
                    ):
                        cleanup_failures.append("owned_file_cleanup_failed")
                except BaseException:
                    cleanup_failures.append("owned_file_cleanup_failed")

    if cleanup_failures:
        raise QualificationError("cleanup_failed")
    if primary is not None:
        raise primary
    if pre_snapshot is None or post_snapshot is None or containers_after is None:
        raise QualificationError("oracle_failed")
    if negative_result is None or len(formats_result) != 5:
        raise QualificationError("oracle_failed")

    duration = time.monotonic() - started
    semantic_actions = len(formats_result) + len(formats_result) - 1
    if (
        client.request_count != contract["execution_bounds"]["max_http_requests"]
        or semantic_actions
        != contract["execution_bounds"]["max_semantic_actions"]
        or duration > contract["execution_bounds"]["max_duration_seconds"]
    ):
        raise QualificationError("oracle_failed")

    receipt = {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "capability_ids": [contract["capability_id"]],
        "mode": "execute",
        "status": "passed",
        "failure": None,
        "blockers": [],
        "contract_sha256": _sha(contract_raw),
        "target": contract["target"],
        "started_at": started_at,
        "completed_at": _utc_now(),
        "duration_seconds": round(duration, 6),
        "http_request_count": client.request_count,
        "semantic_action_count": semantic_actions,
        "network_scope": "numeric-loopback-only",
        "source_fixture": {
            "path": contract["source_fixture"]["path"],
            "bytes": static["source_bytes"],
            "sha256": static["source_sha256"],
        },
        "tool_identity": {
            name: {
                "sha256": static["tool_hashes"][name],
                "version": versions[name],
            }
            for name in ("ffmpeg", "ffprobe")
        },
        "runtime_identity": containers_before,
        "pre_state": _snapshot_public(pre_snapshot, contract),
        "formats": formats_result,
        "adjacent_negative": negative_result,
        "cleanup": {
            "failures": [],
            "positive_files_created": 5,
            "positive_files_deleted": 5,
            "invalid_file_created": False,
            "all_qualifier_owned_ids_absent": True,
            "complete_file_list_exact": True,
            "rt_vlm_asset_statistics_exact": True,
            "lvs_ready_exact": True,
            "lvs_model_identity_exact": True,
            "lvs_metadata_exact": True,
            "container_identity_exact": True,
            "post_state": _snapshot_public(post_snapshot, contract),
        },
        "observations": client.observations,
        "forbidden_actions_observed": [],
        "writes_or_lifecycle_actions": True,
        "warehouse_sample_bundle": False,
    }
    _privacy_walk(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    live = subparsers.add_parser("execute")
    live.add_argument("--ack", required=True)
    args = parser.parse_args()
    try:
        result = plan() if args.command == "plan" else execute(args.ack)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool_id": "thor-lvs-formats-runtime",
                    "status": "failed",
                    "failure": exc.code,
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
