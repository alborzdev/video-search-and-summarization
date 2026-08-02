#!/usr/bin/env python3
"""Produce bounded, Warehouse-free evidence for the two MV3DT config tools.

The default action is an inert plan.  Execution imports only checksum-locked
repository Python modules and writes below one private temporary root.  A
promotable aggregate is emitted only from a clean committed checkout against
an exact executor-ready oracle successor.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
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
from typing import Any, Callable, Iterator
from unittest.mock import patch

import yaml
from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
ACK = "I_ACKNOWLEDGE_OFFLINE_MV3DT_CONFIG_UTILS_RUNTIME_EVIDENCE"
EXECUTOR_RELATIVE = (
    "deploy/docker/thor-local/qualification/"
    "mv3dt-config-utils-runtime-evidence-successor/executor.py"
)
EXPECTED_CAPABILITIES = [
    "tool.mv3dt.cam-info-generator",
    "tool.mv3dt.pub-sub-generator",
]
EXPECTED_NAMESPACES = {
    "tool.mv3dt.cam-info-generator": "vss-oracle-tool-mv3dt-cam-info-generator",
    "tool.mv3dt.pub-sub-generator": "vss-oracle-tool-mv3dt-pub-sub-generator",
}
EXPECTED_WORKLOAD = {
    "units": 1,
    "requests_per_unit": 7,
    "overhead_requests": 0,
    "calculated_max_requests": 7,
    "phases": ["positive_run_1", "positive_run_2", "adjacent_negative"],
}
EXPECTED_MAX_ACTIONS = {
    "tool.mv3dt.cam-info-generator": 7,
    "tool.mv3dt.pub-sub-generator": 10,
}
EXPECTED_SUPPORTING_ACTIONS = {
    "tool.mv3dt.cam-info-generator": 0,
    "tool.mv3dt.pub-sub-generator": 3,
}
EXPECTED_SUPPORTING_ARGUMENT_PARSER_CALLS = {
    "tool.mv3dt.cam-info-generator": 3,
    "tool.mv3dt.pub-sub-generator": 3,
}
EXPECTED_IMPORTED_SOURCE_FUNCTION_INVOCATIONS = {
    "tool.mv3dt.cam-info-generator": 10,
    "tool.mv3dt.pub-sub-generator": 13,
}
EXPECTED_SOURCE_FUNCTION_COUNTS = {
    "tool.mv3dt.cam-info-generator": {
        "cam._parse_model_args": 4,
        "cam.generate_cam_info_files": 6,
        "pub.generate_pub_sub_config": 0,
    },
    "tool.mv3dt.pub-sub-generator": {
        "cam._parse_model_args": 3,
        "cam.generate_cam_info_files": 3,
        "pub.generate_pub_sub_config": 7,
    },
}
MAX_PRODUCT_EXECUTION_SECONDS = 900
FINAL_GAP = (
    "No known gap: a current target-bound offline runtime receipt covers the exact "
    "MV3DT configuration generator contract twice, including adjacent-negative "
    "behavior, determinism, and exact cleanup without the Warehouse sample bundle."
)
LEDGER_BINDING_KEYS = (
    "feature_id",
    "kind",
    "title",
    "source_claims",
    "acceptance_class",
    "thor_state",
    "runtime_state",
    "contract",
    "gap",
)


class EvidenceError(RuntimeError):
    """A binding, confinement rule, execution, or semantic oracle failed."""


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
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise EvidenceError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON: {path}") from exc


def repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise EvidenceError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    current = root
    try:
        for component in candidate.parts:
            current /= component
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
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
    """Open every parent component with openat/O_NOFOLLOW from the filesystem root."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.name or absolute == Path(absolute.anchor):
        raise EvidenceError("receipt output must name a file")
    current_fd = os.open(
        absolute.anchor,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
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


def safe_output_path(path: Path) -> Path:
    """Validate an output path through component-wise openat traversal."""
    absolute, parent_fd = open_safe_output_parent(path)
    os.close(parent_fd)
    return absolute


def publish_receipt_exclusive(path: Path, rendered: str) -> None:
    """Create a receipt exactly once through an opened, verified parent directory."""
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
        written = 0
        while written < len(payload):
            written += os.write(receipt_fd, payload[written:])
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
    return result.stdout.strip()


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = strict_json(path)
    schema = strict_json(CONTRACT_SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(contract),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise EvidenceError(f"contract schema violation at {location}: {error.message}")
    if [
        row.get("capability_id") for row in contract["capabilities"]
    ] != EXPECTED_CAPABILITIES:
        raise EvidenceError("exact two-capability order drift")
    if (
        contract["policy"].get("target_case_actions_per_capability") != 7
        or contract["policy"].get("supporting_cam_generation_actions")
        != EXPECTED_SUPPORTING_ACTIONS
        or contract["policy"].get("aggregate_bounded_capability_actions") != 17
        or contract["policy"].get("aggregate_requests") != 14
        or contract["policy"].get("aggregate_imported_helper_invocations") != 6
        or contract["policy"].get(
            "aggregate_total_imported_source_function_invocations"
        )
        != 23
        or contract["policy"].get("aggregate_imported_source_function_counts")
        != {
            "cam._parse_model_args": 7,
            "cam.generate_cam_info_files": 9,
            "pub.generate_pub_sub_config": 7,
        }
    ):
        raise EvidenceError("tool action/request envelope drift")
    return contract


def require_default_contract(path: Path) -> Path:
    """Reject alternate --contract inputs so the recorded default hash is truthful."""
    try:
        resolved = path.resolve(strict=True)
        expected = CONTRACT_PATH.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("contract path is absent or inaccessible") from exc
    if resolved != expected or path.is_symlink():
        raise EvidenceError(
            "--contract must name the package's canonical contract.json"
        )
    return expected


@contextlib.contextmanager
def product_execution_deadline(seconds: float) -> Iterator[None]:
    """Apply a hard wall-clock deadline to imported product-source execution."""
    if seconds <= 0:
        raise EvidenceError("product execution deadline must be positive")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def timed_out(_signum: int, _frame: Any) -> None:
        raise EvidenceError(f"product execution exceeded {seconds:g}-second deadline")

    signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def instrument_source_functions(cam_module: Any, pub_module: Any) -> dict[str, int]:
    counts = {
        "cam._parse_model_args": 0,
        "cam.generate_cam_info_files": 0,
        "pub.generate_pub_sub_config": 0,
    }

    def wrap(module: Any, attribute: str, counter_key: str) -> None:
        original = getattr(module, attribute)

        def counted(*args: Any, **kwargs: Any) -> Any:
            counts[counter_key] += 1
            return original(*args, **kwargs)

        setattr(module, attribute, counted)

    wrap(cam_module, "_parse_model_args", "cam._parse_model_args")
    wrap(cam_module, "generate_cam_info_files", "cam.generate_cam_info_files")
    wrap(pub_module, "generate_pub_sub_config", "pub.generate_pub_sub_config")
    return counts


def source_count_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {key: after[key] - before[key] for key in before}


def _rows_by_id(document: dict[str, Any], collection: str, key: str) -> dict[str, Any]:
    rows = document.get(collection)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise EvidenceError(f"invalid {collection} collection")
    result = {row.get(key): row for row in rows}
    if len(result) != len(rows):
        raise EvidenceError(f"duplicate or missing identity in {collection}")
    return result


def _expected_ledger_binding(capability: dict[str, Any]) -> dict[str, Any]:
    return {key: capability[key] for key in LEDGER_BINDING_KEYS}


def _validate_future_oracle(
    current: dict[str, Any],
    future: dict[str, Any],
    capability: dict[str, Any],
    fixture_lock: dict[str, str],
) -> None:
    capability_id = capability["id"]
    if future.get("capability_id") != capability_id:
        raise EvidenceError(f"future oracle capability drift: {capability_id}")
    if future.get("oracle_id") != f"oracle.{capability_id}":
        raise EvidenceError(f"future oracle identity drift: {capability_id}")
    prospective_binding = _expected_ledger_binding(capability)
    prospective_binding["thor_state"] = "wired"
    prospective_binding["runtime_state"] = "passed_current"
    prospective_binding["gap"] = FINAL_GAP
    if future.get("ledger_binding") != prospective_binding:
        raise EvidenceError(f"future oracle ledger binding drift: {capability_id}")

    preserved = (
        "profile",
        "mode",
        "reviewed_scenario_ids",
        "expected_observations",
        "assertions",
        "admission_prerequisites",
        "current_state",
        "evidence",
    )
    for key in preserved:
        if future.get(key) != current.get(key):
            raise EvidenceError(
                f"future oracle changed preserved {key}: {capability_id}"
            )
    if future.get("current_state") != "open_unexecuted" or future.get("evidence") != []:
        raise EvidenceError(
            f"future oracle contains premature evidence: {capability_id}"
        )

    current_fixture = copy.deepcopy(current["fixture"])
    future_fixture = copy.deepcopy(future.get("fixture"))
    if not isinstance(future_fixture, dict):
        raise EvidenceError(f"future oracle fixture absent: {capability_id}")
    current_fixture["materialization"] = None
    materialization = future_fixture.get("materialization")
    future_fixture["materialization"] = None
    if future_fixture != current_fixture:
        raise EvidenceError(f"future oracle changed fixture semantics: {capability_id}")
    if materialization != {
        "path": fixture_lock["path"],
        "generator": EXECUTOR_RELATIVE,
        "sha256": fixture_lock["sha256"],
    }:
        raise EvidenceError(f"future oracle fixture authority drift: {capability_id}")

    execution = future.get("execution_bounds", {})
    current_execution = current.get("execution_bounds", {})
    for key in (
        "network_scope",
        "max_duration_seconds",
        "model_staging",
        "warehouse_sample_bundle",
    ):
        if execution.get(key) != current_execution.get(key):
            raise EvidenceError(
                f"future oracle changed execution {key}: {capability_id}"
            )
    if (
        execution.get("executor") != EXECUTOR_RELATIVE
        or execution.get("collectors") != [EXECUTOR_RELATIVE]
        or execution.get("max_actions") != EXPECTED_MAX_ACTIONS[capability_id]
        or execution.get("max_requests") != 7
        or execution.get("max_duration_seconds") != MAX_PRODUCT_EXECUTION_SECONDS
        or execution.get("workload") != EXPECTED_WORKLOAD
    ):
        raise EvidenceError(f"future oracle execution envelope drift: {capability_id}")

    cleanup = future.get("cleanup", {})
    current_cleanup = current.get("cleanup", {})
    namespace = EXPECTED_NAMESPACES[capability_id]
    for key in ("mutation", "pre_state", "restore", "postconditions"):
        if cleanup.get(key) != current_cleanup.get(key):
            raise EvidenceError(f"future oracle changed cleanup {key}: {capability_id}")
    if (
        cleanup.get("targets") != [namespace]
        or cleanup.get("allowlist") != [namespace]
        or cleanup.get("executor") != EXECUTOR_RELATIVE
        or cleanup.get("postcondition_collectors") != [EXECUTOR_RELATIVE]
    ):
        raise EvidenceError(f"future oracle cleanup authority drift: {capability_id}")
    if future.get("acceptance_readiness") != {
        "classification": "executor_ready",
        "blockers": [],
    }:
        raise EvidenceError(f"future oracle readiness drift: {capability_id}")


def verify_bindings(
    contract: dict[str, Any],
    *,
    oracle_document: Path | None,
    require_clean: bool,
    require_executor_ready: bool,
) -> dict[str, Any]:
    if contract != strict_json(CONTRACT_PATH):
        raise EvidenceError("in-memory contract differs from canonical contract.json")
    if (
        contract.get("package_id")
        != "thor-mv3dt-config-utils-runtime-evidence-successor-v1"
    ):
        raise EvidenceError("package identity drift")
    for section in (
        "network_allowed",
        "docker_allowed",
        "service_lifecycle_allowed",
        "model_access_allowed",
        "downloads_allowed",
        "credentials_allowed",
    ):
        if contract["policy"].get(section) is not False:
            raise EvidenceError(f"confinement policy drift: {section}")
    if contract["policy"].get("warehouse_sample_bundle") != "excluded":
        raise EvidenceError("Warehouse sample must remain excluded")

    payload_path = repo_file(
        "deploy/docker/thor-local/qualification/"
        "mv3dt-config-utils-runtime-evidence-successor/fixtures/"
        "two-camera-calibration.json"
    )
    payload_sha = sha_file(payload_path)
    if (
        payload_sha
        != "055c9cf201030130d9a449721492a495534815b81425cd98477ad25cdb7712b4"
    ):
        raise EvidenceError("shared calibration payload drift")

    current_oracle_path = repo_file(contract["target"]["current_oracle_document"])
    current_ledger_path = repo_file(contract["target"]["current_ledger_document"])
    current_oracles = strict_json(current_oracle_path)
    ledger = strict_json(current_ledger_path)
    oracle_by_id = _rows_by_id(current_oracles, "oracles", "capability_id")
    ledger_by_id = _rows_by_id(ledger, "capabilities", "id")

    selected_rows: dict[str, str] = {}
    ledger_rows: dict[str, str] = {}
    fixture_hashes: dict[str, str] = {}
    for spec in contract["capabilities"]:
        capability_id = spec["capability_id"]
        if spec["oracle_id"] != f"oracle.{capability_id}":
            raise EvidenceError(f"oracle identity drift: {capability_id}")
        oracle = oracle_by_id.get(capability_id)
        capability = ledger_by_id.get(capability_id)
        if oracle is None or capability is None:
            raise EvidenceError(f"current authority row absent: {capability_id}")
        oracle_sha = sha_bytes(canonical_bytes(oracle))
        ledger_sha = sha_bytes(canonical_bytes(capability))
        if oracle_sha != spec["current_oracle_sha256"]:
            raise EvidenceError(f"current oracle row drift: {capability_id}")
        if ledger_sha != spec["current_ledger_row_sha256"]:
            raise EvidenceError(f"current ledger row drift: {capability_id}")
        if oracle.get("ledger_binding") != _expected_ledger_binding(capability):
            raise EvidenceError(f"current oracle ledger binding drift: {capability_id}")
        selected_rows[capability_id] = oracle_sha
        ledger_rows[capability_id] = ledger_sha

        for lock in spec["source_controls"]:
            if sha_file(repo_file(lock["path"])) != lock["sha256"]:
                raise EvidenceError(f"source lock mismatch: {lock['path']}")
        fixture_lock = spec["fixture_manifest"]
        fixture_path = repo_file(fixture_lock["path"])
        if sha_file(fixture_path) != fixture_lock["sha256"]:
            raise EvidenceError(f"fixture manifest drift: {capability_id}")
        fixture = strict_json(fixture_path)
        if (
            fixture.get("capability_id") != capability_id
            or fixture.get("fixture_id") != f"fixture.{capability_id}"
            or fixture.get("namespace") != EXPECTED_NAMESPACES[capability_id]
            or fixture.get("warehouse_sample_bundle") != "excluded"
            or fixture.get("source_payload")
            != {
                "path": str(payload_path.relative_to(REPO_ROOT)),
                "sha256": payload_sha,
            }
            or fixture.get("positive", {}).get("runs") != 2
            or len(fixture.get("adjacent_negative_case_ids", [])) != 5
        ):
            raise EvidenceError(f"fixture manifest semantics drift: {capability_id}")
        fixture_hashes[capability_id] = fixture_lock["sha256"]

    history = contract["corroborating_history"]
    if sha_file(repo_file(history["path"])) != history["sha256"]:
        raise EvidenceError("corroborating candidate receipt drift")
    if history.get("authority") != "non_promoting_candidate_only":
        raise EvidenceError("historical evidence authority escalation")

    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain", "--untracked-files=all")
    checkout_clean = status == ""
    if require_clean and not checkout_clean:
        raise EvidenceError("checkout is not fully clean; refusing promotable receipt")
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            contract["target"]["upstream_commit"],
            "HEAD",
        ],
        cwd=REPO_ROOT,
        check=False,
        timeout=30,
    )
    if ancestor.returncode:
        raise EvidenceError("upstream target commit is not an ancestor of HEAD")

    execution_oracle_input = (
        current_oracle_path if oracle_document is None else oracle_document
    )
    try:
        if execution_oracle_input.is_absolute():
            execution_oracle_relative = str(
                execution_oracle_input.relative_to(REPO_ROOT)
            )
        else:
            execution_oracle_relative = str(execution_oracle_input)
        execution_oracle_path = repo_file(execution_oracle_relative)
    except (OSError, ValueError) as exc:
        raise EvidenceError(
            "execution oracle must be a committed repository file"
        ) from exc
    execution_registry = strict_json(execution_oracle_path)
    if execution_registry.get("target") != current_oracles.get("target"):
        raise EvidenceError("execution oracle target differs from current authority")
    execution_by_id = _rows_by_id(execution_registry, "oracles", "capability_id")
    execution_hashes: dict[str, str] = {}
    execution_ready = True
    for spec in contract["capabilities"]:
        capability_id = spec["capability_id"]
        future = execution_by_id.get(capability_id)
        if future is None:
            raise EvidenceError(f"execution oracle row absent: {capability_id}")
        execution_hashes[capability_id] = sha_bytes(canonical_bytes(future))
        try:
            _validate_future_oracle(
                oracle_by_id[capability_id],
                future,
                ledger_by_id[capability_id],
                spec["fixture_manifest"],
            )
        except EvidenceError:
            execution_ready = False
            if require_executor_ready:
                raise
    if require_executor_ready and not execution_ready:
        raise EvidenceError(
            "execution oracle rows are not exact executor-ready authority"
        )

    return {
        "checkout_head": head,
        "checkout_tree": tree,
        "checkout_clean": checkout_clean,
        "checkout_status_porcelain_sha256": sha_bytes(status.encode("utf-8")),
        "upstream_commit": contract["target"]["upstream_commit"],
        "product_version": contract["target"]["product_version"],
        "current_oracle_document_path": str(current_oracle_path.relative_to(REPO_ROOT)),
        "current_oracle_row_sha256": selected_rows,
        "current_ledger_row_sha256": ledger_rows,
        "execution_oracle_document_path": execution_oracle_relative,
        "execution_oracle_document_sha256": sha_file(execution_oracle_path),
        "execution_oracle_row_sha256": execution_hashes,
        "execution_oracles_executor_ready": execution_ready,
        "fixture_manifest_sha256": fixture_hashes,
        "contract_sha256": sha_file(CONTRACT_PATH),
        "executor_sha256": sha_file(Path(__file__)),
    }


def verify_environment(contract: dict[str, Any]) -> dict[str, Any]:
    expected = contract["environment"]
    observed_distributions: dict[str, str] = {}
    for distribution in expected["observed_distributions"]:
        try:
            observed_distributions[distribution] = importlib.metadata.version(
                distribution
            )
        except importlib.metadata.PackageNotFoundError as exc:
            raise EvidenceError(
                f"required current-Thor distribution absent: {distribution}"
            ) from exc
    if observed_distributions != expected["observed_distributions"]:
        raise EvidenceError(
            f"current-Thor distribution identity drift: {observed_distributions}"
        )
    import cv2
    import numpy as np
    import tqdm

    observed_modules = {
        "numpy": np.__version__,
        "cv2": cv2.__version__,
        "yaml": yaml.__version__,
        "tqdm": tqdm.__version__,
    }
    if observed_modules != expected["observed_modules"]:
        raise EvidenceError(f"current-Thor module identity drift: {observed_modules}")
    if platform.system().lower() != "linux" or platform.machine() != "aarch64":
        raise EvidenceError("execution host is not Linux aarch64")
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if version != expected["python_major_minor"]:
        raise EvidenceError(f"Python identity drift: {version}")
    if expected.get("declared_versions_match_observed") is not False:
        raise EvidenceError("dependency caveat was incorrectly removed")
    return {
        "platform": "linux-aarch64",
        "python": platform.python_version(),
        "declared_requirements": expected["declared_requirements"],
        "observed_distributions": observed_distributions,
        "observed_modules": observed_modules,
        "declared_versions_match_observed": False,
        "dependency_caveat": expected["dependency_caveat"],
        "normative_scope": "observed_current_thor_behavior_only",
    }


def load_module(name: str, relative: str) -> Any:
    path = repo_file(relative)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EvidenceError(f"cannot load source module: {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def network_denied() -> Iterator[None]:
    def reject(*_args: Any, **_kwargs: Any) -> None:
        raise EvidenceError("network access attempted by offline executor")

    with (
        patch.object(socket.socket, "connect", reject),
        patch.object(socket, "create_connection", reject),
    ):
        yield


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def tree_hash(root: Path) -> tuple[str, dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        raise EvidenceError(f"output root is not a real directory: {root}")
    records: list[dict[str, str]] = []
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise EvidenceError(f"unexpected output type: {path}")
        relative = path.relative_to(root).as_posix()
        digest = sha_file(path)
        files[relative] = digest
        records.append({"path": relative, "sha256": digest})
    return sha_bytes(canonical_bytes(records)), files


def _payload(contract: dict[str, Any]) -> tuple[Path, dict[str, Any], str]:
    path = repo_file(
        "deploy/docker/thor-local/qualification/"
        "mv3dt-config-utils-runtime-evidence-successor/fixtures/"
        "two-camera-calibration.json"
    )
    return path, strict_json(path), sha_file(path)


def _expect_value_error(case_id: str, action: Callable[[], Any]) -> dict[str, Any]:
    try:
        action()
    except (ValueError, FileNotFoundError) as exc:
        return {
            "case_id": case_id,
            "rejected": True,
            "exception": type(exc).__name__,
        }
    raise EvidenceError(f"adjacent negative did not fail closed: {case_id}")


def _cam_semantics(output: Path) -> dict[str, Any]:
    files = sorted(output.glob("*.yml"))
    if [path.stem for path in files] != ["custom_cam_a", "custom_cam_b"]:
        raise EvidenceError("camInfo output camera set drift")
    semantic: dict[str, Any] = {}
    expected_models = [
        {"classID": 0, "height": 1.7, "radius": 0.3},
        {"classID": 1, "height": 1.2, "radius": 0.25},
    ]
    for path in files:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "projectionMatrix_3x4_w2p",
            "modelInfo",
        }:
            raise EvidenceError(f"camInfo schema drift: {path.name}")
        projection = value["projectionMatrix_3x4_w2p"]
        if (
            not isinstance(projection, list)
            or len(projection) != 12
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in projection
            )
        ):
            raise EvidenceError(f"camInfo projection drift: {path.name}")
        if value["modelInfo"] != expected_models:
            raise EvidenceError(f"camInfo model priors drift: {path.name}")
        semantic[path.stem] = {
            "projection_shape": [3, 4],
            "projection_value_count": 12,
            "class_ids": [0, 1],
            "finite": True,
        }
    return semantic


def run_cam_positive(
    root: Path, contract: dict[str, Any], cam_module: Any
) -> dict[str, Any]:
    payload_path, _payload_value, payload_sha = _payload(contract)
    input_path = root / "input/calibration.json"
    input_path.parent.mkdir(parents=True)
    shutil.copyfile(payload_path, input_path)
    before = sha_file(input_path)
    output = root / "camInfo"
    entries = cam_module._parse_model_args([["0", "1.7", "0.3"], ["1", "1.2", "0.25"]])
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        count = cam_module.generate_cam_info_files(input_path, output, entries)
    if count != 2 or sha_file(input_path) != before:
        raise EvidenceError("camInfo generation count or input immutability failed")
    digest, files = tree_hash(output)
    expected = contract["capabilities"][0]["expected_output_locks"][
        "cam_info_tree_sha256"
    ]
    if digest != expected:
        raise EvidenceError(f"camInfo output lock drift: {digest}")
    return {
        "payload_sha256": payload_sha,
        "output_sha256": digest,
        "file_sha256": files,
        "semantic": _cam_semantics(output),
        "input_unchanged": True,
    }


def run_cam_negatives(root: Path, cam_module: Any) -> list[dict[str, Any]]:
    base = strict_json(
        repo_file(
            "deploy/docker/thor-local/qualification/"
            "mv3dt-config-utils-runtime-evidence-successor/fixtures/"
            "two-camera-calibration.json"
        )
    )
    entries = cam_module._parse_model_args([["0", "1.7", "0.3"]])
    negative_root = root / "negatives"
    negative_root.mkdir()

    unsafe = copy.deepcopy(base)
    unsafe["sensors"][0]["id"] = "../escape"
    unsafe_path = negative_root / "unsafe.json"
    write_json(unsafe_path, unsafe)
    results = [
        _expect_value_error(
            "unsafe-sensor-id",
            lambda: cam_module.generate_cam_info_files(
                unsafe_path, negative_root / "unsafe-out", entries
            ),
        )
    ]
    if (root / "escape.yml").exists():
        raise EvidenceError("unsafe sensor negative escaped namespace")

    duplicate = copy.deepcopy(base)
    duplicate["sensors"][1]["id"] = duplicate["sensors"][0]["id"]
    duplicate_path = negative_root / "duplicate.json"
    write_json(duplicate_path, duplicate)
    results.append(
        _expect_value_error(
            "duplicate-sensor-id",
            lambda: cam_module.generate_cam_info_files(
                duplicate_path, negative_root / "duplicate-out", entries
            ),
        )
    )

    bad_matrix = copy.deepcopy(base)
    bad_matrix["sensors"][0]["cameraMatrix"] = [[1, 2], [3, 4]]
    bad_matrix_path = negative_root / "bad-matrix.json"
    write_json(bad_matrix_path, bad_matrix)
    results.append(
        _expect_value_error(
            "invalid-camera-matrix",
            lambda: cam_module.generate_cam_info_files(
                bad_matrix_path, negative_root / "bad-matrix-out", entries
            ),
        )
    )
    results.append(
        _expect_value_error(
            "duplicate-class-id",
            lambda: cam_module._parse_model_args(
                [["0", "1.0", "0.2"], ["0", "2.0", "0.4"]]
            ),
        )
    )

    outside = negative_root / "outside"
    outside.mkdir()
    symlink_output = negative_root / "linked-output"
    symlink_output.symlink_to(outside, target_is_directory=True)
    results.append(
        _expect_value_error(
            "symlink-output",
            lambda: cam_module.generate_cam_info_files(
                repo_file(
                    "deploy/docker/thor-local/qualification/"
                    "mv3dt-config-utils-runtime-evidence-successor/fixtures/"
                    "two-camera-calibration.json"
                ),
                symlink_output,
                entries,
            ),
        )
    )
    return results


def _pub_semantics(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "pubBrokerTopicStr",
        "subPeerBrokerTopicStrs",
    }:
        raise EvidenceError("pub/sub schema drift")
    cameras = ["custom_cam_a", "custom_cam_b"]
    pubs = value["pubBrokerTopicStr"]
    subs = value["subPeerBrokerTopicStrs"]
    expected_pubs = {camera: f"localhost:1883;/trck/{camera}" for camera in cameras}
    if pubs != expected_pubs or set(subs) != set(cameras):
        raise EvidenceError("pub/sub publication or camera mapping drift")
    for camera, peer in zip(cameras, reversed(cameras), strict=True):
        if (
            subs[camera] != [expected_pubs[peer]]
            or expected_pubs[camera] in subs[camera]
        ):
            raise EvidenceError("pub/sub FOV neighbor topology drift")
    return {
        "broker": "localhost:1883",
        "camera_ids": cameras,
        "topics": [expected_pubs[camera] for camera in cameras],
        "peer_counts": {camera: 1 for camera in cameras},
        "self_subscriptions": 0,
        "overlap_threshold": 0.1,
    }


def _prepare_cam_info(root: Path, cam_module: Any) -> Path:
    payload_path, _value, _sha = _payload({})
    output = root / "camInfo"
    entries = cam_module._parse_model_args([["0", "1.7", "0.3"], ["1", "1.2", "0.25"]])
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        cam_module.generate_cam_info_files(payload_path, output, entries)
    _cam_semantics(output)
    return output


def run_pub_positive(
    root: Path, contract: dict[str, Any], cam_module: Any, pub_module: Any
) -> dict[str, Any]:
    payload_path, _payload_value, payload_sha = _payload(contract)
    before = sha_file(payload_path)
    cam_info = _prepare_cam_info(root, cam_module)
    output = root / "peer_configs"
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        result = pub_module.generate_pub_sub_config(
            cam_info_path=cam_info,
            mqtt_brokers="localhost:1883",
            minimum_object_size=1,
            neighbor_criteria="overlap_threshold:0.1",
            output_path=output,
            range_of_interest=[-4, -2, 6, 10],
        )
    expected_path = output / "pub_sub_info_config.yml"
    if result != expected_path or sha_file(payload_path) != before:
        raise EvidenceError("pub/sub output path or input immutability failed")
    digest = sha_file(expected_path)
    expected = contract["capabilities"][1]["expected_output_locks"][
        "pub_sub_file_sha256"
    ]
    if digest != expected:
        raise EvidenceError(f"pub/sub output lock drift: {digest}")
    return {
        "payload_sha256": payload_sha,
        "output_sha256": digest,
        "file_sha256": {"pub_sub_info_config.yml": digest},
        "semantic": _pub_semantics(expected_path),
        "input_unchanged": True,
    }


def run_pub_negatives(
    root: Path, cam_module: Any, pub_module: Any
) -> list[dict[str, Any]]:
    negative_root = root / "negatives"
    negative_root.mkdir()
    cam_info = _prepare_cam_info(negative_root / "source", cam_module)
    common = {
        "cam_info_path": cam_info,
        "mqtt_brokers": "localhost:1883",
        "minimum_object_size": 1,
        "neighbor_criteria": "overlap_threshold:0.1",
        "range_of_interest": [-4, -2, 6, 10],
    }

    def invoke(case: str, **updates: Any) -> Any:
        arguments = dict(common)
        arguments.update(updates)
        arguments.setdefault("output_path", negative_root / f"{case}-out")
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return pub_module.generate_pub_sub_config(**arguments)

    results = [
        _expect_value_error(
            "invalid-broker", lambda: invoke("bad-broker", mqtt_brokers="not a broker")
        ),
        _expect_value_error(
            "invalid-overlap-threshold",
            lambda: invoke("bad-threshold", neighbor_criteria="overlap_threshold:1.1"),
        ),
        _expect_value_error(
            "invalid-range-of-interest",
            lambda: invoke("bad-roi", range_of_interest=[0, 0, 0, 1]),
        ),
    ]
    empty = negative_root / "empty"
    empty.mkdir()
    results.append(
        _expect_value_error(
            "empty-camera-directory",
            lambda: invoke("empty", cam_info_path=empty),
        )
    )
    outside = negative_root / "outside"
    outside.mkdir()
    linked = negative_root / "linked-output"
    linked.symlink_to(outside, target_is_directory=True)
    results.append(
        _expect_value_error(
            "symlink-output",
            lambda: invoke("symlink", output_path=linked),
        )
    )
    return results


def _observation_and_assertion_evidence(
    oracle: dict[str, Any], deterministic: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    values: dict[str, Any] = {
        "contract_identity": {"contract": oracle["ledger_binding"]["contract"]},
        "semantic_result": True,
        "deterministic_output": deterministic,
    }
    observations: list[dict[str, Any]] = []
    for required in oracle["expected_observations"]:
        observation_id = required["id"]
        if observation_id not in values:
            raise EvidenceError(f"unsupported oracle observation: {observation_id}")
        observations.append(
            {"id": observation_id, "result": "pass", "value": values[observation_id]}
        )

    assertions: list[dict[str, Any]] = []
    for required in oracle["assertions"]:
        operator = required["operator"]
        if operator == "recorded_pass":
            observed = values.get(required["observation"])
            if observed is not True:
                raise EvidenceError(f"recorded-pass assertion failed: {required['id']}")
        elif operator == "equals":
            parts = required["observation"].split("/")
            observed: Any = values
            for part in parts:
                if not isinstance(observed, dict) or part not in observed:
                    raise EvidenceError(
                        f"assertion path not observed: {required['observation']}"
                    )
                observed = observed[part]
            if observed != required["expected"]:
                raise EvidenceError(f"equals assertion failed: {required['id']}")
        else:
            raise EvidenceError(f"unsupported oracle operator: {operator}")
        assertions.append(
            {
                "id": required["id"],
                "observation": required["observation"],
                "operator": operator,
                "expected": required["expected"],
                "observed": observed,
                "result": "pass",
            }
        )
    return observations, assertions


def _official_receipt(
    capability: dict[str, Any],
    oracle: dict[str, Any],
    observations: list[dict[str, Any]],
    assertions: list[dict[str, Any]],
) -> dict[str, Any]:
    target = strict_json(
        repo_file("deploy/docker/thor-local/parity/official-capabilities.json")
    )["target"]
    materialization = oracle["fixture"]["materialization"]
    cleanup = oracle["cleanup"]
    return {
        "schema_version": 1,
        "capability_id": capability["id"],
        "oracle_id": oracle["oracle_id"],
        "oracle_sha256": sha_bytes(canonical_bytes(oracle)),
        "result": "passed_current",
        "target": {
            "product_version": target["product_version"],
            "ga_commit": target["ga_commit"],
            "main_commit": target["main_commit"],
            "captured_on": target["captured_on"],
        },
        "scenario_ids": oracle["reviewed_scenario_ids"],
        "fixture": {
            "id": oracle["fixture"]["id"],
            "path": materialization["path"],
            "sha256": materialization["sha256"],
        },
        "observations": observations,
        "assertions": assertions,
        "cleanup": {
            "result": "pass",
            "mutation": cleanup["mutation"],
            "targets": cleanup["targets"],
            "allowlist": cleanup["allowlist"],
            "pre_state_captured": True,
            "postconditions": [
                {"description": description, "result": "pass"}
                for description in cleanup["postconditions"]
            ],
        },
    }


def _runtime_evidence_binding(
    row: dict[str, Any],
    oracle: dict[str, Any],
    bindings: dict[str, Any],
    captured_at_utc: str,
) -> dict[str, Any]:
    evidence_payload = {
        key: value
        for key, value in row.items()
        if key not in {"official_receipt", "runtime_evidence_binding"}
    }
    return {
        "schema_version": 1,
        "captured_at_utc": captured_at_utc,
        "executor_sha256": bindings["executor_sha256"],
        "contract_sha256": bindings["contract_sha256"],
        "oracle_sha256": sha_bytes(canonical_bytes(oracle)),
        "oracle_document_sha256": bindings["execution_oracle_document_sha256"],
        "official_receipt_sha256": (
            sha_bytes(canonical_bytes(row["official_receipt"]))
            if "official_receipt" in row
            else None
        ),
        "product_execution_deadline_seconds": MAX_PRODUCT_EXECUTION_SECONDS,
        "bounded_capability_actions": row["bounded_capability_actions"],
        "target_case_actions": row["target_case_actions"],
        "supporting_cam_generation_actions": row["supporting_cam_generation_actions"],
        "requests": row["requests"],
        "imported_helper_invocations": row["imported_helper_invocations"],
        "total_imported_source_function_invocations": row[
            "total_imported_source_function_invocations"
        ],
        "run_output_sha256": row["run_output_sha256"],
        "positive_output_sha256": row["positive_observations"]["output_sha256"],
        "adjacent_negatives_sha256": sha_bytes(
            canonical_bytes(row["adjacent_negatives"])
        ),
        "capability_evidence_sha256": sha_bytes(canonical_bytes(evidence_payload)),
    }


def _load_official_verifier() -> Any:
    parity_dir = REPO_ROOT / "deploy/docker/thor-local/parity"
    inserted = str(parity_dir) not in sys.path
    if inserted:
        sys.path.insert(0, str(parity_dir))
    try:
        return load_module(
            "mv3dt_config_utils_official_verifier",
            "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        )
    finally:
        if inserted:
            sys.path.remove(str(parity_dir))


def validate_result_exact(
    result: dict[str, Any],
    *,
    development: bool | None,
    oracle_registry: dict[str, Any] | None = None,
) -> None:
    """Deeply validate the aggregate beyond the deliberately small JSON schema."""

    top_keys = {
        "schema_version",
        "package_id",
        "mode",
        "status",
        "captured_at_utc",
        "bindings",
        "environment",
        "capability_results",
        "cleanup",
        "confinement",
        "promotion",
    }
    if set(result) != top_keys:
        raise EvidenceError("aggregate receipt top-level fields are not exact")
    if result.get("schema_version") != 1 or result.get("package_id") != (
        "thor-mv3dt-config-utils-runtime-evidence-successor-v1"
    ):
        raise EvidenceError("aggregate receipt identity drift")
    plan_mode = result.get("status") == "plan"
    if plan_mode != (result.get("mode") == "plan"):
        raise EvidenceError("aggregate mode/status mismatch")

    if plan_mode:
        if development is not None or result.get("captured_at_utc") is not None:
            raise EvidenceError("plan receipt execution state drift")
        expected_plan_capability_keys = {
            "capability_id",
            "oracle_id",
            "status",
            "independent_runs",
            "bounded_capability_actions",
            "target_case_actions",
            "supporting_cam_generation_actions",
            "requests",
            "imported_helper_invocations",
            "total_imported_source_function_invocations",
            "imported_source_function_counts",
            "deterministic_output",
            "fixture_sha256",
            "payload_sha256",
            "run_output_sha256",
            "positive_observations",
            "adjacent_negatives",
            "cleanup",
        }
        for expected_id, row in zip(
            EXPECTED_CAPABILITIES, result["capability_results"], strict=True
        ):
            if (
                set(row) != expected_plan_capability_keys
                or row.get("capability_id") != expected_id
                or row.get("oracle_id") != f"oracle.{expected_id}"
                or row.get("status") != "plan"
                or row.get("independent_runs") != 0
                or row.get("bounded_capability_actions") != 0
                or row.get("target_case_actions") != 0
                or row.get("supporting_cam_generation_actions") != 0
                or row.get("requests") != 0
                or row.get("imported_helper_invocations") != 0
                or row.get("total_imported_source_function_invocations") != 0
                or row.get("imported_source_function_counts") != {}
                or row.get("deterministic_output") is not False
                or row.get("run_output_sha256") != []
                or row.get("positive_observations") != {}
                or row.get("adjacent_negatives") != []
                or row.get("cleanup") != {"execution_performed": False}
            ):
                raise EvidenceError(f"plan capability result drift: {expected_id}")
        if result["cleanup"] != {"execution_performed": False}:
            raise EvidenceError("plan cleanup drift")
        if set(result["environment"]) != {"execution_performed", "dependency_caveat"}:
            raise EvidenceError("plan environment fields are not exact")
        if result["environment"]["execution_performed"] is not False:
            raise EvidenceError("plan falsely reports environment execution")
        if set(result["confinement"]) != {
            "network_calls",
            "docker_calls",
            "service_lifecycle_calls",
            "model_accesses",
            "downloads",
            "warehouse_sample_accesses",
        } or any(result["confinement"].values()):
            raise EvidenceError("plan confinement drift")
        if set(result["promotion"]) != {
            "receipt_is_runtime_evidence",
            "aggregate_is_promotable",
            "ledger_mutation_performed",
            "requires_separate_reviewed_metadata_integration",
            "dependency_pin_parity_claimed",
        }:
            raise EvidenceError("plan promotion fields are not exact")
        if (
            result["promotion"]["receipt_is_runtime_evidence"] is not False
            or result["promotion"]["aggregate_is_promotable"] is not False
            or result["promotion"]["ledger_mutation_performed"] is not False
            or result["promotion"]["requires_separate_reviewed_metadata_integration"]
            is not True
            or result["promotion"]["dependency_pin_parity_claimed"] is not False
        ):
            raise EvidenceError("plan promotion semantics drift")
        return

    if development is None or result.get("status") != "pass":
        raise EvidenceError("execution receipt validation mode missing")
    if not isinstance(result.get("captured_at_utc"), str) or not result[
        "captured_at_utc"
    ].endswith("Z"):
        raise EvidenceError("execution capture timestamp drift")
    binding_keys = {
        "checkout_head",
        "checkout_tree",
        "checkout_clean",
        "checkout_status_porcelain_sha256",
        "upstream_commit",
        "product_version",
        "current_oracle_document_path",
        "current_oracle_row_sha256",
        "current_ledger_row_sha256",
        "execution_oracle_document_path",
        "execution_oracle_document_sha256",
        "execution_oracle_row_sha256",
        "execution_oracles_executor_ready",
        "fixture_manifest_sha256",
        "contract_sha256",
        "executor_sha256",
    }
    if set(result["bindings"]) != binding_keys:
        raise EvidenceError("execution binding fields are not exact")
    bindings = result["bindings"]
    if bindings["execution_oracles_executor_ready"] is not True:
        raise EvidenceError("execution authority/cleanliness drift")
    if not development and bindings["checkout_clean"] is not True:
        raise EvidenceError("promotable aggregate is not clean-checkout bound")
    if not development and bindings["checkout_status_porcelain_sha256"] != sha_bytes(
        b""
    ):
        raise EvidenceError(
            "promotable aggregate status digest is not the empty checkout"
        )

    environment_keys = {
        "platform",
        "python",
        "declared_requirements",
        "observed_distributions",
        "observed_modules",
        "declared_versions_match_observed",
        "dependency_caveat",
        "normative_scope",
    }
    if set(result["environment"]) != environment_keys:
        raise EvidenceError("execution environment fields are not exact")
    if (
        result["environment"]["declared_versions_match_observed"] is not False
        or result["environment"]["normative_scope"]
        != "observed_current_thor_behavior_only"
    ):
        raise EvidenceError("dependency caveat semantics drift")

    capability_keys = {
        "capability_id",
        "oracle_id",
        "status",
        "independent_runs",
        "bounded_capability_actions",
        "target_case_actions",
        "supporting_cam_generation_actions",
        "requests",
        "imported_helper_invocations",
        "total_imported_source_function_invocations",
        "imported_source_function_counts",
        "deterministic_output",
        "fixture_sha256",
        "payload_sha256",
        "run_output_sha256",
        "positive_observations",
        "adjacent_negatives",
        "oracle_observations",
        "oracle_assertions",
        "runtime_evidence_binding",
        "cleanup",
    }
    if not development:
        capability_keys.add("official_receipt")
    if len(result["capability_results"]) != 2:
        raise EvidenceError("execution capability denominator drift")
    if oracle_registry is None:
        raise EvidenceError("execution receipt requires its exact oracle registry")
    future_by_id = _rows_by_id(oracle_registry, "oracles", "capability_id")
    ledger = strict_json(
        repo_file("deploy/docker/thor-local/parity/official-capabilities.json")
    )
    ledger_by_id = _rows_by_id(ledger, "capabilities", "id")
    verifier = _load_official_verifier() if not development else None
    for expected_id, row in zip(
        EXPECTED_CAPABILITIES, result["capability_results"], strict=True
    ):
        if set(row) != capability_keys:
            raise EvidenceError(
                f"capability result fields are not exact: {expected_id}"
            )
        if (
            row["capability_id"] != expected_id
            or row["oracle_id"] != f"oracle.{expected_id}"
            or row["status"] != "pass"
            or row["independent_runs"] != 2
            or row["bounded_capability_actions"] != EXPECTED_MAX_ACTIONS[expected_id]
            or row["target_case_actions"] != 7
            or row["supporting_cam_generation_actions"]
            != EXPECTED_SUPPORTING_ACTIONS[expected_id]
            or row["requests"] != 7
            or row["imported_helper_invocations"]
            != EXPECTED_SUPPORTING_ARGUMENT_PARSER_CALLS[expected_id]
            or row["total_imported_source_function_invocations"]
            != EXPECTED_IMPORTED_SOURCE_FUNCTION_INVOCATIONS[expected_id]
            or row["imported_source_function_counts"]
            != EXPECTED_SOURCE_FUNCTION_COUNTS[expected_id]
            or row["deterministic_output"] is not True
            or len(row["run_output_sha256"]) != 2
            or row["run_output_sha256"][0] != row["run_output_sha256"][1]
            or len(row["adjacent_negatives"]) != 5
            or any(
                set(case) != {"case_id", "rejected", "exception"}
                or case["rejected"] is not True
                for case in row["adjacent_negatives"]
            )
        ):
            raise EvidenceError(f"capability execution semantics drift: {expected_id}")
        if (
            set(row["positive_observations"])
            != {
                "payload_sha256",
                "output_sha256",
                "file_sha256",
                "semantic",
                "input_unchanged",
            }
            or row["positive_observations"]["input_unchanged"] is not True
        ):
            raise EvidenceError(f"positive observation fields drift: {expected_id}")
        if row["cleanup"] != {
            "namespace": EXPECTED_NAMESPACES[expected_id],
            "pre_state_captured": "absent",
            "temporary_files_only": True,
            "removed": True,
            "siblings_unchanged": True,
        }:
            raise EvidenceError(f"capability cleanup drift: {expected_id}")
        oracle = future_by_id[expected_id]
        if row["runtime_evidence_binding"] != _runtime_evidence_binding(
            row, oracle, bindings, result["captured_at_utc"]
        ):
            raise EvidenceError(f"outer runtime evidence binding drift: {expected_id}")
        expected_observation_ids = [
            item["id"] for item in oracle["expected_observations"]
        ]
        expected_assertion_ids = [item["id"] for item in oracle["assertions"]]
        if [
            item.get("id") for item in row["oracle_observations"]
        ] != expected_observation_ids:
            raise EvidenceError(f"oracle observation denominator drift: {expected_id}")
        if [
            item.get("id") for item in row["oracle_assertions"]
        ] != expected_assertion_ids:
            raise EvidenceError(f"oracle assertion denominator drift: {expected_id}")
        if development:
            if "official_receipt" in row:
                raise EvidenceError(
                    "development aggregate exposed a promotable official receipt"
                )
        else:
            prospective = {
                "id": expected_id,
                "scenario_ids": ledger_by_id[expected_id]["scenario_ids"],
                **copy.deepcopy(oracle["ledger_binding"]),
            }
            try:
                verifier._validate_bound_runtime_evidence(
                    prospective,
                    oracle,
                    row["official_receipt"],
                    ledger["target"],
                )
            except Exception as exc:
                raise EvidenceError(
                    f"canonical official receipt validation failed: {expected_id}: {exc}"
                ) from exc

    if result["cleanup"] != {
        "root_removed": True,
        "exact_namespace_count": 2,
        "sibling_names_unchanged": True,
        "repository_mutations": 0,
    }:
        raise EvidenceError("aggregate cleanup fields or semantics drift")
    confinement = result["confinement"]
    if set(confinement) != {
        "network_calls",
        "docker_calls",
        "service_lifecycle_calls",
        "model_accesses",
        "downloads",
        "warehouse_sample_accesses",
        "bounded_capability_actions",
        "target_case_actions",
        "supporting_cam_generation_actions",
        "requests",
        "imported_helper_invocations",
        "total_imported_source_function_invocations",
        "imported_source_function_counts",
        "product_subprocess_calls",
        "provenance_git_command_count",
        "network_boundary",
        "product_execution_deadline_seconds",
    }:
        raise EvidenceError("aggregate confinement fields are not exact")
    if (
        any(
            confinement[key] != 0
            for key in (
                "network_calls",
                "docker_calls",
                "service_lifecycle_calls",
                "model_accesses",
                "downloads",
                "warehouse_sample_accesses",
                "product_subprocess_calls",
            )
        )
        or confinement["bounded_capability_actions"] != 17
        or confinement["target_case_actions"] != 14
        or confinement["supporting_cam_generation_actions"] != 3
        or confinement["requests"] != 14
        or confinement["imported_helper_invocations"] != 6
        or confinement["total_imported_source_function_invocations"] != 23
        or confinement["imported_source_function_counts"]
        != {
            "cam._parse_model_args": 7,
            "cam.generate_cam_info_files": 9,
            "pub.generate_pub_sub_config": 7,
        }
        or confinement["provenance_git_command_count"] != 5
        or confinement["product_execution_deadline_seconds"] != 900
    ):
        raise EvidenceError("aggregate confinement counts drift")
    promotion = result["promotion"]
    if set(promotion) != {
        "receipt_is_runtime_evidence",
        "aggregate_is_promotable",
        "eligible_capability_ids",
        "family_id",
        "ledger_mutation_performed",
        "requires_separate_reviewed_metadata_integration",
        "development_smoke_only",
        "dependency_pin_parity_claimed",
    }:
        raise EvidenceError("aggregate promotion fields are not exact")
    if (
        promotion["receipt_is_runtime_evidence"] is development
        or promotion["aggregate_is_promotable"] is development
        or promotion["eligible_capability_ids"] != EXPECTED_CAPABILITIES
        or promotion["family_id"] != "mv3dt-config-utils"
        or promotion["ledger_mutation_performed"] is not False
        or promotion["requires_separate_reviewed_metadata_integration"] is not True
        or promotion["development_smoke_only"] is not development
        or promotion["dependency_pin_parity_claimed"] is not False
    ):
        raise EvidenceError("aggregate promotion semantics drift")


def execute(
    contract: dict[str, Any], *, oracle_document: Path, development: bool
) -> dict[str, Any]:
    bindings = verify_bindings(
        contract,
        oracle_document=oracle_document,
        require_clean=not development,
        require_executor_ready=True,
    )
    environment = verify_environment(contract)
    captured_at_utc = (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    registry = strict_json(REPO_ROOT / bindings["execution_oracle_document_path"])
    future_by_id = _rows_by_id(registry, "oracles", "capability_id")
    ledger = strict_json(repo_file(contract["target"]["current_ledger_document"]))
    ledger_by_id = _rows_by_id(ledger, "capabilities", "id")
    cam_module = load_module(
        "mv3dt_config_utils_cam_runtime",
        "tools/rtvi-cv-mv3dt-utils/generate_cam_info_configs.py",
    )
    pub_module = load_module(
        "mv3dt_config_utils_pub_runtime",
        "tools/rtvi-cv-mv3dt-utils/generate_pub_sub_configs.py",
    )
    source_function_counts = instrument_source_functions(cam_module, pub_module)

    temporary = Path(tempfile.mkdtemp(prefix="vss-mv3dt-config-utils-"))
    sentinel = temporary / "adjacent-sentinel"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    sentinel_sha = sha_file(sentinel)
    capability_results: list[dict[str, Any]] = []
    try:
        with (
            product_execution_deadline(MAX_PRODUCT_EXECUTION_SECONDS),
            network_denied(),
        ):
            for spec in contract["capabilities"]:
                capability_id = spec["capability_id"]
                source_counts_before = dict(source_function_counts)
                namespace = EXPECTED_NAMESPACES[capability_id]
                namespace_root = temporary / namespace
                if namespace_root.exists():
                    raise EvidenceError(
                        f"namespace pre-state is not absent: {namespace}"
                    )
                siblings_before = sorted(path.name for path in temporary.iterdir())
                namespace_root.mkdir()
                run_one = namespace_root / "run-1"
                run_two = namespace_root / "run-2"
                negative_root = namespace_root / "adjacent-negatives"
                run_one.mkdir()
                run_two.mkdir()
                negative_root.mkdir()
                if spec["adapter"] == "cam_info_generator":
                    first = run_cam_positive(run_one, contract, cam_module)
                    second = run_cam_positive(run_two, contract, cam_module)
                    negatives = run_cam_negatives(negative_root, cam_module)
                elif spec["adapter"] == "pub_sub_generator":
                    first = run_pub_positive(run_one, contract, cam_module, pub_module)
                    second = run_pub_positive(run_two, contract, cam_module, pub_module)
                    negatives = run_pub_negatives(negative_root, cam_module, pub_module)
                else:
                    raise EvidenceError(f"unknown adapter: {spec['adapter']}")
                capability_source_counts = source_count_delta(
                    source_counts_before, source_function_counts
                )
                if (
                    capability_source_counts
                    != EXPECTED_SOURCE_FUNCTION_COUNTS[capability_id]
                ):
                    raise EvidenceError(
                        f"imported source-function count drift: {capability_id}"
                    )
                if canonical_bytes(first) != canonical_bytes(second):
                    raise EvidenceError(f"independent output drift: {capability_id}")
                if len(negatives) != 5 or not all(row["rejected"] for row in negatives):
                    raise EvidenceError(
                        f"adjacent-negative coverage drift: {capability_id}"
                    )
                if [row["case_id"] for row in negatives] != strict_json(
                    repo_file(spec["fixture_manifest"]["path"])
                )["adjacent_negative_case_ids"]:
                    raise EvidenceError(
                        f"adjacent-negative order drift: {capability_id}"
                    )

                oracle = future_by_id[capability_id]
                observations, assertions = _observation_and_assertion_evidence(
                    oracle, True
                )
                digest = sha_bytes(canonical_bytes(first))
                result: dict[str, Any] = {
                    "capability_id": capability_id,
                    "oracle_id": spec["oracle_id"],
                    "status": "pass",
                    "independent_runs": 2,
                    "bounded_capability_actions": EXPECTED_MAX_ACTIONS[capability_id],
                    "target_case_actions": 7,
                    "supporting_cam_generation_actions": EXPECTED_SUPPORTING_ACTIONS[
                        capability_id
                    ],
                    "requests": 7,
                    "imported_helper_invocations": (
                        EXPECTED_SUPPORTING_ARGUMENT_PARSER_CALLS[capability_id]
                    ),
                    "total_imported_source_function_invocations": (
                        EXPECTED_IMPORTED_SOURCE_FUNCTION_INVOCATIONS[capability_id]
                    ),
                    "imported_source_function_counts": capability_source_counts,
                    "deterministic_output": True,
                    "fixture_sha256": spec["fixture_manifest"]["sha256"],
                    "payload_sha256": first["payload_sha256"],
                    "run_output_sha256": [digest, digest],
                    "positive_observations": first,
                    "adjacent_negatives": negatives,
                    "oracle_observations": observations,
                    "oracle_assertions": assertions,
                    "cleanup": {
                        "namespace": namespace,
                        "pre_state_captured": "absent",
                        "temporary_files_only": True,
                        "removed": False,
                        "siblings_unchanged": False,
                    },
                }
                shutil.rmtree(namespace_root)
                siblings_after = sorted(path.name for path in temporary.iterdir())
                if (
                    namespace_root.exists()
                    or siblings_after != siblings_before
                    or sha_file(sentinel) != sentinel_sha
                ):
                    raise EvidenceError(
                        f"exact namespace cleanup failed: {capability_id}"
                    )
                result["cleanup"]["removed"] = True
                result["cleanup"]["siblings_unchanged"] = True
                if not development:
                    result["official_receipt"] = _official_receipt(
                        ledger_by_id[capability_id], oracle, observations, assertions
                    )
                result["runtime_evidence_binding"] = _runtime_evidence_binding(
                    result, oracle, bindings, captured_at_utc
                )
                capability_results.append(result)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    if temporary.exists():
        raise EvidenceError("private temporary root cleanup failed")
    if source_function_counts != {
        "cam._parse_model_args": 7,
        "cam.generate_cam_info_files": 9,
        "pub.generate_pub_sub_config": 7,
    }:
        raise EvidenceError("aggregate imported source-function count drift")
    post_status = git("status", "--porcelain", "--untracked-files=all")
    if (
        sha_bytes(post_status.encode("utf-8"))
        != bindings["checkout_status_porcelain_sha256"]
    ):
        raise EvidenceError("repository status changed during evidence execution")

    aggregate = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "target_bound_offline_runtime_evidence",
        "status": "pass",
        "captured_at_utc": captured_at_utc,
        "bindings": bindings,
        "environment": environment,
        "capability_results": capability_results,
        "cleanup": {
            "root_removed": True,
            "exact_namespace_count": 2,
            "sibling_names_unchanged": True,
            "repository_mutations": 0,
        },
        "confinement": {
            "network_calls": 0,
            "docker_calls": 0,
            "service_lifecycle_calls": 0,
            "model_accesses": 0,
            "downloads": 0,
            "warehouse_sample_accesses": 0,
            "bounded_capability_actions": 17,
            "target_case_actions": 14,
            "supporting_cam_generation_actions": 3,
            "requests": 14,
            "imported_helper_invocations": 6,
            "total_imported_source_function_invocations": 23,
            "imported_source_function_counts": source_function_counts,
            "product_subprocess_calls": 0,
            "provenance_git_command_count": 5,
            "network_boundary": "socket connect/create_connection denied during all imported tool actions",
            "product_execution_deadline_seconds": MAX_PRODUCT_EXECUTION_SECONDS,
        },
        "promotion": {
            "receipt_is_runtime_evidence": not development,
            "aggregate_is_promotable": not development,
            "eligible_capability_ids": EXPECTED_CAPABILITIES,
            "family_id": "mv3dt-config-utils",
            "ledger_mutation_performed": False,
            "requires_separate_reviewed_metadata_integration": True,
            "development_smoke_only": development,
            "dependency_pin_parity_claimed": False,
        },
    }
    validate_result_exact(aggregate, development=development, oracle_registry=registry)
    Draft202012Validator(strict_json(RESULT_SCHEMA_PATH)).validate(aggregate)
    return aggregate


def plan(
    contract: dict[str, Any], oracle_document: Path | None = None
) -> dict[str, Any]:
    bindings = verify_bindings(
        contract,
        oracle_document=oracle_document,
        require_clean=False,
        require_executor_ready=False,
    )
    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "plan",
        "status": "plan",
        "captured_at_utc": None,
        "bindings": bindings,
        "environment": {
            "execution_performed": False,
            "dependency_caveat": contract["environment"]["dependency_caveat"],
        },
        "capability_results": [
            {
                "capability_id": row["capability_id"],
                "oracle_id": row["oracle_id"],
                "status": "plan",
                "independent_runs": 0,
                "bounded_capability_actions": 0,
                "target_case_actions": 0,
                "supporting_cam_generation_actions": 0,
                "requests": 0,
                "imported_helper_invocations": 0,
                "total_imported_source_function_invocations": 0,
                "imported_source_function_counts": {},
                "deterministic_output": False,
                "fixture_sha256": row["fixture_manifest"]["sha256"],
                "payload_sha256": "055c9cf201030130d9a449721492a495534815b81425cd98477ad25cdb7712b4",
                "run_output_sha256": [],
                "positive_observations": {},
                "adjacent_negatives": [],
                "cleanup": {"execution_performed": False},
            }
            for row in contract["capabilities"]
        ],
        "cleanup": {"execution_performed": False},
        "confinement": {
            "network_calls": 0,
            "docker_calls": 0,
            "service_lifecycle_calls": 0,
            "model_accesses": 0,
            "downloads": 0,
            "warehouse_sample_accesses": 0,
        },
        "promotion": {
            "receipt_is_runtime_evidence": False,
            "aggregate_is_promotable": False,
            "ledger_mutation_performed": False,
            "requires_separate_reviewed_metadata_integration": True,
            "dependency_pin_parity_claimed": False,
        },
    }
    validate_result_exact(result, development=None)
    Draft202012Validator(strict_json(RESULT_SCHEMA_PATH)).validate(result)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--acknowledge", default="")
        parser.add_argument("--oracle-document", type=Path)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--allow-dirty-development", action="store_true")
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        contract = load_contract(require_default_contract(args.contract))
        output_path = safe_output_path(args.output) if args.output is not None else None
        if args.execute:
            if args.acknowledge != ACK:
                raise EvidenceError(f"--execute requires --acknowledge {ACK}")
            if args.oracle_document is None:
                raise EvidenceError(
                    "--execute requires an executor-ready --oracle-document"
                )
            if not args.allow_dirty_development and args.output is None:
                raise EvidenceError(
                    "promotable execution requires --output outside the repository"
                )
            if output_path is not None:
                if not args.allow_dirty_development:
                    try:
                        output_path.relative_to(REPO_ROOT.resolve(strict=True))
                    except ValueError:
                        pass
                    else:
                        raise EvidenceError(
                            "promotable receipt output must be outside repository"
                        )
            result = execute(
                contract,
                oracle_document=args.oracle_document,
                development=args.allow_dirty_development,
            )
        else:
            result = plan(contract, args.oracle_document)
        rendered = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if output_path is not None:
            publish_receipt_exclusive(output_path, rendered)
        else:
            sys.stdout.write(rendered)
        return 0
    except (
        EvidenceError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
