#!/usr/bin/env python3
"""Build and verify an ephemeral SpatialAI environment from locked local wheels."""

from __future__ import annotations

import sys

if __name__ == "__main__" and not sys.flags.isolated:
    print(
        "ERROR: direct execution requires isolated mode: python3 -I materializer.py",
        file=sys.stderr,
    )
    raise SystemExit(1)

import argparse
import ctypes
import datetime as dt
import email
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sysconfig
import tempfile
from typing import Any, Iterable
import zipfile

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
PRODUCT_ROOT = REPO_ROOT / "libs/analytics/spatialai-data-utils"
PRODUCT_ROOT_REL = os.fspath(PRODUCT_ROOT.relative_to(REPO_ROOT))
LOCK_PATH = HERE / "lock.json"
LOCK_SCHEMA_PATH = HERE / "lock.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
PRODUCER_LOCK_PATH = HERE / "producer-lock.json"
PRODUCER_LOCK_SCHEMA_PATH = HERE / "producer-lock.schema.json"
INTEGRATED_RECEIPT_SCHEMA_PATH = HERE / "integrated-receipt.schema.json"
PRODUCER_ROOT = HERE.parent / "spatial-ai-utils-runtime-evidence-successor"
PRODUCER_ROOT_REL = os.fspath(PRODUCER_ROOT.relative_to(REPO_ROOT))
PRODUCER_CONTRACT_PATH = PRODUCER_ROOT / "contract.json"
PRODUCER_CONTRACT_SCHEMA_PATH = PRODUCER_ROOT / "contract.schema.json"
PRODUCER_EXECUTOR_PATH = PRODUCER_ROOT / "executor.py"
PRODUCER_RESULT_SCHEMA_PATH = PRODUCER_ROOT / "result.schema.json"
METADATA_SELECTOR_REL = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
METADATA_SELECTOR_SCHEMA_REL = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
METADATA_SET_SCHEMA_REL = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
ACK = "I_ACKNOWLEDGE_EPHEMERAL_OFFLINE_SPATIAL_AI_ENV"
PRODUCER_ACK = "I_ACKNOWLEDGE_OFFLINE_SPATIAL_AI_UTILS_RUNTIME_EVIDENCE"
TEMP_PREFIX = "vss-spatial-ai-offline-env."
PRODUCER_TEMP_PREFIX = "vss-spatial-ai-runtime."
PRODUCER_TIMEOUT_SECONDS = 930
CAPABILITY_IDS = [
    "manifest-entry.spatial-ai-utils.00-calibration-and-camera-grouping",
    "manifest-entry.spatial-ai-utils.01-3d-2d-geometry",
    "manifest-entry.spatial-ai-utils.02-multiview-visualization",
    "manifest-entry.spatial-ai-utils.03-detection-map",
    "manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count",
    "manifest-entry.spatial-ai-utils.05-nvschema-conversion",
    "manifest-entry.spatial-ai-utils.06-video-frame-tools",
]
EXECUTOR_READY_CAPABILITY_IDS = [CAPABILITY_IDS[index] for index in (1, 4, 5)]
PRODUCT_FUNCTION_CALLS_BY_CAPABILITY = dict(
    zip(CAPABILITY_IDS, (17, 15, 11, 37, 16, 9, 17), strict=True)
)
NEGATIVE_CASE_IDS = {
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
PRODUCT_FUNCTION_COUNTS = {
    "00": {
        "bev.calculate_group_origins_from_calibration": 2,
        "bev.create_camera_clusters_from_calibration": 2,
        "bev.create_camera_groups_from_calibration": 2,
        "group.apply_group_reassignments": 4,
        "group.parse_moves": 5,
        "origin.calculate_and_update_group_origins": 2,
    },
    "01": {
        "boxes.box3d_to_corners": 4,
        "projection.project_bev_objects_bbox_in_image": 2,
        "projection.project_boxes_3d_to_2d": 4,
        "projection.project_points_3d_to_image": 3,
        "projection_cli.main": 2,
    },
    "02": {
        "visual.draw_bbox3d_on_bev": 2,
        "visual.draw_bbox3d_multicam": 2,
        "visual.draw_bbox3d_on_img": 7,
    },
    "03": {
        "detection.accumulate": 8,
        "detection.calc_ap": 8,
        "detection.evaluate_detection": 4,
        "detection.evaluate_detection_per_BEV_sensor": 2,
        "detection.load_boxes_from_jsonl": 9,
        "detection.save_detection_results": 4,
        "detection.split_files_by_sensor": 2,
    },
    "04": {
        "tracking.CLEAR.eval_sequence": 4,
        "tracking.Count.eval_sequence": 4,
        "tracking.HOTA.eval_sequence": 4,
        "tracking.Identity.eval_sequence": 4,
    },
    "05": {"nvschema.convert_sparse4d_to_nvschema": 5, "nvschema.load_nvschema": 4},
    "06": {
        "video.frames_to_video": 3,
        "video.list_frame_paths": 7,
        "video.video_to_frames": 7,
    },
}
REQUIRED_MODULES = {
    "calibration_grouping": ["numpy", "shapely"],
    "geometry_projection": ["numpy"],
    "multiview_visualization": ["numpy", "cv2"],
    "detection_map": ["numpy", "pandas", "nuscenes"],
    "tracking_metrics": ["numpy", "scipy"],
    "nvschema_conversion": ["numpy", "scipy"],
    "video_frame_tools": ["numpy", "cv2", "tqdm"],
}
EMPTY_TREE_SHA256 = hashlib.sha256(b"{}").hexdigest()
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
NETWORK_DENIAL_MARKER = "VSS_OFFLINE_NETWORK_DENIED"
DEFAULT_CACHE_ROOT = Path(
    os.environ.get("PIP_CACHE_DIR", Path.home() / ".cache" / "pip")
)


class MaterializationError(RuntimeError):
    """A lock, cache, confinement, install, validation, or cleanup check failed."""


def require_isolated_execution() -> None:
    if not sys.flags.isolated:
        raise MaterializationError("execution requires Python isolated mode (-I)")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_json_bytes(payload: bytes, label: str) -> Any:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise MaterializationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"invalid JSON: {label}") from exc


def strict_json(path: Path) -> Any:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise MaterializationError(f"invalid JSON: {path}") from exc
    return _strict_json_bytes(payload, os.fspath(path))


def _read_repo_json_record(relative: str) -> tuple[bytes, Any]:
    path = _repo_file(relative)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise MaterializationError(f"repository JSON read failed: {relative}") from exc
    return payload, _strict_json_bytes(payload, relative)


def schema_errors(value: Any, schema_path: Path) -> list[str]:
    schema = strict_json(schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in errors
    ]


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    try:
        if path.is_symlink() or path.resolve(strict=True) != LOCK_PATH.resolve(
            strict=True
        ):
            raise MaterializationError("--lock must name the canonical lock.json")
    except OSError as exc:
        raise MaterializationError("lock is absent or inaccessible") from exc
    lock = strict_json(path)
    errors = schema_errors(lock, LOCK_SCHEMA_PATH)
    if errors:
        raise MaterializationError(f"lock schema violation: {errors[0]}")
    artifacts = lock["artifacts"]
    names = [row["name"] for row in artifacts]
    filenames = [row["canonical_filename"] for row in artifacts]
    hashes = [row["sha256"] for row in artifacts]
    if names != sorted(names) or len(set(names)) != len(names):
        raise MaterializationError("artifact names must be unique and sorted")
    if len(set(filenames)) != len(filenames) or len(set(hashes)) != len(hashes):
        raise MaterializationError("artifact filenames and hashes must be unique")
    if len(artifacts) != lock["policy"]["artifact_count"]:
        raise MaterializationError("artifact count drift")
    for row in artifacts:
        if row["cache_identity"]["version"] != row["version"]:
            raise MaterializationError(f"cache version drift: {row['name']}")
    return lock


def validate_host(lock: dict[str, Any]) -> dict[str, str]:
    expected = lock["target"]
    observed = {
        "system": platform.system(),
        "machine": platform.machine(),
        "python_major_minor": ".".join(platform.python_version_tuple()[:2]),
        "python": platform.python_version(),
        "implementation": "cp" if platform.python_implementation() == "CPython" else "",
        "abi": f"cp{sys.version_info.major}{sys.version_info.minor}",
        "soabi": str(sysconfig.get_config_var("SOABI")),
    }
    for key in (
        "system",
        "machine",
        "python_major_minor",
        "implementation",
        "abi",
        "soabi",
    ):
        if observed[key] != expected[key]:
            raise MaterializationError(
                f"host {key} mismatch: expected {expected[key]}, observed {observed[key]}"
            )
    return observed


def _safe_existing_directory(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        if absolute.is_symlink() or not absolute.is_dir():
            raise MaterializationError(
                f"{label} is not a regular directory: {absolute}"
            )
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise MaterializationError(
            f"{label} is absent or inaccessible: {absolute}"
        ) from exc
    lowered = {part.lower() for part in resolved.parts}
    if lowered & {"warehouse", "model", "models"}:
        raise MaterializationError(
            f"{label} names a forbidden data boundary: {resolved}"
        )
    return resolved


def _iter_cache_candidates(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            base = Path(directory)
            dirnames[:] = sorted(
                name for name in dirnames if not (base / name).is_symlink()
            )
            for name in sorted(filenames):
                if not (name.endswith(".body") or name.endswith(".whl")):
                    continue
                path = base / name
                try:
                    mode = path.lstat().st_mode
                except OSError:
                    continue
                if stat.S_ISREG(mode) and not stat.S_ISLNK(mode):
                    yield path


def inspect_locked_wheel(path: Path, artifact: dict[str, Any]) -> None:
    try:
        with zipfile.ZipFile(path) as wheel:
            metadata_paths = [
                name
                for name in wheel.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            wheel_paths = [
                name for name in wheel.namelist() if name.endswith(".dist-info/WHEEL")
            ]
            if len(metadata_paths) != 1 or len(wheel_paths) != 1:
                raise MaterializationError(
                    f"wheel metadata cardinality drift: {artifact['name']}"
                )
            metadata = wheel.read(metadata_paths[0])
            wheel_metadata = email.message_from_bytes(wheel.read(wheel_paths[0]))
            package_metadata = email.message_from_bytes(metadata)
            observed = {
                "project": package_metadata.get("Name"),
                "version": package_metadata.get("Version"),
                "dist_info": metadata_paths[0].split("/")[0],
                "metadata_sha256": sha_bytes(metadata),
                "root_is_purelib": wheel_metadata.get("Root-Is-Purelib") == "true",
                "wheel_tags": wheel_metadata.get_all("Tag", []),
            }
            expected = {
                "project": artifact["cache_identity"]["project"],
                "version": artifact["version"],
                "dist_info": artifact["dist_info"],
                "metadata_sha256": artifact["metadata_sha256"],
                "root_is_purelib": artifact["root_is_purelib"],
                "wheel_tags": artifact["wheel_tags"],
            }
            if observed != expected:
                raise MaterializationError(
                    f"embedded wheel metadata drift: {artifact['name']}"
                )
            bad_member = wheel.testzip()
            if bad_member is not None:
                raise MaterializationError(
                    f"wheel CRC failure for {artifact['name']}: {bad_member}"
                )
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise MaterializationError(f"invalid locked wheel: {artifact['name']}") from exc


def resolve_cache_artifacts(
    lock: dict[str, Any], cache_roots: list[Path]
) -> tuple[dict[str, Path], dict[str, int]]:
    roots = [_safe_existing_directory(path, "cache root") for path in cache_roots]
    by_size: dict[int, list[dict[str, Any]]] = {}
    for artifact in lock["artifacts"]:
        by_size.setdefault(artifact["size"], []).append(artifact)
    matches: dict[str, list[Path]] = {row["sha256"]: [] for row in lock["artifacts"]}
    examined = 0
    for candidate in _iter_cache_candidates(roots):
        examined += 1
        try:
            rows = by_size.get(candidate.stat().st_size)
        except OSError:
            continue
        if not rows:
            continue
        digest = sha_file(candidate)
        if digest in matches:
            matches[digest].append(candidate)
    missing = [row["name"] for row in lock["artifacts"] if not matches[row["sha256"]]]
    if missing:
        raise MaterializationError(
            "locked artifacts absent from configured caches: " + ", ".join(missing)
        )
    resolved: dict[str, Path] = {}
    duplicates = 0
    for artifact in lock["artifacts"]:
        sources = sorted(matches[artifact["sha256"]], key=lambda path: os.fspath(path))
        duplicates += len(sources) - 1
        source = sources[0]
        inspect_locked_wheel(source, artifact)
        resolved[artifact["name"]] = source
    return resolved, {
        "configured_roots": len(cache_roots),
        "existing_roots": len(roots),
        "regular_candidates_examined": examined,
        "matched_artifacts": len(resolved),
        "duplicate_content_sources": duplicates,
    }


def materialize_wheelhouse(
    lock: dict[str, Any], sources: dict[str, Path], wheelhouse: Path
) -> dict[str, Any]:
    wheelhouse.mkdir(mode=0o700)
    inventory: list[dict[str, Any]] = []
    for artifact in lock["artifacts"]:
        source = sources[artifact["name"]]
        destination = wheelhouse / artifact["canonical_filename"]
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        if (
            destination.stat().st_size != artifact["size"]
            or sha_file(destination) != artifact["sha256"]
        ):
            raise MaterializationError(f"materialized wheel drift: {artifact['name']}")
        inspect_locked_wheel(destination, artifact)
        inventory.append(
            {
                "filename": artifact["canonical_filename"],
                "sha256": artifact["sha256"],
                "size": artifact["size"],
            }
        )
    observed_names = sorted(path.name for path in wheelhouse.iterdir())
    expected_names = sorted(row["canonical_filename"] for row in lock["artifacts"])
    if observed_names != expected_names:
        raise MaterializationError("wheelhouse file-set drift")
    return {
        "artifact_count": len(inventory),
        "aggregate_bytes": sum(row["size"] for row in inventory),
        "inventory_sha256": sha_bytes(canonical_bytes(inventory)),
    }


NETWORK_GUARD_SOURCE = f"""\
import socket
import sys

MARKER = {NETWORK_DENIAL_MARKER!r}

class OfflineNetworkDenied(RuntimeError):
    pass

def deny(*args, **kwargs):
    raise OfflineNetworkDenied(MARKER)

class OfflineSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        deny()

def audit(event, args):
    if event in {{
        "socket.__new__", "socket.connect", "socket.connect_ex", "socket.bind",
        "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
        "socket.gethostbyaddr"
    }}:
        deny()

sys.addaudithook(audit)
socket.socket = OfflineSocket
socket.SocketType = OfflineSocket
socket.socketpair = deny
socket.create_connection = deny
socket.getaddrinfo = deny
"""


# Linux AArch64 syscall numbers. The target lock rejects every other host before
# any child is launched. This inherited seccomp filter is the OS-level boundary;
# sitecustomize above adds an explicit error marker and covers resolver helpers.
_AARCH64_NETWORK_SYSCALLS = (
    198,  # socket
    199,  # socketpair
    200,  # bind
    201,  # listen
    202,  # accept
    203,  # connect
    204,  # getsockname
    205,  # getpeername
    206,  # sendto
    207,  # recvfrom
    208,  # setsockopt
    209,  # getsockopt
    210,  # shutdown
    211,  # sendmsg
    212,  # recvmsg
    242,  # accept4
    243,  # recvmmsg
    269,  # sendmmsg
)


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_SockFilter))]


def _install_no_network_seccomp() -> None:
    """Deny all Linux AArch64 socket syscalls in a child before exec."""
    bpf_ld_w_abs = 0x20
    bpf_jmp_jeq_k = 0x15
    bpf_ret_k = 0x06
    audit_arch_aarch64 = 0xC00000B7
    seccomp_ret_kill_process = 0x80000000
    seccomp_ret_errno = 0x00050000
    seccomp_ret_allow = 0x7FFF0000
    eperm = 1
    pr_set_no_new_privs = 38
    pr_set_seccomp = 22
    seccomp_mode_filter = 2

    instructions = [
        _SockFilter(bpf_ld_w_abs, 0, 0, 4),
        _SockFilter(bpf_jmp_jeq_k, 1, 0, audit_arch_aarch64),
        _SockFilter(bpf_ret_k, 0, 0, seccomp_ret_kill_process),
        _SockFilter(bpf_ld_w_abs, 0, 0, 0),
    ]
    for syscall_number in _AARCH64_NETWORK_SYSCALLS:
        instructions.extend(
            (
                _SockFilter(bpf_jmp_jeq_k, 0, 1, syscall_number),
                _SockFilter(bpf_ret_k, 0, 0, seccomp_ret_errno | eperm),
            )
        )
    instructions.append(_SockFilter(bpf_ret_k, 0, 0, seccomp_ret_allow))
    filters = (_SockFilter * len(instructions))(*instructions)
    program = _SockFprog(len(instructions), filters)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(pr_set_no_new_privs, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    if libc.prctl(pr_set_seccomp, seccomp_mode_filter, ctypes.byref(program)) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_SECCOMP failed")


def _child_environment(root: Path, guard: Path, wheelhouse: Path) -> dict[str, str]:
    home = root / "home"
    scratch = root / "tmp"
    home.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": os.fspath(home),
        "TMPDIR": os.fspath(scratch),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONPATH": os.fspath(guard),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_NO_INDEX": "1",
        "PIP_FIND_LINKS": os.fspath(wheelhouse),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PIP_ROOT_USER_ACTION": "ignore",
        "NO_PROXY": "*",
        "no_proxy": "*",
    }


def run_child(
    argv: list[str], env: dict[str, str], cwd: Path, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            preexec_fn=_install_no_network_seccomp,
        )
    except subprocess.TimeoutExpired as exc:
        raise MaterializationError(
            f"child command exceeded the {timeout}-second deadline"
        ) from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise MaterializationError(
            f"child command failed ({result.returncode}): {' '.join(argv[:4])}: "
            f"{detail[-1] if detail else '<no output>'}"
        )
    return result


def write_requirements(lock: dict[str, Any], path: Path) -> None:
    lines = [
        f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}"
        for row in lock["artifacts"]
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_environment(
    lock: dict[str, Any], root: Path, wheelhouse: Path
) -> tuple[dict[str, Any], Path, dict[str, str]]:
    guard = root / "network-guard"
    guard.mkdir(mode=0o700)
    (guard / "sitecustomize.py").write_text(NETWORK_GUARD_SOURCE, encoding="utf-8")
    env = _child_environment(root, guard, wheelhouse)
    probe = subprocess.run(
        [sys.executable, "-s", "-c", "import socket; socket.socket()"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        preexec_fn=_install_no_network_seccomp,
    )
    if probe.returncode == 0 or NETWORK_DENIAL_MARKER not in (
        probe.stdout + probe.stderr
    ):
        raise MaterializationError("network denial guard probe did not fail closed")

    kernel_probe_env = dict(env)
    kernel_probe_env.pop("PYTHONPATH")
    kernel_probe = subprocess.run(
        [sys.executable, "-s", "-c", "import socket; socket.socket()"],
        cwd=root,
        env=kernel_probe_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        preexec_fn=_install_no_network_seccomp,
    )
    if kernel_probe.returncode == 0 or "Operation not permitted" not in (
        kernel_probe.stdout + kernel_probe.stderr
    ):
        raise MaterializationError("kernel network-denial probe did not fail closed")

    venv = root / "venv"
    run_child([sys.executable, "-s", "-m", "venv", os.fspath(venv)], env, root)
    venv_python = venv / "bin" / "python"
    pip_version = run_child(
        [os.fspath(venv_python), "-s", "-m", "pip", "--version"], env, root
    ).stdout.split()[1]
    if pip_version != lock["target"]["bootstrap_pip"]:
        raise MaterializationError(
            f"bootstrap pip mismatch: expected {lock['target']['bootstrap_pip']}, "
            f"observed {pip_version}"
        )
    requirements = root / "requirements.lock.txt"
    write_requirements(lock, requirements)
    run_child(
        [
            os.fspath(venv_python),
            "-s",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            os.fspath(wheelhouse),
            "--no-deps",
            "--only-binary=:all:",
            "--require-hashes",
            "-r",
            os.fspath(requirements),
        ],
        env,
        root,
    )
    pip_check = run_child(
        [os.fspath(venv_python), "-s", "-m", "pip", "check"], env, root
    ).stdout.strip()
    if pip_check != "No broken requirements found.":
        raise MaterializationError(f"unexpected pip check output: {pip_check}")

    expected_versions = {row["name"]: row["version"] for row in lock["artifacts"]}
    smoke_script = """
import importlib
import importlib.metadata
import json
import platform
import sysconfig

expected = json.loads(%r)
imports = json.loads(%r)
observed = {name: importlib.metadata.version(name) for name in expected}
if observed != expected:
    raise SystemExit("installed version drift")
for name in imports:
    importlib.import_module(name)
print(json.dumps({
    "versions": observed,
    "imports": imports,
    "python": platform.python_version(),
    "machine": platform.machine(),
    "soabi": sysconfig.get_config_var("SOABI"),
}, sort_keys=True))
""" % (json.dumps(expected_versions), json.dumps(lock["smoke_imports"]))
    smoke_env = dict(env)
    smoke_env["PYTHONPATH"] = os.pathsep.join(
        (os.fspath(guard), os.fspath(PRODUCT_ROOT))
    )
    smoke = json.loads(
        run_child(
            [os.fspath(venv_python), "-s", "-c", smoke_script], smoke_env, root
        ).stdout
    )
    if (
        smoke["machine"] != lock["target"]["machine"]
        or smoke["soabi"] != lock["target"]["soabi"]
        or smoke["imports"] != lock["smoke_imports"]
    ):
        raise MaterializationError("import-smoke target drift")
    result = {
        "python": smoke["python"],
        "machine": smoke["machine"],
        "soabi": smoke["soabi"],
        "pip": pip_version,
        "pip_check": pip_check,
        "installed_artifact_count": len(smoke["versions"]),
        "installed_versions_sha256": sha_bytes(canonical_bytes(smoke["versions"])),
        "smoke_imports": smoke["imports"],
    }
    return result, venv_python, env


def _locked_wheelhouse(lock: dict[str, Any]) -> dict[str, Any]:
    inventory = [
        {
            "filename": row["canonical_filename"],
            "sha256": row["sha256"],
            "size": row["size"],
        }
        for row in lock["artifacts"]
    ]
    return {
        "artifact_count": len(inventory),
        "aggregate_bytes": sum(row["size"] for row in inventory),
        "inventory_sha256": sha_bytes(canonical_bytes(inventory)),
    }


def _locked_versions(lock: dict[str, Any]) -> dict[str, str]:
    return {row["name"]: row["version"] for row in lock["artifacts"]}


def _locked_source_inventory_sha256(lock: dict[str, Any]) -> str:
    inventory = [
        {
            "name": row["name"],
            "sha256": row["sha256"],
            "size": row["size"],
            "metadata_sha256": row["metadata_sha256"],
        }
        for row in lock["artifacts"]
    ]
    return sha_bytes(canonical_bytes(inventory))


def _base_receipt_bindings(lock: dict[str, Any]) -> dict[str, str]:
    return {
        "lock_sha256": sha_file(LOCK_PATH),
        "materializer_sha256": sha_file(HERE / "materializer.py"),
        "source_inventory_sha256": _locked_source_inventory_sha256(lock),
    }


def _execution_sha256(receipt: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(receipt))
    payload["bindings"].pop("execution_sha256", None)
    return sha_bytes(canonical_bytes(payload))


def _confinement_policy() -> dict[str, bool | int]:
    return {
        "network_denied": True,
        "network_guard_probe_passed": True,
        "kernel_network_denial_probe_passed": True,
        "pip_no_index": True,
        "pip_find_links_only": True,
        "pip_cache_disabled": True,
        "user_site_disabled": True,
        "docker_calls": 0,
        "service_lifecycle_calls": 0,
        "model_accesses": 0,
        "warehouse_sample_accesses": 0,
        "downloads": 0,
    }


def _promotion_policy() -> dict[str, bool]:
    return {
        "canonical_parity_mutated": False,
        "runtime_producer_mutated": False,
        "receipt_is_runtime_evidence": False,
    }


def validate_receipt(
    receipt: dict[str, Any],
    lock: dict[str, Any],
    *,
    expected_cache_scan: dict[str, int],
    expected_temporary_root: str,
) -> None:
    errors = schema_errors(receipt, RECEIPT_SCHEMA_PATH)
    if errors:
        raise MaterializationError(f"receipt schema violation: {errors[0]}")
    if receipt["target"] != lock["target"]:
        raise MaterializationError("receipt target drift")
    if receipt["policy"] != lock["policy"]:
        raise MaterializationError("receipt policy drift")
    expected_bindings = _base_receipt_bindings(lock)
    expected_bindings["execution_sha256"] = _execution_sha256(receipt)
    if receipt["bindings"] != expected_bindings:
        raise MaterializationError("receipt binding drift")
    if receipt["cache_scan"] != expected_cache_scan:
        raise MaterializationError("receipt cache-scan drift")
    artifact_count = len(lock["artifacts"])
    scan = receipt["cache_scan"]
    if (
        scan["existing_roots"] != scan["configured_roots"]
        or scan["matched_artifacts"] != artifact_count
        or scan["regular_candidates_examined"]
        < artifact_count + scan["duplicate_content_sources"]
    ):
        raise MaterializationError("receipt cache-scan invariant drift")
    if receipt["wheelhouse"] != _locked_wheelhouse(lock):
        raise MaterializationError("receipt wheelhouse drift")
    locked_versions = _locked_versions(lock)
    expected_environment = {
        "python": platform.python_version(),
        "machine": lock["target"]["machine"],
        "soabi": lock["target"]["soabi"],
        "pip": lock["target"]["bootstrap_pip"],
        "pip_check": "No broken requirements found.",
        "installed_artifact_count": len(locked_versions),
        "installed_versions_sha256": sha_bytes(canonical_bytes(locked_versions)),
        "smoke_imports": lock["smoke_imports"],
    }
    if receipt["environment"] != expected_environment:
        raise MaterializationError("receipt environment drift")
    expected_cleanup = {
        "temporary_root": expected_temporary_root,
        "pre_state": "absent",
        "removed": True,
        "sentinel_unchanged": True,
        "source_artifacts_unchanged": True,
    }
    if receipt["cleanup"] != expected_cleanup:
        raise MaterializationError("receipt cleanup drift")
    if receipt["confinement"] != _confinement_policy():
        raise MaterializationError("receipt confinement-policy drift")
    if receipt["promotion"] != _promotion_policy():
        raise MaterializationError("receipt promotion-policy drift")


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise MaterializationError(f"producer lock path escapes repository: {relative}")
    candidate = REPO_ROOT / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise MaterializationError(
            f"producer lock path is inaccessible: {relative}"
        ) from exc
    current = REPO_ROOT.resolve(strict=True)
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise MaterializationError(
                f"producer lock path contains a symlink: {relative}"
            )
    if not resolved.is_file():
        raise MaterializationError(f"producer lock path is not a file: {relative}")
    return resolved


def _validated_ancestor_commit(commit: str) -> str:
    try:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", f"{commit}^{{commit}}"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise MaterializationError(
            "producer binding commit is not an existing commit object"
        ) from exc
    if resolved != commit:
        raise MaterializationError("producer binding commit is not full canonical hex")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise MaterializationError(
            "producer binding commit is not an ancestor of the current checkout"
        )
    return resolved


def _blob_at_commit(commit: str, relative: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise MaterializationError(
            f"producer locked path is absent at binding commit: {relative}"
        ) from exc


def _verify_regular_files_at_commit(commit: str, relative_paths: list[str]) -> None:
    try:
        output = subprocess.run(
            ["git", "ls-tree", "-r", "-z", commit, "--", *relative_paths],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise MaterializationError("cannot inspect binding-commit tree modes") from exc
    observed: dict[str, str] = {}
    try:
        for record in (part for part in output.split(b"\0") if part):
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, _ = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise MaterializationError(
                    f"producer locked path is not a regular file at binding commit: {path}"
                )
            observed[path] = mode
    except (UnicodeDecodeError, ValueError) as exc:
        raise MaterializationError("invalid binding-commit tree metadata") from exc
    if set(observed) != set(relative_paths):
        raise MaterializationError("binding-commit tracked regular-file set drift")


def _validate_producer_binding_commit(lock: dict[str, Any]) -> None:
    commit = _validated_ancestor_commit(lock["producer_binding_commit"])
    locked_by_path: dict[str, str] = {}
    for row in _producer_locked_files(lock):
        prior = locked_by_path.setdefault(row["path"], row["sha256"])
        if prior != row["sha256"]:
            raise MaterializationError(
                f"conflicting producer lock hashes: {row['path']}"
            )
    paths = sorted(locked_by_path)
    _verify_regular_files_at_commit(commit, paths)
    for path in paths:
        if sha_bytes(_blob_at_commit(commit, path)) != locked_by_path[path]:
            raise MaterializationError(f"producer binding-commit blob drift: {path}")


def _tracked_root_paths(root_relative: str) -> list[str]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z", "--", root_relative],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        paths = [part.decode("utf-8") for part in output.split(b"\0") if part]
    except (subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        raise MaterializationError(
            "cannot enumerate tracked import-sensitive files"
        ) from exc
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise MaterializationError(
            "tracked import-sensitive path set is not unique and sorted"
        )
    return paths


def _verify_import_tree(root: Path, expected_relative_paths: set[str]) -> None:
    observed: set[str] = set()
    executable_suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES) + (
        ".py",
        ".pyc",
        ".pyo",
    )

    def visit(directory: Path, relative_parent: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise MaterializationError(f"cannot scan import root: {directory}") from exc
        for entry in entries:
            relative = relative_parent / entry.name
            rendered = relative.as_posix()
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise MaterializationError(
                    f"cannot inspect import-root entry: {rendered}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise MaterializationError(
                    f"import root contains a symlink: {rendered}"
                )
            if stat.S_ISDIR(mode):
                if entry.name == "__pycache__":
                    raise MaterializationError(
                        f"import root contains __pycache__: {rendered}"
                    )
                visit(Path(entry.path), relative)
            elif stat.S_ISREG(mode):
                if rendered not in expected_relative_paths:
                    classification = (
                        "executable import shadow"
                        if entry.name.endswith(executable_suffixes)
                        else "unlisted package data"
                    )
                    raise MaterializationError(
                        f"import root contains {classification}: {rendered}"
                    )
                observed.add(rendered)
            else:
                raise MaterializationError(
                    f"import root contains a special file: {rendered}"
                )

    visit(root, Path())
    if observed != expected_relative_paths:
        missing = sorted(expected_relative_paths - observed)
        raise MaterializationError(
            "import-root manifest files are absent: " + ", ".join(missing[:3])
        )


def verify_import_roots(producer_lock: dict[str, Any]) -> None:
    roots = (
        (PRODUCT_ROOT, PRODUCT_ROOT_REL, "product_root_manifest"),
        (PRODUCER_ROOT, PRODUCER_ROOT_REL, "producer_root_manifest"),
    )
    for root, root_relative, key in roots:
        prefix = root_relative + "/"
        manifest_paths = [row["path"] for row in producer_lock[key]]
        if manifest_paths != _tracked_root_paths(root_relative):
            raise MaterializationError(f"{key} tracked-path manifest drift")
        relative_paths = {
            path.removeprefix(prefix)
            for path in manifest_paths
            if path.startswith(prefix)
        }
        if len(relative_paths) != len(manifest_paths):
            raise MaterializationError(f"{key} path escaped reviewed root")
        _verify_import_tree(root, relative_paths)


def _rows_by_id(document: Any, collection: str, key: str) -> dict[str, Any]:
    if not isinstance(document, dict) or not isinstance(document.get(collection), list):
        raise MaterializationError(f"metadata {collection} collection is absent")
    rows = document[collection]
    indexed = {row.get(key): row for row in rows if isinstance(row, dict)}
    if len(indexed) != len(rows):
        raise MaterializationError(f"metadata {collection} rows are malformed")
    return indexed


def _validate_metadata_alignment(
    contract: dict[str, Any],
    selected_ledger: Any,
    selected_oracle: Any,
) -> None:
    _, root_ledger_document = _read_repo_json_record(
        contract["target"]["current_ledger_document"]
    )
    _, root_oracle_document = _read_repo_json_record(
        contract["target"]["current_oracle_document"]
    )
    expected_target = {
        "main_commit": contract["target"]["upstream_commit"],
        "product_version": contract["target"]["product_version"],
    }
    for label, document in (
        ("root ledger", root_ledger_document),
        ("root oracle", root_oracle_document),
        ("selected ledger", selected_ledger),
        ("selected oracle", selected_oracle),
    ):
        target = document.get("target") if isinstance(document, dict) else None
        if not isinstance(target, dict) or any(
            target.get(key) != value for key, value in expected_target.items()
        ):
            raise MaterializationError(f"{label} target drift")
    root_ledger = _rows_by_id(root_ledger_document, "capabilities", "id")
    root_oracles = _rows_by_id(root_oracle_document, "oracles", "capability_id")
    selected_rows = _rows_by_id(selected_ledger, "capabilities", "id")
    selected_oracles = _rows_by_id(selected_oracle, "oracles", "capability_id")
    if (
        len(root_ledger) != 289
        or len(root_oracles) != 289
        or len(selected_rows) != 500
        or len(selected_oracles) != 500
    ):
        raise MaterializationError("metadata denominator drift")
    for capability in contract["capabilities"]:
        capability_id = capability["capability_id"]
        row = root_ledger.get(capability_id)
        oracle = root_oracles.get(capability_id)
        if (
            row is None
            or oracle is None
            or selected_rows.get(capability_id) != row
            or selected_oracles.get(capability_id) != oracle
            or sha_bytes(canonical_bytes(row))
            != capability["current_ledger_row_sha256"]
            or sha_bytes(canonical_bytes(oracle)) != capability["current_oracle_sha256"]
        ):
            raise MaterializationError(
                f"root/selected SpatialAI metadata drift: {capability_id}"
            )
        readiness = oracle.get("acceptance_readiness")
        expected_classification = (
            "executor_ready"
            if capability_id in EXECUTOR_READY_CAPABILITY_IDS
            else "planning_index_only"
        )
        blockers = readiness.get("blockers") if isinstance(readiness, dict) else None
        if (
            row.get("feature_id") != "spatial-ai-utils"
            or row.get("runtime_state") != "not_qualified"
            or oracle.get("current_state") != "open_unexecuted"
            or oracle.get("evidence") != []
            or not isinstance(readiness, dict)
            or readiness.get("classification") != expected_classification
            or (expected_classification == "executor_ready" and blockers != [])
            or (
                expected_classification == "planning_index_only"
                and (not isinstance(blockers, list) or not blockers)
            )
        ):
            raise MaterializationError(
                f"root/selected SpatialAI state drift: {capability_id}"
            )
    external_id = contract["policy"]["external_provider_entry"]
    external = root_ledger.get(external_id)
    external_oracle = root_oracles.get(external_id)
    if (
        external is None
        or external_oracle is None
        or selected_rows.get(external_id) != external
        or selected_oracles.get(external_id) != external_oracle
        or (
            external.get("acceptance_class"),
            external.get("thor_state"),
            external.get("runtime_state"),
        )
        != ("external_optional", "external_optional", "not_applicable")
        or external_oracle.get("current_state") != "external_boundary_unexecuted"
    ):
        raise MaterializationError("root/selected external boundary drift")


def _active_metadata_lock_state(
    contract: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    selector_payload, selector = _read_repo_json_record(METADATA_SELECTOR_REL)
    selector_schema_payload, selector_schema = _read_repo_json_record(
        METADATA_SELECTOR_SCHEMA_REL
    )
    selector_errors = list(Draft202012Validator(selector_schema).iter_errors(selector))
    if selector_errors:
        raise MaterializationError(
            f"metadata selector schema violation: {selector_errors[0].message}"
        )
    if not isinstance(selector, dict):
        raise MaterializationError("metadata selector is not an object")
    selected_id = selector.get("selected_set")
    available = selector.get("available_sets")
    if not isinstance(available, list):
        raise MaterializationError("metadata selector set list is absent")
    entries = [
        row
        for row in available
        if isinstance(row, dict) and row.get("set_id") == selected_id
    ]
    if len(entries) != 1:
        raise MaterializationError("metadata selector identity drift")
    entry = entries[0]
    descriptor_path = entry.get("descriptor_path")
    if not isinstance(descriptor_path, str):
        raise MaterializationError("metadata descriptor path is absent")
    descriptor_payload, descriptor = _read_repo_json_record(descriptor_path)
    metadata_set_schema_payload, metadata_set_schema = _read_repo_json_record(
        METADATA_SET_SCHEMA_REL
    )
    descriptor_errors = list(
        Draft202012Validator(metadata_set_schema).iter_errors(descriptor)
    )
    if descriptor_errors:
        raise MaterializationError(
            f"metadata descriptor schema violation: {descriptor_errors[0].message}"
        )
    if (
        sha_bytes(descriptor_payload) != entry.get("descriptor_raw_sha256")
        or not isinstance(descriptor, dict)
        or descriptor.get("set_id") != selected_id
        or descriptor.get("lifecycle") != "live_ready"
    ):
        raise MaterializationError("metadata descriptor binding drift")
    documents = descriptor.get("documents")
    target = descriptor.get("target")
    if not isinstance(documents, dict) or not isinstance(target, dict):
        raise MaterializationError("metadata descriptor content drift")
    ledger = documents.get("official_capabilities")
    oracle = documents.get("capability_oracles")
    if not isinstance(ledger, dict) or not isinstance(oracle, dict):
        raise MaterializationError("metadata selected documents drift")
    ledger_path = ledger.get("path")
    oracle_path = oracle.get("path")
    if not isinstance(ledger_path, str) or not isinstance(oracle_path, str):
        raise MaterializationError("metadata selected document path drift")
    ledger_payload, selected_ledger = _read_repo_json_record(ledger_path)
    oracle_payload, selected_oracle = _read_repo_json_record(oracle_path)
    if sha_bytes(ledger_payload) != ledger.get("raw_sha256") or sha_bytes(
        oracle_payload
    ) != oracle.get("raw_sha256"):
        raise MaterializationError("metadata selected document digest drift")
    expected_target = {
        "main_commit": contract["target"]["upstream_commit"],
        "product_version": contract["target"]["product_version"],
    }
    if any(target.get(key) != value for key, value in expected_target.items()):
        raise MaterializationError("metadata selected target drift")
    _validate_metadata_alignment(contract, selected_ledger, selected_oracle)
    controls = [
        {"path": METADATA_SELECTOR_REL, "sha256": sha_bytes(selector_payload)},
        {
            "path": METADATA_SELECTOR_SCHEMA_REL,
            "sha256": sha_bytes(selector_schema_payload),
        },
        {"path": descriptor_path, "sha256": sha_bytes(descriptor_payload)},
        {
            "path": METADATA_SET_SCHEMA_REL,
            "sha256": sha_bytes(metadata_set_schema_payload),
        },
        {"path": ledger_path, "sha256": sha_bytes(ledger_payload)},
        {"path": oracle_path, "sha256": sha_bytes(oracle_payload)},
    ]
    selection = {
        "selector_path": METADATA_SELECTOR_REL,
        "selected_set_id": selected_id,
        "descriptor_path": descriptor_path,
        "selected_ledger_path": ledger_path,
        "selected_oracle_path": oracle_path,
        "target_main_commit": expected_target["main_commit"],
        "target_product_version": expected_target["product_version"],
    }
    return controls, selection


def load_producer_lock() -> dict[str, Any]:
    lock = strict_json(PRODUCER_LOCK_PATH)
    errors = schema_errors(lock, PRODUCER_LOCK_SCHEMA_PATH)
    if errors:
        raise MaterializationError(f"producer lock schema violation: {errors[0]}")
    if lock["capability_ids"] != CAPABILITY_IDS:
        raise MaterializationError("producer lock capability selection drift")
    if (
        lock["expectations"]["product_function_calls_by_capability"]
        != PRODUCT_FUNCTION_CALLS_BY_CAPABILITY
    ):
        raise MaterializationError("producer product-function accounting lock drift")
    contract = strict_json(PRODUCER_CONTRACT_PATH)
    errors = schema_errors(contract, PRODUCER_CONTRACT_SCHEMA_PATH)
    if errors:
        raise MaterializationError(f"producer contract schema violation: {errors[0]}")
    if [row["capability_id"] for row in contract["capabilities"]] != CAPABILITY_IDS:
        raise MaterializationError("producer contract capability order drift")

    expected_bundle = [
        {"path": os.fspath(path.relative_to(REPO_ROOT)), "sha256": sha_file(path)}
        for path in (
            PRODUCER_CONTRACT_PATH,
            PRODUCER_CONTRACT_SCHEMA_PATH,
            PRODUCER_EXECUTOR_PATH,
            PRODUCER_RESULT_SCHEMA_PATH,
        )
    ]
    if lock["producer_bundle"] != expected_bundle:
        raise MaterializationError("producer bundle lock drift")
    expected_canonical = [
        {
            "path": contract["target"][key],
            "sha256": sha_file(_repo_file(contract["target"][key])),
        }
        for key in ("current_ledger_document", "current_oracle_document")
    ]
    if lock["canonical_controls"] != expected_canonical:
        raise MaterializationError("producer canonical-control lock drift")
    expected_metadata_controls, expected_metadata_selection = (
        _active_metadata_lock_state(contract)
    )
    if lock["metadata_controls"] != expected_metadata_controls:
        raise MaterializationError("producer metadata-control lock drift")
    if lock["metadata_selection"] != expected_metadata_selection:
        raise MaterializationError("producer metadata-selection lock drift")
    expected_fixtures = [row["fixture_manifest"] for row in contract["capabilities"]]
    if lock["fixture_controls"] != expected_fixtures:
        raise MaterializationError("producer fixture lock drift")
    expected_sources = sorted(
        {
            (source["path"], source["sha256"])
            for row in contract["capabilities"]
            for source in row["source_controls"]
        }
    )
    expected_source_rows = [
        {"path": path, "sha256": digest} for path, digest in expected_sources
    ]
    if lock["product_source_controls"] != expected_source_rows:
        raise MaterializationError("producer product-source lock drift")
    for root_relative, key in (
        (PRODUCT_ROOT_REL, "product_root_manifest"),
        (PRODUCER_ROOT_REL, "producer_root_manifest"),
    ):
        manifest_paths = [row["path"] for row in lock[key]]
        if manifest_paths != _tracked_root_paths(root_relative):
            raise MaterializationError(f"{key} tracked-path manifest drift")
    _validate_producer_binding_commit(lock)
    for row in (
        lock["producer_bundle"]
        + lock["canonical_controls"]
        + lock["metadata_controls"]
        + lock["fixture_controls"]
        + lock["product_source_controls"]
        + lock["product_root_manifest"]
        + lock["producer_root_manifest"]
    ):
        if sha_file(_repo_file(row["path"])) != row["sha256"]:
            raise MaterializationError(f"producer locked file drift: {row['path']}")
    return lock


def _producer_locked_files(lock: dict[str, Any]) -> list[dict[str, str]]:
    return (
        lock["producer_bundle"]
        + lock["canonical_controls"]
        + lock["metadata_controls"]
        + lock["fixture_controls"]
        + lock["product_source_controls"]
        + lock["product_root_manifest"]
        + lock["producer_root_manifest"]
    )


def _producer_snapshot(lock: dict[str, Any]) -> dict[str, str]:
    return {
        row["path"]: sha_file(_repo_file(row["path"]))
        for row in _producer_locked_files(lock)
    }


def _producer_lock_row(lock: dict[str, Any], path: Path) -> dict[str, str]:
    relative = os.fspath(path.relative_to(REPO_ROOT))
    return next(row for row in lock["producer_bundle"] if row["path"] == relative)


def _import_sensitive_manifests_sha256(producer_lock: dict[str, Any]) -> str:
    return sha_bytes(
        canonical_bytes(
            {
                "product_root_manifest": producer_lock["product_root_manifest"],
                "producer_root_manifest": producer_lock["producer_root_manifest"],
            }
        )
    )


def _checkout_state() -> tuple[str, str, str]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", f"{head}^{{tree}}"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return head, tree, status


def _merge_base(ancestor: str, checkout_head: str) -> str:
    return subprocess.run(
        ["git", "merge-base", ancestor, checkout_head],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _expected_producer_promotion() -> dict[str, Any]:
    return {
        "ledger_mutation_performed": False,
        "oracle_mutation_performed": False,
        "external_provider_entry_touched": False,
        "development_smoke_only": False,
        "family_id": "spatial-ai-utils",
        "eligible_capability_ids": CAPABILITY_IDS,
        "requires_separate_reviewed_metadata_integration": True,
        "receipt_is_runtime_evidence": True,
        "aggregate_is_promotable": True,
    }


def _mirrored_integrated_promotion(producer_receipt: dict[str, Any]) -> dict[str, Any]:
    nested = producer_receipt.get("promotion")
    if nested != _expected_producer_promotion():
        raise MaterializationError("producer authority envelope drift")
    return {
        "canonical_parity_mutated": False,
        "runtime_producer_mutated": False,
        "development_smoke_only": nested["development_smoke_only"],
        "family_id": nested["family_id"],
        "eligible_capability_ids": nested["eligible_capability_ids"],
        "requires_separate_reviewed_metadata_integration": nested[
            "requires_separate_reviewed_metadata_integration"
        ],
        "receipt_is_runtime_evidence": nested["receipt_is_runtime_evidence"],
        "aggregate_is_promotable": nested["aggregate_is_promotable"],
    }


def validate_removed_producer_temporary_root(
    value: Any, owned_root: Path | None
) -> Path:
    """Validate a child-reported removed path without ever deleting it."""
    if not isinstance(value, str) or not value:
        raise MaterializationError("producer temporary root identity is absent")
    temporary_root = Path(value)
    suffix = temporary_root.name.removeprefix(PRODUCER_TEMP_PREFIX)
    if (
        not temporary_root.is_absolute()
        or os.path.normpath(value) != value
        or not temporary_root.name.startswith(PRODUCER_TEMP_PREFIX)
        or not suffix
        or os.path.lexists(value)
    ):
        raise MaterializationError("producer aggregate cleanup drift")
    if owned_root is not None:
        expected_parent = (owned_root / "tmp").resolve(strict=True)
        if temporary_root.parent != expected_parent:
            raise MaterializationError(
                "producer temporary root escaped materializer root"
            )
    return temporary_root


def validate_producer_receipt(
    result: dict[str, Any], producer_lock: dict[str, Any], owned_root: Path | None
) -> dict[str, int]:
    errors = schema_errors(result, PRODUCER_RESULT_SCHEMA_PATH)
    if errors:
        raise MaterializationError(f"producer receipt schema violation: {errors[0]}")
    if (
        result.get("schema_version") != 1
        or result.get("package_id")
        != "thor-spatial-ai-utils-runtime-evidence-successor-v1"
        or result["mode"] != "target_bound_offline_runtime_evidence"
        or result["status"] != "pass"
    ):
        raise MaterializationError("producer receipt is not an all-pass execution")
    bindings = result["bindings"]
    contract = strict_json(PRODUCER_CONTRACT_PATH)
    metadata = producer_lock["metadata_selection"]
    metadata_hashes = {
        row["path"]: row["sha256"] for row in producer_lock["metadata_controls"]
    }
    checkout_head, checkout_tree, checkout_status = _checkout_state()
    upstream_commit = contract["target"]["upstream_commit"]
    ancestry_merge_base = _merge_base(upstream_commit, checkout_head)
    expected_bindings = {
        "contract_sha256": _producer_lock_row(producer_lock, PRODUCER_CONTRACT_PATH)[
            "sha256"
        ],
        "executor_sha256": _producer_lock_row(producer_lock, PRODUCER_EXECUTOR_PATH)[
            "sha256"
        ],
        "ledger_document_sha256": producer_lock["canonical_controls"][0]["sha256"],
        "oracle_document_sha256": producer_lock["canonical_controls"][1]["sha256"],
        "checkout_head": checkout_head,
        "checkout_tree": checkout_tree,
        "checkout_clean": True,
        "checkout_status_porcelain_sha256": sha_bytes(b""),
        "invocation_allow_dirty_development": False,
        "target_upstream_commit": upstream_commit,
        "target_ancestry_merge_base": upstream_commit,
        "metadata_selector_path": metadata["selector_path"],
        "metadata_selector_raw_sha256": metadata_hashes[metadata["selector_path"]],
        "selected_metadata_set_id": metadata["selected_set_id"],
        "selected_descriptor_path": metadata["descriptor_path"],
        "selected_descriptor_raw_sha256": metadata_hashes[metadata["descriptor_path"]],
        "selected_ledger_path": metadata["selected_ledger_path"],
        "selected_ledger_raw_sha256": metadata_hashes[metadata["selected_ledger_path"]],
        "selected_oracle_path": metadata["selected_oracle_path"],
        "selected_oracle_raw_sha256": metadata_hashes[metadata["selected_oracle_path"]],
        "selected_target_main_commit": metadata["target_main_commit"],
        "selected_target_product_version": metadata["target_product_version"],
        "canonical_rows_are_open_unexecuted": True,
        "executor_ready_capabilities": EXECUTOR_READY_CAPABILITY_IDS,
    }
    if (
        checkout_status != ""
        or ancestry_merge_base != upstream_commit
        or bindings != expected_bindings
    ):
        raise MaterializationError("producer receipt binding drift")
    rows = result["capability_results"]
    if [row["capability_id"] for row in rows] != CAPABILITY_IDS:
        raise MaterializationError("producer result capability order drift")
    expected_calls = PRODUCT_FUNCTION_CALLS_BY_CAPABILITY
    contract_by_id = {row["capability_id"]: row for row in contract["capabilities"]}
    for row, capability_id in zip(rows, CAPABILITY_IDS, strict=True):
        short_id = capability_id.split(".")[2][:2]
        capability = contract_by_id[capability_id]
        negative_ids = [case["case_id"] for case in row["adjacent_negatives"]]
        expected_action_ids = {"positive-run-1", "positive-run-2"} | set(
            NEGATIVE_CASE_IDS[short_id]
        )
        observation_hash = sha_bytes(canonical_bytes(row["positive_observations"]))
        if (
            row["status"] != "pass"
            or row["oracle_id"] != capability["oracle_id"]
            or row["fixture_sha256"] != capability["fixture_manifest"]["sha256"]
            or row["independent_runs"] != 2
            or row["bounded_capability_actions"] != 7
            or row["requests"] != 7
            or set(row["target_action_ids"]) != expected_action_ids
            or row["deterministic_output"] is not True
            or len(row["run_output_sha256"]) != 2
            or row["run_output_sha256"][0] != row["run_output_sha256"][1]
            or negative_ids != NEGATIVE_CASE_IDS[short_id]
            or not all(case["rejected"] is True for case in row["adjacent_negatives"])
            or row["imported_product_function_invocations"]
            != expected_calls[capability_id]
            or row["imported_product_function_counts"]
            != PRODUCT_FUNCTION_COUNTS[short_id]
            or row["run_output_sha256"] != [observation_hash, observation_hash]
        ):
            raise MaterializationError(f"producer accounting drift: {capability_id}")
        cleanup = row["cleanup"]
        if (
            cleanup["namespace"] != f"spatial-ai-{capability_id.split('.')[2]}"
            or cleanup["pre_state_captured"] != "absent"
            or cleanup["temporary_files_only"] is not True
            or cleanup["removed"] is not True
            or cleanup["siblings_unchanged"] is not True
            or not isinstance(cleanup["owned_tree_sha256"], str)
            or len(cleanup["owned_tree_sha256"]) != 64
            or cleanup["post_cleanup_tree_sha256"] != EMPTY_TREE_SHA256
        ):
            raise MaterializationError(f"producer cleanup drift: {capability_id}")
        binding = row["runtime_evidence_binding"]
        expected_binding = {
            "captured_at_utc": result["captured_at_utc"],
            "executor_sha256": bindings["executor_sha256"],
            "contract_sha256": bindings["contract_sha256"],
            "current_oracle_sha256": capability["current_oracle_sha256"],
            "current_ledger_row_sha256": capability["current_ledger_row_sha256"],
            "fixture_sha256": capability["fixture_manifest"]["sha256"],
            "capability_evidence_sha256": observation_hash,
            "target_case_actions": 7,
            "requests": 7,
            "target_action_ids_sha256": sha_bytes(
                canonical_bytes(row["target_action_ids"])
            ),
            "imported_product_function_invocations": expected_calls[capability_id],
            "imported_product_function_counts_sha256": sha_bytes(
                canonical_bytes(PRODUCT_FUNCTION_COUNTS[short_id])
            ),
        }
        if binding != expected_binding:
            raise MaterializationError(
                f"producer evidence-binding drift: {capability_id}"
            )
    confinement = result["confinement"]
    expected = producer_lock["expectations"]
    accounting = {
        "capabilities_passed": sum(row["status"] == "pass" for row in rows),
        "bounded_capability_actions": sum(
            row["bounded_capability_actions"] for row in rows
        ),
        "requests": sum(row["requests"] for row in rows),
        "product_function_calls": sum(
            row["imported_product_function_invocations"] for row in rows
        ),
        "independent_positive_runs": sum(row["independent_runs"] for row in rows),
        "adjacent_negatives": sum(len(row["adjacent_negatives"]) for row in rows),
    }
    expected_accounting = {
        key: expected[key]
        for key in (
            "capabilities_passed",
            "bounded_capability_actions",
            "requests",
            "product_function_calls",
            "independent_positive_runs",
            "adjacent_negatives",
        )
    }
    if accounting != expected_accounting:
        raise MaterializationError("producer aggregate accounting drift")
    if (
        confinement["bounded_capability_actions"]
        != accounting["bounded_capability_actions"]
        or confinement["requests"] != accounting["requests"]
        or confinement["imported_product_function_invocations"]
        != accounting["product_function_calls"]
        or confinement["product_execution_deadline_seconds"] != 900
        or confinement["external_activity_instrumented"] is not True
        or confinement["whole_temp_root_scanned"] is not True
        or any(confinement[key] != 0 for key in EXTERNAL_ACTIVITY_KEYS)
    ):
        raise MaterializationError("producer confinement drift")
    preflight = result["environment"]["capability_preflight"]
    if list(preflight) != CAPABILITY_IDS:
        raise MaterializationError("producer all-seven preflight drift")
    for capability_id in CAPABILITY_IDS:
        adapter = contract_by_id[capability_id]["adapter"]
        observed = preflight[capability_id]
        if (
            observed["ready"] is not True
            or observed["required_modules"] != REQUIRED_MODULES[adapter]
            or observed["missing_modules"] != []
            or observed["import_failures"] != []
            or set(observed["observed_versions"]) != set(REQUIRED_MODULES[adapter])
        ):
            raise MaterializationError("producer all-seven preflight drift")
    aggregate_cleanup = result["cleanup"]
    validate_removed_producer_temporary_root(
        aggregate_cleanup["executor_owned_temporary_root"], owned_root
    )
    if (
        aggregate_cleanup["pre_execution_tree_sha256"] != EMPTY_TREE_SHA256
        or aggregate_cleanup["post_execution_tree_sha256"] != EMPTY_TREE_SHA256
        or not isinstance(aggregate_cleanup["sentinel_sha256"], str)
        or len(aggregate_cleanup["sentinel_sha256"]) != 64
        or aggregate_cleanup["checkout_status_before_sha256"] != sha_bytes(b"")
        or aggregate_cleanup["checkout_status_after_sha256"] != sha_bytes(b"")
        or aggregate_cleanup["removed"] is not True
        or aggregate_cleanup["siblings_unchanged"] is not True
    ):
        raise MaterializationError("producer aggregate cleanup drift")
    if result["promotion"] != _expected_producer_promotion():
        raise MaterializationError("producer authority envelope drift")
    return accounting


def run_canonical_producer(
    venv_python: Path,
    env: dict[str, str],
    root: Path,
    producer_lock: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, int]]:
    child_receipt = root / "producer-receipt.json"
    argv = [
        os.fspath(venv_python),
        "-I",
        "-s",
        os.fspath(PRODUCER_EXECUTOR_PATH),
        "--execute",
    ]
    for capability_id in CAPABILITY_IDS:
        argv.extend(("--select", capability_id))
    argv.extend(("--acknowledge", PRODUCER_ACK, "--output", os.fspath(child_receipt)))
    run_child(argv, env, root, timeout=PRODUCER_TIMEOUT_SECONDS)
    if child_receipt.is_symlink() or not child_receipt.is_file():
        raise MaterializationError(
            "canonical producer did not create a regular receipt"
        )
    receipt_stat = child_receipt.stat()
    if stat.S_IMODE(receipt_stat.st_mode) != 0o600 or receipt_stat.st_nlink != 1:
        raise MaterializationError(
            "canonical producer receipt is not private and unique"
        )
    raw = child_receipt.read_bytes()
    result = _strict_json_bytes(raw, os.fspath(child_receipt))
    accounting = validate_producer_receipt(result, producer_lock, root)
    return result, sha_bytes(raw), accounting


def _integrated_execution_sha256(receipt: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(receipt))
    payload["bindings"].pop("execution_sha256", None)
    return sha_bytes(canonical_bytes(payload))


def validate_integrated_receipt(
    receipt: dict[str, Any],
    lock: dict[str, Any],
    producer_lock: dict[str, Any],
    *,
    expected_cache_scan: dict[str, int],
    expected_temporary_root: str,
) -> None:
    errors = schema_errors(receipt, INTEGRATED_RECEIPT_SCHEMA_PATH)
    if errors:
        raise MaterializationError(f"integrated receipt schema violation: {errors[0]}")
    validate_receipt(
        receipt["environment_receipt"],
        lock,
        expected_cache_scan=expected_cache_scan,
        expected_temporary_root=expected_temporary_root,
    )
    expected_bindings = {
        "environment_receipt_sha256": sha_bytes(
            canonical_bytes(receipt["environment_receipt"])
        ),
        "producer_lock_sha256": sha_file(PRODUCER_LOCK_PATH),
        "producer_contract_sha256": _producer_lock_row(
            producer_lock, PRODUCER_CONTRACT_PATH
        )["sha256"],
        "producer_executor_sha256": _producer_lock_row(
            producer_lock, PRODUCER_EXECUTOR_PATH
        )["sha256"],
        "producer_result_schema_sha256": _producer_lock_row(
            producer_lock, PRODUCER_RESULT_SCHEMA_PATH
        )["sha256"],
        "import_sensitive_manifests_sha256": _import_sensitive_manifests_sha256(
            producer_lock
        ),
        "producer_receipt_sha256": receipt["bindings"]["producer_receipt_sha256"],
        "execution_sha256": _integrated_execution_sha256(receipt),
    }
    if receipt["bindings"] != expected_bindings:
        raise MaterializationError("integrated receipt binding drift")
    rendered_producer = (
        json.dumps(receipt["producer_receipt"], indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if sha_bytes(rendered_producer) != receipt["bindings"]["producer_receipt_sha256"]:
        raise MaterializationError("nested producer receipt content binding drift")
    accounting = validate_producer_receipt(
        receipt["producer_receipt"], producer_lock, None
    )
    # The nested producer cleanup path was already validated while its owned root
    # existed; after cleanup only its exact prefix and absence remain observable.
    validate_removed_producer_temporary_root(
        receipt["producer_receipt"]["cleanup"]["executor_owned_temporary_root"],
        None,
    )
    if receipt["accounting"] != accounting:
        raise MaterializationError("integrated accounting drift")
    if receipt["selection"] != {"kind": "all", "capability_ids": CAPABILITY_IDS}:
        raise MaterializationError("integrated selection drift")
    if receipt["confinement"] != {
        "inherited_kernel_network_denial": True,
        "import_shadow_scan_passed": True,
        "outer_timeout_seconds": PRODUCER_TIMEOUT_SECONDS,
        **{key: 0 for key in EXTERNAL_ACTIVITY_KEYS},
    }:
        raise MaterializationError("integrated confinement drift")
    if receipt["cleanup"] != {
        "materializer_temporary_root": expected_temporary_root,
        "materializer_temporary_root_removed": True,
        "producer_temporary_root_removed": True,
        "producer_bundle_unchanged": True,
        "canonical_controls_unchanged": True,
        "product_sources_unchanged": True,
        "import_sensitive_roots_unchanged": True,
    }:
        raise MaterializationError("integrated cleanup drift")
    if receipt["promotion"] != _mirrored_integrated_promotion(
        receipt["producer_receipt"]
    ):
        raise MaterializationError("integrated promotion drift")


def materialize(
    lock: dict[str, Any],
    cache_roots: list[Path],
    work_parent: Path,
    *,
    run_producer: bool = False,
) -> dict[str, Any]:
    require_isolated_execution()
    validate_host(lock)
    if any(path.suffix in {".whl", ".body"} for path in HERE.rglob("*")):
        raise MaterializationError("wheel binary found inside repository package")
    parent = _safe_existing_directory(work_parent, "work parent")
    try:
        parent.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise MaterializationError("work parent must be outside the repository")

    producer_lock = load_producer_lock() if run_producer else None
    if producer_lock is not None:
        verify_import_roots(producer_lock)
    producer_snapshot = (
        _producer_snapshot(producer_lock) if producer_lock is not None else None
    )
    sources, scan = resolve_cache_artifacts(lock, cache_roots)
    source_hashes = {name: sha_file(path) for name, path in sorted(sources.items())}
    root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=parent))
    sentinel = parent / f".{root.name}.sentinel"
    sentinel_hash: str | None = None
    receipt: dict[str, Any] | None = None
    try:
        with sentinel.open("xb") as stream:
            stream.write(b"spatial-ai-offline-env-sentinel\n")
            stream.flush()
            os.fsync(stream.fileno())
        sentinel_hash = sha_file(sentinel)
        wheelhouse = root / "wheelhouse"
        wheelhouse_result = materialize_wheelhouse(lock, sources, wheelhouse)
        environment, venv_python, child_env = build_environment(lock, root, wheelhouse)
        if {
            name: sha_file(path) for name, path in sorted(sources.items())
        } != source_hashes:
            raise MaterializationError("source cache artifact changed during execution")
        receipt = {
            "schema_version": 1,
            "package_id": lock["package_id"],
            "mode": "offline_materialization",
            "status": "pass",
            "captured_at_utc": dt.datetime.now(dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "bindings": _base_receipt_bindings(lock),
            "target": lock["target"],
            "policy": lock["policy"],
            "cache_scan": scan,
            "wheelhouse": wheelhouse_result,
            "environment": environment,
            "confinement": _confinement_policy(),
            "cleanup": {
                "temporary_root": root.name,
                "pre_state": "absent",
                "removed": True,
                "sentinel_unchanged": True,
                "source_artifacts_unchanged": True,
            },
            "promotion": _promotion_policy(),
        }
        receipt["bindings"]["execution_sha256"] = _execution_sha256(receipt)
        if producer_lock is not None:
            producer_receipt, producer_receipt_sha256, accounting = (
                run_canonical_producer(venv_python, child_env, root, producer_lock)
            )
            if _producer_snapshot(producer_lock) != producer_snapshot:
                raise MaterializationError(
                    "producer bundle, canonical controls, or product sources changed"
                )
            verify_import_roots(producer_lock)
            receipt = {
                "schema_version": 1,
                "package_id": "thor-spatial-ai-offline-integrated-runtime-v1",
                "mode": "offline_environment_with_canonical_spatial_ai_all",
                "status": "pass",
                "captured_at_utc": dt.datetime.now(dt.timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "bindings": {
                    "environment_receipt_sha256": sha_bytes(canonical_bytes(receipt)),
                    "producer_lock_sha256": sha_file(PRODUCER_LOCK_PATH),
                    "producer_contract_sha256": _producer_lock_row(
                        producer_lock, PRODUCER_CONTRACT_PATH
                    )["sha256"],
                    "producer_executor_sha256": _producer_lock_row(
                        producer_lock, PRODUCER_EXECUTOR_PATH
                    )["sha256"],
                    "producer_result_schema_sha256": _producer_lock_row(
                        producer_lock, PRODUCER_RESULT_SCHEMA_PATH
                    )["sha256"],
                    "import_sensitive_manifests_sha256": _import_sensitive_manifests_sha256(
                        producer_lock
                    ),
                    "producer_receipt_sha256": producer_receipt_sha256,
                },
                "selection": {"kind": "all", "capability_ids": CAPABILITY_IDS},
                "environment_receipt": receipt,
                "producer_receipt": producer_receipt,
                "accounting": accounting,
                "confinement": {
                    "inherited_kernel_network_denial": True,
                    "import_shadow_scan_passed": True,
                    "outer_timeout_seconds": PRODUCER_TIMEOUT_SECONDS,
                    **{key: 0 for key in EXTERNAL_ACTIVITY_KEYS},
                },
                "cleanup": {
                    "materializer_temporary_root": root.name,
                    "materializer_temporary_root_removed": True,
                    "producer_temporary_root_removed": True,
                    "producer_bundle_unchanged": True,
                    "canonical_controls_unchanged": True,
                    "product_sources_unchanged": True,
                    "import_sensitive_roots_unchanged": True,
                },
                "promotion": _mirrored_integrated_promotion(producer_receipt),
            }
            receipt["bindings"]["execution_sha256"] = _integrated_execution_sha256(
                receipt
            )
    finally:
        source_unchanged = all(
            path.is_file() and sha_file(path) == source_hashes[name]
            for name, path in sorted(sources.items())
        )
        shutil.rmtree(root, ignore_errors=True)
        if root.exists():
            raise MaterializationError("temporary environment cleanup failed")
        if sentinel_hash is not None and (
            not sentinel.is_file() or sha_file(sentinel) != sentinel_hash
        ):
            raise MaterializationError("adjacent cleanup sentinel changed")
        if sentinel.exists():
            sentinel.unlink()
        if not source_unchanged:
            raise MaterializationError("source cache artifact changed during execution")
        if (
            producer_lock is not None
            and _producer_snapshot(producer_lock) != producer_snapshot
        ):
            raise MaterializationError(
                "producer bundle, canonical controls, or product sources changed"
            )
        if producer_lock is not None:
            verify_import_roots(producer_lock)
    if receipt is None:
        raise MaterializationError("materialization did not produce a receipt")
    if producer_lock is None:
        validate_receipt(
            receipt,
            lock,
            expected_cache_scan=scan,
            expected_temporary_root=root.name,
        )
    else:
        if _producer_snapshot(producer_lock) != producer_snapshot:
            raise MaterializationError(
                "producer bundle, canonical controls, or product sources changed"
            )
        validate_integrated_receipt(
            receipt,
            lock,
            producer_lock,
            expected_cache_scan=scan,
            expected_temporary_root=root.name,
        )
    return receipt


def open_safe_output_parent(path: Path) -> tuple[Path, int]:
    destination = Path(os.path.abspath(os.fspath(path)))
    if not destination.name:
        raise MaterializationError(
            "output parent must be an existing regular directory"
        )
    try:
        resolved_parent = destination.parent.resolve(strict=True)
        resolved_parent.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        pass
    except OSError as exc:
        raise MaterializationError(
            "output parent must be an existing regular directory"
        ) from exc
    else:
        raise MaterializationError("output receipt must be outside the repository")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", directory_flags)
    try:
        for component in destination.parent.parts[1:]:
            next_descriptor = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        try:
            os.stat(destination.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise MaterializationError("output receipt already exists")
        return destination, descriptor
    except MaterializationError:
        os.close(descriptor)
        raise
    except OSError as exc:
        os.close(descriptor)
        raise MaterializationError("secure output publication failed") from exc


def publish_exclusive(
    path: Path,
    rendered: str,
    validate_after_write: Any | None = None,
) -> None:
    destination, descriptor = open_safe_output_parent(path)
    output_descriptor = -1
    created = False
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            output_descriptor = os.open(
                destination.name, flags, 0o600, dir_fd=descriptor
            )
            created = True
        except FileExistsError as exc:
            raise MaterializationError("output receipt already exists") from exc
        output_stat = os.fstat(output_descriptor)
        if (
            not stat.S_ISREG(output_stat.st_mode)
            or stat.S_IMODE(output_stat.st_mode) != 0o600
            or output_stat.st_nlink != 1
        ):
            raise MaterializationError("output receipt is not private and unique")
        data = rendered.encode("utf-8")
        offset = 0
        while offset < len(data):
            written = os.write(output_descriptor, data[offset:])
            if written <= 0:
                raise MaterializationError("output receipt write made no progress")
            offset += written
        os.fsync(output_descriptor)
        os.lseek(output_descriptor, 0, os.SEEK_SET)
        observed = b""
        while len(observed) < len(data):
            chunk = os.read(output_descriptor, len(data) - len(observed))
            if not chunk:
                break
            observed += chunk
        if observed != data or os.read(output_descriptor, 1) != b"":
            raise MaterializationError("published receipt bytes differ")
        if validate_after_write is not None:
            validate_after_write()
        final_descriptor_stat = os.fstat(output_descriptor)
        final_name_stat = os.stat(
            destination.name, dir_fd=descriptor, follow_symlinks=False
        )
        if (
            not stat.S_ISREG(final_name_stat.st_mode)
            or stat.S_IMODE(final_name_stat.st_mode) != 0o600
            or final_name_stat.st_nlink != 1
            or (final_name_stat.st_dev, final_name_stat.st_ino)
            != (final_descriptor_stat.st_dev, final_descriptor_stat.st_ino)
        ):
            raise MaterializationError("published receipt identity changed")
        os.fsync(descriptor)
    except BaseException as exc:
        if created:
            try:
                descriptor_stat = os.fstat(output_descriptor)
                name_stat = os.stat(
                    destination.name, dir_fd=descriptor, follow_symlinks=False
                )
                if (name_stat.st_dev, name_stat.st_ino) == (
                    descriptor_stat.st_dev,
                    descriptor_stat.st_ino,
                ):
                    os.unlink(destination.name, dir_fd=descriptor)
                    os.fsync(descriptor)
            except OSError:
                pass
        if isinstance(exc, MaterializationError):
            raise
        raise MaterializationError("secure output publication failed") from exc
    finally:
        if output_descriptor >= 0:
            os.close(output_descriptor)
        os.close(descriptor)


def revalidate_for_publication(receipt: dict[str, Any]) -> None:
    lock = load_lock()
    if receipt.get("package_id") == "thor-spatial-ai-offline-integrated-runtime-v1":
        producer_lock = load_producer_lock()
        verify_import_roots(producer_lock)
        validate_integrated_receipt(
            receipt,
            lock,
            producer_lock,
            expected_cache_scan=receipt["environment_receipt"]["cache_scan"],
            expected_temporary_root=receipt["cleanup"]["materializer_temporary_root"],
        )
    else:
        validate_receipt(
            receipt,
            lock,
            expected_cache_scan=receipt["cache_scan"],
            expected_temporary_root=receipt["cleanup"]["temporary_root"],
        )


def plan(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": lock["package_id"],
        "mode": "inert_plan",
        "artifact_count": len(lock["artifacts"]),
        "target": lock["target"],
        "network_allowed": False,
        "writes_performed": False,
        "execute_requires_acknowledgement": ACK,
        "integrated_mode": {
            "selection": "all",
            "producer_acknowledgement": PRODUCER_ACK,
            "network_allowed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--acknowledge")
    parser.add_argument("--cache-root", type=Path, action="append")
    parser.add_argument("--work-parent", type=Path, default=Path("/tmp"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-canonical-spatial-ai-producer", action="store_true")
    parser.add_argument("--producer-selection", choices=("all",))
    parser.add_argument("--producer-acknowledge")
    args = parser.parse_args(argv)
    try:
        lock = load_lock(args.lock)
        if not args.execute:
            if (
                args.acknowledge is not None
                or args.output is not None
                or args.cache_root
                or args.run_canonical_spatial_ai_producer
                or args.producer_selection is not None
                or args.producer_acknowledge is not None
            ):
                raise MaterializationError("execution-only flags require --execute")
            print(json.dumps(plan(lock), indent=2, sort_keys=True))
            return 0
        if args.acknowledge != ACK:
            raise MaterializationError(f"--execute requires --acknowledge {ACK}")
        if args.output is None:
            raise MaterializationError("--execute requires --output")
        producer_flags_present = (
            args.producer_selection is not None or args.producer_acknowledge is not None
        )
        if args.run_canonical_spatial_ai_producer:
            if args.producer_selection != "all":
                raise MaterializationError(
                    "integrated execution requires --producer-selection all"
                )
            if args.producer_acknowledge != PRODUCER_ACK:
                raise MaterializationError(
                    "integrated execution requires --producer-acknowledge "
                    + PRODUCER_ACK
                )
        elif producer_flags_present:
            raise MaterializationError(
                "producer flags require --run-canonical-spatial-ai-producer"
            )
        _, output_parent_descriptor = open_safe_output_parent(args.output)
        os.close(output_parent_descriptor)
        roots = args.cache_root or [DEFAULT_CACHE_ROOT]
        receipt = materialize(
            lock,
            roots,
            args.work_parent,
            run_producer=args.run_canonical_spatial_ai_producer,
        )
        publish_exclusive(
            args.output,
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            validate_after_write=lambda: revalidate_for_publication(receipt),
        )
        return 0
    except MaterializationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
