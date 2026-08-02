#!/usr/bin/env python3
"""Authorization-gated Playwright candidate for Video Management semantics."""

from __future__ import annotations

import argparse
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
MANIFEST_SCHEMA_PATH = HERE / "manifest.schema.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt.schema.json"
HARNESS_PATH = HERE / "harness.mjs"
MAX_CONFIG_BYTES = 32 * 1024 * 1024
MAX_TOOL_BYTES = 256 * 1024 * 1024
MAX_PLAYWRIGHT_FILES = 4096
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ExecutorError(RuntimeError):
    """Stable error category; sensitive tool and browser details stay private."""

    CODES = {
        "authorization_required",
        "browser_oracle_failed",
        "configuration_error",
        "invalid_manifest",
        "tool_failed",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _digest(raw: bytes | str) -> str:
    value = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc


def _read_regular(
    path: Path,
    maximum: int,
    code: str,
    *,
    absolute: bool = False,
    executable: bool = False,
) -> bytes:
    if absolute and not path.is_absolute():
        raise ExecutorError(code)
    if absolute:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current /= part
            try:
                if stat.S_ISLNK(current.lstat().st_mode):
                    raise ExecutorError(code)
            except ExecutorError:
                raise
            except OSError as exc:
                raise ExecutorError(code) from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExecutorError(code) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= maximum
            or (executable and before.st_mode & 0o111 == 0)
        ):
            raise ExecutorError(code)
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(131072, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, key) != getattr(after, key) for key in fields
        ):
            raise ExecutorError(code)
        return raw
    finally:
        os.close(descriptor)


def _decode(raw: bytes, code: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ExecutorError(code)
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _token: (_ for _ in ()).throw(ExecutorError(code)),
        )
    except ExecutorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError(code) from exc
    if not isinstance(value, dict):
        raise ExecutorError(code)
    return value


def _json(path: Path, code: str = "configuration_error") -> dict[str, Any]:
    return _decode(_read_regular(path, MAX_CONFIG_BYTES, code), code)


def _schema(value: Any, path: Path, code: str) -> None:
    try:
        schema = _json(path)
        Draft202012Validator.check_schema(schema)
        if list(Draft202012Validator(schema).iter_errors(value)):
            raise ExecutorError(code)
    except ExecutorError:
        raise
    except Exception as exc:
        raise ExecutorError("configuration_error") from exc


def _repo_path(relative: str) -> Path:
    value = Path(relative)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise ExecutorError("configuration_error")
    current = ROOT
    for part in value.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ExecutorError("configuration_error")
        except ExecutorError:
            raise
        except OSError as exc:
            raise ExecutorError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise ExecutorError("configuration_error") from exc
    return current


def _absolute_directory(path: Path, code: str) -> Path:
    if not path.is_absolute():
        raise ExecutorError(code)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ExecutorError(code) from exc
        if stat.S_ISLNK(mode):
            raise ExecutorError(code)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise ExecutorError(code) from exc
    if resolved != path or not path.is_dir():
        raise ExecutorError(code)
    return path


def _tree_digest(root: Path, code: str) -> str:
    root = _absolute_directory(root, code)
    pending = [root]
    rows: list[dict[str, Any]] = []
    total = 0
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise ExecutorError(code) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_symlink():
                    raise ExecutorError(code)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise ExecutorError(code)
            except OSError as exc:
                raise ExecutorError(code) from exc
            raw = _read_regular(path, MAX_TOOL_BYTES, code, absolute=True)
            total += len(raw)
            if len(rows) >= MAX_PLAYWRIGHT_FILES or total > MAX_TOOL_BYTES:
                raise ExecutorError(code)
            rows.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _digest(raw),
                    "size": len(raw),
                }
            )
    rows.sort(key=lambda row: row["path"])
    if not rows:
        raise ExecutorError(code)
    return _digest(_canonical(rows))


def _one(rows: Any, key: str, expected: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise ExecutorError("configuration_error")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get(key) == expected
    ]
    if len(matches) != 1:
        raise ExecutorError("configuration_error")
    return matches[0]


def compile_plan() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH)
    expected_workflow = [
        "capture-pre-state",
        "upload-mp4",
        "upload-mkv",
        "multi-upload",
        "manage-rtsp",
        "observe-upload-progress",
        "load-template-environment",
        "confirm-bulk-delete",
        "cancel-bulk-delete",
        "restore-owned-state",
        "verify-postconditions",
    ]
    if (
        contract.get("schema_version") != 1
        or contract.get("package_id")
        != "thor-ui-video-management-playwright-successor-v1"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or contract.get("semantic_workflow") != expected_workflow
        or contract.get("browser_availability", {}).get("codex_browser_plugin")
        != "absent"
        or contract.get("browser_availability", {}).get("browser_launch_allowed")
        is not False
        or contract.get("runtime_boundary", {}).get("preexisting_browser_preserved")
        is not True
        or contract.get("ownership", {}).get(
            "agent_delete_requires_exact_success_and_identity"
        )
        is not True
        or contract.get("ownership", {}).get("empty_vst_sensor_identity_preserved")
        is not True
        or contract.get("ownership", {}).get(
            "destructive_dialog_irreversible_warning_observed"
        )
        is not True
        or contract.get("canonical_boundary", {}).get("canonical_bound") is not False
        or contract.get("canonical_boundary", {}).get("executor_ready") is not False
        or contract.get("canonical_boundary", {}).get("promotion_eligible") is not False
        or contract.get("canonical_boundary", {}).get("playwright_entry_files_pinned")
        is not True
        or contract.get("canonical_boundary", {}).get(
            "playwright_transitive_graph_pinned"
        )
        is not True
        or contract.get("bounds")
        != {
            "max_duration_seconds": 240,
            "internal_workflow_deadline_seconds": 175,
            "cleanup_reserve_seconds": 45,
            "parent_failsafe_margin_seconds": 20,
            "max_browser_actions": 40,
            "max_api_exchanges": 32,
            "semantic_checkpoints": 11,
            "max_tool_stdout_bytes": 4194304,
            "max_tool_stderr_bytes": 1048576,
            "min_fixture_bytes_each_exclusive": 10485760,
            "max_fixture_bytes_each": 12582912,
        }
    ):
        raise ExecutorError("configuration_error")

    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 22:
        raise ExecutorError("configuration_error")
    seen: set[str] = set()
    for lock in locks:
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
            or not SHA256_RE.fullmatch(str(lock["sha256"]))
        ):
            raise ExecutorError("configuration_error")
        seen.add(lock["path"])
        if (
            _digest(
                _read_regular(
                    _repo_path(lock["path"]), MAX_CONFIG_BYTES, "configuration_error"
                )
            )
            != lock["sha256"]
        ):
            raise ExecutorError("configuration_error")

    required_lifecycle_and_topology_paths = {
        "services/ui/packages/nv-metropolis-bp-vss-ui/video-management/"
        "lib-src/videoDelete.ts",
        "services/ui/packages/nv-metropolis-bp-vss-ui/video-management/"
        "lib-src/rtspStream.ts",
        "deploy/docker/services/ui/compose.yml",
        "deploy/docker/services/infra/haproxy/compose.yml",
        "deploy/docker/services/infra/haproxy/haproxy.cfg.template",
    }
    if not required_lifecycle_and_topology_paths.issubset(seen):
        raise ExecutorError("configuration_error")

    implementation_locks = contract.get("implementation_locks")
    if not isinstance(implementation_locks, list) or len(implementation_locks) != 2:
        raise ExecutorError("configuration_error")
    implementation_paths: set[str] = set()
    for lock in implementation_locks:
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in implementation_paths
            or not SHA256_RE.fullmatch(str(lock["sha256"]))
        ):
            raise ExecutorError("configuration_error")
        implementation_paths.add(lock["path"])
        if (
            _digest(
                _read_regular(
                    _repo_path(lock["path"]), MAX_CONFIG_BYTES, "configuration_error"
                )
            )
            != lock["sha256"]
        ):
            raise ExecutorError("configuration_error")
    if implementation_paths != {
        "deploy/docker/thor-local/qualification/"
        "ui-video-management-playwright-successor/executor.py",
        "deploy/docker/thor-local/qualification/"
        "ui-video-management-playwright-successor/harness.mjs",
    }:
        raise ExecutorError("configuration_error")

    selected = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
            "post-state-capability-oracles.json"
        )
    )
    if selected.get("schema_version") != 2 or len(selected.get("oracles", [])) != 500:
        raise ExecutorError("configuration_error")
    row = _one(
        selected["oracles"], "oracle_id", "oracle.runtime.ui.video-management-tab"
    )
    bounds = row.get("execution_bounds", {})
    expected_contract = {
        "bulk_delete": "irreversible",
        "file_types": ["MP4", "MKV"],
        "multi_upload": True,
        "optional_template_environment": True,
        "rtsp_management": True,
        "upload_progress": True,
        "wave3_acceptance": {
            "executor_ready": False,
            "materialized": False,
            "package": "agent-smartcity",
            "planning_requirement_ids": ["ui-tiny-media"],
        },
    }
    if (
        row.get("capability_id") != contract["capability_id"]
        or row.get("current_state") != "open_unexecuted"
        or row.get("evidence") != []
        or row.get("fixture", {}).get("input", {}).get("contract") != expected_contract
        or bounds.get("max_requests") != 11
        or bounds.get("max_actions") != 11
        or bounds.get("executor") is not None
        or bounds.get("collectors") != []
    ):
        raise ExecutorError("configuration_error")

    predecessor = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/base-semantic-runtime-evidence/"
            "contract.json"
        )
    )
    case = _one(predecessor.get("cases"), "planning_requirement_id", "ui-tiny-media")
    if (
        case.get("adapter") != "manual-browser-receipt"
        or case.get("max_requests") != 11
        or case.get("max_actions") != 11
        or [step.get("id") for step in case.get("workflow", [])] != expected_workflow
    ):
        raise ExecutorError("configuration_error")
    ui_contract = _json(
        _repo_path(
            "deploy/docker/thor-local/qualification/ui-runtime-contracts/contract.json"
        )
    )
    ui_case = _one(
        ui_contract.get("requirements"), "planning_requirement_id", "ui-tiny-media"
    )
    if (
        ui_case.get("max_duration_seconds") != 240
        or ui_case.get("max_browser_actions") != 40
        or ui_case.get("max_api_exchanges") != 32
        or ui_case.get("owned_resource_suffixes")
        != ["video-mp4", "video-mkv", "rtsp-sensor"]
        or ui_contract.get("policy", {}).get("runtime_executor_implemented")
        is not False
    ):
        raise ExecutorError("configuration_error")

    harness = _read_regular(HARNESS_PATH, MAX_CONFIG_BYTES, "configuration_error")
    if (
        b"connectOverCDP" not in harness
        or b".launch(" in harness
        or b"launchPersistentContext" in harness
        or b"browser.close(" in harness
    ):
        raise ExecutorError("configuration_error")
    Draft202012Validator.check_schema(_json(MANIFEST_SCHEMA_PATH))
    Draft202012Validator.check_schema(_json(RECEIPT_SCHEMA_PATH))
    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "inert_plan_valid",
        "runtime_activity_performed": False,
        "selected_metadata_rows": 500,
        "selected_ui_state": "open_unexecuted_null_bound",
        "semantic_checkpoints": 11,
        "max_browser_actions": 40,
        "max_api_exchanges": 32,
        "browser_plugin": "absent_regular_playwright_fallback",
        "browser_launch_allowed": False,
        "playwright_entry_files_pinned": True,
        "playwright_transitive_graph_pinned": True,
        "canonical_bound": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
    }


def _origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ExecutorError("invalid_manifest") from exc
    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ExecutorError("invalid_manifest")
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ExecutorError("invalid_manifest") from exc
    if not address.is_loopback:
        raise ExecutorError("invalid_manifest")
    rendered = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{rendered}:{port}"


def _validate_manifest_value(value: dict[str, Any]) -> dict[str, Any]:
    _schema(value, MANIFEST_SCHEMA_PATH, "invalid_manifest")
    if not RUN_ID_RE.fullmatch(value["run_id"]):
        raise ExecutorError("invalid_manifest")
    origins = [
        _origin(value[key])
        for key in ("ui_origin", "cdp_origin", "vst_origin", "agent_origin")
    ]
    if origins[1] in {origins[0], origins[2], origins[3]}:
        raise ExecutorError("invalid_manifest")
    for key, origin in zip(
        ("ui_origin", "cdp_origin", "vst_origin", "agent_origin"), origins
    ):
        value[key] = origin

    run_id = value["run_id"]
    expected_names = [f"{run_id}.video-mp4.mp4", f"{run_id}.video-mkv.mkv"]
    if value["owned_rtsp_name"] != f"{run_id}.rtsp-sensor":
        raise ExecutorError("invalid_manifest")
    fixture_hashes: set[str] = set()
    for index, item in enumerate(value["fixtures"]):
        fixture_path = Path(item["path"])
        try:
            resolved = fixture_path.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ExecutorError("invalid_manifest") from exc
        if (
            fixture_path != resolved
            or fixture_path.name != expected_names[index]
            or item["extension"] != (".mp4" if index == 0 else ".mkv")
        ):
            raise ExecutorError("invalid_manifest")
        raw = _read_regular(fixture_path, 12582912, "invalid_manifest", absolute=True)
        if (
            len(raw) <= 10485760
            or _digest(raw) != item["sha256"]
            or item["sha256"] in fixture_hashes
        ):
            raise ExecutorError("invalid_manifest")
        fixture_hashes.add(item["sha256"])

    for path_key, hash_key, executable in (
        ("node_executable", "node_sha256", True),
        ("playwright_module", "playwright_sha256", False),
    ):
        selected = Path(value[path_key])
        try:
            resolved = selected.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise ExecutorError("invalid_manifest") from exc
        if selected != resolved:
            raise ExecutorError("invalid_manifest")
        raw = _read_regular(
            selected,
            MAX_TOOL_BYTES,
            "invalid_manifest",
            absolute=True,
            executable=executable,
        )
        if _digest(raw) != value[hash_key]:
            raise ExecutorError("invalid_manifest")

    packages: dict[str, tuple[Path, dict[str, Any]]] = {}
    for item in value["playwright_packages"]:
        name = item["name"]
        root = _absolute_directory(Path(item["path"]), "invalid_manifest")
        if root.name != name or name in packages:
            raise ExecutorError("invalid_manifest")
        if _tree_digest(root, "invalid_manifest") != item["tree_sha256"]:
            raise ExecutorError("invalid_manifest")
        package = _decode(
            _read_regular(
                root / "package.json",
                MAX_CONFIG_BYTES,
                "invalid_manifest",
                absolute=True,
            ),
            "invalid_manifest",
        )
        if package.get("name") != name or package.get("version") != item["version"]:
            raise ExecutorError("invalid_manifest")
        item["path"] = str(root)
        packages[name] = (root, package)
    if set(packages) != {"playwright", "playwright-core"}:
        raise ExecutorError("invalid_manifest")
    playwright_root, playwright_package = packages["playwright"]
    _core_root, core_package = packages["playwright-core"]
    version = value["playwright_packages"][0]["version"]
    versions = {row["version"] for row in value["playwright_packages"]}
    playwright_dependencies = playwright_package.get("dependencies")
    playwright_optional = playwright_package.get("optionalDependencies", {})
    core_dependencies = core_package.get("dependencies", {})
    core_optional = core_package.get("optionalDependencies", {})
    if (
        len(versions) != 1
        or playwright_dependencies != {"playwright-core": version}
        or not isinstance(playwright_optional, dict)
        or set(playwright_optional) - {"fsevents"}
        or core_dependencies != {}
        or core_optional != {}
        or playwright_package.get("peerDependencies", {}) != {}
        or core_package.get("peerDependencies", {}) != {}
    ):
        raise ExecutorError("invalid_manifest")
    try:
        Path(value["playwright_module"]).relative_to(playwright_root)
    except ValueError as exc:
        raise ExecutorError("invalid_manifest") from exc
    return value


def _manifest(path: Path) -> dict[str, Any]:
    if not path.is_absolute():
        raise ExecutorError("invalid_manifest")
    value = _decode(
        _read_regular(path, MAX_CONFIG_BYTES, "invalid_manifest", absolute=True),
        "invalid_manifest",
    )
    return _validate_manifest_value(value)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _run_harness(manifest: Mapping[str, Any]) -> dict[str, Any]:
    child_input = _canonical(manifest)
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_PROXY": "127.0.0.1,::1",
        "no_proxy": "127.0.0.1,::1",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
    }
    try:
        process = subprocess.Popen(
            [manifest["node_executable"], str(HARNESS_PATH)],
            cwd=HERE,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise ExecutorError("tool_failed") from exc
    assert (
        process.stdin is not None
        and process.stdout is not None
        and process.stderr is not None
    )
    try:
        process.stdin.write(child_input)
        process.stdin.close()
    except OSError as exc:
        _terminate(process)
        raise ExecutorError("tool_failed") from exc

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, ("stdout", 4194304))
    selector.register(process.stderr, selectors.EVENT_READ, ("stderr", 1048576))
    buffers: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + 240
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise ExecutorError("tool_failed")
            events = selector.select(timeout=min(0.25, deadline - time.monotonic()))
            for key, _mask in events:
                label, maximum = key.data
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except OSError as exc:
                    raise ExecutorError("tool_failed") from exc
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[label].extend(chunk)
                if len(buffers[label]) > maximum:
                    raise ExecutorError("tool_failed")
        remaining = max(0.0, deadline - time.monotonic())
        try:
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise ExecutorError("tool_failed") from exc
    except BaseException:
        _terminate(process)
        raise
    finally:
        selector.close()
    if return_code != 0 or buffers["stderr"]:
        raise ExecutorError("browser_oracle_failed")
    return _decode(bytes(buffers["stdout"]), "browser_oracle_failed")


def execute(
    *, manifest: Mapping[str, Any], acknowledgement: str, runner: Any = _run_harness
) -> dict[str, Any]:
    plan = compile_plan()
    contract = _json(CONTRACT_PATH)
    if acknowledgement != contract["authorization"]["acknowledgement"]:
        raise ExecutorError("authorization_required")
    if not isinstance(manifest, Mapping):
        raise ExecutorError("invalid_manifest")
    value = _validate_manifest_value(dict(manifest))
    result = runner(value)
    expected_keys = {
        "status",
        "browser_actions",
        "api_exchanges",
        "semantic_checkpoints",
        "checks",
        "cleanup",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected_keys
        or result.get("status") != "pass"
        or result.get("semantic_checkpoints") != 11
        or type(result.get("browser_actions")) is not int
        or not 11 <= result["browser_actions"] <= 40
        or type(result.get("api_exchanges")) is not int
        or not 1 <= result["api_exchanges"] <= 32
    ):
        raise ExecutorError("browser_oracle_failed")
    expected_checks = {
        "page_identity": True,
        "not_blank": True,
        "no_framework_overlay": True,
        "console_health": True,
        "interaction_proof": True,
        "mp4": True,
        "mkv": True,
        "multi_upload": True,
        "rtsp_positive": True,
        "rtsp_adjacent_negative": True,
        "upload_progress": True,
        "template_environment": True,
        "bulk_delete_confirm": True,
        "bulk_delete_cancel": True,
        "ordered_multichunk_protocol": True,
        "upload_payload_digest_integrity": True,
    }
    checks = result.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks)
        != set(expected_checks) | {"desktop_screenshot", "mobile_screenshot"}
        or any(
            checks.get(key) is not expected for key, expected in expected_checks.items()
        )
        or not SHA256_RE.fullmatch(str(checks.get("desktop_screenshot")))
        or not SHA256_RE.fullmatch(str(checks.get("mobile_screenshot")))
    ):
        raise ExecutorError("browser_oracle_failed")
    if result.get("cleanup") != {
        "registered_owned_resources": 3,
        "deleted_owned_resources": 3,
        "owned_absent": True,
        "unrelated_state_restored": True,
    }:
        raise ExecutorError("browser_oracle_failed")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "candidate_pass",
        "contract_sha256": _digest(
            _read_regular(CONTRACT_PATH, MAX_CONFIG_BYTES, "configuration_error")
        ),
        "manifest_sha256": _digest(_canonical(value)),
        "run_id_sha256": _digest(value["run_id"]),
        "origin_sha256": [
            _digest(value[key])
            for key in ("ui_origin", "cdp_origin", "vst_origin", "agent_origin")
        ],
        "tool_entry_file_sha256": [
            value["node_sha256"],
            value["playwright_sha256"],
        ],
        "fixture_sha256": [row["sha256"] for row in value["fixtures"]],
        "playwright_tree_sha256": [
            row["tree_sha256"] for row in value["playwright_packages"]
        ],
        "budget": {
            "semantic_checkpoints": 11,
            "browser_actions": result["browser_actions"],
            "api_exchanges": result["api_exchanges"],
            "max_browser_actions": 40,
            "max_api_exchanges": 32,
            "max_duration_seconds": 240,
        },
        "checks": checks,
        "cleanup": result["cleanup"],
        "browser_plugin": "absent_regular_playwright_fallback",
        "playwright_entry_files_pinned": True,
        "playwright_transitive_graph_pinned": True,
        "canonical_bound": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "warehouse_sample_bundle": "excluded",
    }
    _schema(receipt, RECEIPT_SCHEMA_PATH, "configuration_error")
    if plan["canonical_bound"] is not False:
        raise ExecutorError("configuration_error")
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("plan")
    live = subparsers.add_parser("execute-playwright")
    live.add_argument("--manifest", required=True)
    live.add_argument("--acknowledgement", required=True)
    args = parser.parse_args(argv)
    command = args.command or "plan"
    try:
        if command == "plan":
            result = compile_plan()
        else:
            contract = _json(CONTRACT_PATH)
            if args.acknowledgement != contract["authorization"]["acknowledgement"]:
                raise ExecutorError("authorization_required")
            manifest = _manifest(Path(args.manifest))
            result = execute(
                manifest=manifest,
                acknowledgement=args.acknowledgement,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except ExecutorError as exc:
        print(json.dumps({"status": "error", "code": exc.code}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
