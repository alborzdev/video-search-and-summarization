#!/usr/bin/env python3
"""Build and verify an ephemeral SpatialAI environment from locked local wheels."""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import email
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any, Iterable
import zipfile

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
PRODUCT_ROOT = REPO_ROOT / "libs/analytics/spatialai-data-utils"
LOCK_PATH = HERE / "lock.json"
LOCK_SCHEMA_PATH = HERE / "lock.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
ACK = "I_ACKNOWLEDGE_EPHEMERAL_OFFLINE_SPATIAL_AI_ENV"
TEMP_PREFIX = "vss-spatial-ai-offline-env."
NETWORK_DENIAL_MARKER = "VSS_OFFLINE_NETWORK_DENIED"
DEFAULT_CACHE_ROOT = Path(
    os.environ.get("PIP_CACHE_DIR", Path.home() / ".cache" / "pip")
)


class MaterializationError(RuntimeError):
    """A lock, cache, confinement, install, validation, or cleanup check failed."""


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


def strict_json(path: Path) -> Any:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise MaterializationError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"invalid JSON: {path}") from exc


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
) -> dict[str, Any]:
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
    return {
        "python": smoke["python"],
        "machine": smoke["machine"],
        "soabi": smoke["soabi"],
        "pip": pip_version,
        "pip_check": pip_check,
        "installed_artifact_count": len(smoke["versions"]),
        "installed_versions_sha256": sha_bytes(canonical_bytes(smoke["versions"])),
        "smoke_imports": smoke["imports"],
    }


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


def materialize(
    lock: dict[str, Any], cache_roots: list[Path], work_parent: Path
) -> dict[str, Any]:
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
        environment = build_environment(lock, root, wheelhouse)
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
    if receipt is None:
        raise MaterializationError("materialization did not produce a receipt")
    validate_receipt(
        receipt,
        lock,
        expected_cache_scan=scan,
        expected_temporary_root=root.name,
    )
    return receipt


def publish_exclusive(path: Path, rendered: str) -> None:
    destination = Path(os.path.abspath(os.fspath(path)))
    if (
        not destination.name
        or not destination.parent.is_dir()
        or destination.parent.is_symlink()
    ):
        raise MaterializationError(
            "output parent must be an existing regular directory"
        )
    try:
        with destination.open("x", encoding="utf-8") as stream:
            os.chmod(destination, 0o600)
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise MaterializationError("output receipt already exists") from exc


def plan(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": lock["package_id"],
        "mode": "inert_plan",
        "artifact_count": len(lock["artifacts"]),
        "target": lock["target"],
        "network_allowed": False,
        "writes_performed": False,
        "execute_requires_acknowledgement": ACK,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--acknowledge")
    parser.add_argument("--cache-root", type=Path, action="append")
    parser.add_argument("--work-parent", type=Path, default=Path("/tmp"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        lock = load_lock(args.lock)
        if not args.execute:
            if (
                args.acknowledge is not None
                or args.output is not None
                or args.cache_root
            ):
                raise MaterializationError("execution-only flags require --execute")
            print(json.dumps(plan(lock), indent=2, sort_keys=True))
            return 0
        if args.acknowledge != ACK:
            raise MaterializationError(f"--execute requires --acknowledge {ACK}")
        if args.output is None:
            raise MaterializationError("--execute requires --output")
        roots = args.cache_root or [DEFAULT_CACHE_ROOT]
        receipt = materialize(lock, roots, args.work_parent)
        publish_exclusive(
            args.output, json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
        return 0
    except MaterializationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
