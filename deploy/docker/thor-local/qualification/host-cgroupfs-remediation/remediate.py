#!/usr/bin/env python3
"""Failure-closed Docker cgroupfs remediation for Thor.

The default mode is a pure plan.  ``inspect`` is read-only.  Host mutation is
reachable only through the exact acknowledgement and an effective uid of zero.
The transaction engine is deliberately separated from ``SystemRuntime`` so its
failure and rollback paths can be exercised without touching Docker or /etc.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

sys.dont_write_bytecode = True

TOOL_ID = "thor-host-cgroupfs-remediation"
ACKNOWLEDGEMENT = "I_AUTHORIZE_DOCKER_CGROUPFS_RESTART_AND_EXACT_WORKLOAD_RESTORATION"
RECOVERY_ACKNOWLEDGEMENT = "I_AUTHORIZE_DOCKER_CGROUPFS_FAILURE_RECOVERY"
DAEMON_PATH = Path("/etc/docker/daemon.json")
JOURNAL_ROOT = Path("/var/lib/vss-thor/cgroup-remediation")
ACTIVE_JOURNAL = JOURNAL_ROOT / "active.json"
LOCK_PATH = Path("/run/lock/vss-thor-cgroup-remediation.lock")
DOCKER = "/usr/bin/docker"
DOCKERD = "/usr/bin/dockerd"
SYSTEMCTL = "/usr/bin/systemctl"
MANAGED_SIGNALS = {signal.SIGINT, signal.SIGTERM}
MAX_OUTPUT = 1024 * 1024
SERVICE_DEADLINE_SECONDS = 180.0
HEALTH_DEADLINE_SECONDS = 900.0
POLL_SECONDS = 2.0
DOCKER_READ_ATTEMPTS = 5
DOCKER_READ_RETRY_SECONDS = 0.5
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
UNIT_EXEC_RUNTIME_FIELD = re.compile(
    r"\s*;\s*(?:start_time|stop_time|pid|code|status)="
    r"(?:\[[^\]]*\]|\([^)]*\)|[^;}]*)(?=\s*;|\s*})"
)
HERE = Path(__file__).resolve().parent
EVIDENCE_SCHEMA = HERE / "evidence.schema.json"
_EVIDENCE_VALIDATOR: Draft202012Validator | None = None


class RemediationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RemediationError("json_value_not_canonical") from exc
    return _sha256(encoded)


def _stable_unit_exec_start(value: str) -> str:
    """Remove systemd's per-invocation fields while retaining command semantics."""
    return " ".join(UNIT_EXEC_RUNTIME_FIELD.sub("", value).split())


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemediationError("daemon_json_duplicate_key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise RemediationError(f"json_nonfinite_number_{value.lower()}")


def _strict_json_loads(content: str | bytes) -> Any:
    try:
        return json.loads(
            content,
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except RemediationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemediationError("json_invalid") from exc


def parse_daemon_config(content: bytes, *, exists: bool = True) -> dict[str, Any]:
    if not exists:
        return {}
    try:
        value = _strict_json_loads(content)
    except RemediationError as exc:
        if exc.code == "json_invalid":
            raise RemediationError("daemon_json_invalid") from exc
        raise
    except Exception as exc:
        raise RemediationError("daemon_json_invalid") from exc
    if not isinstance(value, dict):
        raise RemediationError("daemon_json_not_object")
    return value


def merge_cgroupfs(config: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """Return a semantics-preserving copy with exactly one cgroupfs option."""
    try:
        merged = _strict_json_loads(json.dumps(config, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise RemediationError("daemon_json_nonfinite_or_unserializable") from exc
    options = merged.get("exec-opts", [])
    if not isinstance(options, list) or not all(
        isinstance(item, str) for item in options
    ):
        raise RemediationError("daemon_exec_opts_not_string_array")
    cgroup_options = [
        item for item in options if item.startswith("native.cgroupdriver=")
    ]
    if len(cgroup_options) > 1:
        raise RemediationError("daemon_multiple_cgroup_driver_options")
    malformed = [item for item in options if item == "native.cgroupdriver"]
    if malformed:
        raise RemediationError("daemon_malformed_cgroup_driver_option")
    merged["exec-opts"] = [
        item for item in options if not item.startswith("native.cgroupdriver=")
    ] + ["native.cgroupdriver=cgroupfs"]
    candidate = (json.dumps(merged, indent=2, allow_nan=False) + "\n").encode("utf-8")
    verify_semantic_delta(config, merged)
    return merged, candidate


def _without_cgroup_option(value: dict[str, Any]) -> dict[str, Any]:
    try:
        copy = _strict_json_loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise RemediationError("daemon_json_nonfinite_or_unserializable") from exc
    options = copy.get("exec-opts", [])
    if isinstance(options, list):
        remaining = [
            item
            for item in options
            if not (isinstance(item, str) and item.startswith("native.cgroupdriver="))
        ]
        if remaining:
            copy["exec-opts"] = remaining
        else:
            copy.pop("exec-opts", None)
    return copy


def verify_semantic_delta(before: dict[str, Any], after: dict[str, Any]) -> None:
    if _without_cgroup_option(before) != _without_cgroup_option(after):
        raise RemediationError("daemon_unapproved_semantic_delta")
    options = after.get("exec-opts")
    if (
        not isinstance(options, list)
        or options.count("native.cgroupdriver=cgroupfs") != 1
    ):
        raise RemediationError("daemon_candidate_missing_exact_cgroupfs")
    if any(
        isinstance(item, str)
        and item.startswith("native.cgroupdriver=")
        and item != "native.cgroupdriver=cgroupfs"
        for item in options
    ):
        raise RemediationError("daemon_candidate_conflicting_cgroup_driver")


@dataclass(frozen=True)
class FileState:
    exists: bool
    content: bytes
    mode: int = 0o644
    uid: int = 0
    gid: int = 0
    xattrs: tuple[tuple[str, bytes], ...] = ()

    @property
    def digest(self) -> str | None:
        return _sha256(self.content) if self.exists else None


def _candidate_file_state(original: FileState, candidate: bytes) -> FileState:
    return FileState(
        True,
        candidate,
        original.mode,
        original.uid,
        original.gid,
        original.xattrs,
    )


def _file_metadata_evidence(state: FileState) -> dict[str, Any]:
    xattrs = [
        [name, _sha256(value)]
        for name, value in sorted(state.xattrs, key=lambda item: item[0])
    ]
    identity = {
        "exists": state.exists,
        "mode": state.mode,
        "uid": state.uid,
        "gid": state.gid,
        "xattrs_sha256": _canonical_sha(xattrs),
    }
    return {**identity, "metadata_sha256": _canonical_sha(identity)}


@dataclass(frozen=True)
class ContainerState:
    id: str
    name: str
    status: str
    running: bool
    paused: bool
    restarting: bool
    dead: bool
    restart_policy: str
    auto_remove: bool
    started_at: str
    health: str | None = None


@dataclass(frozen=True)
class HostSnapshot:
    driver: str
    live_restore: bool
    swarm: str
    rootless: bool
    unit_exec_start: str
    unit_drop_ins: str
    config: FileState
    containers: tuple[ContainerState, ...]

    @property
    def inventory_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.id for item in self.containers))

    @property
    def running_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.id for item in self.containers if item.running))

    @property
    def healthy_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(item.id for item in self.containers if item.health == "healthy")
        )

    @property
    def running_digest(self) -> str:
        return _canonical_sha(list(self.running_ids))

    @property
    def inventory_digest(self) -> str:
        return _canonical_sha(list(self.inventory_ids))


@dataclass(frozen=True)
class Inspection:
    snapshot: HostSnapshot
    candidate: bytes
    candidate_config: dict[str, Any]
    candidate_validated: bool
    blockers: tuple[str, ...]
    active_recovery: bool = False


@dataclass(frozen=True)
class Transaction:
    id: str


class Runtime(Protocol):
    @contextlib.contextmanager
    def lock(self) -> Iterator[None]: ...

    def inspect(self) -> Inspection: ...
    def prepare(self, inspection: Inspection) -> Transaction: ...
    def phase(self, transaction: Transaction, phase: str) -> None: ...
    def install_candidate(
        self, transaction: Transaction, inspection: Inspection
    ) -> None: ...
    def restart_docker(self, expected_driver: str) -> None: ...
    def snapshot(self) -> HostSnapshot: ...
    def start_container(self, container_id: str) -> None: ...
    def wait_healthy(self, container_ids: tuple[str, ...]) -> None: ...
    def restore_original(self, transaction: Transaction) -> None: ...
    def complete(self, transaction: Transaction, evidence: dict[str, Any]) -> None: ...
    def active_transaction(self) -> tuple[Transaction, HostSnapshot, str] | None: ...


def admission_blockers(snapshot: HostSnapshot) -> list[str]:
    blockers: list[str] = []
    if snapshot.driver not in {"systemd", "cgroupfs"}:
        blockers.append("docker_cgroup_driver_unrecognized")
    if snapshot.live_restore:
        blockers.append("docker_live_restore_must_be_disabled")
    if snapshot.swarm != "inactive":
        blockers.append("docker_swarm_must_be_inactive")
    if snapshot.rootless:
        blockers.append("rootless_docker_not_supported")
    if snapshot.unit_drop_ins.strip():
        blockers.append("docker_unit_drop_ins_require_review")
    if "/usr/bin/dockerd" not in snapshot.unit_exec_start:
        blockers.append("docker_unit_exec_start_unexpected")
    if (
        "--exec-opt" in snapshot.unit_exec_start
        or "--config-file" in snapshot.unit_exec_start
    ):
        blockers.append("docker_unit_conflicting_daemon_option")
    ids = [item.id for item in snapshot.containers]
    if len(ids) != len(set(ids)) or any(
        not CONTAINER_ID.fullmatch(item) for item in ids
    ):
        blockers.append("container_inventory_invalid")
    if any(
        item.running
        and (item.auto_remove or item.paused or item.restarting or item.dead)
        for item in snapshot.containers
    ):
        blockers.append("running_container_state_not_restorable")
    if any(
        not item.running and item.restart_policy != "no" for item in snapshot.containers
    ):
        blockers.append("nonrunning_container_may_autostart")
    return blockers


def _base_evidence(mode: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool_id": TOOL_ID,
        "mode": mode,
        "status": status,
        "writes_or_lifecycle_actions": False,
        "acknowledgement": (
            RECOVERY_ACKNOWLEDGEMENT if mode == "recover" else ACKNOWLEDGEMENT
        ),
        "failure": None,
        "blockers": [],
        "transaction_id": None,
        "daemon_config": {
            "before_sha256": None,
            "candidate_sha256": None,
            "after_sha256": None,
            "file_state_before": None,
            "file_state_candidate": None,
            "file_state_after": None,
            "strict_json": None,
            "dockerd_validation": None,
            "semantic_delta_only": None,
            "full_file_state_match": None,
            "original_restored": None,
        },
        "docker": {
            "driver_before": None,
            "driver_after": None,
            "restart_attempted": False,
            "rollback_restart_attempted": False,
        },
        "containers": {
            "inventory_before_count": None,
            "inventory_before_ids": None,
            "inventory_before_sha256": None,
            "running_before_count": None,
            "running_before_ids": None,
            "running_before_sha256": None,
            "inventory_after_count": None,
            "inventory_after_ids": None,
            "inventory_after_sha256": None,
            "running_after_count": None,
            "running_after_ids": None,
            "running_after_sha256": None,
            "start_action_count": 0,
            "start_actions": [],
            "start_actions_sha256": _canonical_sha([]),
            "all_start_targets_from_snapshot": True,
            "exact_set_restored": None,
            "healthy_set_restored": None,
        },
        "rollback": {
            "attempted": False,
            "config_restored": None,
            "exact_set_restored": None,
            "failures": [],
        },
    }


def _record_file_state(result: dict[str, Any], which: str, state: FileState) -> None:
    result["daemon_config"][f"file_state_{which}"] = _file_metadata_evidence(state)


def plan() -> dict[str, Any]:
    result = _base_evidence("plan", "planned")
    result["lifecycle"] = [
        "strictly inspect daemon configuration and exact container prestate",
        "merge only native.cgroupdriver=cgroupfs and validate with dockerd",
        "durably journal the exact original before the authorized Docker restart",
        "restore only the pre-snapshot running container IDs",
        "rollback the exact original configuration and running set on failure",
    ]
    return result


def inspection_evidence(inspection: Inspection) -> dict[str, Any]:
    snapshot = inspection.snapshot
    blockers = list(inspection.blockers)
    if (
        not inspection.candidate_validated
        and "dockerd_candidate_validation_failed" not in blockers
    ):
        blockers.append("dockerd_candidate_validation_failed")
    if inspection.active_recovery:
        blockers.append("active_recovery_required")
    status = "blocked" if blockers else "ready"
    result = _base_evidence("inspect", status)
    result["blockers"] = blockers
    result["daemon_config"].update(
        {
            "before_sha256": snapshot.config.digest,
            "candidate_sha256": _sha256(inspection.candidate),
            "strict_json": True,
            "dockerd_validation": inspection.candidate_validated,
            "semantic_delta_only": True,
        }
    )
    _record_file_state(result, "before", snapshot.config)
    _record_file_state(
        result,
        "candidate",
        _candidate_file_state(snapshot.config, inspection.candidate),
    )
    result["docker"]["driver_before"] = snapshot.driver
    result["containers"].update(
        {
            "inventory_before_count": len(snapshot.inventory_ids),
            "inventory_before_ids": list(snapshot.inventory_ids),
            "inventory_before_sha256": snapshot.inventory_digest,
            "running_before_count": len(snapshot.running_ids),
            "running_before_ids": list(snapshot.running_ids),
            "running_before_sha256": snapshot.running_digest,
        }
    )
    return result


def verify_inspection(inspection: Inspection) -> None:
    before = parse_daemon_config(
        inspection.snapshot.config.content,
        exists=inspection.snapshot.config.exists,
    )
    candidate = parse_daemon_config(inspection.candidate)
    verify_semantic_delta(before, candidate)
    if candidate != inspection.candidate_config:
        raise RemediationError("candidate_config_identity_mismatch")
    if not inspection.candidate_validated:
        raise RemediationError("dockerd_candidate_validation_failed")


def _consume_signal() -> int | None:
    pending = signal.sigpending() & MANAGED_SIGNALS
    found: int | None = None
    while pending:
        signum = int(signal.sigwait(pending))
        found = found or signum
        pending = signal.sigpending() & MANAGED_SIGNALS
    return found


def _checkpoint() -> None:
    signum = _consume_signal()
    if signum is not None:
        raise RemediationError(f"interrupted_by_signal_{signum}")


def _snapshot_fields(
    result: dict[str, Any], snapshot: HostSnapshot, suffix: str
) -> None:
    result["containers"].update(
        {
            f"inventory_{suffix}_count": len(snapshot.inventory_ids),
            f"inventory_{suffix}_ids": list(snapshot.inventory_ids),
            f"inventory_{suffix}_sha256": snapshot.inventory_digest,
            f"running_{suffix}_count": len(snapshot.running_ids),
            f"running_{suffix}_ids": list(snapshot.running_ids),
            f"running_{suffix}_sha256": snapshot.running_digest,
        }
    )


def _restore_running_set(
    runtime: Runtime, before: HostSnapshot, result: dict[str, Any]
) -> HostSnapshot:
    current = runtime.snapshot()
    if current.inventory_ids != before.inventory_ids:
        raise RemediationError("container_inventory_drift")
    unexpected = set(current.running_ids) - set(before.running_ids)
    if unexpected:
        raise RemediationError("unexpected_container_activation")
    starts: list[str] = []
    by_id = {item.id: item for item in before.containers}
    missing = set(before.running_ids) - set(current.running_ids)
    for container_id in sorted(missing, key=lambda item: by_id[item].started_at):
        if container_id not in before.running_ids:
            raise RemediationError("start_target_not_in_snapshot")
        runtime.start_container(container_id)
        starts.append(container_id)
    if before.healthy_ids:
        runtime.wait_healthy(before.healthy_ids)
    final = runtime.snapshot()
    result["containers"].update(
        {
            "start_action_count": len(starts),
            "start_actions": starts,
            "start_actions_sha256": _canonical_sha(starts),
            "all_start_targets_from_snapshot": all(
                item in before.running_ids for item in starts
            ),
            "exact_set_restored": final.running_ids == before.running_ids,
            "healthy_set_restored": all(
                next(entry for entry in final.containers if entry.id == item).health
                == "healthy"
                for item in before.healthy_ids
            ),
        }
    )
    if final.inventory_ids != before.inventory_ids:
        raise RemediationError("container_inventory_drift")
    if final.running_ids != before.running_ids:
        raise RemediationError("container_running_set_not_restored")
    if not result["containers"]["healthy_set_restored"]:
        raise RemediationError("container_healthy_set_not_restored")
    return final


def _restoration_snapshot_failures(
    before: HostSnapshot, final: HostSnapshot
) -> list[str]:
    failures: list[str] = []
    if final.driver != before.driver:
        failures.append("driver_mismatch")
    if final.config != before.config:
        failures.append("daemon_file_state_mismatch")
    if (
        final.live_restore != before.live_restore
        or final.swarm != before.swarm
        or final.rootless != before.rootless
        or _stable_unit_exec_start(final.unit_exec_start)
        != _stable_unit_exec_start(before.unit_exec_start)
        or final.unit_drop_ins != before.unit_drop_ins
    ):
        failures.append("docker_host_contract_mismatch")
    if final.inventory_ids != before.inventory_ids:
        failures.append("container_inventory_mismatch")
        return failures
    if final.running_ids != before.running_ids:
        failures.append("container_running_set_mismatch")
    before_by_id = {item.id: item for item in before.containers}
    final_by_id = {item.id: item for item in final.containers}
    for container_id in before.inventory_ids:
        expected = before_by_id[container_id]
        actual = final_by_id[container_id]
        if (
            actual.name != expected.name
            or actual.status != expected.status
            or actual.running != expected.running
            or actual.paused != expected.paused
            or actual.restarting != expected.restarting
            or actual.dead != expected.dead
            or actual.restart_policy != expected.restart_policy
            or actual.auto_remove != expected.auto_remove
            or actual.health != expected.health
        ):
            failures.append("container_state_contract_mismatch")
            break
    return failures


def _rollback(
    runtime: Runtime,
    transaction: Transaction,
    before: HostSnapshot,
    result: dict[str, Any],
) -> None:
    result["rollback"]["attempted"] = True
    failures: list[str] = []
    try:
        runtime.restore_original(transaction)
        result["rollback"]["config_restored"] = True
    except Exception:
        result["rollback"]["config_restored"] = False
        failures.append("rollback_config_restore_failed")
    if result["rollback"]["config_restored"]:
        try:
            result["docker"]["rollback_restart_attempted"] = True
            runtime.restart_docker(before.driver)
        except Exception:
            failures.append("rollback_docker_restart_failed")
        try:
            final = _restore_running_set(runtime, before, result)
            _snapshot_fields(result, final, "after")
            result["daemon_config"]["after_sha256"] = final.config.digest
            _record_file_state(result, "after", final.config)
            result["docker"]["driver_after"] = final.driver
            result["rollback"]["exact_set_restored"] = (
                final.running_ids == before.running_ids
            )
            result["daemon_config"]["full_file_state_match"] = (
                final.config == before.config
            )
            result["daemon_config"]["original_restored"] = result["daemon_config"][
                "full_file_state_match"
            ]
            if not result["daemon_config"]["original_restored"]:
                failures.append("rollback_config_verification_failed")
            restoration_failures = _restoration_snapshot_failures(before, final)
            if (
                not restoration_failures
                and "rollback_docker_restart_failed" in failures
            ):
                failures.remove("rollback_docker_restart_failed")
            failures.extend(
                f"rollback_final_{item}"
                for item in restoration_failures
                if f"rollback_final_{item}" not in failures
            )
        except Exception:
            result["rollback"]["exact_set_restored"] = False
            failures.append("rollback_container_set_restore_failed")
    result["rollback"]["failures"] = failures


def execute_transaction(runtime: Runtime) -> dict[str, Any]:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, MANAGED_SIGNALS)
    result = _base_evidence("execute", "failed")
    transaction: Transaction | None = None
    before: HostSnapshot | None = None
    installed = False
    stage = "inspection"
    try:
        with runtime.lock():
            try:
                _checkpoint()
                inspection = runtime.inspect()
                before = inspection.snapshot
                verify_inspection(inspection)
                if inspection.active_recovery:
                    raise RemediationError("active_recovery_required")
                if inspection.blockers:
                    result["blockers"] = list(inspection.blockers)
                    raise RemediationError("host_admission_blocked")
                _snapshot_fields(result, before, "before")
                result["daemon_config"].update(
                    {
                        "before_sha256": before.config.digest,
                        "candidate_sha256": _sha256(inspection.candidate),
                        "strict_json": True,
                        "dockerd_validation": inspection.candidate_validated,
                        "semantic_delta_only": True,
                    }
                )
                expected_candidate_state = _candidate_file_state(
                    before.config, inspection.candidate
                )
                _record_file_state(result, "before", before.config)
                _record_file_state(result, "candidate", expected_candidate_state)
                result["docker"]["driver_before"] = before.driver
                _checkpoint()
                result["writes_or_lifecycle_actions"] = True
                stage = "prepare_transaction"
                transaction = runtime.prepare(inspection)
                result["transaction_id"] = transaction.id
                runtime.phase(transaction, "prepared")
                _checkpoint()
                stage = "preinstall_snapshot"
                if runtime.snapshot() != before:
                    raise RemediationError("host_state_changed_before_install")
                _checkpoint()
                # This phase must reach stable storage before the daemon file
                # can change. Recovery treats it as possibly installed.
                runtime.phase(transaction, "candidate_installing")
                # Treat installation as possibly mutating before the call. An
                # atomic replacement may have succeeded even if a later fsync
                # or bookkeeping operation raises.
                installed = True
                stage = "install_candidate"
                runtime.install_candidate(transaction, inspection)
                runtime.phase(transaction, "candidate_installed")
                _checkpoint()
                stage = "restart_cgroupfs"
                print(
                    "[cgroup-remediation] Restarting Docker with cgroupfs (up to 3 minutes).",
                    file=sys.stderr,
                    flush=True,
                )
                result["docker"]["restart_attempted"] = True
                runtime.restart_docker("cgroupfs")
                runtime.phase(transaction, "docker_restarted")
                _checkpoint()
                stage = "restore_running_set"
                print(
                    "[cgroup-remediation] Restoring the exact prior running set and waiting for its health checks (up to 15 minutes).",
                    file=sys.stderr,
                    flush=True,
                )
                final = _restore_running_set(runtime, before, result)
                _checkpoint()
                _snapshot_fields(result, final, "after")
                result["daemon_config"]["after_sha256"] = final.config.digest
                _record_file_state(result, "after", final.config)
                result["docker"]["driver_after"] = final.driver
                if final.driver != "cgroupfs":
                    raise RemediationError("post_restart_driver_not_cgroupfs")
                result["daemon_config"]["full_file_state_match"] = (
                    final.config == expected_candidate_state
                )
                if not result["daemon_config"]["full_file_state_match"]:
                    raise RemediationError("post_restart_daemon_file_state_drift")
                stage = "validate_success_evidence"
                result["status"] = "passed"
                validate_evidence(result)
                stage = "complete_success_journal"
                print(
                    "[cgroup-remediation] All postconditions passed; closing the transaction.",
                    file=sys.stderr,
                    flush=True,
                )
                runtime.phase(transaction, "complete")
                runtime.complete(transaction, result)
            except RemediationError as exc:
                result["failure"] = exc.code
                if installed and transaction is not None and before is not None:
                    _rollback(runtime, transaction, before, result)
                    if result["rollback"]["failures"]:
                        with contextlib.suppress(Exception):
                            runtime.phase(transaction, "rollback_incomplete")
                    else:
                        with contextlib.suppress(Exception):
                            runtime.phase(transaction, "rollback_complete")
                            validate_evidence(result)
                            runtime.complete(transaction, result)
                elif transaction is not None:
                    with contextlib.suppress(Exception):
                        runtime.phase(transaction, "aborted_before_install")
                        validate_evidence(result)
                        runtime.complete(transaction, result)
            except Exception as exc:
                kind = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
                result["failure"] = f"unexpected_runtime_error_{stage}_{kind}"
                if installed and transaction is not None and before is not None:
                    _rollback(runtime, transaction, before, result)
                    if result["rollback"]["failures"]:
                        with contextlib.suppress(Exception):
                            runtime.phase(transaction, "rollback_incomplete")
                    else:
                        with contextlib.suppress(Exception):
                            runtime.phase(transaction, "rollback_complete")
                            validate_evidence(result)
                            runtime.complete(transaction, result)
                elif transaction is not None:
                    with contextlib.suppress(Exception):
                        runtime.phase(transaction, "aborted_before_install")
                        validate_evidence(result)
                        runtime.complete(transaction, result)
            # A signal delivered during final journal closure is too late to
            # cancel: the exact set is already restored and the transaction is
            # durably committed. Consume it before restoring the caller's mask.
            _consume_signal()
        validate_evidence(result)
        return result
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def recover_transaction(runtime: Runtime) -> dict[str, Any]:
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, MANAGED_SIGNALS)
    result = _base_evidence("recover", "failed")
    try:
        with runtime.lock():
            active = runtime.active_transaction()
            if active is None:
                result["status"] = "ready"
                validate_evidence(result)
                return result
            transaction, before, phase = active
            result["transaction_id"] = transaction.id
            result["writes_or_lifecycle_actions"] = True
            _snapshot_fields(result, before, "before")
            result["daemon_config"]["before_sha256"] = before.config.digest
            _record_file_state(result, "before", before.config)
            result["docker"]["driver_before"] = before.driver
            if phase in {"initializing", "prepared", "aborted_before_install"}:
                final = runtime.snapshot()
                differences = _restoration_snapshot_failures(before, final)
                _snapshot_fields(result, final, "after")
                result["daemon_config"]["after_sha256"] = final.config.digest
                _record_file_state(result, "after", final.config)
                result["daemon_config"]["full_file_state_match"] = (
                    final.config == before.config
                )
                result["daemon_config"]["original_restored"] = result["daemon_config"][
                    "full_file_state_match"
                ]
                result["docker"]["driver_after"] = final.driver
                result["rollback"].update(
                    {
                        "attempted": False,
                        "config_restored": result["daemon_config"][
                            "full_file_state_match"
                        ],
                        "exact_set_restored": not differences,
                    }
                )
                result["containers"].update(
                    {
                        "exact_set_restored": not differences,
                        "healthy_set_restored": not any(
                            "health" in item for item in differences
                        ),
                    }
                )
                if differences:
                    result["failure"] = "recovery_final_snapshot_mismatch"
                    result["rollback"]["failures"] = [
                        f"recovery_final_{item}" for item in differences
                    ]
                    return result
                result["status"] = "passed"
                validate_evidence(result)
                runtime.complete(transaction, result)
                return result
            _rollback(runtime, transaction, before, result)
            final = runtime.snapshot()
            _snapshot_fields(result, final, "after")
            result["daemon_config"]["after_sha256"] = final.config.digest
            _record_file_state(result, "after", final.config)
            result["daemon_config"]["full_file_state_match"] = (
                final.config == before.config
            )
            result["daemon_config"]["original_restored"] = result["daemon_config"][
                "full_file_state_match"
            ]
            result["docker"]["driver_after"] = final.driver
            final_differences = _restoration_snapshot_failures(before, final)
            for item in final_differences:
                failure = f"recovery_final_{item}"
                if failure not in result["rollback"]["failures"]:
                    result["rollback"]["failures"].append(failure)
            if final_differences:
                result["rollback"]["exact_set_restored"] = False
                result["containers"]["exact_set_restored"] = False
            if result["rollback"]["failures"]:
                result["failure"] = "recovery_incomplete"
            else:
                result["status"] = "passed"
                result["failure"] = None
                validate_evidence(result)
                runtime.complete(transaction, result)
            return result
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def validate_evidence(value: dict[str, Any]) -> None:
    global _EVIDENCE_VALIDATOR
    if _EVIDENCE_VALIDATOR is None:
        try:
            schema = _strict_json_loads(EVIDENCE_SCHEMA.read_bytes())
            if not isinstance(schema, dict):
                raise RemediationError("evidence_schema_not_object")
            Draft202012Validator.check_schema(schema)
            _EVIDENCE_VALIDATOR = Draft202012Validator(schema)
        except (OSError, SchemaError, RemediationError) as exc:
            raise RemediationError("evidence_schema_invalid") from exc
    try:
        _EVIDENCE_VALIDATOR.validate(value)
    except ValidationError as exc:
        raise RemediationError("evidence_schema_validation_failed") from exc

    mode = value["mode"]
    status = value["status"]
    expected_ack = RECOVERY_ACKNOWLEDGEMENT if mode == "recover" else ACKNOWLEDGEMENT
    if value["acknowledgement"] != expected_ack:
        raise RemediationError("evidence_acknowledgement_invalid")
    allowed_statuses = {
        "plan": {"planned", "failed"},
        "inspect": {"ready", "blocked", "failed"},
        "execute": {"passed", "failed"},
        "recover": {"ready", "passed", "failed"},
    }
    if status not in allowed_statuses[mode]:
        raise RemediationError("evidence_mode_status_invalid")
    if ("lifecycle" in value) != (status == "planned"):
        raise RemediationError("evidence_lifecycle_presence_invalid")
    if mode in {"plan", "inspect"} and value["writes_or_lifecycle_actions"]:
        raise RemediationError("evidence_read_only_mode_writes_invalid")
    if mode == "recover":
        expected_writes = value["transaction_id"] is not None
        if value["writes_or_lifecycle_actions"] != expected_writes:
            raise RemediationError("evidence_recovery_writes_invalid")
    if status == "failed" and not value["failure"]:
        raise RemediationError("evidence_failure_missing")
    if status != "failed" and value["failure"] is not None:
        raise RemediationError("evidence_unexpected_failure")
    if status == "blocked" and not value["blockers"]:
        raise RemediationError("evidence_blockers_missing")
    if status in {"planned", "ready", "passed"} and value["blockers"]:
        raise RemediationError("evidence_unexpected_blockers")

    if (
        mode == "plan"
        or (mode == "inspect" and status == "failed")
        or (mode == "recover" and status == "ready")
    ):
        daemon = value["daemon_config"]
        if any(item is not None for item in daemon.values()):
            raise RemediationError("evidence_inert_daemon_fields_invalid")
        docker = value["docker"]
        if (
            docker["driver_before"] is not None
            or docker["driver_after"] is not None
            or docker["restart_attempted"]
            or docker["rollback_restart_attempted"]
        ):
            raise RemediationError("evidence_inert_docker_fields_invalid")
        containers = value["containers"]
        identity_fields = [
            key
            for key in containers
            if key.startswith("inventory_") or key.startswith("running_")
        ]
        if any(containers[key] is not None for key in identity_fields):
            raise RemediationError("evidence_inert_container_fields_invalid")
        if (
            containers["start_action_count"] != 0
            or containers["start_actions"]
            or containers["exact_set_restored"] is not None
            or containers["healthy_set_restored"] is not None
        ):
            raise RemediationError("evidence_inert_container_actions_invalid")
        rollback = value["rollback"]
        if (
            rollback["attempted"]
            or rollback["config_restored"] is not None
            or rollback["exact_set_restored"] is not None
            or rollback["failures"]
        ):
            raise RemediationError("evidence_inert_rollback_fields_invalid")

    if mode == "inspect" and status in {"ready", "blocked"}:
        daemon = value["daemon_config"]
        if (
            daemon["candidate_sha256"] is None
            or daemon["file_state_before"] is None
            or daemon["file_state_candidate"] is None
            or daemon["file_state_candidate"]["exists"] is not True
            or daemon["after_sha256"] is not None
            or daemon["file_state_after"] is not None
            or daemon["strict_json"] is not True
            or daemon["semantic_delta_only"] is not True
            or daemon["full_file_state_match"] is not None
            or daemon["original_restored"] is not None
        ):
            raise RemediationError("evidence_inspect_daemon_fields_invalid")
        containers = value["containers"]
        if (
            containers["inventory_before_ids"] is None
            or containers["running_before_ids"] is None
            or containers["inventory_after_ids"] is not None
            or containers["running_after_ids"] is not None
            or containers["start_action_count"] != 0
            or containers["start_actions"]
            or containers["exact_set_restored"] is not None
            or containers["healthy_set_restored"] is not None
        ):
            raise RemediationError("evidence_inspect_container_fields_invalid")

    for name in ("file_state_before", "file_state_candidate", "file_state_after"):
        metadata = value["daemon_config"][name]
        if metadata is None:
            continue
        identity = {
            "exists": metadata["exists"],
            "mode": metadata["mode"],
            "uid": metadata["uid"],
            "gid": metadata["gid"],
            "xattrs_sha256": metadata["xattrs_sha256"],
        }
        if metadata["metadata_sha256"] != _canonical_sha(identity):
            raise RemediationError("evidence_file_metadata_digest_invalid")

    containers = value["containers"]
    for family in ("inventory", "running"):
        for side in ("before", "after"):
            ids = containers[f"{family}_{side}_ids"]
            count = containers[f"{family}_{side}_count"]
            digest = containers[f"{family}_{side}_sha256"]
            if ids is None:
                if count is not None or digest is not None:
                    raise RemediationError("evidence_container_null_coupling_invalid")
                continue
            if count != len(ids) or digest != _canonical_sha(ids):
                raise RemediationError("evidence_container_identity_digest_invalid")
    starts = containers["start_actions"]
    if containers["start_action_count"] != len(starts):
        raise RemediationError("evidence_start_count_invalid")
    if containers["start_actions_sha256"] != _canonical_sha(starts):
        raise RemediationError("evidence_start_digest_invalid")

    if value.get("status") == "passed" and value.get("mode") == "execute":
        if value["docker"]["driver_after"] != "cgroupfs":
            raise RemediationError("evidence_pass_driver_invalid")
        if not value["containers"]["exact_set_restored"]:
            raise RemediationError("evidence_pass_container_set_invalid")
        if not value["containers"]["all_start_targets_from_snapshot"]:
            raise RemediationError("evidence_pass_start_targets_invalid")
        before_running = value["containers"]["running_before_ids"]
        after_running = value["containers"]["running_after_ids"]
        before_inventory = value["containers"]["inventory_before_ids"]
        after_inventory = value["containers"]["inventory_after_ids"]
        starts = value["containers"]["start_actions"]
        if before_running != after_running or before_inventory != after_inventory:
            raise RemediationError("evidence_pass_exact_ids_invalid")
        if not set(starts).issubset(before_running):
            raise RemediationError("evidence_pass_start_subset_invalid")
        if value["containers"]["start_action_count"] != len(starts):
            raise RemediationError("evidence_pass_start_count_invalid")
        if value["containers"]["start_actions_sha256"] != _canonical_sha(starts):
            raise RemediationError("evidence_pass_start_digest_invalid")
        if value["containers"]["running_before_sha256"] != _canonical_sha(
            before_running
        ):
            raise RemediationError("evidence_pass_before_running_digest_invalid")
        if value["containers"]["inventory_before_sha256"] != _canonical_sha(
            before_inventory
        ):
            raise RemediationError("evidence_pass_before_inventory_digest_invalid")
        if (
            value["containers"]["running_before_sha256"]
            != value["containers"]["running_after_sha256"]
        ):
            raise RemediationError("evidence_pass_running_digest_invalid")
        if (
            value["containers"]["inventory_before_sha256"]
            != value["containers"]["inventory_after_sha256"]
        ):
            raise RemediationError("evidence_pass_inventory_digest_invalid")
        if (
            value["daemon_config"]["after_sha256"]
            != value["daemon_config"]["candidate_sha256"]
        ):
            raise RemediationError("evidence_pass_config_digest_invalid")
        if (
            value["daemon_config"]["file_state_after"]
            != value["daemon_config"]["file_state_candidate"]
            or value["daemon_config"]["full_file_state_match"] is not True
        ):
            raise RemediationError("evidence_pass_file_state_invalid")
        if value["rollback"]["attempted"]:
            raise RemediationError("evidence_pass_rollback_invalid")
        if value["containers"]["healthy_set_restored"] is not True:
            raise RemediationError("evidence_pass_health_invalid")
    if value.get("status") == "passed" and value.get("mode") == "recover":
        if value["rollback"]["config_restored"] is not True:
            raise RemediationError("evidence_recovery_config_invalid")
        if value["rollback"]["exact_set_restored"] is not True:
            raise RemediationError("evidence_recovery_container_set_invalid")
        if value["transaction_id"] is None:
            raise RemediationError("evidence_recovery_transaction_missing")
        if (
            value["daemon_config"]["before_sha256"]
            != value["daemon_config"]["after_sha256"]
            or value["daemon_config"]["file_state_before"]
            != value["daemon_config"]["file_state_after"]
            or value["daemon_config"]["full_file_state_match"] is not True
            or value["daemon_config"]["original_restored"] is not True
        ):
            raise RemediationError("evidence_recovery_file_state_invalid")
        if (
            containers["inventory_before_ids"] != containers["inventory_after_ids"]
            or containers["running_before_ids"] != containers["running_after_ids"]
        ):
            raise RemediationError("evidence_recovery_exact_ids_invalid")


class SystemRuntime:
    """Closed-command, fixed-path implementation for an explicitly authorized run."""

    _env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "DOCKER_HOST": "unix:///run/docker.sock",
    }

    def __init__(self) -> None:
        self._transaction_dirs: dict[str, Path] = {}

    def _run(
        self,
        argv: tuple[str, ...],
        *,
        input_bytes: bytes | None = None,
        timeout: float = 30.0,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        if not argv or argv[0] not in {DOCKER, DOCKERD, SYSTEMCTL}:
            raise RemediationError("command_not_allowlisted")
        try:
            completed = subprocess.run(
                argv,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RemediationError("command_timed_out") from exc
        except OSError as exc:
            raise RemediationError("command_execution_failed") from exc
        if len(completed.stdout) > MAX_OUTPUT or len(completed.stderr) > MAX_OUTPUT:
            raise RemediationError("command_output_limit_exceeded")
        if check and completed.returncode != 0:
            raise RemediationError("command_failed")
        return completed

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        self._mkdir_durable(LOCK_PATH.parent, 0o755)
        fd = os.open(
            LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
        )
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RemediationError("remediation_lock_busy") from exc
            yield
        finally:
            os.close(fd)

    def _read_config(self) -> FileState:
        try:
            fd = os.open(DAEMON_PATH, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        except FileNotFoundError:
            return FileState(False, b"")
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0:
                raise RemediationError("daemon_file_identity_unsafe")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_OUTPUT:
                    raise RemediationError("daemon_file_too_large")
                chunks.append(chunk)
            attrs = tuple(
                (name, os.getxattr(fd, name)) for name in sorted(os.listxattr(fd))
            )
            return FileState(
                True,
                b"".join(chunks),
                stat.S_IMODE(info.st_mode),
                info.st_uid,
                info.st_gid,
                attrs,
            )
        finally:
            os.close(fd)

    def _docker_text(self, *args: str) -> str:
        # The Docker socket can accept a request just before daemon startup is
        # completely quiescent.  Read-only probes made in that small window may
        # see a broken pipe or timeout even though the daemon is healthy.  Keep
        # lifecycle calls single-shot, but retry bounded, idempotent reads.
        retryable = {"command_failed", "command_timed_out", "command_execution_failed"}
        for attempt in range(DOCKER_READ_ATTEMPTS):
            try:
                output = self._run((DOCKER, *args)).stdout
                try:
                    return output.decode("utf-8", "strict").strip()
                except UnicodeDecodeError as exc:
                    raise RemediationError("command_output_not_utf8") from exc
            except RemediationError as exc:
                if exc.code not in retryable or attempt + 1 == DOCKER_READ_ATTEMPTS:
                    raise
                time.sleep(DOCKER_READ_RETRY_SECONDS)
        raise RemediationError("docker_read_retry_exhausted")

    def _container_health(
        self, container_ids: tuple[str, ...]
    ) -> dict[str, str | None]:
        if any(not CONTAINER_ID.fullmatch(item) for item in container_ids):
            raise RemediationError("container_id_invalid")
        if not container_ids:
            return {}
        template = "{{json .Id}} {{json .State}}"
        lines = self._docker_text(
            "container", "inspect", "--format", template, *container_ids
        )
        result: dict[str, str | None] = {}
        decoder = json.JSONDecoder()
        try:
            for line in lines.splitlines():
                container_id, index = decoder.raw_decode(line)
                while index < len(line) and line[index].isspace():
                    index += 1
                state, index = decoder.raw_decode(line, index)
                if line[index:].strip():
                    raise ValueError("trailing container health data")
                if (
                    not isinstance(container_id, str)
                    or not CONTAINER_ID.fullmatch(container_id)
                    or not isinstance(state, dict)
                    or container_id in result
                ):
                    raise ValueError("invalid container health data")
                health_record = state.get("Health")
                health = (
                    health_record.get("Status")
                    if isinstance(health_record, dict)
                    else None
                )
                if health is not None and not isinstance(health, str):
                    raise ValueError("invalid container health status")
                result[container_id] = health
        except (json.JSONDecodeError, ValueError) as exc:
            raise RemediationError("container_health_inspect_invalid") from exc
        if set(result) != set(container_ids):
            raise RemediationError("container_health_inventory_mismatch")
        return result

    def _containers(self) -> tuple[ContainerState, ...]:
        raw_ids = self._docker_text("container", "ls", "-aq", "--no-trunc")
        ids = tuple(item for item in raw_ids.splitlines() if item)
        if not ids:
            return ()
        if any(not CONTAINER_ID.fullmatch(item) for item in ids):
            raise RemediationError("container_inventory_invalid")
        # Serialize State as one JSON value. Docker 29 evaluates a missing map
        # key as a template error, so accessing ``.State.Health`` directly fails
        # for containers without a HEALTHCHECK. Keep HostConfig field-specific
        # so unrelated bind, logging, and runtime configuration is never read.
        template = (
            "{{json .Id}} {{json .Name}} {{json .State}} "
            "{{json .HostConfig.RestartPolicy.Name}} {{json .HostConfig.AutoRemove}}"
        )
        lines = self._docker_text("container", "inspect", "--format", template, *ids)
        result: list[ContainerState] = []
        decoder = json.JSONDecoder()
        for line in lines.splitlines():
            values: list[Any] = []
            index = 0
            while index < len(line):
                while index < len(line) and line[index].isspace():
                    index += 1
                value, index = decoder.raw_decode(line, index)
                values.append(value)
            if len(values) != 5:
                raise RemediationError("container_inspect_invalid")
            state = values[2]
            if not isinstance(state, dict):
                raise RemediationError("container_inspect_invalid")
            health_record = state.get("Health")
            health = (
                health_record.get("Status") if isinstance(health_record, dict) else None
            )
            required = (
                values[0],
                values[1],
                state.get("Status"),
                state.get("Running"),
                state.get("Paused"),
                state.get("Restarting"),
                state.get("Dead"),
                values[3],
                values[4],
                state.get("StartedAt"),
            )
            if (
                not all(
                    isinstance(item, str)
                    for item in (*required[:3], required[7], required[9])
                )
                or not all(
                    isinstance(item, bool) for item in (*required[3:7], required[8])
                )
                or (health is not None and not isinstance(health, str))
            ):
                raise RemediationError("container_inspect_invalid")
            result.append(
                ContainerState(
                    id=required[0],
                    name=required[1].removeprefix("/"),
                    status=required[2],
                    running=required[3],
                    paused=required[4],
                    restarting=required[5],
                    dead=required[6],
                    restart_policy=required[7],
                    auto_remove=required[8],
                    started_at=required[9],
                    health=health,
                )
            )
        return tuple(sorted(result, key=lambda item: item.id))

    def snapshot(self) -> HostSnapshot:
        driver = self._docker_text("info", "--format", "{{.CgroupDriver}}")
        live_restore = (
            self._docker_text("info", "--format", "{{.LiveRestoreEnabled}}") == "true"
        )
        swarm = self._docker_text("info", "--format", "{{.Swarm.LocalNodeState}}")
        security = self._docker_text("info", "--format", "{{json .SecurityOptions}}")
        unit = self._run(
            (
                SYSTEMCTL,
                "show",
                "docker.service",
                "--property=ExecStart,DropInPaths",
                "--no-pager",
            )
        ).stdout.decode("utf-8", "strict")
        fields = dict(line.split("=", 1) for line in unit.splitlines() if "=" in line)
        return HostSnapshot(
            driver=driver,
            live_restore=live_restore,
            swarm=swarm,
            rootless="rootless" in security.lower(),
            unit_exec_start=_stable_unit_exec_start(fields.get("ExecStart", "")),
            unit_drop_ins=fields.get("DropInPaths", ""),
            config=self._read_config(),
            containers=self._containers(),
        )

    def inspect(self) -> Inspection:
        snapshot = self.snapshot()
        config = parse_daemon_config(
            snapshot.config.content, exists=snapshot.config.exists
        )
        candidate_config, candidate = merge_cgroupfs(config)
        validation = self._run(
            (DOCKERD, "--validate", "--config-file=/dev/stdin"),
            input_bytes=candidate,
            check=False,
        )
        # Docker 29 writes its successful ``configuration OK`` message to
        # stderr, while earlier releases wrote it to stdout.  The documented
        # command contract is the exit status, so do not bind admission to a
        # version-specific output stream.
        validated = validation.returncode == 0
        blockers = admission_blockers(snapshot)
        if not validated:
            blockers.append("dockerd_candidate_validation_failed")
        return Inspection(
            snapshot,
            candidate,
            candidate_config,
            validated,
            tuple(blockers),
            ACTIVE_JOURNAL.exists(),
        )

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @classmethod
    def _mkdir_durable(cls, path: Path, mode: int) -> None:
        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            if cursor.parent == cursor:
                raise RemediationError("durable_directory_parent_missing")
            cursor = cursor.parent
        if not cursor.is_dir():
            raise RemediationError("durable_directory_parent_not_directory")
        for directory in reversed(missing):
            try:
                os.mkdir(directory, mode)
            except FileExistsError:
                if not directory.is_dir():
                    raise RemediationError("durable_directory_race_not_directory")
            else:
                cls._fsync_dir(directory.parent)
                cls._fsync_dir(directory)

    @staticmethod
    def _atomic_bytes(
        path: Path, content: bytes, state: FileState | None = None
    ) -> None:
        if not path.parent.is_dir():
            raise RemediationError("atomic_write_parent_missing")
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        try:
            mode = state.mode if state else 0o600
            os.fchmod(fd, mode)
            if state:
                os.fchown(fd, state.uid, state.gid)
                for key, value in state.xattrs:
                    os.setxattr(fd, key, value)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            SystemRuntime._fsync_dir(path.parent)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        try:
            content = (
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode()
        except (TypeError, ValueError) as exc:
            raise RemediationError("journal_json_not_canonical") from exc
        SystemRuntime._atomic_bytes(path, content)

    def prepare(self, inspection: Inspection) -> Transaction:
        if ACTIVE_JOURNAL.exists():
            raise RemediationError("active_recovery_required")
        self._mkdir_durable(JOURNAL_ROOT, 0o700)
        journal_info = JOURNAL_ROOT.lstat()
        if (
            not stat.S_ISDIR(journal_info.st_mode)
            or journal_info.st_uid != 0
            or stat.S_IMODE(journal_info.st_mode) & 0o077
        ):
            raise RemediationError("journal_root_permissions_unsafe")
        transactions = JOURNAL_ROOT / "transactions"
        self._mkdir_durable(transactions, 0o700)
        transaction_info = transactions.lstat()
        if (
            not stat.S_ISDIR(transaction_info.st_mode)
            or transaction_info.st_uid != 0
            or stat.S_IMODE(transaction_info.st_mode) & 0o077
        ):
            raise RemediationError("journal_transactions_permissions_unsafe")
        transaction = Transaction(uuid.uuid4().hex)
        root = transactions / transaction.id
        if root.exists():
            raise RemediationError("transaction_directory_already_exists")
        self._mkdir_durable(root, 0o700)
        original = inspection.snapshot.config
        self._atomic_bytes(root / "original.bin", original.content)
        self._atomic_bytes(root / "candidate.bin", inspection.candidate)
        state = {
            "schema_version": 1,
            "transaction_id": transaction.id,
            "phase": "initializing",
            "original": {
                "exists": original.exists,
                "sha256": original.digest,
                "mode": original.mode,
                "uid": original.uid,
                "gid": original.gid,
                "xattrs": [
                    [key, base64.b64encode(value).decode()]
                    for key, value in original.xattrs
                ],
            },
            "candidate_sha256": _sha256(inspection.candidate),
            "before": _snapshot_to_json(inspection.snapshot),
        }
        self._atomic_json(root / "state.json", state)
        self._atomic_json(
            ACTIVE_JOURNAL, {"schema_version": 1, "transaction_id": transaction.id}
        )
        self._transaction_dirs[transaction.id] = root
        return transaction

    def _transaction_state(
        self, transaction: Transaction
    ) -> tuple[Path, dict[str, Any]]:
        root = self._transaction_dirs.get(
            transaction.id, JOURNAL_ROOT / "transactions" / transaction.id
        )
        path = root / "state.json"
        value = _strict_json_loads(path.read_bytes())
        if not isinstance(value, dict):
            raise RemediationError("journal_state_not_object")
        if value.get("transaction_id") != transaction.id:
            raise RemediationError("journal_identity_invalid")
        return root, value

    def phase(self, transaction: Transaction, phase: str) -> None:
        root, value = self._transaction_state(transaction)
        value["phase"] = phase
        self._atomic_json(root / "state.json", value)

    def install_candidate(
        self, transaction: Transaction, inspection: Inspection
    ) -> None:
        if self._read_config() != inspection.snapshot.config:
            raise RemediationError("daemon_config_changed_before_install")
        self._atomic_bytes(
            DAEMON_PATH, inspection.candidate, inspection.snapshot.config
        )

    def restart_docker(self, expected_driver: str) -> None:
        self._run((SYSTEMCTL, "restart", "--no-block", "docker.service"), timeout=15)
        deadline = time.monotonic() + SERVICE_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            try:
                completed = self._run(
                    (DOCKER, "info", "--format", "{{.CgroupDriver}}"),
                    check=False,
                    timeout=10,
                )
                if (
                    completed.returncode == 0
                    and completed.stdout.decode("utf-8", "strict").strip()
                    == expected_driver
                ):
                    return
            except RemediationError as exc:
                # Loading the existing container inventory can make the first
                # Docker API probe exceed its per-call timeout on Thor.  The
                # service-level deadline, not one transient probe, governs the
                # restart.  A lifecycle-command failure above remains fatal.
                if exc.code not in {
                    "command_timed_out",
                    "command_execution_failed",
                }:
                    raise
            except UnicodeDecodeError as exc:
                raise RemediationError("command_output_not_utf8") from exc
            time.sleep(POLL_SECONDS)
        raise RemediationError("docker_restart_deadline_exceeded")

    def start_container(self, container_id: str) -> None:
        if not CONTAINER_ID.fullmatch(container_id):
            raise RemediationError("container_id_invalid")
        self._run((DOCKER, "container", "start", container_id), timeout=120)

    def wait_healthy(self, container_ids: tuple[str, ...]) -> None:
        if not container_ids:
            return
        deadline = time.monotonic() + HEALTH_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            try:
                health = self._container_health(container_ids)
                if all(health.get(item) == "healthy" for item in container_ids):
                    return
            except RemediationError as exc:
                # A just-restarted daemon may transiently reject an inspect.
                # The final exact snapshot remains the authoritative check.
                if exc.code not in {
                    "command_failed",
                    "command_timed_out",
                    "command_execution_failed",
                    "container_health_inventory_mismatch",
                }:
                    raise
            time.sleep(POLL_SECONDS)
        raise RemediationError("container_health_deadline_exceeded")

    def restore_original(self, transaction: Transaction) -> None:
        root, value = self._transaction_state(transaction)
        meta = value["original"]
        state = FileState(
            bool(meta["exists"]),
            (root / "original.bin").read_bytes(),
            int(meta["mode"]),
            int(meta["uid"]),
            int(meta["gid"]),
            tuple(
                (item[0], base64.b64decode(item[1], validate=True))
                for item in meta["xattrs"]
            ),
        )
        if state.digest != meta["sha256"]:
            raise RemediationError("journal_original_hash_mismatch")
        if state.exists:
            self._atomic_bytes(DAEMON_PATH, state.content, state)
        else:
            with contextlib.suppress(FileNotFoundError):
                DAEMON_PATH.unlink()
            self._fsync_dir(DAEMON_PATH.parent)

    def complete(self, transaction: Transaction, evidence: dict[str, Any]) -> None:
        root, value = self._transaction_state(transaction)
        self._atomic_json(root / "evidence.json", evidence)
        value["phase"] = "closed"
        self._atomic_json(root / "state.json", value)
        with contextlib.suppress(FileNotFoundError):
            ACTIVE_JOURNAL.unlink()
        self._fsync_dir(JOURNAL_ROOT)

    def active_transaction(self) -> tuple[Transaction, HostSnapshot, str] | None:
        if not ACTIVE_JOURNAL.exists():
            return None
        active = _strict_json_loads(ACTIVE_JOURNAL.read_bytes())
        if not isinstance(active, dict):
            raise RemediationError("active_journal_not_object")
        transaction = Transaction(active.get("transaction_id", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", transaction.id):
            raise RemediationError("active_journal_invalid")
        root, state = self._transaction_state(transaction)
        original = (root / "original.bin").read_bytes()
        before = _snapshot_from_json(state["before"], original)
        return transaction, before, state["phase"]


def _snapshot_to_json(snapshot: HostSnapshot) -> dict[str, Any]:
    return {
        "driver": snapshot.driver,
        "live_restore": snapshot.live_restore,
        "swarm": snapshot.swarm,
        "rootless": snapshot.rootless,
        "unit_exec_start": snapshot.unit_exec_start,
        "unit_drop_ins": snapshot.unit_drop_ins,
        "config": {
            "exists": snapshot.config.exists,
            "mode": snapshot.config.mode,
            "uid": snapshot.config.uid,
            "gid": snapshot.config.gid,
            "xattrs": [
                [key, base64.b64encode(value).decode()]
                for key, value in snapshot.config.xattrs
            ],
        },
        "containers": [asdict(item) for item in snapshot.containers],
    }


def _snapshot_from_json(value: dict[str, Any], original: bytes) -> HostSnapshot:
    config = value["config"]
    return HostSnapshot(
        driver=value["driver"],
        live_restore=value["live_restore"],
        swarm=value["swarm"],
        rootless=value["rootless"],
        unit_exec_start=value["unit_exec_start"],
        unit_drop_ins=value["unit_drop_ins"],
        config=FileState(
            config["exists"],
            original,
            config["mode"],
            config["uid"],
            config["gid"],
            tuple(
                (item[0], base64.b64decode(item[1], validate=True))
                for item in config["xattrs"]
            ),
        ),
        containers=tuple(ContainerState(**item) for item in value["containers"]),
    )


def _failure(mode: str, code: str) -> dict[str, Any]:
    value = _base_evidence(mode, "failed")
    value["failure"] = code
    return value


def main(
    argv: list[str] | None = None,
    *,
    runtime: Runtime | None = None,
    effective_uid: int | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Transactional Thor Docker cgroupfs remediation"
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("plan", "inspect", "execute", "recover"),
        default="plan",
    )
    parser.add_argument("--ack", default=None)
    args = parser.parse_args(argv)
    uid = os.geteuid() if effective_uid is None else effective_uid
    if args.mode in {"plan", "inspect"} and args.ack is not None:
        output = _failure(args.mode, "acknowledgement_without_mutating_mode")
    elif args.mode == "plan":
        output = plan()
    elif args.mode == "inspect":
        try:
            output = inspection_evidence((runtime or SystemRuntime()).inspect())
        except RemediationError as exc:
            output = _failure("inspect", exc.code)
        except Exception:
            output = _failure("inspect", "unexpected_runtime_error")
    elif args.mode == "execute" and args.ack != ACKNOWLEDGEMENT:
        output = _failure("execute", "exact_acknowledgement_required")
    elif args.mode == "recover" and args.ack != RECOVERY_ACKNOWLEDGEMENT:
        output = _failure("recover", "exact_recovery_acknowledgement_required")
    elif uid != 0:
        output = _failure(args.mode, "effective_uid_zero_required")
    else:
        try:
            selected = runtime or SystemRuntime()
            output = (
                execute_transaction(selected)
                if args.mode == "execute"
                else recover_transaction(selected)
            )
        except RemediationError as exc:
            output = _failure(args.mode, exc.code)
        except Exception:
            output = _failure(args.mode, "unexpected_runtime_error")
    try:
        validate_evidence(output)
    except RemediationError:
        output = _failure(args.mode, "evidence_validation_failed")
        validate_evidence(output)
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output["status"] in {"planned", "ready", "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
