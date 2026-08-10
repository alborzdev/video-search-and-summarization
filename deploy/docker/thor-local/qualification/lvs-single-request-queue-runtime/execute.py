#!/usr/bin/env python3
"""Qualify the advertised one-video-at-a-time LVS GPU boundary on Thor."""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys
import tempfile
import threading
import time
from typing import Any, Callable
from uuid import UUID


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
ACK = "I_ACK_LVS_TWO_REQUEST_QUEUE_AND_EXACT_CLEANUP"
MAX_STATIC_BYTES = 128 * 1024 * 1024
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
sys.dont_write_bytecode = True


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
    return _decode_json(raw, code="configuration_error"), raw


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


def _base_call(
    function: Callable[..., Any],
    *args: Any,
    fallback: str = "oracle_failed",
    **kwargs: Any,
) -> Any:
    try:
        return function(*args, **kwargs)
    except QualificationError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", fallback)
        if code not in QualificationError.CODES:
            code = fallback
        raise QualificationError(code) from exc


def _load_base(contract: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    dependency = contract["base_dependency"]
    executor = dependency["executor"]
    executor_path = _safe_repo_file(
        executor["path"], executor["sha256"], executor["bytes"]
    )
    contract_row = dependency["contract"]
    base_contract_path = _safe_repo_file(
        contract_row["path"], contract_row["sha256"], contract_row["bytes"]
    )
    module_name = "_thor_lvs_formats_runtime_dependency"
    spec = importlib.util.spec_from_file_location(module_name, executor_path)
    if spec is None or spec.loader is None:
        raise QualificationError("configuration_error")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise QualificationError("configuration_error") from exc
    base_contract, base_raw = _base_call(
        module._load, base_contract_path, fallback="configuration_error"
    )
    if _sha(base_raw) != contract_row["sha256"]:
        raise QualificationError("configuration_error")
    _base_call(module._verify_static, base_contract, fallback="configuration_error")
    return module, base_contract


def _verify_static(contract: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "acknowledgement",
        "assets",
        "autonomous_hitl_defaults",
        "base_dependency",
        "capability_id",
        "cleanup",
        "containers",
        "default_execution_enabled",
        "endpoints",
        "execution_bounds",
        "media",
        "metrics",
        "model_id",
        "official_contract",
        "runtime_queue_topology",
        "schema_version",
        "service_contract",
        "source_fixture",
        "summarization",
        "target",
        "tool_id",
        "transport",
    }
    if set(contract) != expected_keys:
        raise QualificationError("configuration_error")
    if (
        contract["schema_version"] != 1
        or contract["tool_id"] != "thor-lvs-single-request-queue-runtime"
        or contract["capability_id"] != "runtime.lvs.single-request-queue"
        or contract["acknowledgement"] != ACK
        or contract["default_execution_enabled"] is not False
        or contract["target"]
        != {
            "product_version": "3.2.1",
            "ga_commit": "7640d917047cf7b0fd3085eefb8282754b56bc94",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "captured_on": "2026-07-31",
        }
        or contract["endpoints"]
        != {
            "lvs_origin": "http://127.0.0.1:38111",
            "rt_vlm_origin": "http://127.0.0.1:8018",
        }
        or contract["model_id"] != "nim_nvidia_cosmos3-nano-reasoner_bf16-final"
        or contract["official_contract"]
        != {
            "simultaneous_video_processing": False,
            "batch_queue": "external_required",
            "gpu_utilization_boundary": "single_vlm_worker_and_single_inflight_slot",
        }
        or contract["execution_bounds"]
        != {
            "max_duration_seconds": 480,
            "max_http_requests": 750,
            "max_metric_samples": 720,
            "max_semantic_actions": 2,
            "min_free_bytes": 10737418240,
            "network_scope": "numeric-loopback-only",
            "model_staging": "forbidden",
            "service_lifecycle": "forbidden",
            "warehouse_sample_bundle": "excluded",
        }
        or contract["transport"]
        != {
            "max_request_bytes": 4194304,
            "max_response_bytes": 16777216,
            "short_timeout_seconds": 15,
            "summarize_timeout_seconds": 240,
            "tool_timeout_seconds": 120,
        }
        or contract["autonomous_hitl_defaults"]
        != {"scenario": "activity monitoring", "events": ["notable activity"]}
        or contract["summarization"]
        != {
            "chunk_duration": 10,
            "fixed_frames_per_chunk": 8,
            "use_fps_for_chunking": False,
            "seed": 1,
            "max_tokens": 256,
            "expected_chunks_processed": 1,
        }
    ):
        raise QualificationError("configuration_error")

    expected_dependency = {
        "executor": {
            "path": "deploy/docker/thor-local/qualification/lvs-formats-runtime/execute.py",
            "bytes": 51082,
            "sha256": "a52ab32e86cd7f70cb325a0ffe5bb49e669766cc76e7ed221d579c7be10efa4c",
        },
        "contract": {
            "path": "deploy/docker/thor-local/qualification/lvs-formats-runtime/contract.json",
            "bytes": 6972,
            "sha256": "28030f32ef10d0fe240b11671511a75b5b308041732206a258f9e1f333bf20d7",
        },
    }
    if contract["base_dependency"] != expected_dependency:
        raise QualificationError("configuration_error")

    assets = contract["assets"]
    expected_assets = [
        {
            "asset_id": "00000000-0000-4000-8000-000000000031",
            "filename": "vss-lvs-queue-a.mp4",
            "label": "a",
            "sensor_name": "vss-lvs-queue-a",
        },
        {
            "asset_id": "00000000-0000-4000-8000-000000000032",
            "filename": "vss-lvs-queue-b.mp4",
            "label": "b",
            "sensor_name": "vss-lvs-queue-b",
        },
    ]
    if assets != expected_assets:
        raise QualificationError("configuration_error")
    for row in assets:
        try:
            identifier = UUID(row["asset_id"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise QualificationError("configuration_error") from exc
        if identifier.version != 4:
            raise QualificationError("configuration_error")

    expected_media = {
        "derivation": [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
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
        "expected_bytes": 251674,
        "expected_sha256": "bcd1187ab962147762bc832495472fb89c8d047dff52da9d61d4eaeefe71ac6c",
        "mime_type": "video/mp4",
        "format": {
            "codec": "h264",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "width": 640,
            "height": 360,
            "frame_rate": "5/1",
            "duration_seconds": 10.0,
            "video_stream_count": 1,
            "audio_stream_count": 0,
        },
    }
    expected_metrics = {
        "path": "/metrics",
        "poll_interval_seconds": 0.25,
        "maximum_start_skew_seconds": 0.05,
        "required_pending_transition": [2, 1, 0],
        "expected_processed_delta": 2,
        "expected_queue_count_delta": 2,
        "queue_time_semantics": "decode-admission-only-not-model-worker-wait",
        "series": {
            "pending": "video_file_queries_pending",
            "processed": "video_file_queries_processed",
            "queue_count": "vlm_queue_time_seconds_count",
            "queue_sum": "vlm_queue_time_seconds_sum",
        },
        "required_help": {
            "video_file_queries_pending": "Number of video file queries which are queued and yet to be processed",
            "video_file_queries_processed": "Number of video file queries whose processing is complete",
            "vlm_queue_time_seconds": "Time a chunk waited in RTVI's VLM queue before processing",
        },
    }
    if contract["media"] != expected_media or contract["metrics"] != expected_metrics:
        raise QualificationError("configuration_error")

    expected_topology = {
        "container": "vss-rtvi-vlm",
        "environment": {
            "NUM_GPUS": "1",
            "VLM_BATCH_SIZE": "1",
            "VLM_MODEL_TO_USE": "cosmos-reason3",
        },
        "process_flags": {
            "--num-gpus": "1",
            "--vlm-batch-size": "1",
            "--vlm-model-type": "cosmos-reason3",
        },
        "server_module": "server.rtvi_vlm_server",
        "files": [
            {
                "host_path": "services/rtvi/rt-vlm/src/vlm_pipeline/vlm_pipeline.py",
                "container_path": "/opt/nvidia/rtvi/rtvi/vlm_pipeline/vlm_pipeline.py",
                "mount": "read_only_bind",
                "bytes": 85915,
                "sha256": "76e8f53931f600cc6c8f05cf7d1f752688f6ed1e574fecf911e8b8dfee84df44",
                "required_literals": [
                    '"cosmos-reason3": "models.vllm_compatible.vllm_compatible_model.VllmCompatible"',
                    "batch_size=args.vlm_batch_size",
                    "self._num_futures_threads = max(1, vlm_batch_size)",
                    '"max_batch_size": self._batch_size',
                    "return not self._model.can_enqueue_requests()",
                    "self._num_vlm_procs = args.num_gpus",
                ],
            },
            {
                "host_path": "services/rtvi/rt-vlm/src/vlm_pipeline/process_base.py",
                "container_path": "/opt/nvidia/rtvi/rtvi/vlm_pipeline/process_base.py",
                "mount": "read_only_bind",
                "bytes": 18166,
                "sha256": "a56ecdb52ef125b1f0b33b57c8b55a9f4e547a6e53a26bfb6a9d68590b1dea91",
                "required_literals": [
                    "if not self._disabled and self._is_busy():",
                    "if self._supports_batching():",
                    "self.__process_int(**items[0])",
                ],
            },
            {
                "host_path": None,
                "container_path": "/opt/nvidia/rtvi/rtvi/models/vllm_compatible/vllm_compatible_model.py",
                "mount": "image",
                "bytes": 78838,
                "sha256": "3d76dc0a9462ad668d290d50f14f5bc203cdc2acb4618f9d787ce619cf1c5637",
                "required_literals": [
                    "return len(self._inflight_req_ids) < self._max_batch_size"
                ],
            },
        ],
    }
    if contract["runtime_queue_topology"] != expected_topology:
        raise QualificationError("configuration_error")
    host_queue_files: dict[str, Path] = {}
    for row in expected_topology["files"]:
        host_path = row["host_path"]
        if host_path is None:
            continue
        path = _safe_repo_file(host_path, row["sha256"], row["bytes"])
        source = _read_regular(path)
        if any(
            literal.encode("utf-8") not in source
            for literal in row["required_literals"]
        ):
            raise QualificationError("configuration_error")
        host_queue_files[row["container_path"]] = path

    expected_source = {
        "path": "services/alert/warmup/test.mp4",
        "bytes": 2575454,
        "sha256": "f2c16bf02e1d43fa52faf902ff981185c62df092189b41c735c5c27647b44205",
        "duration_seconds": 10.0,
        "warehouse_sample_bundle": False,
    }
    if contract["source_fixture"] != expected_source:
        raise QualificationError("configuration_error")
    source_path = _safe_repo_file(
        expected_source["path"], expected_source["sha256"], expected_source["bytes"]
    )

    cleanup = contract["cleanup"]
    target_ids = [row["asset_id"] for row in assets]
    if (
        cleanup.get("logical_namespace")
        != "vss-oracle-runtime-lvs-single-request-queue"
        or cleanup.get("target_ids") != target_ids
        or len(cleanup.get("postconditions", [])) != 4
    ):
        raise QualificationError("configuration_error")

    base, base_contract = _load_base(contract)
    base_mp4 = next(
        (row for row in base_contract["formats"] if row["extension"] == "mp4"),
        None,
    )
    if (
        base_contract["target"] != contract["target"]
        or base_contract["endpoints"] != contract["endpoints"]
        or base_contract["containers"] != contract["containers"]
        or base_contract["model_id"] != contract["model_id"]
        or base_contract["service_contract"] != contract["service_contract"]
        or base_contract["source_fixture"] != contract["source_fixture"]
        or base_contract["autonomous_hitl_defaults"]
        != contract["autonomous_hitl_defaults"]
        or base_contract["summarization"] != contract["summarization"]
        or base_mp4 is None
        or base_contract["derivation"]["normalized_mp4"]
        != contract["media"]["derivation"]
        or base_mp4["expected_bytes"] != contract["media"]["expected_bytes"]
        or base_mp4["expected_sha256"] != contract["media"]["expected_sha256"]
        or base_mp4["mime_type"] != contract["media"]["mime_type"]
    ):
        raise QualificationError("configuration_error")
    return {
        "base": base,
        "base_contract": base_contract,
        "base_mp4": base_mp4,
        "source_path": source_path,
        "target_ids": target_ids,
        "host_queue_files": host_queue_files,
    }


def plan() -> dict[str, Any]:
    contract, raw = _load(CONTRACT_PATH)
    _verify_static(contract)
    return {
        "schema_version": 1,
        "tool_id": contract["tool_id"],
        "mode": "plan",
        "status": "passed",
        "contract_sha256": _sha(raw),
        "capability_id": contract["capability_id"],
        "execution_bounds": contract["execution_bounds"],
        "acknowledgement_required": True,
        "writes_or_lifecycle_actions": False,
        "warehouse_sample_bundle": False,
    }


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class ConcurrentBudget:
    """Thread-safe direct HTTP transport with exact local origins and bounds."""

    def __init__(self, contract: dict[str, Any], started: float) -> None:
        self._origins = {
            "lvs": ("127.0.0.1", 38111),
            "rt_vlm": ("127.0.0.1", 8018),
        }
        self._transport = contract["transport"]
        self._maximum = contract["execution_bounds"]["max_http_requests"]
        self._deadline = started + contract["execution_bounds"]["max_duration_seconds"]
        self._count = 0
        self._lock = threading.Lock()
        self._observations: list[dict[str, Any]] = []

    @property
    def request_count(self) -> int:
        with self._lock:
            return self._count

    @property
    def observations(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._observations, key=lambda row: row["order"])

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
        if (
            service not in self._origins
            or not path.startswith("/")
            or path.startswith("//")
        ):
            raise QualificationError("configuration_error")
        if body is not None and len(body) > self._transport["max_request_bytes"]:
            raise QualificationError("configuration_error")
        with self._lock:
            self._count += 1
            order = self._count
            if order > self._maximum:
                raise QualificationError("oracle_failed")
        remaining = self._deadline - time.monotonic()
        if remaining <= 0 and not cleanup:
            raise QualificationError("oracle_failed")
        requested_timeout = float(timeout or self._transport["short_timeout_seconds"])
        actual_timeout = (
            requested_timeout
            if cleanup
            else min(requested_timeout, max(0.1, remaining))
        )
        host, port = self._origins[service]
        connection = http.client.HTTPConnection(host, port, timeout=actual_timeout)
        response: http.client.HTTPResponse | None = None
        headers = {"Accept": "*/*"}
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
            observation = {
                "order": order,
                "action_id": action_id,
                "service": service,
                "method": method,
                "path_template": path_template or path,
                "http_status": response.status,
                "response_bytes": len(raw),
                "response_sha256": _sha(raw),
                "cleanup": cleanup,
            }
            with self._lock:
                self._observations.append(observation)
            return Response(response.status, response_headers, raw)
        except QualificationError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise QualificationError("transport_error") from exc
        finally:
            if response is not None:
                response.close()
            connection.close()


def _metric_snapshot(
    client: ConcurrentBudget,
    contract: dict[str, Any],
    action_id: str,
    *,
    cleanup: bool = False,
) -> dict[str, Any]:
    response = client.request(
        "lvs",
        action_id,
        "GET",
        contract["metrics"]["path"],
        cleanup=cleanup,
    )
    media_type = response.headers.get("content-type", "").split(";", 1)[0]
    if response.status != 200 or media_type.strip().lower() != "text/plain":
        raise QualificationError("runtime_unavailable")
    try:
        text = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise QualificationError("invalid_response") from exc
    required_help = contract["metrics"]["required_help"]
    for name, description in required_help.items():
        if f"# HELP {name} {description}" not in text:
            raise QualificationError("runtime_unavailable")
    if (
        "# TYPE video_file_queries_pending gauge" not in text
        or "# TYPE video_file_queries_processed gauge" not in text
        or "# TYPE vlm_queue_time_seconds histogram" not in text
    ):
        raise QualificationError("runtime_unavailable")

    raw_values: dict[str, float] = {}
    for logical, series in contract["metrics"]["series"].items():
        matches = [line for line in text.splitlines() if line.startswith(f"{series} ")]
        if len(matches) != 1:
            raise QualificationError("invalid_response")
        try:
            value = float(matches[0].split(None, 1)[1])
        except (IndexError, ValueError) as exc:
            raise QualificationError("invalid_response") from exc
        if not math.isfinite(value) or value < 0:
            raise QualificationError("invalid_response")
        raw_values[logical] = value
    for name in ("pending", "processed", "queue_count"):
        if not raw_values[name].is_integer():
            raise QualificationError("invalid_response")
    return {
        "pending": int(raw_values["pending"]),
        "processed": int(raw_values["processed"]),
        "queue_count": int(raw_values["queue_count"]),
        "queue_sum_seconds": raw_values["queue_sum"],
    }


def _derive_fixture(
    static: dict[str, Any], contract: dict[str, Any], root: Path, deadline: float
) -> tuple[Path, dict[str, Any], dict[str, str]]:
    base = static["base"]
    base_contract = static["base_contract"]
    versions = _base_call(
        base._tool_versions,
        base_contract,
        deadline=deadline,
        fallback="runtime_unavailable",
    )
    output = root / "vss-lvs-queue.mp4"
    replacements = {"<source>": str(static["source_path"]), "<mp4>": str(output)}
    args = [replacements.get(value, value) for value in contract["media"]["derivation"]]
    _base_call(
        base._run_command,
        [base_contract["tools"]["ffmpeg"]["path"], *args],
        cwd=root,
        timeout=contract["transport"]["tool_timeout_seconds"],
        deadline=deadline,
        fallback="runtime_unavailable",
    )
    probe = _base_call(
        base._probe_media,
        base_contract,
        static["base_mp4"],
        output,
        deadline=deadline,
        fallback="runtime_unavailable",
    )
    if (
        probe["bytes"] != contract["media"]["expected_bytes"]
        or probe["sha256"] != contract["media"]["expected_sha256"]
    ):
        raise QualificationError("runtime_unavailable")
    return output, probe, versions


def _runtime_queue_topology(
    static: dict[str, Any], contract: dict[str, Any], deadline: float
) -> dict[str, Any]:
    base = static["base"]
    topology = contract["runtime_queue_topology"]
    container = topology["container"]
    delimiter = "|vss-queue-topology-field|"
    template = f"{{{{json .Config.Env}}}}{delimiter}{{{{json .Mounts}}}}"
    raw = _base_call(
        base._run_command,
        ["/usr/bin/docker", "inspect", "--format", template, container],
        cwd=REPO,
        timeout=30,
        deadline=deadline,
        fallback="runtime_unavailable",
    )
    parts = raw.decode("utf-8", errors="strict").strip().split(delimiter)
    if len(parts) != 2:
        raise QualificationError("runtime_unavailable")
    environment_rows = _decode_json(
        parts[0].encode("utf-8"), code="runtime_unavailable", object_only=False
    )
    mounts = _decode_json(
        parts[1].encode("utf-8"), code="runtime_unavailable", object_only=False
    )
    if not isinstance(environment_rows, list) or not isinstance(mounts, list):
        raise QualificationError("runtime_unavailable")
    environment: dict[str, str] = {}
    for row in environment_rows:
        if not isinstance(row, str) or "=" not in row:
            raise QualificationError("runtime_unavailable")
        key, value = row.split("=", 1)
        if key in environment:
            raise QualificationError("runtime_unavailable")
        environment[key] = value
    selected_environment = {
        key: environment.get(key) for key in topology["environment"]
    }
    if selected_environment != topology["environment"]:
        raise QualificationError("runtime_unavailable")

    file_results: list[dict[str, Any]] = []
    check_code = (
        "import hashlib,json,sys;from pathlib import Path;"
        "p=Path(sys.argv[1]);b=p.read_bytes();n=json.loads(sys.argv[2]);"
        "print(json.dumps({'regular':p.is_file() and not p.is_symlink(),"
        "'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),"
        "'literals_present':all(x.encode('utf-8') in b for x in n)}))"
    )
    for row in topology["files"]:
        matching_mounts = [
            item
            for item in mounts
            if isinstance(item, dict)
            and item.get("Destination") == row["container_path"]
        ]
        if row["mount"] == "read_only_bind":
            host_path = static["host_queue_files"].get(row["container_path"])
            if (
                host_path is None
                or len(matching_mounts) != 1
                or matching_mounts[0].get("Type") != "bind"
                or matching_mounts[0].get("Source") != str(host_path.resolve())
                or matching_mounts[0].get("RW") is not False
                or matching_mounts[0].get("Mode") != "ro"
            ):
                raise QualificationError("runtime_unavailable")
        elif row["mount"] == "image":
            if matching_mounts:
                raise QualificationError("runtime_unavailable")
        else:
            raise QualificationError("configuration_error")
        result_raw = _base_call(
            base._run_command,
            [
                "/usr/bin/docker",
                "exec",
                container,
                "/usr/bin/python3",
                "-c",
                check_code,
                row["container_path"],
                json.dumps(row["required_literals"], separators=(",", ":")),
            ],
            cwd=REPO,
            timeout=30,
            deadline=deadline,
            fallback="runtime_unavailable",
        )
        result = _decode_json(result_raw, code="runtime_unavailable")
        if result != {
            "regular": True,
            "bytes": row["bytes"],
            "sha256": row["sha256"],
            "literals_present": True,
        }:
            raise QualificationError("runtime_unavailable")
        file_results.append(
            {
                "container_path": row["container_path"],
                "provenance": row["mount"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "required_literal_count": len(row["required_literals"]),
                "required_literals_present": True,
            }
        )

    top_raw = _base_call(
        base._run_command,
        ["/usr/bin/docker", "top", container, "-eo", "pid,ppid,args"],
        cwd=REPO,
        timeout=30,
        deadline=deadline,
        fallback="runtime_unavailable",
    )
    process_rows: list[str] = []
    for line in top_raw.decode("utf-8", errors="strict").splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3 and topology["server_module"] in parts[2]:
            process_rows.append(parts[2])
    if len(process_rows) != 1:
        raise QualificationError("runtime_unavailable")
    try:
        arguments = shlex.split(process_rows[0])
    except ValueError as exc:
        raise QualificationError("runtime_unavailable") from exc
    module_positions = [
        index
        for index, value in enumerate(arguments[:-1])
        if value == "-m" and arguments[index + 1] == topology["server_module"]
    ]
    if len(module_positions) != 1:
        raise QualificationError("runtime_unavailable")
    selected_flags: dict[str, str] = {}
    for flag, expected in topology["process_flags"].items():
        positions = [
            index for index, value in enumerate(arguments[:-1]) if value == flag
        ]
        if len(positions) != 1 or arguments[positions[0] + 1] != expected:
            raise QualificationError("runtime_unavailable")
        selected_flags[flag] = expected

    return {
        "container": container,
        "environment": selected_environment,
        "server_process_count": 1,
        "server_module": topology["server_module"],
        "process_flags": selected_flags,
        "files": file_results,
        "single_gpu": True,
        "single_vlm_process": True,
        "vlm_batch_size_one": True,
        "single_inflight_slot": True,
    }


def _find_transition(
    samples: list[dict[str, Any]], baseline_processed: int
) -> list[dict[str, Any]]:
    requirements = [
        (2, baseline_processed),
        (1, baseline_processed + 1),
        (0, baseline_processed + 2),
    ]
    transition: list[dict[str, Any]] = []
    cursor = 0
    for pending, processed in requirements:
        match: dict[str, Any] | None = None
        for index in range(cursor, len(samples)):
            row = samples[index]
            if row["pending"] == pending and row["processed"] == processed:
                match = row | {"sample_index": index}
                cursor = index + 1
                break
        if match is None:
            raise QualificationError("oracle_failed")
        transition.append(match)
    return transition


def _privacy_walk(value: Any) -> None:
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
            _privacy_walk(item)
    elif isinstance(value, list):
        for item in value:
            _privacy_walk(item)
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


def _retain_receipt(receipt: dict[str, Any]) -> None:
    raw = (
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    temporary = HERE / f".runtime-receipt.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, flags, 0o644)
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(temporary, RECEIPT_PATH)
    except FileExistsError as exc:
        raise QualificationError("evidence_already_retained") from exc
    except OSError as exc:
        raise QualificationError("configuration_error") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def execute(acknowledgement: str, *, retain: bool) -> dict[str, Any]:
    contract, contract_raw = _load(CONTRACT_PATH)
    static = _verify_static(contract)
    if acknowledgement != ACK:
        raise QualificationError("authorization_required")
    if RECEIPT_PATH.exists():
        raise QualificationError("evidence_already_retained")
    if shutil.disk_usage(REPO).free < contract["execution_bounds"]["min_free_bytes"]:
        raise QualificationError("runtime_unavailable")

    base = static["base"]
    base_contract = static["base_contract"]
    started_at = _utc_now()
    started = time.monotonic()
    deadline = started + contract["execution_bounds"]["max_duration_seconds"]
    client = ConcurrentBudget(contract, started)
    pre_snapshot: dict[str, Any] | None = None
    post_snapshot: dict[str, Any] | None = None
    containers_before: dict[str, Any] | None = None
    containers_after: dict[str, Any] | None = None
    queue_topology: dict[str, Any] | None = None
    attempted_ids: set[str] = set()
    cleanup_failures: list[str] = []
    primary: QualificationError | None = None
    probe: dict[str, Any] | None = None
    versions: dict[str, str] | None = None
    baseline_metrics: dict[str, Any] | None = None
    final_metrics: dict[str, Any] | None = None
    samples: list[dict[str, Any]] = []
    worker_results: list[dict[str, Any]] = []
    transition: list[dict[str, Any]] = []
    start_skew = 0.0
    wall_duration = 0.0

    with tempfile.TemporaryDirectory(prefix="vss-lvs-queue-") as temporary:
        root = Path(temporary)
        fixture, probe, versions = _derive_fixture(static, contract, root, deadline)
        media = _read_regular(fixture, contract["transport"]["max_request_bytes"])
        try:
            containers_before = _base_call(
                base._container_identity,
                base_contract,
                deadline=deadline,
                fallback="runtime_unavailable",
            )
            queue_topology = _runtime_queue_topology(static, contract, deadline)
            pre_snapshot = _base_call(
                base._service_snapshot,
                client,
                base_contract,
                phase="pre",
                fallback="runtime_unavailable",
            )
            pre_files = pre_snapshot["files"]
            pre_ids = {str(row["id"]) for row in pre_files}
            if pre_ids.intersection(static["target_ids"]):
                raise QualificationError("oracle_failed")
            baseline_metrics = _metric_snapshot(client, contract, "pre-queue-metrics")
            if baseline_metrics["pending"] != 0:
                raise QualificationError("runtime_unavailable")

            for row in contract["assets"]:
                attempted_ids.add(row["asset_id"])
                body, content_type = _base_call(
                    base._multipart,
                    identifier=row["asset_id"],
                    filename=row["filename"],
                    mime_type=contract["media"]["mime_type"],
                    sensor_name=row["sensor_name"],
                    media=media,
                    boundary_suffix=f"queue-{row['label']}",
                )
                uploaded = client.request(
                    "lvs",
                    f"upload-{row['label']}",
                    "POST",
                    "/files",
                    body=body,
                    content_type=content_type,
                )
                _base_call(
                    base._validate_uploaded_file,
                    uploaded,
                    identifier=row["asset_id"],
                    filename=row["filename"],
                    sensor_name=row["sensor_name"],
                    size=len(media),
                    require_media_type=True,
                )
                readback = client.request(
                    "lvs",
                    f"readback-{row['label']}",
                    "GET",
                    f"/files/{row['asset_id']}",
                    path_template="/files/{qualifier-owned-id}",
                )
                _base_call(
                    base._validate_uploaded_file,
                    readback,
                    identifier=row["asset_id"],
                    filename=row["filename"],
                    sensor_name=row["sensor_name"],
                    size=len(media),
                    require_media_type=False,
                )

            barrier = threading.Barrier(3)
            release: dict[str, float] = {}

            def summarize(row: dict[str, Any]) -> dict[str, Any]:
                try:
                    barrier.wait(timeout=5)
                except threading.BrokenBarrierError as exc:
                    raise QualificationError("oracle_failed") from exc
                request_started = time.monotonic()
                request_body = {
                    "id": row["asset_id"],
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
                response = client.request(
                    "lvs",
                    f"summarize-{row['label']}",
                    "POST",
                    "/v1/summarize",
                    body=_canonical(request_body),
                    content_type="application/json",
                    timeout=contract["transport"]["summarize_timeout_seconds"],
                )
                completed = time.monotonic()
                result = _base_call(
                    base._validate_summary,
                    response,
                    identifier=row["asset_id"],
                    model=contract["model_id"],
                    expected_chunks=contract["summarization"][
                        "expected_chunks_processed"
                    ],
                )
                return {
                    "label": row["label"],
                    "start_offset_seconds": round(request_started - release["at"], 6),
                    "completion_offset_seconds": round(completed - release["at"], 6),
                    "duration_seconds": round(completed - request_started, 6),
                    "summarization": result,
                }

            executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="lvs-queue-proof"
            )
            futures: list[Future[dict[str, Any]]] = []
            try:
                futures = [
                    executor.submit(summarize, row) for row in contract["assets"]
                ]
                release["at"] = time.monotonic()
                try:
                    barrier.wait(timeout=5)
                except threading.BrokenBarrierError as exc:
                    raise QualificationError("oracle_failed") from exc
                sample_limit = contract["execution_bounds"]["max_metric_samples"]
                while len(samples) < sample_limit:
                    metric = _metric_snapshot(
                        client,
                        contract,
                        f"queue-metric-sample-{len(samples) + 1:04d}",
                    )
                    metric["offset_seconds"] = round(
                        time.monotonic() - release["at"], 6
                    )
                    samples.append(metric)
                    if (
                        all(future.done() for future in futures)
                        and metric["pending"] == 0
                    ):
                        break
                    time.sleep(contract["metrics"]["poll_interval_seconds"])
                else:
                    raise QualificationError("oracle_failed")
                worker_results = [future.result() for future in futures]
            finally:
                executor.shutdown(wait=True, cancel_futures=False)

            worker_results.sort(key=lambda row: row["label"])
            starts = [row["start_offset_seconds"] for row in worker_results]
            start_skew = max(starts) - min(starts)
            wall_duration = max(
                row["completion_offset_seconds"] for row in worker_results
            )
            final_metrics = samples[-1]
            processed_delta = final_metrics["processed"] - baseline_metrics["processed"]
            queue_count_delta = (
                final_metrics["queue_count"] - baseline_metrics["queue_count"]
            )
            queue_sum_delta = (
                final_metrics["queue_sum_seconds"]
                - baseline_metrics["queue_sum_seconds"]
            )
            if (
                start_skew > contract["metrics"]["maximum_start_skew_seconds"]
                or processed_delta != contract["metrics"]["expected_processed_delta"]
                or queue_count_delta
                != contract["metrics"]["expected_queue_count_delta"]
                or any(
                    row["pending"] not in {0, 1, 2}
                    or not baseline_metrics["processed"]
                    <= row["processed"]
                    <= baseline_metrics["processed"] + 2
                    for row in samples
                )
            ):
                raise QualificationError("oracle_failed")
            transition = _find_transition(samples, baseline_metrics["processed"])

            for row in contract["assets"]:
                _base_call(
                    base._delete_owned,
                    client,
                    row["asset_id"],
                    row["label"],
                    fallback="cleanup_failed",
                )
                attempted_ids.discard(row["asset_id"])
            restored_files = _base_call(
                base._read_file_list,
                client,
                "verify-exact-file-cleanup",
                fallback="cleanup_failed",
            )
            if _canonical(restored_files) != _canonical(pre_files):
                raise QualificationError("cleanup_failed")
            post_snapshot = _base_call(
                base._service_snapshot,
                client,
                base_contract,
                phase="post",
                cleanup=True,
                fallback="cleanup_failed",
            )
            containers_after = _base_call(
                base._container_identity,
                base_contract,
                deadline=deadline,
                fallback="cleanup_failed",
            )
            if (
                not _base_call(base._snapshot_exact, pre_snapshot, post_snapshot)
                or containers_after != containers_before
                or {str(row["id"]) for row in post_snapshot["files"]}.intersection(
                    static["target_ids"]
                )
            ):
                raise QualificationError("cleanup_failed")
        except QualificationError as exc:
            primary = exc
        except Exception as exc:
            primary = QualificationError("oracle_failed")
            primary.__cause__ = exc
        finally:
            if attempted_ids:
                try:
                    current = _base_call(
                        base._read_file_list,
                        client,
                        "cleanup-discover-owned-files",
                        cleanup=True,
                        fallback="cleanup_failed",
                    )
                    current_ids = {str(row["id"]) for row in current}
                    for row in contract["assets"]:
                        if row["asset_id"] in current_ids:
                            _base_call(
                                base._delete_owned,
                                client,
                                row["asset_id"],
                                f"recovery-{row['label']}",
                                cleanup=True,
                                fallback="cleanup_failed",
                            )
                    restored = _base_call(
                        base._read_file_list,
                        client,
                        "cleanup-verify-owned-files",
                        cleanup=True,
                        fallback="cleanup_failed",
                    )
                    if pre_snapshot is None or _canonical(restored) != _canonical(
                        pre_snapshot["files"]
                    ):
                        cleanup_failures.append("owned_file_cleanup_failed")
                except Exception:
                    cleanup_failures.append("owned_file_cleanup_failed")

    if cleanup_failures:
        raise QualificationError("cleanup_failed")
    if primary is not None:
        raise primary
    if any(
        value is None
        for value in (
            pre_snapshot,
            post_snapshot,
            containers_before,
            containers_after,
            queue_topology,
            probe,
            versions,
            baseline_metrics,
            final_metrics,
        )
    ):
        raise QualificationError("oracle_failed")
    duration = time.monotonic() - started
    if (
        client.request_count > contract["execution_bounds"]["max_http_requests"]
        or len(samples) > contract["execution_bounds"]["max_metric_samples"]
        or duration > contract["execution_bounds"]["max_duration_seconds"]
        or len(worker_results) != contract["execution_bounds"]["max_semantic_actions"]
    ):
        raise QualificationError("oracle_failed")

    processed_delta = final_metrics["processed"] - baseline_metrics["processed"]
    queue_count_delta = final_metrics["queue_count"] - baseline_metrics["queue_count"]
    queue_sum_delta = (
        final_metrics["queue_sum_seconds"] - baseline_metrics["queue_sum_seconds"]
    )
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
        "semantic_action_count": len(worker_results),
        "network_scope": "numeric-loopback-only",
        "source_fixture": {
            "path": contract["source_fixture"]["path"],
            "bytes": contract["source_fixture"]["bytes"],
            "sha256": contract["source_fixture"]["sha256"],
        },
        "derived_fixture": probe,
        "tool_identity": {
            name: {
                "sha256": base_contract["tools"][name]["sha256"],
                "version": versions[name],
            }
            for name in ("ffmpeg", "ffprobe")
        },
        "runtime_identity": containers_before,
        "runtime_queue_topology": queue_topology,
        "pre_state": _base_call(base._snapshot_public, pre_snapshot, base_contract),
        "queue_proof": {
            "submitted_requests": 2,
            "simultaneous_video_processing_contract": False,
            "batch_queue_contract": "external_required",
            "gpu_utilization_boundary": "single_vlm_worker_and_single_inflight_slot",
            "start_skew_seconds": round(start_skew, 6),
            "total_wall_seconds": round(wall_duration, 6),
            "baseline": baseline_metrics,
            "final": final_metrics,
            "processed_delta": processed_delta,
            "queue_count_delta": queue_count_delta,
            "queue_sum_delta_seconds": round(queue_sum_delta, 9),
            "required_pending_transition": contract["metrics"][
                "required_pending_transition"
            ],
            "observed_transition": transition,
            "metric_sample_count": len(samples),
            "metric_samples_sha256": _canonical_sha(samples),
            "metric_samples": samples,
            "responses": worker_results,
        },
        "cleanup": {
            "failures": [],
            "files_created": 2,
            "files_deleted": 2,
            "all_qualifier_owned_ids_absent": True,
            "complete_file_list_exact": True,
            "rt_vlm_asset_statistics_exact": True,
            "lvs_ready_exact": True,
            "lvs_model_identity_exact": True,
            "lvs_metadata_exact": True,
            "container_identity_exact": True,
            "post_state": _base_call(
                base._snapshot_public, post_snapshot, base_contract
            ),
        },
        "observations": client.observations,
        "forbidden_actions_observed": [],
        "writes_or_lifecycle_actions": True,
        "warehouse_sample_bundle": False,
    }
    _privacy_walk(receipt)
    if retain:
        _retain_receipt(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan")
    live = subparsers.add_parser("execute")
    live.add_argument("--ack", required=True)
    live.add_argument("--retain", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            plan() if args.command == "plan" else execute(args.ack, retain=args.retain)
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except QualificationError as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool_id": "thor-lvs-single-request-queue-runtime",
                    "status": "failed",
                    "failure": exc.code,
                },
                sort_keys=True,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool_id": "thor-lvs-single-request-queue-runtime",
                    "status": "failed",
                    "failure": "oracle_failed",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
