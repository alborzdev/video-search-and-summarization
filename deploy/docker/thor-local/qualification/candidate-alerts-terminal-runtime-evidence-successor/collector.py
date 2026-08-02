#!/usr/bin/env python3
"""Bounded terminal/cancellation runtime candidate for on-demand Alerts."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any, Callable, Sequence

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
EVIDENCE_SCHEMA_PATH = HERE / "evidence.schema.json"
PREDECESSOR_PATH = HERE.parent / "candidate-alerts-runtime-evidence" / "collector.py"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
PLAIN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
CORRELATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


def _load_predecessor() -> Any:
    spec = importlib.util.spec_from_file_location(
        "candidate_alerts_predecessor", PREDECESSOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("predecessor collector is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


predecessor = _load_predecessor()
common = predecessor.common


class CollectorError(RuntimeError):
    CODES = {
        "authorization_required",
        "cleanup_failed",
        "configuration_error",
        "fixture_error",
        "oracle_failed",
        "source_drift",
        "transport_error",
    }

    def __init__(self, code: str) -> None:
        self.code = code if code in self.CODES else "configuration_error"
        super().__init__(self.code)


def _read_regular(path: Path, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CollectorError("configuration_error") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise CollectorError("configuration_error")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            if not chunk:
                raise CollectorError("configuration_error")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, key) != getattr(after, key) for key in stable):
            raise CollectorError("configuration_error")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _decode(raw: bytes, code: str = "configuration_error") -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise CollectorError(code)
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(CollectorError(code)),
        )
    except CollectorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectorError(code) from exc


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CollectorError("configuration_error") from exc


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _repo_path(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or not item.parts or ".." in item.parts:
        raise CollectorError("configuration_error")
    current = ROOT
    for part in item.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise CollectorError("configuration_error")
        except OSError as exc:
            raise CollectorError("configuration_error") from exc
    try:
        current.resolve(strict=True).relative_to(ROOT)
    except (OSError, ValueError) as exc:
        raise CollectorError("configuration_error") from exc
    return current


def _contract() -> dict[str, Any]:
    value = _decode(_read_regular(CONTRACT_PATH))
    if not isinstance(value, dict):
        raise CollectorError("configuration_error")
    return value


def _validate(value: Any, schema_path: Path, code: str = "configuration_error") -> None:
    schema = _decode(_read_regular(schema_path))
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise CollectorError("configuration_error") from exc
    if list(Draft202012Validator(schema).iter_errors(value)):
        raise CollectorError(code)


def compile_plan() -> dict[str, Any]:
    contract = _contract()
    bounds = contract.get("execution_bounds", {})
    terminal = contract.get("terminal_contract", {})
    decision = contract.get("decision", {})
    if (
        contract.get("collector_id")
        != "candidate-alerts-terminal-runtime-evidence-successor"
        or contract.get("predecessor_collector_id")
        != "candidate-alerts-runtime-evidence"
        or contract.get("default_execution_enabled") is not False
        or contract.get("warehouse_sample_bundle") != "excluded"
        or bounds
        != {
            "max_requests": 22,
            "max_actions": 22,
            "positive_terminal_poll_attempts": 10,
            "cancel_terminal_observations": 2,
            "poll_delay_seconds": 1,
            "max_duration_seconds": 300,
            "cleanup_reserve_seconds": 30,
            "max_request_bytes": 65536,
            "max_response_bytes": 1048576,
            "timeout_seconds": 10,
        }
        or terminal.get("server_generated_correlation_id") is not True
        or terminal.get("get_status_required") is not True
        or terminal.get("delete_cancel_required") is not True
        or terminal.get("positive_sink_outcome") != "acknowledged"
        or terminal.get("cancel_before_publish_requires_cancellation_accepted")
        is not True
        or decision.get("stale_client_correlation_assumption_removed") is not True
        or decision.get("terminal_completion_and_sink_receipt_observable") is not True
        or decision.get("cancellation_before_publish_observable") is not True
        or decision.get("runtime_receipt_present") is not False
        or decision.get("executor_ready") is not False
        or decision.get("promotion_eligible") is not False
        or decision.get("canonical_state_advanced") is not False
    ):
        raise CollectorError("configuration_error")
    locks = contract.get("source_locks")
    if not isinstance(locks, list) or len(locks) != 14:
        raise CollectorError("configuration_error")
    seen: set[str] = set()
    sources: dict[str, bytes] = {}
    for lock in locks:
        if (
            not isinstance(lock, dict)
            or set(lock) != {"path", "sha256"}
            or lock["path"] in seen
        ):
            raise CollectorError("configuration_error")
        seen.add(lock["path"])
        raw = _read_regular(_repo_path(lock["path"]))
        if _sha(raw) != lock["sha256"]:
            raise CollectorError("source_drift")
        sources[lock["path"]] = raw
    routes = sources[
        "services/alert/alert-agent-web/app/api/verification_routes.py"
    ].decode()
    service = sources[
        "services/alert/alert-agent-web/app/service/ondemand_verification_service.py"
    ].decode()
    store = sources[
        "services/alert/alert-agent-web/app/service/terminal_job_store.py"
    ].decode()
    handler = sources[
        "services/alert/handlers/direct_media/direct_media_handler.py"
    ].decode()
    predecessor_source = sources[
        "deploy/docker/thor-local/qualification/candidate-alerts-runtime-evidence/collector.py"
    ].decode()
    required = (
        "job_handle = service.register()" in routes
        and '"statusUrl": f"/api/v1/verification/ondemand/{correlation_id}"' in routes
        and '@router.get(\n    "/ondemand/{correlation_id}"' in routes
        and '@router.delete(\n    "/ondemand/{correlation_id}"' in routes
        and "self.job_store.begin_publish(" in service
        and "def begin_publish(" in store
        and 'job.state = "publishing"' in store
        and 'accepted = job.state in {"queued", "running"}' in store
        and "before_publish" in handler
        and 'positive_body.get("correlationId") != positive_id' in predecessor_source
    )
    if not required:
        raise CollectorError("source_drift")
    accepted, cancelled, fixture_sha = predecessor._validate_fixture(contract)
    if (
        accepted.get("expected_publish") is not True
        or cancelled.get("expected_publish") is not False
    ):
        raise CollectorError("fixture_error")
    _validate(
        {
            "schema_version": 1,
            "collector_id": contract["collector_id"],
            "status": "candidate_terminal_evidence_pass_non_promoting",
            "contract_sha256": "0" * 64,
            "fixture_sha256": fixture_sha,
            "target_origin_sha256": "0" * 64,
            "media_url_sha256": "0" * 64,
            "accepted_alert_sha256": "0" * 64,
            "cancel_alert_sha256": "0" * 64,
            "positive": {
                "correlation_id_sha256": "0" * 64,
                "status_url_sha256": "0" * 64,
                "polls": 1,
                "terminal_state": "completed",
                "processing_outcome": "verified",
                "sink_transport": "elastic",
                "sink_outcome": "acknowledged",
                "sink_identity_sha256": "0" * 64,
            },
            "cancellation": {
                "correlation_id_sha256": "0" * 64,
                "status_url_sha256": "0" * 64,
                "delete_accepted": True,
                "terminal_state": "cancelled",
                "terminal_observations": 2,
                "result_absent": True,
                "delayed_no_publish_result": True,
            },
            "budget": {
                "requests": 13,
                "max_requests": 22,
                "actions": 13,
                "max_actions": 22,
                "max_duration_seconds": 300,
                "cleanup_reserve_seconds": 30,
            },
            "actions": [
                {
                    "order": index,
                    "action_id": f"action-{index}",
                    "method": "GET",
                    "path_kind": "health",
                    "http_status": 200,
                    "payload_bytes": 0,
                    "payload_sha256": _sha(b""),
                }
                for index in range(1, 14)
            ],
            "cleanup": {
                "exact_config_deleted": True,
                "owned_config_absent": True,
                "non_owned_config_projection_restored": True,
                "terminal_job_delete_api_available": False,
                "terminal_records_retained_until_ttl_or_restart": True,
            },
            "runtime_evidence_published": False,
            "executor_ready": False,
            "promotion_eligible": False,
            "canonical_state_advanced": False,
            "warehouse_sample_bundle": "excluded",
        },
        EVIDENCE_SCHEMA_PATH,
    )
    return {
        "schema_version": 1,
        "collector_id": contract["collector_id"],
        "mode": "inert-plan",
        "status": "pass",
        "runtime_requests": 0,
        "runtime_actions": 0,
        "request_bound": 22,
        "action_bound": 22,
        "positive_poll_bound": 10,
        "cancel_terminal_observations": 2,
        "contract_sha256": _sha(_read_regular(CONTRACT_PATH)),
        "fixture_sha256": fixture_sha,
        "runtime_receipt_present": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }


def _json_response(result: Any) -> dict[str, Any]:
    if result.media_type != "application/json":
        raise CollectorError("transport_error")
    value = _decode(result.body, "transport_error")
    if not isinstance(value, dict):
        raise CollectorError("transport_error")
    return value


def _timestamp(value: Any) -> float:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CollectorError("oracle_failed")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise CollectorError("oracle_failed") from exc
    return parsed.timestamp()


def _accepted_job(value: Any, event_id: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise CollectorError("oracle_failed")
    correlation_id = value.get("correlationId")
    if not isinstance(correlation_id, str) or not CORRELATION_RE.fullmatch(
        correlation_id
    ):
        raise CollectorError("oracle_failed")
    status_url = f"/api/v1/verification/ondemand/{correlation_id}"
    if (
        value.get("status") != "accepted"
        or value.get("statusUrl") != status_url
        or correlation_id == event_id
        or not isinstance(value.get("message"), str)
    ):
        raise CollectorError("oracle_failed")
    _timestamp(value.get("timestamp"))
    return correlation_id, status_url


def _job_snapshot(value: Any, correlation_id: str) -> dict[str, Any]:
    allowed = {
        "correlationId",
        "state",
        "terminal",
        "createdAt",
        "updatedAt",
        "result",
        "error",
        "cancellationAccepted",
    }
    if not isinstance(value, dict) or not set(value).issubset(allowed):
        raise CollectorError("oracle_failed")
    state = value.get("state")
    terminal = value.get("terminal")
    if (
        value.get("correlationId") != correlation_id
        or state
        not in {"queued", "running", "publishing", "completed", "failed", "cancelled"}
        or type(terminal) is not bool
        or terminal != (state in TERMINAL_STATES)
    ):
        raise CollectorError("oracle_failed")
    created = _timestamp(value.get("createdAt"))
    updated = _timestamp(value.get("updatedAt"))
    if updated < created:
        raise CollectorError("oracle_failed")
    return value


def _positive_terminal(value: dict[str, Any]) -> tuple[str, str]:
    if (
        value.get("state") != "completed"
        or value.get("terminal") is not True
        or "error" in value
        or "cancellationAccepted" in value
    ):
        raise CollectorError("oracle_failed")
    result = value.get("result")
    if (
        not isinstance(result, dict)
        or not set(result).issubset(
            {
                "processingOutcome",
                "sinkDelivery",
                "verdict",
                "verificationResponseCode",
                "errorSource",
            }
        )
        or result.get("processingOutcome") != "verified"
    ):
        raise CollectorError("oracle_failed")
    sink = result.get("sinkDelivery")
    if not isinstance(sink, dict) or sink.get("outcome") != "acknowledged":
        raise CollectorError("oracle_failed")
    transport = sink.get("transport")
    required: tuple[str, ...]
    forbidden: tuple[str, ...]
    if transport == "elastic":
        required = ("documentId", "index")
        forbidden = ("topic", "partition", "offset")
    elif transport == "kafka":
        required = ("topic", "partition", "offset")
        forbidden = ("documentId", "index")
    else:
        raise CollectorError("oracle_failed")
    if any(key in sink for key in forbidden) or set(sink) != {
        "transport",
        "outcome",
        *required,
    }:
        raise CollectorError("oracle_failed")
    for key in required:
        item = sink.get(key)
        if (
            not isinstance(item, str)
            or not 1 <= len(item) <= 256
            or "\n" in item
            or "\r" in item
        ):
            raise CollectorError("oracle_failed")
    return transport, _sha(_canonical(sink))


def _cancelled(value: dict[str, Any], *, delete_response: bool) -> None:
    if (
        value.get("state") != "cancelled"
        or value.get("terminal") is not True
        or "result" in value
        or "error" in value
        or (delete_response and value.get("cancellationAccepted") is not True)
        or (not delete_response and "cancellationAccepted" in value)
    ):
        raise CollectorError("oracle_failed")


def run_collector(
    *,
    run_id: str,
    acknowledgement: str,
    origin: str,
    media_url: str,
    opener_factory: Callable[[], Any],
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    plan = compile_plan()
    contract = _contract()
    if not isinstance(run_id, str) or not PLAIN_ID_RE.fullmatch(run_id):
        raise CollectorError("authorization_required")
    guard = common.RunAuthorizationGuard.from_token(
        run_id=run_id,
        authorization_id=contract["authorization"]["authorization_id"],
        authorization_token=contract["authorization"]["acknowledgement"],
    )
    try:
        identity = guard.admit(
            run_id=run_id,
            authorization_id=contract["authorization"]["authorization_id"],
            authorization_token=acknowledgement,
        )
    except common.EvidenceCommonError as exc:
        raise CollectorError("authorization_required") from exc
    try:
        media_url = predecessor._media_url(media_url)
    except predecessor.CollectorError as exc:
        raise CollectorError("configuration_error") from exc
    if not callable(opener_factory) or not callable(sleeper) or not callable(monotonic):
        raise CollectorError("configuration_error")
    suffix = _sha(run_id)[:16]
    alert_type = f"vss_oracle_terminal_{suffix}"
    missing_type = f"vss_oracle_terminal_missing_{suffix}"
    exact_config_path = f"/api/v1/verification/config/{alert_type}"
    static_paths = [*contract["target"]["static_paths"], exact_config_path]
    try:
        initial_target = common.LoopbackTarget.admit(origin, static_paths)
    except common.EvidenceCommonError as exc:
        raise CollectorError("configuration_error") from exc
    opener = opener_factory()
    budget = common.ExecutionBudget(max_requests=22, max_actions=22)
    bounds = contract["execution_bounds"]
    started = monotonic()
    deadline = started + bounds["max_duration_seconds"]
    in_cleanup = False
    dynamic_paths: list[str] = []
    actions: list[dict[str, Any]] = []

    def make_transport() -> Any:
        target = common.LoopbackTarget.admit(
            initial_target.origin, [*static_paths, *dynamic_paths]
        )
        return common.BoundedHTTPTransport(
            target=target,
            opener=opener,
            budget=budget,
            max_request_bytes=bounds["max_request_bytes"],
            max_response_bytes=bounds["max_response_bytes"],
            timeout_seconds=bounds["timeout_seconds"],
        )

    transport = make_transport()

    def call(
        action_id: str, method: str, path: str, path_kind: str, *, body: bytes = b""
    ) -> tuple[Any, dict[str, Any]]:
        remaining = deadline - monotonic()
        reserve = 0 if in_cleanup else bounds["cleanup_reserve_seconds"]
        if remaining - reserve < bounds["timeout_seconds"]:
            raise CollectorError("transport_error")
        try:
            result = transport.request(
                method,
                path,
                body=body,
                media_type="application/json" if body else None,
            )
            budget.consume_action()
        except common.EvidenceCommonError as exc:
            raise CollectorError("transport_error") from exc
        value = _json_response(result)
        actions.append(
            {
                "order": budget.actions,
                "action_id": action_id,
                "method": method,
                "path_kind": path_kind,
                "http_status": result.status,
                "payload_bytes": len(result.body),
                "payload_sha256": _sha(result.body),
            }
        )
        return result, value

    accepted, cancel_alert, fixture_sha = predecessor._validate_fixture(contract)
    prompt = (
        "Return yes only when the candidate alert is visible in the supplied media."
    )
    ownership_marker = (
        "vss-oracle-owner-"
        + _sha(
            _canonical(
                {
                    "authorization_token_sha256": identity.authorization_token_sha256,
                    "collector_id": contract["collector_id"],
                    "run_id": run_id,
                    "resource_id": alert_type,
                }
            )
        )[:32]
    )
    expected_config = {
        "alert_type": alert_type,
        "prompt": prompt,
        "system_prompt": "Answer only yes or no.",
        "output_category": ownership_marker,
        "vlm_params": {"num_frames": 4, "temperature": 0.0, "max_tokens": 32},
    }
    pre_configs: list[dict[str, Any]] = []
    post_configs: list[dict[str, Any]] = []
    config_owned = False
    config_deleted = False
    positive_id = ""
    positive_status_url = ""
    positive_polls = 0
    sink_transport = ""
    sink_identity_sha = ""
    cancel_id = ""
    cancel_status_url = ""
    primary: BaseException | None = None
    cleanup_failed = False
    try:
        health_result, health = call("health", "GET", "/health", "health")
        if health_result.status != 200 or health.get("status") != "ok":
            raise CollectorError("oracle_failed")
        pre_result, pre = call(
            "pre-state", "GET", "/api/v1/verification/config", "config-collection"
        )
        pre_configs = predecessor._configs(pre_result)
        if any(item.get("alert_type") == alert_type for item in pre_configs):
            raise CollectorError("oracle_failed")
        created_result, created = call(
            "create-config",
            "POST",
            "/api/v1/verification/config",
            "config-collection",
            body=_canonical(expected_config),
        )
        if created_result.status != 201 or not predecessor._is_exact_owned_config(
            created, expected_config, ownership_marker
        ):
            raise CollectorError("oracle_failed")
        inspect_result, inspected = call(
            "inspect-config", "GET", exact_config_path, "config-exact"
        )
        if inspect_result.status != 200 or not predecessor._is_exact_owned_config(
            inspected, expected_config, ownership_marker
        ):
            raise CollectorError("oracle_failed")
        config_owned = True

        positive_event_id = f"{accepted['alert_id']}-{suffix}"
        positive_payload = {
            "id": positive_event_id,
            "sensorId": accepted["sensor_id"],
            "category": alert_type,
            "info": {"media_urls": [media_url], "media_type": "video"},
        }
        positive_result, positive = call(
            "positive-submit",
            "POST",
            "/api/v1/verification/ondemand",
            "ondemand-collection",
            body=_canonical(positive_payload),
        )
        if positive_result.status != 202:
            raise CollectorError("oracle_failed")
        positive_id, positive_status_url = _accepted_job(positive, positive_event_id)
        dynamic_paths.append(positive_status_url)
        transport = make_transport()
        previous_rank = -1
        created_at: str | None = None
        terminal_positive: dict[str, Any] | None = None
        ranks = {
            "queued": 0,
            "running": 1,
            "publishing": 2,
            "completed": 3,
            "failed": 3,
            "cancelled": 3,
        }
        for attempt in range(bounds["positive_terminal_poll_attempts"]):
            if attempt:
                sleeper(float(bounds["poll_delay_seconds"]))
            status_result, raw_status = call(
                f"positive-poll-{attempt + 1}",
                "GET",
                positive_status_url,
                "ondemand-server-job",
            )
            if status_result.status != 200:
                raise CollectorError("oracle_failed")
            snapshot = _job_snapshot(raw_status, positive_id)
            if created_at is None:
                created_at = snapshot["createdAt"]
            elif snapshot["createdAt"] != created_at:
                raise CollectorError("oracle_failed")
            rank = ranks[snapshot["state"]]
            if rank < previous_rank:
                raise CollectorError("oracle_failed")
            previous_rank = rank
            positive_polls += 1
            if snapshot["terminal"]:
                terminal_positive = snapshot
                break
        if terminal_positive is None:
            raise CollectorError("oracle_failed")
        sink_transport, sink_identity_sha = _positive_terminal(terminal_positive)

        cancel_event_id = f"{cancel_alert['alert_id']}-{suffix}"
        cancel_payload = {
            "id": cancel_event_id,
            "sensorId": cancel_alert["sensor_id"],
            "category": alert_type,
            "info": {"media_urls": [media_url], "media_type": "video"},
        }
        cancel_submit_result, cancel_submit = call(
            "cancel-submit",
            "POST",
            "/api/v1/verification/ondemand",
            "ondemand-collection",
            body=_canonical(cancel_payload),
        )
        if cancel_submit_result.status != 202:
            raise CollectorError("oracle_failed")
        cancel_id, cancel_status_url = _accepted_job(cancel_submit, cancel_event_id)
        if cancel_id == positive_id:
            raise CollectorError("oracle_failed")
        dynamic_paths.append(cancel_status_url)
        transport = make_transport()
        delete_result, delete_value = call(
            "cancel-delete",
            "DELETE",
            cancel_status_url,
            "ondemand-server-job",
        )
        if delete_result.status != 202:
            raise CollectorError("oracle_failed")
        cancelled_delete = _job_snapshot(delete_value, cancel_id)
        _cancelled(cancelled_delete, delete_response=True)
        cancel_created_at = cancelled_delete["createdAt"]
        cancel_updated_at = cancelled_delete["updatedAt"]
        for observation in range(bounds["cancel_terminal_observations"]):
            if observation:
                sleeper(float(bounds["poll_delay_seconds"]))
            cancel_get_result, cancel_get = call(
                f"cancel-observe-{observation + 1}",
                "GET",
                cancel_status_url,
                "ondemand-server-job",
            )
            if cancel_get_result.status != 200:
                raise CollectorError("oracle_failed")
            cancel_snapshot = _job_snapshot(cancel_get, cancel_id)
            _cancelled(cancel_snapshot, delete_response=False)
            if (
                cancel_snapshot["createdAt"] != cancel_created_at
                or cancel_snapshot["updatedAt"] != cancel_updated_at
            ):
                raise CollectorError("oracle_failed")

        adjacent_result, adjacent = call(
            "adjacent-negative",
            "POST",
            "/api/v1/verification/ondemand",
            "ondemand-collection",
            body=_canonical(
                {
                    "id": f"adjacent-{suffix}",
                    "sensorId": cancel_alert["sensor_id"],
                    "category": missing_type,
                    "info": {"media_urls": [media_url], "media_type": "video"},
                }
            ),
        )
        if (
            adjacent_result.status != 400
            or adjacent.get("status") != "error"
            or adjacent.get("error") != "unknown_category"
            or "correlationId" in adjacent
        ):
            raise CollectorError("oracle_failed")
    except BaseException as exc:
        primary = exc
    finally:
        in_cleanup = True
        if config_owned:
            try:
                deleted_result, deleted_value = call(
                    "cleanup-config",
                    "DELETE",
                    exact_config_path,
                    "config-exact",
                )
                if (
                    deleted_result.status != 200
                    or deleted_value.get("status") != "success"
                ):
                    cleanup_failed = True
                else:
                    config_deleted = True
            except BaseException:
                cleanup_failed = True
            try:
                post_result, _post = call(
                    "post-state",
                    "GET",
                    "/api/v1/verification/config",
                    "config-collection",
                )
                post_configs = predecessor._configs(post_result)
                if any(
                    item.get("alert_type") == alert_type for item in post_configs
                ) or _canonical(pre_configs) != _canonical(post_configs):
                    cleanup_failed = True
            except BaseException:
                cleanup_failed = True
    if cleanup_failed:
        raise CollectorError("cleanup_failed")
    if primary is not None:
        if isinstance(primary, CollectorError):
            raise primary
        if isinstance(primary, common.EvidenceCommonError):
            raise CollectorError("transport_error") from primary
        raise CollectorError("oracle_failed") from primary
    if (
        not config_deleted
        or not positive_id
        or not cancel_id
        or not 1 <= positive_polls <= 10
        or budget.requests != budget.actions
        or not 13 <= budget.requests <= 22
        or monotonic() - started > bounds["max_duration_seconds"]
        or not sink_transport
        or not sink_identity_sha
    ):
        raise CollectorError("oracle_failed")
    result = {
        "schema_version": 1,
        "collector_id": contract["collector_id"],
        "status": "candidate_terminal_evidence_pass_non_promoting",
        "contract_sha256": plan["contract_sha256"],
        "fixture_sha256": fixture_sha,
        "target_origin_sha256": _sha(initial_target.origin),
        "media_url_sha256": _sha(media_url),
        "accepted_alert_sha256": _sha(_canonical(accepted)),
        "cancel_alert_sha256": _sha(_canonical(cancel_alert)),
        "positive": {
            "correlation_id_sha256": _sha(positive_id),
            "status_url_sha256": _sha(positive_status_url),
            "polls": positive_polls,
            "terminal_state": "completed",
            "processing_outcome": "verified",
            "sink_transport": sink_transport,
            "sink_outcome": "acknowledged",
            "sink_identity_sha256": sink_identity_sha,
        },
        "cancellation": {
            "correlation_id_sha256": _sha(cancel_id),
            "status_url_sha256": _sha(cancel_status_url),
            "delete_accepted": True,
            "terminal_state": "cancelled",
            "terminal_observations": 2,
            "result_absent": True,
            "delayed_no_publish_result": True,
        },
        "budget": {
            "requests": budget.requests,
            "max_requests": 22,
            "actions": budget.actions,
            "max_actions": 22,
            "max_duration_seconds": 300,
            "cleanup_reserve_seconds": 30,
        },
        "actions": actions,
        "cleanup": {
            "exact_config_deleted": True,
            "owned_config_absent": True,
            "non_owned_config_projection_restored": True,
            "terminal_job_delete_api_available": False,
            "terminal_records_retained_until_ttl_or_restart": True,
        },
        "runtime_evidence_published": False,
        "executor_ready": False,
        "promotion_eligible": False,
        "canonical_state_advanced": False,
        "warehouse_sample_bundle": "excluded",
    }
    _validate(result, EVIDENCE_SCHEMA_PATH)
    return result


def live_opener() -> Any:
    return predecessor.live_opener()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("plan")
    execute = commands.add_parser("execute")
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--acknowledgement", required=True)
    execute.add_argument("--origin", default="http://127.0.0.1:9080")
    execute.add_argument("--media-url", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {None, "plan"}:
            value = compile_plan()
        else:
            value = run_collector(
                run_id=args.run_id,
                acknowledgement=args.acknowledgement,
                origin=args.origin,
                media_url=args.media_url,
                opener_factory=live_opener,
            )
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (CollectorError, common.EvidenceCommonError) as exc:
        code = exc.code if hasattr(exc, "code") else "configuration_error"
        print(json.dumps({"status": "fail", "error": code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
