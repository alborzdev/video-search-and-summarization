#!/usr/bin/env python3
"""Bounded, capability-local runtime evidence for SpatialAI utilities 00--06.

The default command is inert. Execution imports locked repository sources,
uses only checked-in tiny fixture manifests and an executor-owned temporary
tree, denies network access, and never touches VSS services or Warehouse data.
"""

from __future__ import annotations

import argparse
import builtins
import contextlib
import copy
import datetime as dt
import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import types
from typing import Any, Callable, Iterator

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
PACKAGE_ROOT = REPO_ROOT / "libs/analytics/spatialai-data-utils"
ACK = "I_ACKNOWLEDGE_OFFLINE_SPATIAL_AI_UTILS_RUNTIME_EVIDENCE"
EXECUTOR_REL = (
    "deploy/docker/thor-local/qualification/"
    "spatial-ai-utils-runtime-evidence-successor/executor.py"
)
EXPECTED_CAPABILITIES = [
    "manifest-entry.spatial-ai-utils.00-calibration-and-camera-grouping",
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-entry.spatial-ai-utils.02-multiview-visualization",
    "manifest-entry.spatial-ai-utils.03-detection-map",
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
    "manifest-entry.spatial-ai-utils.06-video-frame-tools",
]
EXPECTED_EXECUTOR_READY_CAPABILITIES = [
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
]
SHORT_IDS = {
    value.split(".")[2].split("-")[0]: value for value in EXPECTED_CAPABILITIES
}
REQUIRED_MODULES = {
    "calibration_grouping": ("numpy", "shapely"),
    "geometry_projection": ("numpy",),
    "multiview_visualization": ("numpy", "cv2"),
    "detection_map": ("numpy", "pandas", "nuscenes"),
    "tracking_metrics": ("numpy", "scipy"),
    "nvschema_conversion": ("numpy", "scipy"),
    "video_frame_tools": ("numpy", "cv2", "tqdm"),
}
NAMESPACES = {
    capability_id: f"spatial-ai-{capability_id.split('.')[2]}"
    for capability_id in EXPECTED_CAPABILITIES
}
_ACTIVE_PRODUCT_CALLS: dict[str, int] | None = None
_ACTIVE_ACTION_COUNTS: dict[str, int] | None = None
_ACTIVE_ACTIVITY_COUNTS: dict[str, int] | None = None
_ACTIVE_NAMESPACE: Path | None = None
EMPTY_TREE_SHA256 = hashlib.sha256(b"{}").hexdigest()
TEMP_PREFIX = "vss-spatial-ai-runtime."

EXTERNAL_ACTIVITY_KEYS = (
    "network_calls",
    "docker_calls",
    "service_lifecycle_calls",
    "model_accesses",
    "downloads",
    "warehouse_sample_accesses",
    "product_subprocess_calls",
    "filesystem_escape_attempts",
)
OS_PROCESS_ENTRYPOINTS = tuple(
    name
    for name in (
        "fork",
        "forkpty",
        "_execvpe",
        "_spawnvef",
        "posix_spawn",
        "posix_spawnp",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    )
    if hasattr(os, name)
)
EXPECTED_PRODUCT_FUNCTION_COUNTS = {
    "00": {
        "group.apply_group_reassignments": 4,
        "group.parse_moves": 5,
        "origin.calculate_and_update_group_origins": 2,
    },
    "01": {
        "boxes.box3d_to_corners": 4,
        "projection.project_boxes_3d_to_2d": 4,
        "projection.project_points_3d_to_image": 1,
    },
    "02": {
        "visual.draw_bbox3d_multicam": 2,
        "visual.draw_bbox3d_on_img": 5,
    },
    "03": {
        "detection.evaluate_detection": 2,
        "detection.load_boxes_from_jsonl": 7,
        "detection.save_detection_results": 2,
    },
    "04": {
        "tracking.CLEAR.eval_sequence": 4,
        "tracking.Count.eval_sequence": 4,
        "tracking.HOTA.eval_sequence": 4,
        "tracking.Identity.eval_sequence": 4,
    },
    "05": {
        "nvschema.convert_sparse4d_to_nvschema": 5,
        "nvschema.load_nvschema": 4,
    },
    "06": {
        "video.frames_to_video": 3,
        "video.list_frame_paths": 5,
        "video.video_to_frames": 5,
    },
}
EXPECTED_NEGATIVE_CASE_IDS = {
    "00": [
        "malformed-move",
        "empty-camera",
        "empty-group",
        "unknown-camera-strict",
        "unknown-group-strict",
    ],
    "01": [
        "legacy-7dof",
        "fully-offscreen",
        "missing-intrinsic",
        "scalar-box",
        "malformed-world2img",
    ],
    "02": [
        "missing-transform",
        "ambiguous-transform",
        "legacy-7dof",
        "malformed-world2img",
        "missing-image",
    ],
    "03": [
        "missing-ground-truth",
        "missing-prediction",
        "malformed-jsonl",
        "malformed-timestamp",
        "legacy-short-box",
    ],
    "04": [
        "identity-switch",
        "empty-tracker",
        "empty-ground-truth",
        "similarity-shape-mismatch",
        "missing-required-count",
    ],
    "05": [
        "unknown-class",
        "missing-results",
        "strict-short-coordinates",
        "invalid-output-format",
        "malformed-frame-token",
    ],
    "06": [
        "empty-frame-list",
        "empty-frame-directory",
        "missing-video",
        "empty-video",
        "invalid-video",
    ],
}
EXPECTED_OBSERVATION_KEYS = {
    "00": {"updated", "groups"},
    "01": {"corner_shape", "visible_ids", "pixels"},
    "02": {"shape", "nonzero_pixels", "pixel_sha256", "inputs_unchanged"},
    "03": {
        "summary",
        "written_files",
        "semantic_output_sha256",
        "determinism_scope",
    },
    "04": {"hota", "clear", "identity", "count", "identity_mismatch"},
    "05": {"output_sha256", "record", "loaded_frame_ids", "fixed_clock"},
    "06": {
        "order",
        "encode_status",
        "decode_status",
        "video_sha256",
        "decoded_pixel_sha256",
    },
}


class EvidenceError(RuntimeError):
    """A binding, confinement, execution, or semantic assertion failed."""


class ConfinementError(EvidenceError):
    """A prohibited external action or namespace escape was attempted."""


_AUDIT_STATE_ATTRIBUTE = "_vss_spatial_ai_runtime_audit_state_v1"
_audit_state = getattr(sys, _AUDIT_STATE_ATTRIBUTE, None)
if _audit_state is None:
    _audit_state = {
        "counters": None,
        "namespace_getter": None,
        "error_type": ConfinementError,
    }
    setattr(sys, _AUDIT_STATE_ATTRIBUTE, _audit_state)

    def _runtime_audit_hook(event: str, args: tuple[Any, ...]) -> None:
        counters = _audit_state["counters"]
        if counters is None:
            return

        error_type = _audit_state["error_type"]

        def deny(counter: str, message: str) -> None:
            counters[counter] += 1
            raise error_type(message)

        def namespace_path(path: Any, dir_fd: int | None = None) -> Path:
            if not isinstance(path, (str, bytes, os.PathLike)):
                deny(
                    "filesystem_escape_attempts",
                    "filesystem mutation used an unresolvable path",
                )
            candidate = Path(os.fsdecode(path))
            if not candidate.is_absolute():
                if dir_fd is None or dir_fd == -1:
                    candidate = Path.cwd() / candidate
                else:
                    try:
                        candidate = (
                            Path(os.readlink(f"/proc/self/fd/{dir_fd}")) / candidate
                        )
                    except OSError:
                        deny(
                            "filesystem_escape_attempts",
                            f"cannot resolve mutation directory fd: {dir_fd}",
                        )
            return candidate

        def render_path(path: Any) -> str:
            if isinstance(path, (str, bytes, os.PathLike)):
                return json.dumps(os.fsdecode(path), ensure_ascii=True)
            return f"<{type(path).__name__}>"

        def require_namespace(
            path: Any, dir_fd: int | None = None, operation: str = "mutation"
        ) -> None:
            getter = _audit_state["namespace_getter"]
            namespaces = getter() if getter is not None else ()
            if not namespaces:
                deny(
                    "filesystem_escape_attempts",
                    f"filesystem {operation} attempted without an owned namespace: "
                    f"path={render_path(path)}",
                )
            candidate = namespace_path(path, dir_fd)
            resolved = candidate.resolve(strict=False)
            for namespace in namespaces:
                try:
                    resolved.relative_to(namespace.resolve(strict=False))
                    return
                except ValueError:
                    continue
            deny(
                "filesystem_escape_attempts",
                f"filesystem {operation} escaped owned namespace: "
                f"path={render_path(candidate)}",
            )

        if event == "open":
            path = args[0] if args else None
            if isinstance(path, (str, bytes, os.PathLike)):
                lowered = os.fsdecode(path).lower()
                parts = set(Path(lowered).parts)
                if "warehouse" in parts or "warehouse" in Path(lowered).name:
                    deny(
                        "warehouse_sample_accesses", f"forbidden external input: {path}"
                    )
                if parts & {"model", "models"} or Path(lowered).suffix in {
                    ".engine",
                    ".onnx",
                    ".plan",
                    ".safetensors",
                    ".pt",
                    ".pth",
                    ".trt",
                }:
                    deny("model_accesses", f"forbidden external input: {path}")
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            mutation_flags = (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            )
            if flags & mutation_flags:
                require_namespace(path, operation="open")
        elif event == "os.mkdir":
            require_namespace(args[0], args[2] if len(args) > 2 else None, "mkdir")
        elif event in {
            "os.remove",
            "os.rmdir",
            "os.chmod",
            "os.chown",
            "os.utime",
            "os.truncate",
        }:
            require_namespace(
                args[0],
                args[-1] if event != "os.truncate" else None,
                event,
            )
        elif event == "os.rename":
            require_namespace(args[0], args[2] if len(args) > 2 else None, event)
            require_namespace(args[1], args[3] if len(args) > 3 else None, event)
        elif event == "os.link":
            require_namespace(args[1], args[3] if len(args) > 3 else None, event)
        elif event == "os.symlink":
            require_namespace(args[1], args[2] if len(args) > 2 else None, event)
        elif event in {
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.posix_spawnp",
            "os.fork",
            "os.forkpty",
            "os.exec",
            "pty.spawn",
        }:
            rendered = " ".join(str(item) for item in args[:2]).lower()
            counters["product_subprocess_calls"] += 1
            if "docker" in rendered or "compose" in rendered:
                counters["docker_calls"] += 1
            if any(token in rendered for token in ("systemctl", "service", "kubectl")):
                counters["service_lifecycle_calls"] += 1
            raise error_type("product subprocess execution is prohibited")
        elif event in {
            "socket.__new__",
            "socket.connect",
            "socket.connect_ex",
            "socket.bind",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyname_ex",
            "socket.gethostbyaddr",
        }:
            counters["network_calls"] += 1
            counters["downloads"] += 1
            raise error_type("network access is prohibited")

    sys.addaudithook(_runtime_audit_hook)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def strict_json(path: Path) -> Any:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in rows:
            if key in value:
                raise EvidenceError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON: {path}") from exc


def repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise EvidenceError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    current = root
    try:
        for part in candidate.parts:
            current /= part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise EvidenceError(
                    f"repository input contains symlink component: {relative}"
                )
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except EvidenceError:
        raise
    except (OSError, ValueError) as exc:
        raise EvidenceError(f"repository path escape or absence: {relative}") from exc
    if not stat.S_ISREG(resolved.lstat().st_mode):
        raise EvidenceError(f"repository input is not a regular file: {relative}")
    return resolved


def open_safe_output_parent(path: Path) -> tuple[Path, int]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.name or absolute == Path(absolute.anchor):
        raise EvidenceError("receipt output must name a file")
    current_fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in absolute.parent.parts[1:]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return absolute, current_fd
    except OSError as exc:
        os.close(current_fd)
        raise EvidenceError(
            "receipt output parent is absent, symlinked, or not a directory"
        ) from exc


def publish_receipt_exclusive(path: Path, rendered: str) -> None:
    destination, parent_fd = open_safe_output_parent(path)
    receipt_fd: int | None = None
    created = False
    try:
        receipt_fd = os.open(
            destination.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        created = True
        if not stat.S_ISREG(os.fstat(receipt_fd).st_mode):
            raise EvidenceError("receipt output leaf is not a regular file")
        payload = rendered.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(receipt_fd, payload[offset:])
        os.fsync(receipt_fd)
    except FileExistsError as exc:
        raise EvidenceError("receipt output path already exists") from exc
    except Exception:
        if created:
            try:
                os.unlink(destination.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if receipt_fd is not None:
            os.close(receipt_fd)
        os.close(parent_fd)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = strict_json(path)
    schema = strict_json(CONTRACT_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(contract),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = ".".join(str(item) for item in first.absolute_path) or "<root>"
        raise EvidenceError(f"contract schema violation at {where}: {first.message}")
    if [
        row["capability_id"] for row in contract["capabilities"]
    ] != EXPECTED_CAPABILITIES:
        raise EvidenceError("exact seven-capability order drift")
    if contract["policy"]["external_provider_entry"].split(".")[2][:2] != "07":
        raise EvidenceError("AWS/GCS external boundary drift")
    return contract


def require_default_contract(path: Path) -> None:
    try:
        if path.is_symlink() or path.resolve(strict=True) != CONTRACT_PATH.resolve(
            strict=True
        ):
            raise EvidenceError("--contract must name the canonical contract.json")
    except OSError as exc:
        raise EvidenceError("contract path is absent or inaccessible") from exc


def verify_target_environment(contract: dict[str, Any]) -> dict[str, str]:
    expected_platform = contract["environment"]["platform"]
    expected_python = contract["environment"]["python_major_minor"]
    observed_system = platform.system()
    observed_machine = platform.machine()
    observed_python = ".".join(platform.python_version_tuple()[:2])
    if expected_platform != "linux-aarch64":
        raise EvidenceError("contract target platform drift")
    if observed_system != "Linux" or observed_machine != "aarch64":
        raise EvidenceError(
            "runtime target mismatch: expected Linux/aarch64, "
            f"observed {observed_system}/{observed_machine}"
        )
    if observed_python != expected_python or expected_python != "3.12":
        raise EvidenceError(
            f"runtime Python mismatch: expected 3.12, observed {observed_python}"
        )
    return {
        "platform": expected_platform,
        "system": observed_system,
        "machine": observed_machine,
        "python_major_minor": observed_python,
        "python_full": platform.python_version(),
    }


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise EvidenceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.rstrip("\n")


@contextlib.contextmanager
def product_execution_deadline(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        raise EvidenceError("product execution deadline must be positive")
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)

    def timed_out(_signum: int, _frame: Any) -> None:
        raise EvidenceError(f"product execution exceeded {seconds:g}-second deadline")

    signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
        signal.signal(signal.SIGALRM, old_handler)


def _increment_activity(key: str) -> None:
    if _ACTIVE_ACTIVITY_COUNTS is None:
        raise EvidenceError("external-activity guard is not active")
    _ACTIVE_ACTIVITY_COUNTS[key] += 1


def _classify_forbidden_read(path: Any) -> str | None:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    lowered = os.fsdecode(path).lower()
    parts = set(Path(lowered).parts)
    if "warehouse" in parts or "warehouse" in Path(lowered).name:
        return "warehouse_sample_accesses"
    if parts & {"model", "models"} or Path(lowered).suffix in {
        ".engine",
        ".onnx",
        ".plan",
        ".safetensors",
        ".pt",
        ".pth",
        ".trt",
    }:
        return "model_accesses"
    return None


def _render_diagnostic_path(path: Any) -> str:
    if isinstance(path, (str, bytes, os.PathLike)):
        return json.dumps(os.fsdecode(path), ensure_ascii=True)
    return f"<{type(path).__name__}>"


def _require_mutation_in_namespace(
    path: Any, dir_fd: int | None = None, operation: str = "mutation"
) -> None:
    namespaces = (_ACTIVE_NAMESPACE,) if _ACTIVE_NAMESPACE is not None else ()
    if not namespaces or not isinstance(path, (str, bytes, os.PathLike)):
        _increment_activity("filesystem_escape_attempts")
        raise ConfinementError(
            f"filesystem {operation} attempted without an owned namespace: "
            f"path={_render_diagnostic_path(path)}"
        )
    candidate = Path(os.fsdecode(path))
    if not candidate.is_absolute():
        if dir_fd is None:
            candidate = Path.cwd() / candidate
        else:
            try:
                candidate = Path(os.readlink(f"/proc/self/fd/{dir_fd}")) / candidate
            except OSError as exc:
                _increment_activity("filesystem_escape_attempts")
                raise ConfinementError(
                    f"cannot resolve mutation directory fd: {dir_fd}"
                ) from exc
    resolved = candidate.resolve(strict=False)
    for namespace in namespaces:
        try:
            resolved.relative_to(namespace.resolve(strict=False))
            return
        except ValueError:
            continue
    _increment_activity("filesystem_escape_attempts")
    raise ConfinementError(
        f"filesystem {operation} escaped owned namespace: "
        f"path={_render_diagnostic_path(candidate)}"
    )


@contextlib.contextmanager
def external_activity_denied(counters: dict[str, int]) -> Iterator[None]:
    """Instrument and deny network, subprocess, forbidden reads, and escaped writes."""
    global _ACTIVE_ACTIVITY_COUNTS
    if set(counters) != set(EXTERNAL_ACTIVITY_KEYS) or any(counters.values()):
        raise EvidenceError("external-activity counters must start at exact zero")
    if _audit_state["counters"] is not None:
        raise EvidenceError("external-activity guard is already active")
    originals = {
        "socket": socket.socket,
        "socket_type": socket.SocketType,
        "socketpair": socket.socketpair,
        "create_connection": socket.create_connection,
        "getaddrinfo": socket.getaddrinfo,
        "run": subprocess.run,
        "popen_process": subprocess.Popen,
        "call": subprocess.call,
        "check_call": subprocess.check_call,
        "check_output": subprocess.check_output,
        "os_system": os.system,
        "os_popen": os.popen,
        "builtin_open": builtins.open,
        "io_open": io.open,
        "os_open": os.open,
        "mkdir": os.mkdir,
        "rename": os.rename,
        "replace": os.replace,
        "unlink": os.unlink,
        "remove": os.remove,
        "rmdir": os.rmdir,
        "link": os.link,
        "symlink": os.symlink,
        "chmod": os.chmod,
        "chown": os.chown,
        "utime": os.utime,
        "truncate": os.truncate,
        "mkfifo": os.mkfifo,
        "mknod": os.mknod,
        "os_process": {name: getattr(os, name) for name in OS_PROCESS_ENTRYPOINTS},
    }

    def reject_network(*_args: Any, **_kwargs: Any) -> Any:
        _increment_activity("network_calls")
        _increment_activity("downloads")
        raise ConfinementError("network access is prohibited")

    def reject_subprocess(*args: Any, **kwargs: Any) -> Any:
        _increment_activity("product_subprocess_calls")
        rendered = " ".join(str(item) for item in args[:1]).lower()
        if "docker" in rendered or "compose" in rendered:
            _increment_activity("docker_calls")
        if any(token in rendered for token in ("systemctl", "service", "kubectl")):
            _increment_activity("service_lifecycle_calls")
        raise ConfinementError("product subprocess execution is prohibited")

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        forbidden = _classify_forbidden_read(file)
        if forbidden is not None:
            _increment_activity(forbidden)
            raise ConfinementError(f"forbidden external input: {file}")
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            _require_mutation_in_namespace(file, operation="open")
        return originals["builtin_open"](file, mode, *args, **kwargs)

    def guarded_io_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        forbidden = _classify_forbidden_read(file)
        if forbidden is not None:
            _increment_activity(forbidden)
            raise ConfinementError(f"forbidden external input: {file}")
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            _require_mutation_in_namespace(file, operation="open")
        return originals["io_open"](file, mode, *args, **kwargs)

    def guarded_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        forbidden = _classify_forbidden_read(path)
        if forbidden is not None:
            _increment_activity(forbidden)
            raise ConfinementError(f"forbidden external input: {path}")
        mutation_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & mutation_flags:
            _require_mutation_in_namespace(path, operation="open")
        return originals["os_open"](path, flags, *args, **kwargs)

    def guarded_mkdir(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "mkdir")
        return originals["mkdir"](path, *args, **kwargs)

    def guarded_rename(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(src, kwargs.get("src_dir_fd"), "rename-source")
        _require_mutation_in_namespace(dst, kwargs.get("dst_dir_fd"), "rename-target")
        return originals["rename"](src, dst, *args, **kwargs)

    def guarded_replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(src, kwargs.get("src_dir_fd"), "replace-source")
        _require_mutation_in_namespace(dst, kwargs.get("dst_dir_fd"), "replace-target")
        return originals["replace"](src, dst, *args, **kwargs)

    def guarded_unlink(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "unlink")
        return originals["unlink"](path, *args, **kwargs)

    def guarded_remove(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "remove")
        return originals["remove"](path, *args, **kwargs)

    def guarded_rmdir(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "rmdir")
        return originals["rmdir"](path, *args, **kwargs)

    def guarded_link(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(dst, kwargs.get("dst_dir_fd"), "link-target")
        return originals["link"](src, dst, *args, **kwargs)

    def guarded_symlink(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(dst, kwargs.get("dir_fd"), "symlink-target")
        return originals["symlink"](src, dst, *args, **kwargs)

    def guarded_metadata(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "chmod")
        return originals["chmod"](path, *args, **kwargs)

    def guarded_chown(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "chown")
        return originals["chown"](path, *args, **kwargs)

    def guarded_utime(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "utime")
        return originals["utime"](path, *args, **kwargs)

    def guarded_truncate(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, operation="truncate")
        return originals["truncate"](path, *args, **kwargs)

    def guarded_mkfifo(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "mkfifo")
        return originals["mkfifo"](path, *args, **kwargs)

    def guarded_mknod(path: Any, *args: Any, **kwargs: Any) -> Any:
        _require_mutation_in_namespace(path, kwargs.get("dir_fd"), "mknod")
        return originals["mknod"](path, *args, **kwargs)

    _ACTIVE_ACTIVITY_COUNTS = counters
    _audit_state["counters"] = counters
    _audit_state["namespace_getter"] = lambda: tuple(
        namespace for namespace in (_ACTIVE_NAMESPACE,) if namespace is not None
    )
    _audit_state["error_type"] = ConfinementError
    socket.socket = reject_network  # type: ignore[assignment]
    socket.SocketType = reject_network  # type: ignore[assignment,misc]
    socket.socketpair = reject_network  # type: ignore[assignment]
    socket.create_connection = reject_network  # type: ignore[assignment]
    socket.getaddrinfo = reject_network  # type: ignore[assignment]
    subprocess.run = reject_subprocess  # type: ignore[assignment]
    subprocess.Popen = reject_subprocess  # type: ignore[assignment,misc]
    subprocess.call = reject_subprocess  # type: ignore[assignment]
    subprocess.check_call = reject_subprocess  # type: ignore[assignment]
    subprocess.check_output = reject_subprocess  # type: ignore[assignment]
    os.system = reject_subprocess  # type: ignore[assignment]
    os.popen = reject_subprocess  # type: ignore[assignment]
    builtins.open = guarded_open  # type: ignore[assignment]
    io.open = guarded_io_open  # type: ignore[assignment]
    os.open = guarded_os_open  # type: ignore[assignment]
    os.mkdir = guarded_mkdir  # type: ignore[assignment]
    os.rename = guarded_rename  # type: ignore[assignment]
    os.replace = guarded_replace  # type: ignore[assignment]
    os.unlink = guarded_unlink  # type: ignore[assignment]
    os.remove = guarded_remove  # type: ignore[assignment]
    os.rmdir = guarded_rmdir  # type: ignore[assignment]
    os.link = guarded_link  # type: ignore[assignment]
    os.symlink = guarded_symlink  # type: ignore[assignment]
    os.chmod = guarded_metadata  # type: ignore[assignment]
    os.chown = guarded_chown  # type: ignore[assignment]
    os.utime = guarded_utime  # type: ignore[assignment]
    os.truncate = guarded_truncate  # type: ignore[assignment]
    os.mkfifo = guarded_mkfifo  # type: ignore[assignment]
    os.mknod = guarded_mknod  # type: ignore[assignment]
    for name in OS_PROCESS_ENTRYPOINTS:
        setattr(os, name, reject_subprocess)
    try:
        yield
    finally:
        _audit_state["counters"] = None
        _audit_state["namespace_getter"] = None
        socket.socket = originals["socket"]  # type: ignore[assignment]
        socket.SocketType = originals["socket_type"]  # type: ignore[assignment,misc]
        socket.socketpair = originals["socketpair"]  # type: ignore[assignment]
        socket.create_connection = originals["create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = originals["getaddrinfo"]  # type: ignore[assignment]
        subprocess.run = originals["run"]  # type: ignore[assignment]
        subprocess.Popen = originals["popen_process"]  # type: ignore[assignment,misc]
        subprocess.call = originals["call"]  # type: ignore[assignment]
        subprocess.check_call = originals["check_call"]  # type: ignore[assignment]
        subprocess.check_output = originals["check_output"]  # type: ignore[assignment]
        os.system = originals["os_system"]  # type: ignore[assignment]
        os.popen = originals["os_popen"]  # type: ignore[assignment]
        builtins.open = originals["builtin_open"]  # type: ignore[assignment]
        io.open = originals["io_open"]  # type: ignore[assignment]
        os.open = originals["os_open"]  # type: ignore[assignment]
        os.mkdir = originals["mkdir"]  # type: ignore[assignment]
        os.rename = originals["rename"]  # type: ignore[assignment]
        os.replace = originals["replace"]  # type: ignore[assignment]
        os.unlink = originals["unlink"]  # type: ignore[assignment]
        os.remove = originals["remove"]  # type: ignore[assignment]
        os.rmdir = originals["rmdir"]  # type: ignore[assignment]
        os.link = originals["link"]  # type: ignore[assignment]
        os.symlink = originals["symlink"]  # type: ignore[assignment]
        os.chmod = originals["chmod"]  # type: ignore[assignment]
        os.chown = originals["chown"]  # type: ignore[assignment]
        os.utime = originals["utime"]  # type: ignore[assignment]
        os.truncate = originals["truncate"]  # type: ignore[assignment]
        os.mkfifo = originals["mkfifo"]  # type: ignore[assignment]
        os.mknod = originals["mknod"]  # type: ignore[assignment]
        for name, function in originals["os_process"].items():
            setattr(os, name, function)
        _ACTIVE_ACTIVITY_COUNTS = None


@contextlib.contextmanager
def network_denied() -> Iterator[None]:
    counters = {key: 0 for key in EXTERNAL_ACTIVITY_KEYS}
    with external_activity_denied(counters):
        yield


def verify_static_locks(contract: dict[str, Any]) -> None:
    for capability in contract["capabilities"]:
        fixture = capability["fixture_manifest"]
        if sha_file(repo_file(fixture["path"])) != fixture["sha256"]:
            raise EvidenceError(f"fixture drift: {capability['capability_id']}")
        for lock in capability["source_controls"]:
            if sha_file(repo_file(lock["path"])) != lock["sha256"]:
                raise EvidenceError(f"source drift: {lock['path']}")


def _rows_by_id(document: dict[str, Any], collection: str, key: str) -> dict[str, Any]:
    rows = document.get(collection)
    if not isinstance(rows, list):
        raise EvidenceError(f"missing {collection} collection")
    indexed = {row.get(key): row for row in rows if isinstance(row, dict)}
    if len(indexed) != len(rows):
        raise EvidenceError(f"duplicate or malformed rows in {collection}")
    return indexed


def verify_bindings(contract: dict[str, Any], require_clean: bool) -> dict[str, Any]:
    ledger_path = repo_file(contract["target"]["current_ledger_document"])
    oracle_path = repo_file(contract["target"]["current_oracle_document"])
    ledger = _rows_by_id(strict_json(ledger_path), "capabilities", "id")
    oracles = _rows_by_id(strict_json(oracle_path), "oracles", "capability_id")
    for capability in contract["capabilities"]:
        capability_id = capability["capability_id"]
        row = ledger.get(capability_id)
        oracle = oracles.get(capability_id)
        if row is None or oracle is None:
            raise EvidenceError(f"missing canonical row: {capability_id}")
        if sha_bytes(canonical_bytes(row)) != capability["current_ledger_row_sha256"]:
            raise EvidenceError(f"current ledger row drift: {capability_id}")
        if sha_bytes(canonical_bytes(oracle)) != capability["current_oracle_sha256"]:
            raise EvidenceError(f"current oracle row drift: {capability_id}")
        if (
            row.get("feature_id") != "spatial-ai-utils"
            or row.get("runtime_state") != "not_qualified"
        ):
            raise EvidenceError(f"unexpected current ledger state: {capability_id}")
        if (
            oracle.get("current_state") != "open_unexecuted"
            or oracle.get("evidence") != []
        ):
            raise EvidenceError(f"unexpected current oracle state: {capability_id}")
        readiness = oracle.get("acceptance_readiness")
        expected_classification = (
            "executor_ready"
            if capability_id in EXPECTED_EXECUTOR_READY_CAPABILITIES
            else "planning_index_only"
        )
        if (
            not isinstance(readiness, dict)
            or readiness.get("classification") != expected_classification
        ):
            raise EvidenceError(f"unexpected current oracle readiness: {capability_id}")
        blockers = readiness.get("blockers")
        if (expected_classification == "executor_ready" and blockers != []) or (
            expected_classification == "planning_index_only"
            and (not isinstance(blockers, list) or not blockers)
        ):
            raise EvidenceError(f"unexpected current oracle blockers: {capability_id}")
    external = ledger.get(contract["policy"]["external_provider_entry"])
    external_oracle = oracles.get(contract["policy"]["external_provider_entry"])
    if not external or (
        external.get("acceptance_class"),
        external.get("thor_state"),
        external.get("runtime_state"),
    ) != ("external_optional", "external_optional", "not_applicable"):
        raise EvidenceError("AWS/GCS external boundary state drift")
    if (
        not external_oracle
        or external_oracle.get("current_state") != "external_boundary_unexecuted"
    ):
        raise EvidenceError("AWS/GCS external oracle drift")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    clean = status == ""
    if require_clean and not clean:
        raise EvidenceError("promotable receipt requires a completely clean checkout")
    return {
        "contract_sha256": sha_file(CONTRACT_PATH),
        "executor_sha256": sha_file(REPO_ROOT / EXECUTOR_REL),
        "ledger_document_sha256": sha_file(ledger_path),
        "oracle_document_sha256": sha_file(oracle_path),
        "checkout_head": git("rev-parse", "HEAD"),
        "checkout_clean": clean,
        "checkout_status_porcelain_sha256": sha_bytes(status.encode("utf-8")),
        "canonical_rows_are_open_unexecuted": True,
        "executor_ready_capabilities": EXPECTED_EXECUTOR_READY_CAPABILITIES,
    }


@contextlib.contextmanager
def deterministic_dependency_import(name: str) -> Iterator[None]:
    """Prevent a test-only NumPy hardware probe in the nuScenes import chain."""
    numpy = sys.modules.get("numpy")
    if name != "nuscenes" or numpy is None:
        yield
        return
    missing = object()
    previous = numpy.__dict__.get("testing", missing)
    if previous is missing:
        testing_stub = types.ModuleType("numpy.testing")
        testing_stub.__all__ = []
        numpy.__dict__["testing"] = testing_stub
    try:
        yield
    finally:
        if previous is missing:
            del numpy.__dict__["testing"]


def _module_preflight(adapter: str) -> dict[str, Any]:
    observed: dict[str, str] = {}
    missing: list[str] = []
    failures: list[str] = []
    for name in REQUIRED_MODULES[adapter]:
        try:
            with deterministic_dependency_import(name):
                module = importlib.import_module(name)
            version = getattr(module, "__version__", None)
            if version is None:
                try:
                    version = importlib.metadata.version(name)
                except importlib.metadata.PackageNotFoundError:
                    version = "unknown"
            observed[name] = str(version)
        except ConfinementError:
            raise
        except ModuleNotFoundError as exc:
            missing.append(exc.name or name)
        except Exception as exc:  # ABI/import failures are capability-local blockers.
            failures.append(f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
    return {
        "ready": not missing and not failures,
        "required_modules": list(REQUIRED_MODULES[adapter]),
        "observed_versions": observed,
        "missing_modules": sorted(set(missing)),
        "import_failures": failures,
    }


def _import_product(name: str) -> Any:
    package = str(PACKAGE_ROOT)
    if package not in sys.path:
        sys.path.insert(0, package)
    return importlib.import_module(name)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        if value != value:
            return "NaN"
        return round(value, 9)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _expect_exception(case_id: str, action: Callable[[], Any]) -> dict[str, Any]:
    try:
        _target_action(case_id, action)
    except ConfinementError:
        raise
    except Exception as exc:
        return {
            "case_id": case_id,
            "rejected": True,
            "exception_type": type(exc).__name__,
            "message_sha256": sha_bytes(str(exc).encode("utf-8")),
        }
    raise EvidenceError(f"adjacent negative was accepted: {case_id}")


def _expect_status(
    case_id: str, action: Callable[[], Any], expected: Any
) -> dict[str, Any]:
    observed = _target_action(case_id, action)
    if observed != expected:
        raise EvidenceError(
            f"adjacent negative {case_id} returned {observed!r}, expected {expected!r}"
        )
    return {
        "case_id": case_id,
        "rejected": True,
        "exception_type": None,
        "message_sha256": sha_bytes(str(expected).encode("utf-8")),
    }


def _product_call(
    label: str, function: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Count one literal executor-to-imported-product function invocation."""
    if _ACTIVE_PRODUCT_CALLS is None:
        raise EvidenceError("product function called outside a capability action")
    _ACTIVE_PRODUCT_CALLS[label] = _ACTIVE_PRODUCT_CALLS.get(label, 0) + 1
    return function(*args, **kwargs)


def _target_action(case_id: str, action: Callable[[], Any]) -> Any:
    """Count one observed bounded target action and its paired local request."""
    if _ACTIVE_ACTION_COUNTS is None:
        raise EvidenceError("target action called outside a capability execution")
    if case_id in _ACTIVE_ACTION_COUNTS:
        raise EvidenceError(f"duplicate target action id: {case_id}")
    _ACTIVE_ACTION_COUNTS[case_id] = 1
    return action()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def scan_temp_root(root: Path) -> dict[str, dict[str, Any]]:
    """Return an exact deterministic inventory, rejecting symlinks/special files."""
    inventory: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ConfinementError(f"temporary tree contains symlink: {relative}")
        if stat.S_ISDIR(mode):
            inventory[relative] = {"type": "directory"}
        elif stat.S_ISREG(mode):
            inventory[relative] = {
                "type": "file",
                "size": path.stat().st_size,
                "sha256": sha_file(path),
            }
        else:
            raise ConfinementError(f"temporary tree contains special file: {relative}")
    return inventory


def require_exact_owned_tree(
    inventory: dict[str, dict[str, Any]], namespace: str
) -> None:
    prefix = f"{namespace}/"
    if namespace not in inventory or inventory[namespace] != {"type": "directory"}:
        raise ConfinementError(
            f"owned namespace missing from temporary tree: {namespace}"
        )
    escaped = [
        name for name in inventory if name != namespace and not name.startswith(prefix)
    ]
    if escaped:
        raise ConfinementError(
            f"temporary tree contains sibling escape: {', '.join(escaped)}"
        )


CAPABILITY_OWNER_MAX_ENTRIES = 512
CAPABILITY_OWNER_MAX_BYTES = 64 * 1024 * 1024


def validate_capability_owner_tree(
    inventory: dict[str, dict[str, Any]], owner: str
) -> tuple[int, int]:
    require_exact_owned_tree(inventory, owner)
    allowed_prefixes = (f"{owner}/cache", f"{owner}/work")
    unexpected = [
        name
        for name in inventory
        if name != owner
        and not any(
            name == prefix or name.startswith(f"{prefix}/")
            for prefix in allowed_prefixes
        )
    ]
    if unexpected:
        raise ConfinementError(
            f"capability owner contains an unexpected partition: {unexpected[0]}"
        )
    entries = len(inventory)
    total_bytes = sum(
        row["size"] for row in inventory.values() if row["type"] == "file"
    )
    if entries > CAPABILITY_OWNER_MAX_ENTRIES:
        raise ConfinementError(f"capability owner entry bound exceeded: {entries}")
    if total_bytes > CAPABILITY_OWNER_MAX_BYTES:
        raise ConfinementError(f"capability owner byte bound exceeded: {total_bytes}")
    return entries, total_bytes


def validate_removed_temporary_root(value: Any) -> Path:
    """Validate the canonical, independently parent-bound cleanup identity."""
    if not isinstance(value, str) or not value:
        raise EvidenceError("execution cleanup root identity is absent")
    temporary_root = Path(value)
    suffix = temporary_root.name.removeprefix(TEMP_PREFIX)
    try:
        expected_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("execution temporary parent is inaccessible") from exc
    if (
        not temporary_root.is_absolute()
        or os.path.normpath(value) != value
        or not temporary_root.name.startswith(TEMP_PREFIX)
        or not suffix
        or temporary_root.parent != expected_parent
        or os.path.lexists(value)
    ):
        raise EvidenceError("execution cleanup root identity is invalid")
    return temporary_root


@contextlib.contextmanager
def capability_owner_namespace(
    temp_base: Path, capability_id: str
) -> Iterator[dict[str, Any]]:
    """Own cache and work partitions for one full preflight/adapter lifetime."""
    global _ACTIVE_NAMESPACE
    if _ACTIVE_NAMESPACE is not None:
        raise EvidenceError("capability owner entered while another is active")
    owner = temp_base / NAMESPACES[capability_id]
    if owner.exists() or scan_temp_root(temp_base):
        raise ConfinementError("capability owner did not start from an empty tree")
    _ACTIVE_NAMESPACE = owner
    owner.mkdir(mode=0o700)
    state: dict[str, Any] = {
        "owner": owner,
        "work": owner / "work",
        "owned_tree_sha256": None,
        "entry_count": None,
        "aggregate_bytes": None,
    }
    environment_values = {
        "MPLCONFIGDIR": os.fspath(owner / "cache/matplotlib"),
        "XDG_CACHE_HOME": os.fspath(owner / "cache/xdg-cache"),
        "XDG_CONFIG_HOME": os.fspath(owner / "cache/xdg-config"),
        # Matplotlib otherwise shells out to fc-list while building a fresh font
        # cache. Use only its wheel-bundled fonts so subprocess confinement stays
        # exact and provider-free.
        "MPL_IGNORE_SYSTEM_FONTS": "1",
        # joblib otherwise probes physical cores with lscpu during the nuScenes
        # import chain. The bounded executor is deliberately single-process.
        "LOKY_MAX_CPU_COUNT": "1",
    }
    previous = {key: os.environ.get(key) for key in environment_values}
    os.environ.update(environment_values)
    try:
        yield state
        owned_tree = scan_temp_root(temp_base)
        entries, total_bytes = validate_capability_owner_tree(owned_tree, owner.name)
        state["owned_tree_sha256"] = sha_bytes(canonical_bytes(owned_tree))
        state["entry_count"] = entries
        state["aggregate_bytes"] = total_bytes
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _ACTIVE_NAMESPACE = owner
        try:
            if owner.exists():
                shutil.rmtree(owner)
        finally:
            _ACTIVE_NAMESPACE = None
        if owner.exists() or scan_temp_root(temp_base):
            raise ConfinementError("capability owner cleanup failed")


def _calibration_grouping(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    group = _import_product("spatialai_data_utils.core.cameras.group_utils")
    origin = _import_product("spatialai_data_utils.core.cameras.origin")

    def positive() -> dict[str, Any]:
        calibration = {"sensors": copy.deepcopy(fixture["sensors"])}
        moves = _product_call("group.parse_moves", group.parse_moves, fixture["moves"])
        updated, warnings = _product_call(
            "group.apply_group_reassignments",
            group.apply_group_reassignments,
            calibration,
            moves,
            strict=True,
        )
        computed = _product_call(
            "origin.calculate_and_update_group_origins",
            origin.calculate_and_update_group_origins,
            calibration,
            use_frustum=False,
            dilation_distance=1.0,
            image_size=(64, 48),
        )
        groups = {
            sensor["id"]: {
                "name": sensor["group"]["name"],
                "origin": sensor["group"]["origin"],
                "dimensions": sensor["group"]["dimensions"],
            }
            for sensor in computed["sensors"]
        }
        if (
            updated != 1
            or warnings
            or {row["name"] for row in groups.values()} != {"bev-sensor-1"}
        ):
            raise EvidenceError("camera grouping semantic assertion failed")
        return _jsonable({"updated": updated, "groups": groups})

    first = _target_action("positive-run-1", positive)
    second = _target_action("positive-run-2", positive)
    negatives = [
        _expect_exception(
            "malformed-move",
            lambda: _product_call(
                "group.parse_moves", group.parse_moves, ["Camera_00"]
            ),
        ),
        _expect_exception(
            "empty-camera",
            lambda: _product_call(
                "group.parse_moves", group.parse_moves, [":bev-sensor-1"]
            ),
        ),
        _expect_exception(
            "empty-group",
            lambda: _product_call(
                "group.parse_moves", group.parse_moves, ["Camera_00:"]
            ),
        ),
        _expect_exception(
            "unknown-camera-strict",
            lambda: _product_call(
                "group.apply_group_reassignments",
                group.apply_group_reassignments,
                {"sensors": copy.deepcopy(fixture["sensors"])},
                [("missing", "bev-sensor-1")],
                strict=True,
            ),
        ),
        _expect_exception(
            "unknown-group-strict",
            lambda: _product_call(
                "group.apply_group_reassignments",
                group.apply_group_reassignments,
                {"sensors": copy.deepcopy(fixture["sensors"])},
                [("Camera_00", "missing")],
                strict=True,
            ),
        ),
    ]
    if first != second:
        raise EvidenceError("camera grouping output is not deterministic")
    return first, negatives


def _geometry_projection(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    del root
    np = _import_product("numpy")
    boxes = _import_product("spatialai_data_utils.core.boxes.box_3d")
    projection = _import_product("spatialai_data_utils.core.geometry.projection")

    def positive() -> dict[str, Any]:
        values = np.asarray(fixture["boxes_9dof"], dtype=np.float64)
        corners = _product_call(
            "boxes.box3d_to_corners", boxes.box3d_to_corners, values
        )
        pixels, visible = _product_call(
            "projection.project_boxes_3d_to_2d",
            projection.project_boxes_3d_to_2d,
            values,
            fixture["calibration"],
            image_size=tuple(fixture["image_size"]),
        )
        if visible != fixture["expected_visible_ids"] or pixels.shape != (1, 8, 2):
            raise EvidenceError("projection visibility assertion failed")
        return _jsonable(
            {
                "corner_shape": list(corners.shape),
                "visible_ids": visible,
                "pixels": pixels,
            }
        )

    first = _target_action("positive-run-1", positive)
    second = _target_action("positive-run-2", positive)
    offscreen = np.asarray([fixture["boxes_9dof"][1]], dtype=np.float64)

    def fully_offscreen() -> tuple[Any, Any]:
        return _product_call(
            "projection.project_boxes_3d_to_2d",
            projection.project_boxes_3d_to_2d,
            offscreen,
            fixture["calibration"],
            image_size=tuple(fixture["image_size"]),
        )

    off_pixels, off_visible = _target_action("fully-offscreen", fully_offscreen)
    if off_visible or off_pixels.shape != (0, 8, 2):
        raise EvidenceError("offscreen visibility negative was accepted")
    negatives = [
        _expect_exception(
            "legacy-7dof",
            lambda: _product_call(
                "boxes.box3d_to_corners",
                boxes.box3d_to_corners,
                np.asarray([[0, 0, 10, 2, 4, 2, 0]], dtype=float),
            ),
        ),
        {
            "case_id": "fully-offscreen",
            "rejected": True,
            "exception_type": None,
            "message_sha256": sha_bytes(b"empty-visible-set"),
        },
        _expect_exception(
            "missing-intrinsic",
            lambda: _product_call(
                "projection.project_boxes_3d_to_2d",
                projection.project_boxes_3d_to_2d,
                np.asarray([fixture["boxes_9dof"][0]], dtype=float),
                {"w2c_matrix": np.eye(4)},
            ),
        ),
        _expect_exception(
            "scalar-box",
            lambda: _product_call(
                "boxes.box3d_to_corners", boxes.box3d_to_corners, np.asarray(1.0)
            ),
        ),
        _expect_exception(
            "malformed-world2img",
            lambda: _product_call(
                "projection.project_points_3d_to_image",
                projection.project_points_3d_to_image,
                np.zeros((1, 8, 3)),
                np.eye(2),
            ),
        ),
    ]
    if first != second:
        raise EvidenceError("geometry output is not deterministic")
    return first, negatives


def _multiview_visualization(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    del root
    np = _import_product("numpy")
    visual = _import_product("spatialai_data_utils.visualization.box_3d")

    def positive() -> dict[str, Any]:
        shape = tuple(fixture["image_shape"])
        imgs = [np.zeros(shape, dtype=np.uint8) for _ in range(2)]
        before = [sha_bytes(item.tobytes()) for item in imgs]
        output = _product_call(
            "visual.draw_bbox3d_multicam",
            visual.draw_bbox3d_multicam,
            np.asarray(fixture["boxes_9dof"], dtype=float),
            imgs,
            world2imgs=[
                np.asarray(item, dtype=float) for item in fixture["world2imgs"]
            ],
            shade_heading=False,
        )
        after = [sha_bytes(item.tobytes()) for item in imgs]
        if (
            before != after
            or output.shape != (96, 352, 3)
            or int(np.count_nonzero(output)) == 0
        ):
            raise EvidenceError("multiview semantic assertion failed")
        return {
            "shape": list(output.shape),
            "nonzero_pixels": int(np.count_nonzero(output)),
            "pixel_sha256": sha_bytes(output.tobytes()),
            "inputs_unchanged": True,
        }

    first = _target_action("positive-run-1", positive)
    second = _target_action("positive-run-2", positive)
    image = np.zeros(tuple(fixture["image_shape"]), dtype=np.uint8)
    box = np.asarray(fixture["boxes_9dof"], dtype=float)
    world = np.asarray(fixture["world2imgs"][0], dtype=float)
    negatives = [
        _expect_exception(
            "missing-transform",
            lambda: _product_call(
                "visual.draw_bbox3d_on_img", visual.draw_bbox3d_on_img, box, image
            ),
        ),
        _expect_exception(
            "ambiguous-transform",
            lambda: _product_call(
                "visual.draw_bbox3d_on_img",
                visual.draw_bbox3d_on_img,
                box,
                image,
                world2img=world,
                calib_info={},
            ),
        ),
        _expect_exception(
            "legacy-7dof",
            lambda: _product_call(
                "visual.draw_bbox3d_on_img",
                visual.draw_bbox3d_on_img,
                box[:, :7],
                image,
                world2img=world,
            ),
        ),
        _expect_exception(
            "malformed-world2img",
            lambda: _product_call(
                "visual.draw_bbox3d_on_img",
                visual.draw_bbox3d_on_img,
                box,
                image,
                world2img=np.eye(2),
            ),
        ),
        _expect_exception(
            "missing-image",
            lambda: _product_call(
                "visual.draw_bbox3d_on_img",
                visual.draw_bbox3d_on_img,
                box,
                None,
                world2img=world,
            ),
        ),
    ]
    if first != second:
        raise EvidenceError("multiview output is not deterministic")
    return first, negatives


def _detection_row(fixture: dict[str, Any], confidence: float | None) -> dict[str, Any]:
    bbox = {"coordinates": fixture["perfect_box"]}
    if confidence is not None:
        bbox["confidence"] = confidence
    return {
        "id": 1,
        "sensorId": "Camera_00",
        "timestamp": fixture["timestamp"],
        "objects": [{"id": 1, "type": fixture["class_name"], "bbox3d": bbox}],
    }


def _detection_map(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    loaders = _import_product("spatialai_data_utils.eval.detection.loaders")
    evaluate = _import_product("spatialai_data_utils.eval.detection.evaluate")
    classes = _import_product("spatialai_data_utils.eval.detection.data_classes")

    def positive(label: str) -> dict[str, Any]:
        case = root / label
        case.mkdir()
        gt_path, pred_path = case / "gt.jsonl", case / "pred.jsonl"
        _write_json(gt_path, _detection_row(fixture, None))
        _write_json(pred_path, _detection_row(fixture, 0.9))
        gt, pred = _product_call(
            "detection.load_boxes_from_jsonl",
            loaders.load_boxes_from_jsonl,
            str(gt_path),
            str(pred_path),
            fps=fixture["fps"],
            confidence_threshold=fixture["confidence_threshold"],
        )
        config = classes.DetectionConfig(
            # The product loader emits its canonical, case-sensitive primary
            # class name ("Person" in this locked fixture).
            class_range={fixture["class_name"]: 50},
            dist_fcn="center_distance",
            dist_ths=[0.5, 1.0],
            dist_th_tp=0.5,
            min_recall=0.0,
            min_precision=0.0,
            max_boxes_per_sample=500,
            mean_ap_weight=5,
        )
        metrics, details = _product_call(
            "detection.evaluate_detection",
            evaluate.evaluate_detection,
            gt,
            pred,
            config,
            verbose=False,
        )
        summary = _product_call(
            "detection.save_detection_results",
            evaluate.save_detection_results,
            metrics,
            details,
            str(case / "out"),
        )
        semantic = copy.deepcopy(summary)
        semantic.pop("eval_time", None)
        if float(semantic["mean_ap"]) <= 0.99:
            raise EvidenceError("perfect detection mAP assertion failed")
        written_files = sorted(
            path.name for path in (case / "out").iterdir() if path.is_file()
        )
        written_summary = strict_json(case / "out" / "metrics_summary.json")
        written_summary.pop("eval_time", None)
        output_hashes = {
            "metrics_details.json": sha_file(case / "out" / "metrics_details.json"),
            "metrics_summary.json#without-eval_time": sha_bytes(
                canonical_bytes(written_summary)
            ),
        }
        return _jsonable(
            {
                "summary": semantic,
                "written_files": written_files,
                "semantic_output_sha256": output_hashes,
                "determinism_scope": "semantic_payload_excluding_eval_time",
            }
        )

    first = _target_action("positive-run-1", lambda: positive("run-1"))
    second = _target_action("positive-run-2", lambda: positive("run-2"))
    missing = root / "missing.jsonl"
    invalid = root / "invalid.jsonl"
    invalid.write_text("{not-json}\n", encoding="utf-8")
    valid = root / "valid.jsonl"
    _write_json(valid, _detection_row(fixture, 0.9))
    bad_time = root / "bad-time.jsonl"
    bad_time_row = _detection_row(fixture, 0.9)
    bad_time_row["timestamp"] = "not-a-timestamp"
    _write_json(bad_time, bad_time_row)
    short_box = root / "short-box.jsonl"
    short_row = _detection_row(fixture, 0.9)
    short_row["objects"][0]["bbox3d"]["coordinates"] = [0.0] * 7
    _write_json(short_box, short_row)
    negatives = [
        _expect_exception(
            "missing-ground-truth",
            lambda: _product_call(
                "detection.load_boxes_from_jsonl",
                loaders.load_boxes_from_jsonl,
                str(missing),
                str(valid),
                fps=fixture["fps"],
            ),
        ),
        _expect_exception(
            "missing-prediction",
            lambda: _product_call(
                "detection.load_boxes_from_jsonl",
                loaders.load_boxes_from_jsonl,
                str(valid),
                str(missing),
                fps=fixture["fps"],
            ),
        ),
        _expect_exception(
            "malformed-jsonl",
            lambda: _product_call(
                "detection.load_boxes_from_jsonl",
                loaders.load_boxes_from_jsonl,
                str(invalid),
                str(valid),
                fps=fixture["fps"],
            ),
        ),
        _expect_exception(
            "malformed-timestamp",
            lambda: _product_call(
                "detection.load_boxes_from_jsonl",
                loaders.load_boxes_from_jsonl,
                str(bad_time),
                str(valid),
                fps=fixture["fps"],
            ),
        ),
        _expect_exception(
            "legacy-short-box",
            lambda: _product_call(
                "detection.load_boxes_from_jsonl",
                loaders.load_boxes_from_jsonl,
                str(short_box),
                str(valid),
                fps=fixture["fps"],
            ),
        ),
    ]
    if first != second:
        raise EvidenceError("detection semantic output is not deterministic")
    return first, negatives


def _tracking_data(np: Any, fixture: dict[str, Any], key: str) -> dict[str, Any]:
    row = fixture[key]
    gt_ids = [np.asarray(item, dtype=int) for item in row["gt_ids"]]
    tracker_ids = [np.asarray(item, dtype=int) for item in row["tracker_ids"]]
    scores = [np.asarray(item, dtype=float) for item in row["similarity_scores"]]
    return {
        "num_timesteps": fixture["num_timesteps"],
        "num_gt_dets": sum(len(item) for item in gt_ids),
        "num_tracker_dets": sum(len(item) for item in tracker_ids),
        "num_gt_ids": len({int(value) for item in gt_ids for value in item}),
        "num_tracker_ids": len({int(value) for item in tracker_ids for value in item}),
        "gt_ids": gt_ids,
        "tracker_ids": tracker_ids,
        "similarity_scores": scores,
    }


def _tracking_metrics(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    del root
    np = _import_product("numpy")
    metrics_mod = _import_product("spatialai_data_utils.eval.tracking.hota.metrics")

    def evaluate_case(key: str) -> dict[str, Any]:
        data = _tracking_data(np, fixture, key)
        values = {
            "hota": _product_call(
                "tracking.HOTA.eval_sequence",
                metrics_mod.HOTA({"PRINT_CONFIG": False}).eval_sequence,
                copy.deepcopy(data),
            ),
            "clear": _product_call(
                "tracking.CLEAR.eval_sequence",
                metrics_mod.CLEAR({"PRINT_CONFIG": False}).eval_sequence,
                copy.deepcopy(data),
            ),
            "identity": _product_call(
                "tracking.Identity.eval_sequence",
                metrics_mod.Identity({"PRINT_CONFIG": False}).eval_sequence,
                copy.deepcopy(data),
            ),
            "count": _product_call(
                "tracking.Count.eval_sequence",
                metrics_mod.Count().eval_sequence,
                copy.deepcopy(data),
            ),
        }
        return _jsonable(values)

    first = _target_action("positive-run-1", lambda: evaluate_case("perfect"))
    second = _target_action("positive-run-2", lambda: evaluate_case("perfect"))
    mismatch = _target_action(
        "identity-switch", lambda: evaluate_case("identity_mismatch")
    )
    if first["identity"]["IDF1"] != 1.0 or first["clear"]["MOTA"] != 1.0:
        raise EvidenceError("perfect tracking metric assertion failed")
    if mismatch["clear"]["IDSW"] != 1 or mismatch["identity"]["IDF1"] >= 1.0:
        raise EvidenceError("identity mismatch was not detected")
    bad_shape = _tracking_data(np, fixture, "perfect")
    bad_shape["similarity_scores"][0] = np.zeros((2, 2))
    empty_tracker = _tracking_data(np, fixture, "perfect")
    empty_tracker.update(
        {
            "num_tracker_dets": 0,
            "num_tracker_ids": 0,
            "tracker_ids": [np.asarray([], dtype=int), np.asarray([], dtype=int)],
            "similarity_scores": [np.zeros((1, 0)), np.zeros((1, 0))],
        }
    )
    empty_clear = _target_action(
        "empty-tracker",
        lambda: _product_call(
            "tracking.CLEAR.eval_sequence",
            metrics_mod.CLEAR({"PRINT_CONFIG": False}).eval_sequence,
            copy.deepcopy(empty_tracker),
        ),
    )
    if empty_clear["CLR_FN"] != 2:
        raise EvidenceError("empty tracker negative was not detected")
    empty_gt = {
        "num_timesteps": 2,
        "num_gt_dets": 0,
        "num_tracker_dets": 2,
        "num_gt_ids": 0,
        "num_tracker_ids": 1,
        "gt_ids": [np.asarray([], dtype=int), np.asarray([], dtype=int)],
        "tracker_ids": [np.asarray([0]), np.asarray([0])],
        "similarity_scores": [np.zeros((0, 1)), np.zeros((0, 1))],
    }
    empty_identity = _target_action(
        "empty-ground-truth",
        lambda: _product_call(
            "tracking.Identity.eval_sequence",
            metrics_mod.Identity({"PRINT_CONFIG": False}).eval_sequence,
            copy.deepcopy(empty_gt),
        ),
    )
    if empty_identity["IDFP"] != 2:
        raise EvidenceError("empty GT negative was not detected")
    negatives = [
        {
            "case_id": "identity-switch",
            "rejected": True,
            "exception_type": None,
            "message_sha256": sha_bytes(canonical_bytes(mismatch)),
        },
        {
            "case_id": "empty-tracker",
            "rejected": True,
            "exception_type": None,
            "message_sha256": sha_bytes(canonical_bytes(_jsonable(empty_clear))),
        },
        {
            "case_id": "empty-ground-truth",
            "rejected": True,
            "exception_type": None,
            "message_sha256": sha_bytes(canonical_bytes(_jsonable(empty_identity))),
        },
        _expect_exception(
            "similarity-shape-mismatch",
            lambda: _product_call(
                "tracking.HOTA.eval_sequence",
                metrics_mod.HOTA({"PRINT_CONFIG": False}).eval_sequence,
                bad_shape,
            ),
        ),
        _expect_exception(
            "missing-required-count",
            lambda: _product_call(
                "tracking.Count.eval_sequence",
                metrics_mod.Count().eval_sequence,
                {"num_timesteps": 1},
            ),
        ),
    ]
    if first != second:
        raise EvidenceError("tracking output is not deterministic")
    first["identity_mismatch"] = mismatch
    return first, negatives


def _nvschema_conversion(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    converter = _import_product(
        "spatialai_data_utils.converters.nusc_results_to_nvschema"
    )
    loader = _import_product("spatialai_data_utils.loaders.nvschema")
    fixed = dt.datetime.fromisoformat(fixture["fixed_utc"])

    class FixedDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return fixed if tz is None else fixed.astimezone(tz)

    def positive(label: str) -> dict[str, Any]:
        case = root / label
        case.mkdir()
        source = case / "sparse4d.json"
        _write_json(source, {"results": fixture["results"]})
        _product_call(
            "nvschema.convert_sparse4d_to_nvschema",
            converter.convert_sparse4d_to_nvschema,
            str(source),
            str(case / "out"),
            fixture["map_class_names"],
            save_embedding=True,
            base_timestamp=fixed,
        )
        output = case / "out" / "sceneA+bev-sensor-1.json"
        loaded = _product_call(
            "nvschema.load_nvschema",
            loader.load_nvschema,
            str(output),
            output_format="nvschema",
        )
        record = json.loads(output.read_text(encoding="utf-8").strip())
        obj = record["objects"][0]
        coords = obj["bbox3d"]["coordinates"]
        if record["version"] != "4.0" or coords[3:6] != [5.0, 2.0, 1.8]:
            raise EvidenceError("NVSchema conversion assertion failed")
        if obj["bbox3d"]["embedding"] != [{"vector": [0.1, 0.2, 0.3]}] or not loaded:
            raise EvidenceError("NVSchema loader round-trip assertion failed")
        return {
            "output_sha256": sha_file(output),
            "record": _jsonable(record),
            "loaded_frame_ids": sorted(loaded),
        }

    first = _target_action("positive-run-1", lambda: positive("run-1"))
    second = _target_action("positive-run-2", lambda: positive("run-2"))
    bad_class = copy.deepcopy(fixture["results"])
    next(iter(bad_class.values()))[0]["tracking_name"] = "unknown"
    bad_input = root / "bad-class.json"
    _write_json(bad_input, {"results": bad_class})
    missing_results = root / "missing-results.json"
    _write_json(missing_results, {})
    short_schema = root / "short.jsonl"
    _write_json(
        short_schema,
        {
            "id": "0",
            "sensorId": "bev",
            "objects": [
                {"id": "1", "type": "Person", "bbox3d": {"coordinates": [0] * 7}}
            ],
        },
    )
    malformed_token = root / "malformed-token.json"
    _write_json(malformed_token, {"results": {"scene-without-frame": []}})

    def convert_bad(path: Path, output: str) -> Any:
        return _product_call(
            "nvschema.convert_sparse4d_to_nvschema",
            converter.convert_sparse4d_to_nvschema,
            str(path),
            str(root / output),
            fixture["map_class_names"],
            save_embedding=True,
            base_timestamp=fixed,
        )

    negatives = [
        _expect_exception("unknown-class", lambda: convert_bad(bad_input, "bad-out")),
        _expect_exception(
            "missing-results", lambda: convert_bad(missing_results, "missing-out")
        ),
        _expect_exception(
            "strict-short-coordinates",
            lambda: _product_call(
                "nvschema.load_nvschema",
                loader.load_nvschema,
                str(short_schema),
                output_format="gt_json_aicity",
            ),
        ),
        _expect_exception(
            "invalid-output-format",
            lambda: _product_call(
                "nvschema.load_nvschema",
                loader.load_nvschema,
                str(short_schema),
                output_format="unknown",
            ),
        ),
        _expect_exception(
            "malformed-frame-token",
            lambda: convert_bad(malformed_token, "malformed-token-out"),
        ),
    ]
    if first != second:
        raise EvidenceError(
            "NVSchema output is not byte deterministic under fixed clock"
        )
    first["fixed_clock"] = fixture["fixed_utc"]
    return first, negatives


def _video_frame_tools(
    root: Path, fixture: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    np = _import_product("numpy")
    cv2 = _import_product("cv2")
    encode = _import_product(
        "spatialai_data_utils.visualization.video_utils.frame2video"
    )
    decode = _import_product(
        "spatialai_data_utils.visualization.video_utils.video2frame"
    )

    def positive(label: str) -> dict[str, Any]:
        case = root / label
        frames = case / "frames"
        frames.mkdir(parents=True)
        width, height = fixture["frame_size"]
        for index, color in zip((10, 2, 1, 20), fixture["frames_bgr"], strict=True):
            image = np.empty((height, width, 3), dtype=np.uint8)
            image[:] = color
            if not cv2.imwrite(str(frames / f"{index}.png"), image):
                raise EvidenceError("failed to materialize generated frame")
        order = [
            Path(item).name
            for item in _product_call(
                "video.list_frame_paths",
                encode.list_frame_paths,
                str(frames),
                ("*.png",),
            )
        ]
        if order != ["1.png", "2.png", "10.png", "20.png"]:
            raise EvidenceError("numeric frame ordering assertion failed")
        video = case / "tiny.mp4"
        status_encode = _product_call(
            "video.frames_to_video",
            encode.frames_to_video,
            str(frames),
            str(video),
            fps=fixture["fps"],
            codec=fixture["codec"],
            down_sample=fixture["downsample"],
            progress=False,
        )
        decoded = case / "decoded"
        status_decode = _product_call(
            "video.video_to_frames",
            decode.video_to_frames,
            str(video),
            str(decoded),
            frame_skip=fixture["frame_skip"],
            overwrite=True,
            progress=False,
        )
        paths = _product_call(
            "video.list_frame_paths", encode.list_frame_paths, str(decoded), ("*.png",)
        )
        sample = [cv2.imread(item) for item in paths]
        if status_encode != "completed" or status_decode not in {
            "completed",
            "incomplete_extraction",
        }:
            raise EvidenceError(f"codec path failed: {status_encode}/{status_decode}")
        if len(sample) != 4 or any(
            item is None or item.shape[:2] != (24, 32) for item in sample
        ):
            raise EvidenceError("decoded frame count/dimensions assertion failed")
        return {
            "order": order,
            "encode_status": status_encode,
            "decode_status": status_decode,
            "video_sha256": sha_file(video),
            "decoded_pixel_sha256": [sha_bytes(item.tobytes()) for item in sample],
        }

    first = _target_action("positive-run-1", lambda: positive("run-1"))
    second = _target_action("positive-run-2", lambda: positive("run-2"))
    empty = root / "empty"
    empty.mkdir()
    missing_video = root / "missing.mp4"
    zero_video = root / "zero.mp4"
    zero_video.touch()
    invalid_video = root / "invalid.mp4"
    invalid_video.write_bytes(b"not-a-video")
    empty_paths = _target_action(
        "empty-frame-list",
        lambda: _product_call(
            "video.list_frame_paths", encode.list_frame_paths, str(empty), ("*.png",)
        ),
    )
    if empty_paths:
        raise EvidenceError("empty frame listing negative was accepted")
    negatives = [
        {
            "case_id": "empty-frame-list",
            "rejected": True,
            "exception_type": None,
            "message_sha256": sha_bytes(b"empty-list"),
        },
        _expect_status(
            "empty-frame-directory",
            lambda: _product_call(
                "video.frames_to_video",
                encode.frames_to_video,
                str(empty),
                str(root / "empty.mp4"),
                progress=False,
            ),
            "no_frames_found",
        ),
        _expect_status(
            "missing-video",
            lambda: _product_call(
                "video.video_to_frames",
                decode.video_to_frames,
                str(missing_video),
                str(root / "missing-frames"),
            ),
            "file_not_found",
        ),
        _expect_status(
            "empty-video",
            lambda: _product_call(
                "video.video_to_frames",
                decode.video_to_frames,
                str(zero_video),
                str(root / "zero-frames"),
            ),
            "empty_file",
        ),
        _expect_status(
            "invalid-video",
            lambda: _product_call(
                "video.video_to_frames",
                decode.video_to_frames,
                str(invalid_video),
                str(root / "invalid-frames"),
            ),
            "cannot_open",
        ),
    ]
    if not all(row["rejected"] for row in negatives):
        raise EvidenceError("video/frame adjacent negative was accepted")
    if first != second:
        raise EvidenceError("video/frame output is not deterministic")
    return first, negatives


ADAPTERS: dict[
    str, Callable[[Path, dict[str, Any]], tuple[dict[str, Any], list[dict[str, Any]]]]
] = {
    "calibration_grouping": _calibration_grouping,
    "geometry_projection": _geometry_projection,
    "multiview_visualization": _multiview_visualization,
    "detection_map": _detection_map,
    "tracking_metrics": _tracking_metrics,
    "nvschema_conversion": _nvschema_conversion,
    "video_frame_tools": _video_frame_tools,
}


def _empty_result(
    capability: dict[str, Any],
    status: str,
    preflight: dict[str, Any] | None = None,
    owned_tree_sha256: str | None = None,
) -> dict[str, Any]:
    if status == "blocked" and owned_tree_sha256 is None:
        raise EvidenceError("blocked result requires an owned-tree digest")
    if status != "blocked" and owned_tree_sha256 is not None:
        raise EvidenceError("inert result cannot bind an owned-tree digest")
    return {
        "capability_id": capability["capability_id"],
        "oracle_id": capability["oracle_id"],
        "status": status,
        "independent_runs": 0,
        "bounded_capability_actions": 0,
        "requests": 0,
        "target_action_ids": [],
        "imported_product_function_invocations": 0,
        "imported_product_function_counts": {},
        "deterministic_output": False,
        "fixture_sha256": capability["fixture_manifest"]["sha256"],
        "run_output_sha256": [],
        "positive_observations": ({"preflight": preflight} if preflight else {}),
        "adjacent_negatives": [],
        "cleanup": {
            "namespace": NAMESPACES[capability["capability_id"]],
            "pre_state_captured": "absent" if status == "blocked" else "not_created",
            "temporary_files_only": True,
            "removed": True,
            "siblings_unchanged": True,
            "owned_tree_sha256": owned_tree_sha256,
            "post_cleanup_tree_sha256": EMPTY_TREE_SHA256,
        },
        "runtime_evidence_binding": {},
    }


def plan(contract: dict[str, Any], selected: set[str] | None = None) -> dict[str, Any]:
    target_environment = verify_target_environment(contract)
    selected = selected or set(EXPECTED_CAPABILITIES)
    results = [
        _empty_result(
            row, "plan" if row["capability_id"] in selected else "not_selected"
        )
        for row in contract["capabilities"]
    ]
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "plan",
        "captured_at_utc": None,
        "bindings": {
            "contract_sha256": sha_file(CONTRACT_PATH),
            "canonical_rows_are_open_unexecuted": True,
            "executor_ready_capabilities": EXPECTED_EXECUTOR_READY_CAPABILITIES,
        },
        "environment": {
            **target_environment,
            "capability_preflight": {},
        },
        "capability_results": results,
        "cleanup": {
            "executor_owned_temporary_root": None,
            "pre_execution_tree_sha256": EMPTY_TREE_SHA256,
            "post_execution_tree_sha256": EMPTY_TREE_SHA256,
            "sentinel_sha256": None,
            "checkout_status_before_sha256": None,
            "checkout_status_after_sha256": None,
            "removed": True,
            "siblings_unchanged": True,
        },
        "confinement": {
            "bounded_capability_actions": 0,
            "requests": 0,
            "imported_product_function_invocations": 0,
            "product_execution_deadline_seconds": contract["policy"][
                "product_execution_deadline_seconds"
            ],
            "network_calls": 0,
            "docker_calls": 0,
            "service_lifecycle_calls": 0,
            "model_accesses": 0,
            "downloads": 0,
            "warehouse_sample_accesses": 0,
            "product_subprocess_calls": 0,
            "filesystem_escape_attempts": 0,
            "external_activity_instrumented": True,
            "whole_temp_root_scanned": True,
        },
        "promotion": {
            "ledger_mutation_performed": False,
            "oracle_mutation_performed": False,
            "external_provider_entry_touched": False,
            "receipt_is_runtime_evidence": False,
            "aggregate_is_promotable": False,
            "individual_receipt_candidates": [],
        },
    }


def execute(
    contract: dict[str, Any], selected: set[str], allow_dirty_development: bool
) -> dict[str, Any]:
    global _ACTIVE_ACTION_COUNTS, _ACTIVE_NAMESPACE, _ACTIVE_PRODUCT_CALLS
    if not selected or not selected.issubset(EXPECTED_CAPABILITIES):
        raise EvidenceError("execution selection must contain known capabilities")
    target_environment = verify_target_environment(contract)
    bindings = verify_bindings(contract, require_clean=not allow_dirty_development)
    verify_static_locks(contract)
    captured = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    checkout_before = git("status", "--porcelain=v1", "--untracked-files=all")
    temp_base = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    temp_base_receipt_path = os.fspath(temp_base.resolve(strict=True))
    pre_tree = scan_temp_root(temp_base)
    if pre_tree:
        raise EvidenceError("executor temporary root was not initially empty")
    sentinel = temp_base.parent / f".{temp_base.name}.sentinel"
    sentinel_fd = os.open(
        sentinel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        os.write(sentinel_fd, b"spatial-ai-sentinel\n")
        os.fsync(sentinel_fd)
    finally:
        os.close(sentinel_fd)
    sentinel_hash = sha_file(sentinel)
    results: list[dict[str, Any]] = []
    preflights: dict[str, Any] = {}
    activity_counts = {key: 0 for key in EXTERNAL_ACTIVITY_KEYS}
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with (
            external_activity_denied(activity_counts),
            product_execution_deadline(
                contract["policy"]["product_execution_deadline_seconds"]
            ),
        ):
            for capability in contract["capabilities"]:
                capability_id = capability["capability_id"]
                if capability_id not in selected:
                    results.append(_empty_result(capability, "not_selected"))
                    continue
                row: dict[str, Any] | None = None
                with capability_owner_namespace(
                    temp_base, capability_id
                ) as owner_state:
                    preflight = _module_preflight(capability["adapter"])
                    preflights[capability_id] = preflight
                    if preflight["ready"]:
                        namespace = owner_state["work"]
                        if namespace.exists():
                            raise EvidenceError(
                                f"non-absent work partition: {namespace.name}"
                            )
                        namespace.mkdir(mode=0o700)
                        fixture = strict_json(
                            repo_file(capability["fixture_manifest"]["path"])
                        )
                        _ACTIVE_PRODUCT_CALLS = {}
                        _ACTIVE_ACTION_COUNTS = {}
                        try:
                            observation, negatives = ADAPTERS[capability["adapter"]](
                                namespace, fixture
                            )
                            product_counts = dict(sorted(_ACTIVE_PRODUCT_CALLS.items()))
                            target_action_ids = list(_ACTIVE_ACTION_COUNTS)
                        finally:
                            _ACTIVE_PRODUCT_CALLS = None
                            _ACTIVE_ACTION_COUNTS = None
                        if len(target_action_ids) != 7:
                            raise EvidenceError(
                                "observed target action count drift for "
                                f"{capability_id}: {len(target_action_ids)}"
                            )
                        short_id = capability_id.split(".")[2][:2]
                        if product_counts != EXPECTED_PRODUCT_FUNCTION_COUNTS[short_id]:
                            raise EvidenceError(
                                "imported product-function count drift for "
                                f"{capability_id}"
                            )
                        if sum(product_counts.values()) <= 0:
                            raise EvidenceError(
                                "passing capability has no product calls: "
                                f"{capability_id}"
                            )
                        owned_tree = scan_temp_root(temp_base)
                        validate_capability_owner_tree(
                            owned_tree, owner_state["owner"].name
                        )
                        observation_hash = sha_bytes(canonical_bytes(observation))
                        row = {
                            "capability_id": capability_id,
                            "oracle_id": capability["oracle_id"],
                            "status": "pass",
                            "independent_runs": 2,
                            "bounded_capability_actions": len(target_action_ids),
                            "requests": len(target_action_ids),
                            "target_action_ids": target_action_ids,
                            "imported_product_function_invocations": sum(
                                product_counts.values()
                            ),
                            "imported_product_function_counts": product_counts,
                            "deterministic_output": True,
                            "fixture_sha256": capability["fixture_manifest"]["sha256"],
                            "run_output_sha256": [observation_hash, observation_hash],
                            "positive_observations": observation,
                            "adjacent_negatives": negatives,
                            "cleanup": {
                                "namespace": owner_state["owner"].name,
                                "pre_state_captured": "absent",
                                "temporary_files_only": True,
                                "removed": True,
                                "siblings_unchanged": True,
                                "owned_tree_sha256": sha_bytes(
                                    canonical_bytes(owned_tree)
                                ),
                                "post_cleanup_tree_sha256": EMPTY_TREE_SHA256,
                            },
                            "runtime_evidence_binding": {
                                "captured_at_utc": captured,
                                "executor_sha256": bindings["executor_sha256"],
                                "contract_sha256": bindings["contract_sha256"],
                                "current_oracle_sha256": capability[
                                    "current_oracle_sha256"
                                ],
                                "current_ledger_row_sha256": capability[
                                    "current_ledger_row_sha256"
                                ],
                                "fixture_sha256": capability["fixture_manifest"][
                                    "sha256"
                                ],
                                "capability_evidence_sha256": observation_hash,
                                "target_case_actions": len(target_action_ids),
                                "requests": len(target_action_ids),
                                "target_action_ids_sha256": sha_bytes(
                                    canonical_bytes(target_action_ids)
                                ),
                                "imported_product_function_invocations": sum(
                                    product_counts.values()
                                ),
                                "imported_product_function_counts_sha256": sha_bytes(
                                    canonical_bytes(product_counts)
                                ),
                            },
                        }
                owned_tree_sha256 = owner_state["owned_tree_sha256"]
                if owned_tree_sha256 is None:
                    raise EvidenceError("capability owner inventory was not bound")
                if not preflight["ready"]:
                    results.append(
                        _empty_result(
                            capability,
                            "blocked",
                            preflight,
                            owned_tree_sha256=owned_tree_sha256,
                        )
                    )
                    continue
                if row is None:
                    raise EvidenceError("passing capability result was not captured")
                if row["cleanup"]["owned_tree_sha256"] != owned_tree_sha256:
                    raise EvidenceError("capability owner inventory digest drift")
                results.append(row)
        if any(activity_counts.values()):
            raise ConfinementError(
                f"prohibited external activity was attempted: {activity_counts}"
            )
        passed = [row for row in results if row["status"] == "pass"]
        selected_results = [row for row in results if row["capability_id"] in selected]
        status = (
            "pass"
            if selected_results and len(passed) == len(selected_results)
            else "partial"
        )
        total_actions = sum(row["bounded_capability_actions"] for row in results)
        total_product_calls = sum(
            row["imported_product_function_invocations"] for row in results
        )
        checkout_after = git("status", "--porcelain=v1", "--untracked-files=all")
        if checkout_after != checkout_before:
            raise ConfinementError("repository worktree changed during execution")
        if not sentinel.is_file() or sha_file(sentinel) != sentinel_hash:
            raise ConfinementError("adjacent sentinel changed during execution")
        post_tree = scan_temp_root(temp_base)
        if post_tree:
            raise ConfinementError("temporary root not empty at aggregate completion")
        return {
            "schema_version": 1,
            "package_id": contract["package_id"],
            "mode": contract["mode"],
            "status": status,
            "captured_at_utc": captured,
            "bindings": bindings,
            "environment": {
                **target_environment,
                "capability_preflight": preflights,
            },
            "capability_results": results,
            "cleanup": {
                "executor_owned_temporary_root": temp_base_receipt_path,
                "pre_execution_tree_sha256": sha_bytes(canonical_bytes(pre_tree)),
                "post_execution_tree_sha256": sha_bytes(canonical_bytes(post_tree)),
                "sentinel_sha256": sentinel_hash,
                "checkout_status_before_sha256": sha_bytes(
                    checkout_before.encode("utf-8")
                ),
                "checkout_status_after_sha256": sha_bytes(
                    checkout_after.encode("utf-8")
                ),
                "removed": True,
                "siblings_unchanged": True,
            },
            "confinement": {
                "bounded_capability_actions": total_actions,
                "requests": total_actions,
                "imported_product_function_invocations": total_product_calls,
                "product_execution_deadline_seconds": contract["policy"][
                    "product_execution_deadline_seconds"
                ],
                **activity_counts,
                "external_activity_instrumented": True,
                "whole_temp_root_scanned": True,
            },
            "promotion": {
                "ledger_mutation_performed": False,
                "oracle_mutation_performed": False,
                "external_provider_entry_touched": False,
                "receipt_is_runtime_evidence": False,
                "aggregate_is_promotable": False,
                "individual_receipt_candidates": [
                    row["capability_id"] for row in passed
                ],
            },
        }
    finally:
        _ACTIVE_ACTION_COUNTS = None
        _ACTIVE_PRODUCT_CALLS = None
        _ACTIVE_NAMESPACE = None
        sys.dont_write_bytecode = previous_dont_write_bytecode
        shutil.rmtree(temp_base, ignore_errors=True)
        if temp_base.exists():
            raise ConfinementError("executor temporary root removal failed")
        if not sentinel.is_file() or sha_file(sentinel) != sentinel_hash:
            raise ConfinementError("adjacent sentinel changed during cleanup")
        sentinel.unlink()
        if git("status", "--porcelain=v1", "--untracked-files=all") != checkout_before:
            raise ConfinementError("repository worktree changed during execution")


def validate_result(result: dict[str, Any], contract: dict[str, Any]) -> None:
    schema = strict_json(RESULT_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(result),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        raise EvidenceError(f"result schema violation: {first.message}")
    if [
        row["capability_id"] for row in result["capability_results"]
    ] != EXPECTED_CAPABILITIES:
        raise EvidenceError("result capability order drift")
    expected_environment = verify_target_environment(contract)
    environment = result["environment"]
    for key, expected in expected_environment.items():
        if environment[key] != expected:
            raise EvidenceError(f"result environment drift: {key}")

    promotion = result["promotion"]
    if any(
        promotion[key]
        for key in (
            "ledger_mutation_performed",
            "oracle_mutation_performed",
            "external_provider_entry_touched",
            "receipt_is_runtime_evidence",
            "aggregate_is_promotable",
        )
    ):
        raise EvidenceError("staged producer cannot mutate or promote authority")

    contract_by_id = {row["capability_id"]: row for row in contract["capabilities"]}
    passed_ids: list[str] = []
    selected_ids: list[str] = []
    preflight = environment["capability_preflight"]
    for row in result["capability_results"]:
        capability_id = row["capability_id"]
        capability = contract_by_id[capability_id]
        short_id = capability_id.split(".")[2][:2]
        expected_oracle = capability["oracle_id"]
        if row["oracle_id"] != expected_oracle:
            raise EvidenceError(f"oracle id drift: {capability_id}")
        if row["fixture_sha256"] != capability["fixture_manifest"]["sha256"]:
            raise EvidenceError(f"fixture binding drift: {capability_id}")
        cleanup = row["cleanup"]
        if cleanup["namespace"] != NAMESPACES[capability_id]:
            raise EvidenceError(f"cleanup namespace drift: {capability_id}")
        if (
            cleanup["temporary_files_only"] is not True
            or cleanup["removed"] is not True
            or cleanup["siblings_unchanged"] is not True
            or cleanup["post_cleanup_tree_sha256"] != EMPTY_TREE_SHA256
        ):
            raise EvidenceError(f"cleanup proof drift: {capability_id}")

        status = row["status"]
        if status != "not_selected":
            selected_ids.append(capability_id)
        if status == "pass":
            passed_ids.append(capability_id)
            expected_actions = {"positive-run-1", "positive-run-2"} | set(
                EXPECTED_NEGATIVE_CASE_IDS[short_id]
            )
            if (
                row["independent_runs"] != 2
                or row["bounded_capability_actions"] != 7
                or row["requests"] != 7
                or len(row["target_action_ids"]) != 7
                or set(row["target_action_ids"]) != expected_actions
                or row["deterministic_output"] is not True
            ):
                raise EvidenceError(
                    f"passing action/determinism drift: {capability_id}"
                )
            case_ids = [item["case_id"] for item in row["adjacent_negatives"]]
            if case_ids != EXPECTED_NEGATIVE_CASE_IDS[short_id] or not all(
                item["rejected"] is True for item in row["adjacent_negatives"]
            ):
                raise EvidenceError(f"adjacent negative drift: {capability_id}")
            expected_counts = EXPECTED_PRODUCT_FUNCTION_COUNTS[short_id]
            if row["imported_product_function_counts"] != expected_counts:
                raise EvidenceError(f"product function map drift: {capability_id}")
            expected_invocations = sum(expected_counts.values())
            if (
                expected_invocations <= 0
                or row["imported_product_function_invocations"] != expected_invocations
            ):
                raise EvidenceError(f"product function total drift: {capability_id}")
            if set(row["positive_observations"]) != EXPECTED_OBSERVATION_KEYS[short_id]:
                raise EvidenceError(
                    f"positive observation shape drift: {capability_id}"
                )
            observation_hash = sha_bytes(canonical_bytes(row["positive_observations"]))
            if row["run_output_sha256"] != [observation_hash, observation_hash]:
                raise EvidenceError(
                    f"deterministic output digest drift: {capability_id}"
                )
            if (
                cleanup["pre_state_captured"] != "absent"
                or cleanup["owned_tree_sha256"] is None
            ):
                raise EvidenceError(f"passing cleanup state drift: {capability_id}")
            binding = row["runtime_evidence_binding"]
            expected_binding = {
                "captured_at_utc": result["captured_at_utc"],
                "executor_sha256": result["bindings"]["executor_sha256"],
                "contract_sha256": result["bindings"]["contract_sha256"],
                "current_oracle_sha256": capability["current_oracle_sha256"],
                "current_ledger_row_sha256": capability["current_ledger_row_sha256"],
                "fixture_sha256": capability["fixture_manifest"]["sha256"],
                "capability_evidence_sha256": observation_hash,
                "target_case_actions": 7,
                "requests": 7,
                "target_action_ids_sha256": sha_bytes(
                    canonical_bytes(row["target_action_ids"])
                ),
                "imported_product_function_invocations": expected_invocations,
                "imported_product_function_counts_sha256": sha_bytes(
                    canonical_bytes(expected_counts)
                ),
            }
            if binding != expected_binding:
                raise EvidenceError(f"runtime evidence binding drift: {capability_id}")
            if (
                capability_id not in preflight
                or preflight[capability_id]["ready"] is not True
            ):
                raise EvidenceError(f"passing preflight drift: {capability_id}")
        elif status in {"plan", "not_selected", "blocked"}:
            if any(
                (
                    row["independent_runs"],
                    row["bounded_capability_actions"],
                    row["requests"],
                    row["imported_product_function_invocations"],
                )
            ):
                raise EvidenceError(f"non-passing counter drift: {capability_id}")
            if (
                row["target_action_ids"]
                or row["imported_product_function_counts"]
                or row["deterministic_output"] is not False
                or row["run_output_sha256"]
                or row["adjacent_negatives"]
                or row["runtime_evidence_binding"]
            ):
                raise EvidenceError(f"non-passing row drift: {capability_id}")
            if status == "blocked":
                expected_observation = {"preflight": preflight.get(capability_id)}
                if (
                    capability_id not in preflight
                    or preflight[capability_id]["ready"] is not False
                    or row["positive_observations"] != expected_observation
                    or cleanup["pre_state_captured"] != "absent"
                    or cleanup["owned_tree_sha256"] is None
                ):
                    raise EvidenceError(f"blocked preflight drift: {capability_id}")
            elif (
                row["positive_observations"]
                or cleanup["pre_state_captured"] != "not_created"
                or cleanup["owned_tree_sha256"] is not None
            ):
                raise EvidenceError(f"inert row drift: {capability_id}")
        else:  # Schema should make this unreachable.
            raise EvidenceError(f"unknown capability status: {status}")

    if result["mode"] == "plan":
        if (
            result["status"] != "plan"
            or result["captured_at_utc"] is not None
            or any(
                row["status"] not in {"plan", "not_selected"}
                for row in result["capability_results"]
            )
            or preflight
        ):
            raise EvidenceError("plan mode/state coherence drift")
        expected_bindings = {
            "contract_sha256": sha_file(CONTRACT_PATH),
            "canonical_rows_are_open_unexecuted": True,
            "executor_ready_capabilities": EXPECTED_EXECUTOR_READY_CAPABILITIES,
        }
        if result["bindings"] != expected_bindings:
            raise EvidenceError("plan binding drift")
        expected_cleanup = {
            "executor_owned_temporary_root": None,
            "pre_execution_tree_sha256": EMPTY_TREE_SHA256,
            "post_execution_tree_sha256": EMPTY_TREE_SHA256,
            "sentinel_sha256": None,
            "checkout_status_before_sha256": None,
            "checkout_status_after_sha256": None,
            "removed": True,
            "siblings_unchanged": True,
        }
    else:
        if not isinstance(result["captured_at_utc"], str):
            raise EvidenceError("execution capture time is absent")
        if not selected_ids or any(
            row["status"] == "plan" for row in result["capability_results"]
        ):
            raise EvidenceError("execution selection/status coherence drift")
        expected_status = "pass" if passed_ids == selected_ids else "partial"
        if result["status"] != expected_status:
            raise EvidenceError("aggregate execution status drift")
        if set(preflight) != set(selected_ids):
            raise EvidenceError("capability preflight selection drift")
        for capability_id in selected_ids:
            adapter = contract_by_id[capability_id]["adapter"]
            if preflight[capability_id]["required_modules"] != list(
                REQUIRED_MODULES[adapter]
            ):
                raise EvidenceError(f"required module preflight drift: {capability_id}")
        bindings = result["bindings"]
        if (
            bindings["contract_sha256"] != sha_file(CONTRACT_PATH)
            or bindings["executor_sha256"] != sha_file(REPO_ROOT / EXECUTOR_REL)
            or bindings["canonical_rows_are_open_unexecuted"] is not True
            or bindings["executor_ready_capabilities"]
            != EXPECTED_EXECUTOR_READY_CAPABILITIES
        ):
            raise EvidenceError("execution binding drift")
        expected_cleanup = {
            "executor_owned_temporary_root": result["cleanup"][
                "executor_owned_temporary_root"
            ],
            "pre_execution_tree_sha256": EMPTY_TREE_SHA256,
            "post_execution_tree_sha256": EMPTY_TREE_SHA256,
            "sentinel_sha256": result["cleanup"]["sentinel_sha256"],
            "checkout_status_before_sha256": bindings[
                "checkout_status_porcelain_sha256"
            ],
            "checkout_status_after_sha256": bindings[
                "checkout_status_porcelain_sha256"
            ],
            "removed": True,
            "siblings_unchanged": True,
        }
        if (
            not expected_cleanup["executor_owned_temporary_root"]
            or not expected_cleanup["sentinel_sha256"]
        ):
            raise EvidenceError("execution cleanup identity is absent")
        validate_removed_temporary_root(
            expected_cleanup["executor_owned_temporary_root"]
        )

    if result["cleanup"] != expected_cleanup:
        raise EvidenceError("aggregate cleanup proof drift")
    if promotion["individual_receipt_candidates"] != passed_ids:
        raise EvidenceError("individual candidate list drift")
    expected_actions = sum(
        row["bounded_capability_actions"] for row in result["capability_results"]
    )
    expected_requests = sum(row["requests"] for row in result["capability_results"])
    expected_product_calls = sum(
        row["imported_product_function_invocations"]
        for row in result["capability_results"]
    )
    confinement = result["confinement"]
    if (
        confinement["bounded_capability_actions"] != expected_actions
        or confinement["requests"] != expected_requests
        or confinement["imported_product_function_invocations"]
        != expected_product_calls
        or confinement["product_execution_deadline_seconds"]
        != contract["policy"]["product_execution_deadline_seconds"]
        or confinement["external_activity_instrumented"] is not True
        or confinement["whole_temp_root_scanned"] is not True
        or any(confinement[key] != 0 for key in EXTERNAL_ACTIVITY_KEYS)
    ):
        raise EvidenceError("aggregate confinement/accounting drift")


def _resolve_selection(values: list[str] | None) -> set[str]:
    if not values:
        return set(EXPECTED_CAPABILITIES)
    selected: set[str] = set()
    for value in values:
        capability_id = SHORT_IDS.get(value, value)
        if capability_id not in EXPECTED_CAPABILITIES:
            raise EvidenceError(f"unknown capability selection: {value}")
        selected.add(capability_id)
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--select", action="append", metavar="00..06_OR_FULL_ID")
    parser.add_argument("--allow-dirty-development", action="store_true")
    parser.add_argument("--acknowledge")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        require_default_contract(args.contract)
        contract = load_contract(args.contract)
        verify_static_locks(contract)
        selected = _resolve_selection(args.select)
        if args.execute:
            if args.acknowledge != ACK:
                raise EvidenceError(f"--execute requires --acknowledge {ACK}")
            if args.output is None:
                raise EvidenceError("--execute requires --output")
            result = execute(contract, selected, args.allow_dirty_development)
        else:
            if (
                args.output is not None
                or args.acknowledge is not None
                or args.allow_dirty_development
            ):
                raise EvidenceError("execution-only flags require --execute")
            result = plan(contract, selected)
        validate_result(result, contract)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.execute:
            publish_receipt_exclusive(args.output, rendered)
        else:
            print(rendered, end="")
        return 0
    except EvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
