#!/usr/bin/env python3
"""Inert-by-default, bounded executor for the seven pinned protocol cases.

With no arguments this command only compiles and prints plans. Network, process,
container, and lifecycle primitives are reachable only through ``execute`` after
all admission gates have passed.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
CONTRACT_PATH = LANE / "protocol-cases.json"
ACK = "I_ACK_VSS_PROTOCOL_CASE_LIFECYCLE_AND_MUTATIONS"
MAX_BYTES = 1024 * 1024
MAX_EVENTS = 32
MAX_REQUESTS = 32
MAX_SECONDS = 60
CLEANUP_SECONDS = 10
CLEANUP_BYTES = 64 * 1024
COMPOSE_ALLOWLIST = {
    "vss-agent",
    "vss-alert-agent",
    "alert-agent",
    "rt-vlm",
    "vss-rt-vlm",
    "kafka",
    "redis",
    "vios",
    "nvstreamer",
}
EXPECTED_TARGET_ROLES = {
    "protocol-case.agent.websocket": {"websocket"},
    "protocol-case.alert.websocket": {"websocket", "redis"},
    "protocol-case.rt-vlm.sse": {"http"},
    "protocol-case.kafka.nvschema": {"kafka"},
    "protocol-case.redis.events": {"redis"},
    "protocol-case.vios.webrtc-live": {"http"},
    "protocol-case.vios.webrtc-replay": {"http"},
}
RESOURCE_KEYS = {
    "protocol-case.agent.websocket": {"conversation_id"},
    "protocol-case.alert.websocket": {"stream"},
    "protocol-case.rt-vlm.sse": {"asset_id", "model_id", "delete_asset_after"},
    "protocol-case.kafka.nvschema": {"topic", "consumer_group"},
    "protocol-case.redis.events": {"stream", "consumer_group"},
    "protocol-case.vios.webrtc-live": {"stream_id", "peer_id"},
    "protocol-case.vios.webrtc-replay": {
        "stream_id",
        "peer_id",
        "start_time",
        "end_time",
    },
}
EXECUTOR_READY = {
    "protocol-case.alert.websocket",
    "protocol-case.rt-vlm.sse",
    "protocol-case.redis.events",
    "protocol-case.vios.webrtc-live",
    "protocol-case.vios.webrtc-replay",
}
PLAN_STATE = {
    "protocol-case.agent.websocket": "blocked_external_server_contract",
    "protocol-case.alert.websocket": "executor_ready",
    "protocol-case.rt-vlm.sse": "executor_ready",
    "protocol-case.kafka.nvschema": "blocked_nonreversible_topic_mutation_and_missing_product_trigger",
    "protocol-case.redis.events": "executor_ready_transport_fixture_only",
    "protocol-case.vios.webrtc-live": "executor_ready",
    "protocol-case.vios.webrtc-replay": "executor_ready",
}
EVIDENCE_CLASS = {
    case_id: "transport_fixture_only"
    if case_id == "protocol-case.redis.events"
    else "product_protocol"
    for case_id in EXPECTED_TARGET_ROLES
}
CLEANUP_REQUEST_RESERVE = {
    "protocol-case.agent.websocket": 0,
    "protocol-case.alert.websocket": 1,
    "protocol-case.rt-vlm.sse": 1,
    "protocol-case.kafka.nvschema": 1,
    "protocol-case.redis.events": 2,
    "protocol-case.vios.webrtc-live": 1,
    "protocol-case.vios.webrtc-replay": 1,
}


class ExecutorError(RuntimeError):
    """Fail-closed executor error."""


class AdmissionError(ExecutorError):
    """Execution was denied before any transport activation."""


class BoundError(ExecutorError):
    """A declared byte/event/time/request bound was exceeded."""


def _json_load(path: Path) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AdmissionError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError(f"cannot load {path}: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _canonical_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_repo_file(relative: str, expected_sha: str | None = None) -> Path:
    if not relative or relative.startswith("/"):
        raise AdmissionError("path must be non-empty and repository-relative")
    path = (REPO_ROOT / relative).resolve()
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise AdmissionError(f"path escapes repository: {relative}") from exc
    if not path.is_file() or path.is_symlink():
        raise AdmissionError(f"path is not a regular non-symlink: {relative}")
    if expected_sha and hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise AdmissionError(f"file SHA-256 mismatch: {relative}")
    return path


@dataclass(frozen=True)
class Target:
    role: str
    kind: str
    host: str
    port: int
    tls: bool
    ca_file: str | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Target":
        expected = {"role", "kind", "host", "port", "tls"}
        if "ca_file" in raw:
            expected.add("ca_file")
        if set(raw) != expected:
            raise AdmissionError(f"target keys must be exactly {sorted(expected)}")
        role, kind, host, port, tls = (
            raw["role"],
            raw["kind"],
            raw["host"],
            raw["port"],
            raw["tls"],
        )
        if role not in {"websocket", "http", "redis", "kafka"}:
            raise AdmissionError(f"unsupported target role: {role}")
        if type(port) is not int or not 1 <= port <= 65535 or type(tls) is not bool:
            raise AdmissionError("target port/tls is invalid")
        if kind == "numeric_loopback":
            try:
                address = ipaddress.ip_address(host)
            except ValueError as exc:
                raise AdmissionError(
                    "numeric_loopback target must be a numeric IP literal"
                ) from exc
            if not address.is_loopback:
                raise AdmissionError(f"target is not loopback: {host}")
        elif kind == "compose_service":
            if host not in COMPOSE_ALLOWLIST:
                raise AdmissionError(f"compose service is not allowlisted: {host}")
        else:
            raise AdmissionError(f"unsupported target kind: {kind}")
        ca_file = raw.get("ca_file")
        if ca_file is not None:
            _safe_repo_file(ca_file)
        return cls(role=role, kind=kind, host=host, port=port, tls=tls, ca_file=ca_file)

    def evidence(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "kind": self.kind,
            "host": self.host,
            "port": self.port,
            "tls": self.tls,
        }


def _admit_discovered_host(host: str, target: Target) -> None:
    """Reject protocol-discovered endpoints outside the original target class."""
    if target.kind == "numeric_loopback":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise AdmissionError(
                f"discovered endpoint is not a numeric IP literal: {host}"
            ) from exc
        if not address.is_loopback:
            raise AdmissionError(f"discovered endpoint is not loopback: {host}")
    elif host not in COMPOSE_ALLOWLIST:
        raise AdmissionError(f"discovered compose endpoint is not allowlisted: {host}")


def _assert_loopback_ice(candidate: str) -> None:
    fields = candidate.removeprefix("candidate:").split()
    if len(fields) < 8:
        raise AdmissionError("ICE candidate is structurally invalid")
    try:
        address = ipaddress.ip_address(fields[4])
    except ValueError as exc:
        raise AdmissionError(
            "ICE candidate address must be a numeric loopback literal"
        ) from exc
    if not address.is_loopback:
        raise AdmissionError(f"ICE candidate escapes loopback scope: {fields[4]}")


def _assert_sdp_loopback(sdp: str) -> None:
    for line in sdp.splitlines():
        if line.startswith("a=candidate:"):
            _assert_loopback_ice(line.removeprefix("a="))


@dataclass
class Budget:
    deadline_seconds: int
    max_events: int
    max_bytes: int
    max_requests: int
    cleanup_reserve: int = 0
    started: float = field(default_factory=time.monotonic)
    events: int = 0
    bytes_seen: int = 0
    requests: int = 0
    cleanup_mode: bool = False
    cleanup_started: float | None = None

    def check_time(self) -> None:
        if self.cleanup_mode:
            if (
                self.cleanup_started is None
                or time.monotonic() - self.cleanup_started > CLEANUP_SECONDS
            ):
                raise BoundError("cleanup deadline exceeded")
        elif time.monotonic() - self.started > self.deadline_seconds:
            raise BoundError("wall-clock deadline exceeded")

    def begin_cleanup(self) -> None:
        self.cleanup_mode = True
        self.cleanup_started = time.monotonic()

    def request(self) -> None:
        self.check_time()
        limit = (
            self.max_requests
            if self.cleanup_mode
            else self.max_requests - self.cleanup_reserve
        )
        if self.requests >= limit:
            raise BoundError("request bound exceeded")
        self.requests += 1

    def account_bytes(self, payload: bytes) -> None:
        self.account_size(len(payload))

    def account_size(self, size: int) -> None:
        self.check_time()
        if type(size) is not int or size < 0:
            raise BoundError("byte accounting size is invalid")
        limit = self.max_bytes + CLEANUP_BYTES if self.cleanup_mode else self.max_bytes
        if self.bytes_seen + size > limit:
            raise BoundError("byte bound exceeded")
        self.bytes_seen += size

    def observe(self, payload: bytes) -> None:
        self.check_time()
        if self.events >= self.max_events:
            raise BoundError("event bound exceeded")
        self.events += 1
        self.account_bytes(payload)


@dataclass
class ExecutionContext:
    request: dict[str, Any]
    case: dict[str, Any]
    vector: dict[str, Any]
    targets: dict[str, Target]
    budget: Budget
    evidence: dict[str, Any]
    cleanup_stack: list[tuple[str, Callable[[], Any]]] = field(default_factory=list)
    cleanup_complete: bool = False

    def observe(self, kind: str, value: Any, *, result: str = "observed") -> None:
        encoded = value if isinstance(value, bytes) else _canonical_bytes(value)
        self.budget.observe(encoded)
        self.evidence["observations"].append(
            {
                "order": len(self.evidence["observations"]) + 1,
                "at": _utc_now(),
                "kind": kind,
                "result": result,
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )

    def record_control_observation(self, kind: str, value: Any, *, result: str) -> None:
        """Record executor state without obscuring an already-raised bound failure."""
        encoded = value if isinstance(value, bytes) else _canonical_bytes(value)
        self.evidence["observations"].append(
            {
                "order": len(self.evidence["observations"]) + 1,
                "at": _utc_now(),
                "kind": kind,
                "result": result,
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )

    def pre_state(self, kind: str, value: Any) -> None:
        encoded = _canonical_bytes(value)
        self.evidence["pre_state"].append(
            {
                "order": len(self.evidence["pre_state"]) + 1,
                "kind": kind,
                "sha256": _sha(encoded),
                "value": value,
            }
        )

    def push_cleanup(self, action: str, callback: Callable[[], Any]) -> None:
        self.cleanup_stack.append((action, callback))

    def cleanup(self) -> None:
        if self.cleanup_complete:
            return
        self.budget.begin_cleanup()
        if not self.cleanup_stack:
            self.evidence["cleanup"].append(
                {
                    "order": 1,
                    "action": "no_owned_mutation_reached",
                    "result": "pass",
                    "at": _utc_now(),
                }
            )
            self.cleanup_complete = True
            return
        order = 0
        while self.cleanup_stack:
            action, callback = self.cleanup_stack.pop()
            order += 1
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
                status, detail = "pass", "completed"
            except Exception as exc:  # cleanup evidence must survive failures
                status, detail = "fail", f"{type(exc).__name__}: {exc}"
            self.evidence["cleanup"].append(
                {
                    "order": order,
                    "action": action,
                    "result": status,
                    "detail": detail,
                    "at": _utc_now(),
                }
            )
        self.cleanup_complete = True

    async def cleanup_async(self) -> None:
        """Run the same LIFO cleanup inside an active protocol event loop."""
        if self.cleanup_complete:
            return
        self.budget.begin_cleanup()
        if not self.cleanup_stack:
            self.evidence["cleanup"].append(
                {
                    "order": 1,
                    "action": "no_owned_mutation_reached",
                    "result": "pass",
                    "at": _utc_now(),
                }
            )
            self.cleanup_complete = True
            return
        order = 0
        while self.cleanup_stack:
            action, callback = self.cleanup_stack.pop()
            order += 1
            try:
                result = callback()
                if asyncio.iscoroutine(result):
                    await result
                status, detail = "pass", "completed"
            except Exception as exc:  # cleanup evidence must survive failures
                status, detail = "fail", f"{type(exc).__name__}: {exc}"
            self.evidence["cleanup"].append(
                {
                    "order": order,
                    "action": action,
                    "result": status,
                    "detail": detail,
                    "at": _utc_now(),
                }
            )
        self.cleanup_complete = True


def _contract() -> dict[str, Any]:
    return _json_load(CONTRACT_PATH)


def _case_by_id(document: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [case for case in document["cases"] if case["case_id"] == case_id]
    if len(matches) != 1:
        raise AdmissionError(f"unknown or duplicate case_id: {case_id}")
    return matches[0]


def _vector_by_id(case: dict[str, Any], vector_id: str) -> dict[str, Any]:
    vectors = [case["positive_vector"], *case["adjacent_negative_vectors"]]
    matches = [vector for vector in vectors if vector["id"] == vector_id]
    if len(matches) != 1:
        raise AdmissionError(f"vector is not pinned by {case['case_id']}: {vector_id}")
    return matches[0]


def _validate_external_agent_contract(
    raw: dict[str, Any] | None, case: dict[str, Any]
) -> dict[str, Any]:
    if raw is None:
        raise AdmissionError(
            "Agent WebSocket is blocked until an external endpoint/server contract is supplied"
        )
    if set(raw) != {"path", "sha256"}:
        raise AdmissionError("external_agent_contract requires exactly path and sha256")
    path = _safe_repo_file(raw["path"], raw["sha256"])
    contract = _json_load(path)
    expected_keys = {
        "schema_version",
        "case_id",
        "endpoint_path",
        "request_type",
        "response_types",
        "terminal_status",
        "source_identity",
        "disconnect_discards_conversation",
    }
    if set(contract) != expected_keys:
        raise AdmissionError("external Agent contract keys drift")
    if (
        contract["schema_version"] != 1
        or contract["case_id"] != case["case_id"]
        or contract["endpoint_path"] != "/websocket"
        or contract["request_type"] != "user_message"
        or contract["terminal_status"] != "complete"
        or contract["disconnect_discards_conversation"] is not True
        or set(contract["response_types"])
        != {
            "system_response_message",
            "system_intermediate_message",
            "system_interaction_message",
            "error",
        }
        or not isinstance(contract["source_identity"], str)
        or not contract["source_identity"].strip()
    ):
        raise AdmissionError(
            "external Agent endpoint/server contract does not match the pinned client contract"
        )
    return {
        "path": raw["path"],
        "sha256": raw["sha256"],
        "source_identity": contract["source_identity"],
    }


def _validate_resources(case_id: str, resources: Any, run_id: str) -> None:
    if not isinstance(resources, dict) or set(resources) != RESOURCE_KEYS[case_id]:
        raise AdmissionError(
            f"resources for {case_id} must be exactly {sorted(RESOURCE_KEYS[case_id])}"
        )
    for key, value in resources.items():
        if key == "delete_asset_after":
            if type(value) is not bool:
                raise AdmissionError("delete_asset_after must be boolean")
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise AdmissionError(f"resource {key} must be a bounded non-empty string")
    owned_keys = {
        "conversation_id",
        "stream",
        "topic",
        "consumer_group",
        "stream_id",
    }
    for key in owned_keys & set(resources):
        if not resources[key].startswith("vss-protocol-case-"):
            raise AdmissionError(f"resource {key} is outside the owned namespace")
    if not run_id.startswith("vss-protocol-case-") or len(run_id) > 98:
        raise AdmissionError("run_id is outside the owned namespace")


def admit(
    request: dict[str, Any], document: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Target], list[dict[str, Any]]]:
    required = {
        "schema_version",
        "case_id",
        "vector_id",
        "operator_ack",
        "run_id",
        "targets",
        "bounds",
        "resources",
        "credentials_env",
        "evidence_dir",
    }
    optional = {"external_agent_contract"}
    if not required <= set(request) or set(request) - required - optional:
        raise AdmissionError(
            f"execution request keys must be {sorted(required)} plus optional {sorted(optional)}"
        )
    if request["schema_version"] != 1 or request["operator_ack"] != ACK:
        raise AdmissionError("exact operator acknowledgement is required")
    case = _case_by_id(document, request["case_id"])
    vector = _vector_by_id(case, request["vector_id"])
    targets_list = request["targets"]
    if not isinstance(targets_list, list) or not 1 <= len(targets_list) <= 3:
        raise AdmissionError("targets must contain 1..3 entries")
    parsed = [Target.parse(raw) for raw in targets_list]
    if len({target.role for target in parsed}) != len(parsed):
        raise AdmissionError("target roles must be unique")
    targets = {target.role: target for target in parsed}
    if set(targets) != EXPECTED_TARGET_ROLES[case["case_id"]]:
        raise AdmissionError(
            f"target roles must be exactly {sorted(EXPECTED_TARGET_ROLES[case['case_id']])}"
        )
    if any(
        target.tls for role, target in targets.items() if role in {"redis", "kafka"}
    ):
        raise AdmissionError(
            "TLS is not part of the pinned local Redis/Kafka contracts"
        )
    bounds = request["bounds"]
    if set(bounds) != {"deadline_seconds", "max_events", "max_bytes", "max_requests"}:
        raise AdmissionError("bounds keys drift")
    if (
        type(bounds["deadline_seconds"]) is not int
        or not 1
        <= bounds["deadline_seconds"]
        <= min(MAX_SECONDS, vector["deadline_seconds"])
        or type(bounds["max_events"]) is not int
        or not 1 <= bounds["max_events"] <= min(MAX_EVENTS, vector["max_events"])
        or type(bounds["max_bytes"]) is not int
        or not 1024 <= bounds["max_bytes"] <= MAX_BYTES
        or type(bounds["max_requests"]) is not int
        or not 1 <= bounds["max_requests"] <= MAX_REQUESTS
    ):
        raise AdmissionError("bounds exceed the pinned vector or global safety ceiling")
    if bounds["max_requests"] <= CLEANUP_REQUEST_RESERVE[case["case_id"]]:
        raise AdmissionError(
            "request bound leaves no capacity before the reserved cleanup requests"
        )
    credentials = request["credentials_env"]
    if (
        not isinstance(credentials, list)
        or len(credentials) > 4
        or len(set(credentials)) != len(credentials)
    ):
        raise AdmissionError("credentials_env is invalid")
    if any(
        re.fullmatch(r"VSS_PROTOCOL_CASE_[A-Z0-9_]+", name) is None
        for name in credentials
    ):
        raise AdmissionError("credential names must use the VSS_PROTOCOL_CASE_ prefix")
    _validate_resources(case["case_id"], request["resources"], request["run_id"])
    evidence_dir = request["evidence_dir"]
    if not evidence_dir.startswith(
        "deploy/docker/thor-local/qualification/protocol-cases/runtime-evidence/"
    ):
        raise AdmissionError(
            "evidence_dir must be under the protocol-case runtime-evidence directory"
        )
    evidence_parent = (REPO_ROOT / evidence_dir).resolve()
    try:
        evidence_parent.relative_to((LANE / "runtime-evidence").resolve())
    except ValueError as exc:
        raise AdmissionError(
            "evidence_dir escapes the runtime-evidence directory"
        ) from exc
    external = None
    if case["case_id"] == "protocol-case.agent.websocket":
        external = _validate_external_agent_contract(
            request.get("external_agent_contract"), case
        )
    elif case["case_id"] == "protocol-case.kafka.nvschema":
        raise AdmissionError(
            "Kafka execution is blocked until a VSS product trigger and disposable topic create/delete/post-state contract exist"
        )
    elif "external_agent_contract" in request:
        raise AdmissionError(
            "external_agent_contract is only valid for Agent WebSocket"
        )
    admission = [
        {"gate": "explicit_execute_subcommand", "result": "pass"},
        {"gate": "exact_operator_ack", "result": "pass"},
        {"gate": "pinned_case_and_vector", "result": "pass"},
        {"gate": "numeric_loopback_or_compose_allowlist", "result": "pass"},
        {"gate": "no_redirect_or_proxy_transport", "result": "pass"},
        {"gate": "strict_bounds", "result": "pass"},
        {"gate": "owned_namespace", "result": "pass"},
    ]
    if external:
        admission.append(
            {
                "gate": "external_agent_server_contract",
                "result": "pass",
                "binding": external,
            }
        )
    return case, vector, targets, admission


def compile_plans(document: dict[str, Any]) -> list[dict[str, Any]]:
    plans = []
    for case in document["cases"]:
        case_id = case["case_id"]
        plans.append(
            {
                "case_id": case_id,
                "capability_id": case["capability_id"],
                "state": PLAN_STATE[case_id],
                "activation_ready": case_id in EXECUTOR_READY,
                "evidence_class": EVIDENCE_CLASS[case_id],
                "can_advance_capability": case_id in EXECUTOR_READY
                and EVIDENCE_CLASS[case_id] == "product_protocol",
                "network_default": "disabled",
                "positive_vector_id": case["positive_vector"]["id"],
                "negative_vector_ids": [
                    vector["id"] for vector in case["adjacent_negative_vectors"]
                ],
                "required_target_roles": sorted(EXPECTED_TARGET_ROLES[case_id]),
                "required_resource_keys": sorted(RESOURCE_KEYS[case_id]),
                "hard_bounds": {
                    "deadline_seconds": min(
                        MAX_SECONDS, case["positive_vector"]["deadline_seconds"]
                    ),
                    "max_events": min(
                        MAX_EVENTS, case["positive_vector"]["max_events"]
                    ),
                    "max_bytes": MAX_BYTES,
                    "max_requests": MAX_REQUESTS,
                    "cleanup_request_reserve": CLEANUP_REQUEST_RESERVE[case_id],
                    "cleanup_deadline_seconds": CLEANUP_SECONDS,
                    "cleanup_byte_reserve": CLEANUP_BYTES,
                },
                "activation": "execute subcommand + request file + exact operator acknowledgement",
            }
        )
    return plans


class DirectHttpClient:
    """Direct HTTP(S) client: no proxy lookup and redirects are fatal."""

    def __init__(self, target: Target, budget: Budget):
        self.target = target
        self.budget = budget

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        expected: set[int] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        if not path.startswith("/") or "//" in path or "#" in path:
            raise ExecutorError(
                "HTTP path must be an absolute local path without fragments"
            )
        self.budget.request()
        timeout = max(
            0.1, self.budget.deadline_seconds - (time.monotonic() - self.budget.started)
        )
        if self.target.tls:
            context = ssl.create_default_context(
                cafile=str(_safe_repo_file(self.target.ca_file))
                if self.target.ca_file
                else None
            )
            connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                self.target.host, self.target.port, timeout=timeout, context=context
            )
        else:
            connection = http.client.HTTPConnection(
                self.target.host, self.target.port, timeout=timeout
            )
        try:
            if body:
                self.budget.account_bytes(body)
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise ExecutorError(f"redirects are forbidden: HTTP {response.status}")
            payload = response.read(self.budget.max_bytes + 1)
            if len(payload) > self.budget.max_bytes:
                raise BoundError("HTTP response exceeds byte bound")
            self.budget.account_bytes(payload)
            if expected is not None and response.status not in expected:
                raise ExecutorError(
                    f"unexpected HTTP status {response.status}: {_sha(payload)}"
                )
            return (
                response.status,
                {key.lower(): value for key, value in response.getheaders()},
                payload,
            )
        finally:
            connection.close()


class RedisRespClient:
    """Minimal bounded RESP2 client for exact Redis Streams commands."""

    def __init__(self, target: Target, budget: Budget):
        if target.tls:
            raise AdmissionError("Redis TLS is not part of the pinned local contract")
        budget.request()
        timeout = max(
            0.1, budget.deadline_seconds - (time.monotonic() - budget.started)
        )
        self._socket = socket.create_connection(
            (target.host, target.port), timeout=timeout
        )
        self._file = self._socket.makefile("rb")
        self._budget = budget

    def close(self) -> None:
        self._file.close()
        self._socket.close()

    def command(self, *parts: str | bytes | int) -> Any:
        self._budget.request()
        encoded = [
            str(part).encode() if not isinstance(part, bytes) else part
            for part in parts
        ]
        payload = b"*" + str(len(encoded)).encode() + b"\r\n"
        for part in encoded:
            payload += b"$" + str(len(part)).encode() + b"\r\n" + part + b"\r\n"
        if len(payload) > 65536:
            raise BoundError("Redis command exceeds 64 KiB")
        self._budget.account_bytes(payload)
        self._socket.sendall(payload)
        return self._read()

    def _line(self) -> bytes:
        line = self._file.readline(65537)
        if not line.endswith(b"\r\n") or len(line) > 65536:
            raise BoundError("invalid or oversized RESP line")
        self._budget.account_bytes(line)
        return line[:-2]

    def _read(self) -> Any:
        line = self._line()
        prefix, value = line[:1], line[1:]
        if prefix == b"+":
            return value.decode()
        if prefix == b"-":
            raise ExecutorError(f"Redis error: {value.decode(errors='replace')[:256]}")
        if prefix == b":":
            return int(value)
        if prefix == b"$":
            size = int(value)
            if size == -1:
                return None
            if size > self._budget.max_bytes:
                raise BoundError("RESP bulk string exceeds byte bound")
            payload = self._file.read(size + 2)
            self._budget.account_bytes(payload)
            if len(payload) != size + 2 or not payload.endswith(b"\r\n"):
                raise ExecutorError("truncated RESP bulk string")
            return payload[:-2]
        if prefix == b"*":
            count = int(value)
            if count == -1:
                return None
            if not 0 <= count <= self._budget.max_events * 16:
                raise BoundError("RESP array exceeds element bound")
            return [self._read() for _ in range(count)]
        raise ExecutorError("unknown RESP prefix")


def _websocket_connect(target: Target, path: str, budget: Budget):
    """Lazy WebSocket activation; proxy discovery is explicitly disabled."""
    from websockets.sync.client import connect

    budget.request()
    scheme = "wss" if target.tls else "ws"
    ssl_context = None
    if target.tls:
        ssl_context = ssl.create_default_context(
            cafile=str(_safe_repo_file(target.ca_file)) if target.ca_file else None
        )
    return connect(
        f"{scheme}://{target.host}:{target.port}{path}",
        proxy=None,
        open_timeout=budget.deadline_seconds,
        close_timeout=3,
        max_size=budget.max_bytes,
        max_queue=budget.max_events,
        ssl=ssl_context,
    )


def _recv_ws_json(websocket, context: ExecutionContext) -> dict[str, Any]:
    remaining = max(
        0.1,
        context.budget.deadline_seconds - (time.monotonic() - context.budget.started),
    )
    frame = websocket.recv(timeout=remaining)
    payload = frame.encode() if isinstance(frame, str) else frame
    context.observe("websocket_frame", payload)
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ExecutorError("WebSocket frame is not JSON") from exc
    if not isinstance(value, dict):
        raise ExecutorError("WebSocket JSON frame is not an object")
    return value


def _expect_no_ws_application_response(
    websocket, context: ExecutionContext, kind: str
) -> None:
    from websockets.exceptions import ConnectionClosed

    remaining = max(
        0.1,
        context.budget.deadline_seconds - (time.monotonic() - context.budget.started),
    )
    try:
        frame = websocket.recv(timeout=remaining)
    except (TimeoutError, ConnectionClosed):
        context.observe(
            kind,
            {"outcome": "bounded_timeout_without_application_response"},
            result="rejected",
        )
        return
    if isinstance(frame, (str, bytes)):
        payload = frame.encode() if isinstance(frame, str) else frame
        context.observe("unexpected_websocket_frame", payload, result="failed")
    raise ExecutorError("malformed WebSocket input produced an application response")


def _run_agent_ws(context: ExecutionContext) -> None:
    target = context.targets["websocket"]
    conversation = context.request["resources"]["conversation_id"]
    negative = context.vector["id"] != context.case["positive_vector"]["id"]
    fixture = copy.deepcopy(
        context.vector["fixture"]
        if negative
        else context.case["positive_vector"]["fixture"]
    )
    if not negative:
        fixture["conversation_id"] = conversation
    context.pre_state(
        "owned_conversation",
        {"conversation_id": conversation, "state": "not_opened_by_harness"},
    )
    websocket = _websocket_connect(target, "/websocket", context.budget)
    context.push_cleanup("close_owned_agent_websocket", websocket.close)
    context.budget.request()
    websocket.send(json.dumps(fixture, separators=(",", ":")))
    context.observe("websocket_request", fixture)
    if negative:
        from websockets.exceptions import ConnectionClosed

        remaining = max(
            0.1,
            context.budget.deadline_seconds
            - (time.monotonic() - context.budget.started),
        )
        try:
            frame = websocket.recv(timeout=remaining)
        except (TimeoutError, ConnectionClosed):
            context.observe(
                "agent_missing_conversation_rejection",
                {"outcome": "bounded_timeout_without_correlatable_completion"},
                result="rejected",
            )
            return
        payload = frame.encode() if isinstance(frame, str) else frame
        context.observe("websocket_frame", payload)
        try:
            response = json.loads(payload)
        except json.JSONDecodeError:
            context.observe(
                "agent_missing_conversation_rejection",
                {"outcome": "non_json"},
                result="rejected",
            )
            return
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("conversation_id"), str)
            or not response["conversation_id"].strip()
        ):
            context.observe(
                "agent_missing_conversation_rejection",
                {"outcome": "client_validator_rejected_uncorrelatable_frame"},
                result="rejected",
            )
            return
        raise ExecutorError(
            "missing-conversation request unexpectedly produced a correlatable response"
        )
    while True:
        response = _recv_ws_json(websocket, context)
        if response.get("conversation_id") != conversation:
            raise ExecutorError("Agent response conversation_id mismatch")
        if response.get("type") == "error":
            raise ExecutorError("Agent returned error frame")
        if (
            response.get("type") == "system_response_message"
            and response.get("status") == "complete"
        ):
            return


def _redis_pre_state(client: RedisRespClient, stream: str) -> dict[str, Any]:
    exists = client.command("EXISTS", stream)
    length = client.command("XLEN", stream) if exists else 0
    return {"stream": stream, "exists": bool(exists), "length": length}


def _run_alert_ws(context: ExecutionContext) -> None:
    negative = context.vector["id"] != context.case["positive_vector"]["id"]
    if negative:
        context.pre_state("alert_websocket", {"owned_redis_mutation": False})
        websocket = _websocket_connect(
            context.targets["websocket"], "/ws/alerts", context.budget
        )
        context.push_cleanup("close_owned_alert_websocket", websocket.close)
        context.budget.request()
        websocket.send(context.vector["fixture"])
        context.observe("websocket_request", context.vector["fixture"])
        _expect_no_ws_application_response(
            websocket, context, "alert_non_json_rejection"
        )
        return
    stream = context.request["resources"]["stream"]
    redis_client = RedisRespClient(context.targets["redis"], context.budget)
    context.push_cleanup("close_owned_alert_redis_connection", redis_client.close)
    before = _redis_pre_state(redis_client, stream)
    context.pre_state("redis_stream", before)
    if before["exists"]:
        raise AdmissionError("owned alert stream must be absent before mutation")
    websocket = _websocket_connect(
        context.targets["websocket"], "/ws/alerts", context.budget
    )
    context.push_cleanup("close_owned_alert_websocket", websocket.close)
    context.budget.request()
    websocket.send('{"type":"ping"}')
    if _recv_ws_json(websocket, context).get("type") != "pong":
        raise ExecutorError("alert WebSocket ping/pong failed")
    entry_id = redis_client.command(
        "XADD", stream, "*", "case_id", context.request["run_id"], "value", "one"
    )
    entry_text = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
    context.push_cleanup(
        "delete_owned_alert_stream", lambda: redis_client.command("DEL", stream)
    )
    context.observe("redis_xadd", {"stream": stream, "entry_id": entry_text})
    while True:
        response = _recv_ws_json(websocket, context)
        if response.get("type") == "alert" and response.get("stream_name") == stream:
            if (
                response.get("message_id") != entry_text
                or response.get("data", {}).get("case_id") != context.request["run_id"]
                or response.get("data", {}).get("value") != "one"
            ):
                raise ExecutorError("alert frame did not preserve owned Redis entry")
            return


def _parse_sse(payload: bytes, max_events: int) -> list[str]:
    if len(payload) > MAX_BYTES:
        raise BoundError("SSE body exceeds global byte bound")
    text = payload.decode("utf-8")
    events: list[str] = []
    for frame in re.split(r"\r?\n\r?\n", text):
        data = "\n".join(
            line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
        )
        if data:
            events.append(data)
            if len(events) > max_events:
                raise BoundError("SSE event bound exceeded")
    return events


def _run_rt_vlm_sse(context: ExecutionContext) -> None:
    resources = context.request["resources"]
    fixture = copy.deepcopy(context.case["positive_vector"]["fixture"])
    fixture["id"] = resources["asset_id"]
    fixture["model"] = resources["model_id"]
    negative = context.vector["id"] != context.case["positive_vector"]["id"]
    if negative:
        fixture.update(context.vector["fixture"])
    context.pre_state(
        "rt_vlm_asset", {"asset_id": resources["asset_id"], "attested_owned": True}
    )
    client = DirectHttpClient(context.targets["http"], context.budget)
    if resources["delete_asset_after"]:
        context.push_cleanup(
            "delete_owned_rt_vlm_asset",
            lambda: client.request(
                "DELETE", f"/v1/files/{resources['asset_id']}", expected={200, 204, 404}
            ),
        )
    status, headers, payload = client.request(
        "POST",
        "/v1/generate_captions",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        body=_canonical_bytes(fixture),
        expected=None,
    )
    context.observe(
        "rt_vlm_http",
        {"status": status, "content_type": headers.get("content-type", "")},
    )
    if negative:
        if status < 400 or status >= 500:
            raise ExecutorError("negative RT-VLM vector was not rejected with 4xx")
        return
    if status != 200 or "text/event-stream" not in headers.get("content-type", ""):
        raise ExecutorError("RT-VLM did not return HTTP 200 text/event-stream")
    events = _parse_sse(payload, context.budget.max_events)
    if not events or events[-1] != "[DONE]":
        raise ExecutorError("RT-VLM SSE is missing terminal [DONE]")
    usage_count = 0
    last_chunk = -1
    shared_created: Any = None
    for event in events[:-1]:
        value = json.loads(event)
        if value.get("id") is None or value.get("model") != resources["model_id"]:
            raise ExecutorError("RT-VLM SSE identity mismatch")
        if shared_created is None:
            shared_created = value.get("created")
        if value.get("created") is None or value.get("created") != shared_created:
            raise ExecutorError("RT-VLM SSE created value is missing or inconsistent")
        if value.get("usage"):
            usage_count += 1
        for chunk in value.get("chunk_responses", []):
            if usage_count:
                raise ExecutorError("RT-VLM caption chunk followed the usage event")
            if chunk["chunk_id"] < last_chunk:
                raise ExecutorError("RT-VLM chunk ordering regressed")
            last_chunk = chunk["chunk_id"]
    if usage_count != 1:
        raise ExecutorError("RT-VLM must emit exactly one usage event")


def _run_kafka(context: ExecutionContext) -> None:
    raise AdmissionError(
        "Kafka is blocked: a self-produced record would not qualify VSS NvSchema publication, "
        "and writing to a pre-existing topic cannot be exactly reversed"
    )


def _run_redis(context: ExecutionContext) -> None:
    resources = context.request["resources"]
    stream, group = resources["stream"], resources["consumer_group"]
    client = RedisRespClient(context.targets["redis"], context.budget)
    context.push_cleanup("close_owned_redis_connection", client.close)
    before = _redis_pre_state(client, stream)
    context.pre_state("redis_stream", before)
    if before["exists"]:
        raise AdmissionError("owned Redis stream must be absent before mutation")
    try:
        client.command("XGROUP", "CREATE", stream, group, "0", "MKSTREAM")
    except ExecutorError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    context.push_cleanup(
        "delete_owned_redis_stream", lambda: client.command("DEL", stream)
    )
    context.push_cleanup(
        "destroy_owned_redis_group",
        lambda: client.command("XGROUP", "DESTROY", stream, group),
    )
    negative = context.vector["id"] != context.case["positive_vector"]["id"]
    headers = (
        context.vector["fixture"].get("headers")
        if negative
        else '{"content-type":"application/json"}'
    )
    entry_id = client.command(
        "XADD",
        stream,
        "MAXLEN",
        "~",
        "10000",
        "*",
        "key",
        context.request["run_id"],
        "value",
        _canonical_bytes({"case_id": context.request["run_id"]}),
        "headers",
        headers,
    )
    response = client.command(
        "XREADGROUP",
        "GROUP",
        group,
        context.request["run_id"],
        "COUNT",
        "1",
        "BLOCK",
        "100",
        "STREAMS",
        stream,
        ">",
    )
    if not response:
        raise ExecutorError("Redis XREADGROUP returned no owned entry")
    read_entry_id = response[0][1][0][0]
    if read_entry_id != entry_id:
        raise ExecutorError("Redis read entry ID differs from XADD entry ID")
    fields = response[0][1][0][1]
    mapping = {
        fields[index].decode(): fields[index + 1] for index in range(0, len(fields), 2)
    }
    if negative:
        try:
            json.loads(mapping["headers"])
        except json.JSONDecodeError:
            context.observe(
                "redis_header_negative_rejection",
                {"entry_sha256": _sha(entry_id)},
                result="rejected",
            )
            return
        raise ExecutorError("malformed Redis headers unexpectedly decoded")
    if mapping["key"].decode() != context.request["run_id"]:
        raise ExecutorError("Redis key mismatch")
    if json.loads(mapping["value"]) != {"case_id": context.request["run_id"]}:
        raise ExecutorError("Redis value mismatch")
    if json.loads(mapping["headers"]) != {"content-type": "application/json"}:
        raise ExecutorError("Redis headers mismatch")
    entry_ms = int(entry_id.decode().split("-", 1)[0])
    context.observe(
        "redis_events_envelope",
        {
            "stream": stream,
            "entry_id_sha256": _sha(entry_id),
            "timestamp_milliseconds": entry_ms,
        },
    )
    client.command("XACK", stream, group, entry_id)
    pending = client.command("XPENDING", stream, group)
    if not pending or pending[0] != 0:
        raise ExecutorError("Redis pending count is not zero after XACK")


async def _run_vios_async(context: ExecutionContext, replay: bool) -> None:
    resources = context.request["resources"]
    target = context.targets["http"]
    client = DirectHttpClient(target, context.budget)
    prefix = "/api/v1/replay" if replay else "/api/v1/live"
    token_name = "VSS_PROTOCOL_CASE_BEARER_TOKEN"
    if token_name not in context.request["credentials_env"] or not os.environ.get(
        token_name
    ):
        raise AdmissionError(f"secured VIOS calls require {token_name}")
    secure_headers = {
        "Authorization": f"Bearer {os.environ[token_name]}",
        "Content-Type": "application/json",
        "streamId": resources["stream_id"],
    }
    negative = context.vector["id"] != context.case["positive_vector"]["id"]
    if not replay and negative:
        context.pre_state(
            "vios_peer",
            {"peer_id": resources["peer_id"], "owned": True, "started": False},
        )
        status, _, raw = client.request(
            "POST",
            f"{prefix}/stream/start",
            headers=secure_headers,
            body=_canonical_bytes({"streamId": resources["stream_id"]}),
            expected=None,
        )
        context.observe(
            "vios_missing_peer_rejection",
            {"status": status, "response_sha256": _sha(raw)},
            result="rejected",
        )
        if not 400 <= status < 500:
            raise ExecutorError(
                "VIOS live missing-peer vector was not rejected with 4xx"
            )
        return
    try:
        from aiortc import RTCPeerConnection, RTCSessionDescription
        from aiortc.sdp import candidate_from_sdp
    except ImportError as exc:
        raise AdmissionError(
            "VIOS WebRTC execution requires preinstalled aiortc"
        ) from exc
    pc = RTCPeerConnection()
    context.push_cleanup("close_owned_webrtc_peer", pc.close)
    pc.addTransceiver("video", direction="recvonly")
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    _assert_sdp_loopback(pc.localDescription.sdp)
    body: dict[str, Any] = {
        "streamId": resources["stream_id"],
        "peerId": resources["peer_id"],
        "options": {"quality": "auto", "rtptransport": "udp", "timeout": 10},
        "sessionDescription": {"type": "offer", "sdp": pc.localDescription.sdp},
    }
    if replay:
        body.update(
            {"startTime": resources["start_time"], "endTime": resources["end_time"]}
        )
    context.pre_state(
        "vios_peer", {"peer_id": resources["peer_id"], "owned": True, "started": False}
    )
    _, _, raw = client.request(
        "POST",
        f"{prefix}/stream/start",
        headers=secure_headers,
        body=_canonical_bytes(body),
        expected={200},
    )
    answer = json.loads(raw)
    media_session = answer.get("mediaSessionId")
    if answer.get("type") != "answer" or not answer.get("sdp") or not media_session:
        raise ExecutorError("VIOS start response lacks answer/mediaSessionId")
    _assert_sdp_loopback(answer["sdp"])

    def stop() -> None:
        client.request(
            "POST",
            f"{prefix}/stream/stop",
            headers=secure_headers,
            body=_canonical_bytes(
                {"peerId": resources["peer_id"], "mediaSessionId": media_session}
            ),
            expected={200},
        )

    context.push_cleanup("stop_owned_vios_media_session", stop)
    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
    )
    _, _, candidates_raw = client.request(
        "GET",
        f"{prefix}/iceCandidate?peerId={resources['peer_id']}",
        headers={"streamId": resources["stream_id"]},
        expected={200},
    )
    for candidate in json.loads(candidates_raw):
        _assert_loopback_ice(candidate["candidate"])
        parsed = candidate_from_sdp(candidate["candidate"].removeprefix("candidate:"))
        parsed.sdpMid = candidate["sdpMid"]
        parsed.sdpMLineIndex = candidate["sdpMLineIndex"]
        await pc.addIceCandidate(parsed)
    deadline = time.monotonic() + context.budget.deadline_seconds
    track = None
    while time.monotonic() < deadline:
        receivers = [
            receiver
            for receiver in pc.getReceivers()
            if receiver.track and receiver.track.kind == "video"
        ]
        if receivers:
            track = receivers[0].track
            break
        await asyncio.sleep(0.1)
    if track is None:
        raise BoundError("VIOS video track deadline exceeded")
    frame = await asyncio.wait_for(
        track.recv(), timeout=max(0.1, deadline - time.monotonic())
    )
    context.budget.account_size(sum(plane.buffer_size for plane in frame.planes))
    context.observe(
        "webrtc_frame_before_seek" if replay else "webrtc_live_frame",
        {"pts": frame.pts, "time_base": str(frame.time_base)},
    )
    if replay:
        seek = copy.deepcopy(context.case["positive_vector"]["fixture"]["seek"])
        seek.update(context.vector.get("fixture", {}).get("seek", {}))
        seek.update({"peerId": resources["peer_id"], "mediaSessionId": media_session})
        status, _, seek_raw = client.request(
            "POST",
            f"{prefix}/stream/seek",
            headers=secure_headers,
            body=_canonical_bytes(seek),
            expected=None,
        )
        if negative:
            if not 400 <= status < 500:
                raise ExecutorError(
                    "invalid replay seek action was not rejected with 4xx"
                )
            return
        if status != 200:
            raise ExecutorError(f"VIOS replay seek failed: {_sha(seek_raw)}")
        _, _, position_raw = client.request(
            "GET",
            f"{prefix}/stream/seek?mediaSessionId={media_session}&peerId={resources['peer_id']}",
            headers={"streamId": resources["stream_id"]},
            expected={200},
        )
        position = json.loads(position_raw).get("position")
        if type(position) is not int:
            raise ExecutorError("VIOS replay seek position is not int64-compatible")
        after = await asyncio.wait_for(
            track.recv(), timeout=max(0.1, deadline - time.monotonic())
        )
        context.budget.account_size(sum(plane.buffer_size for plane in after.planes))
        context.observe(
            "webrtc_frame_after_seek",
            {"pts": after.pts, "time_base": str(after.time_base), "position": position},
        )


def _run_vios(context: ExecutionContext, replay: bool) -> None:
    async def run_and_cleanup() -> None:
        try:
            await _run_vios_async(context, replay)
        finally:
            await context.cleanup_async()

    asyncio.run(run_and_cleanup())


RUNNERS: dict[str, Callable[[ExecutionContext], None]] = {
    "protocol-case.agent.websocket": _run_agent_ws,
    "protocol-case.alert.websocket": _run_alert_ws,
    "protocol-case.rt-vlm.sse": _run_rt_vlm_sse,
    "protocol-case.kafka.nvschema": _run_kafka,
    "protocol-case.redis.events": _run_redis,
    "protocol-case.vios.webrtc-live": lambda context: _run_vios(context, False),
    "protocol-case.vios.webrtc-replay": lambda context: _run_vios(context, True),
}


def _initial_evidence(
    document: dict[str, Any],
    case: dict[str, Any],
    vector: dict[str, Any],
    request: dict[str, Any],
    targets: dict[str, Target],
    admission: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "case_id": case["case_id"],
        "capability_id": case["capability_id"],
        "target_commit": document["target_commit"],
        "contract_path": str(CONTRACT_PATH.relative_to(REPO_ROOT)),
        "contract_file_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        "contract_set_sha256": document["contract_set_sha256"],
        "case_sha256": _sha(case),
        "source_bindings": [
            {
                "path": source["path"],
                "git_blob_oid": source["git_blob_oid"],
                "content_sha256": source["content_sha256"],
            }
            for source in case["sources"]
        ],
        "vector_id": vector["id"],
        "vector_sha256": _sha(vector),
        "execution_request_sha256": _sha(request),
        "run_id": request["run_id"],
        "evidence_class": EVIDENCE_CLASS[case["case_id"]],
        "can_advance_capability": EVIDENCE_CLASS[case["case_id"]] == "product_protocol",
        "started_at": _utc_now(),
        "finished_at": "",
        "result": "blocked",
        "admission": admission,
        "bounds": request["bounds"],
        "cleanup_request_reserve": CLEANUP_REQUEST_RESERVE[case["case_id"]],
        "cleanup_deadline_seconds": CLEANUP_SECONDS,
        "cleanup_byte_reserve": CLEANUP_BYTES,
        "targets": [targets[role].evidence() for role in sorted(targets)],
        "pre_state": [],
        "observations": [],
        "cleanup": [],
    }


def _write_evidence(request: dict[str, Any], evidence: dict[str, Any]) -> Path:
    directory = (REPO_ROOT / request["evidence_dir"]).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{request['run_id']}-{evidence['vector_id']}.json"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise ExecutorError(f"refusing to overwrite evidence: {path}") from exc
    path.chmod(0o600)
    return path


def execute(request_path: Path) -> tuple[int, str]:
    document = _contract()
    request = _json_load(request_path)
    case, vector, targets, admission = admit(request, document)
    budget = Budget(
        **request["bounds"], cleanup_reserve=CLEANUP_REQUEST_RESERVE[case["case_id"]]
    )
    evidence = _initial_evidence(document, case, vector, request, targets, admission)
    context = ExecutionContext(request, case, vector, targets, budget, evidence)
    exit_code = 1
    try:
        RUNNERS[case["case_id"]](context)
        evidence["result"] = "passed"
        exit_code = 0
    except AdmissionError as exc:
        evidence["result"] = "blocked"
        context.record_control_observation(
            "executor_blocked", {"error": str(exc)}, result="blocked"
        )
    except Exception as exc:
        evidence["result"] = "failed"
        context.record_control_observation(
            "executor_failure",
            {"error_type": type(exc).__name__, "error": str(exc)},
            result="failed",
        )
    finally:
        context.cleanup()
        if any(item["result"] == "fail" for item in evidence["cleanup"]):
            evidence["result"] = "failed"
            exit_code = 1
        evidence["finished_at"] = _utc_now()
    evidence_path = _write_evidence(request, evidence)
    return exit_code, str(evidence_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    plan_parser = subparsers.add_parser(
        "plan", help="compile inert plans; performs no I/O beyond local reads/stdout"
    )
    plan_parser.add_argument("--case-id")
    execute_parser = subparsers.add_parser(
        "execute", help="activate one explicitly acknowledged request"
    )
    execute_parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command in (None, "plan"):
        plans = compile_plans(_contract())
        if getattr(args, "case_id", None):
            plans = [plan for plan in plans if plan["case_id"] == args.case_id]
            if not plans:
                print("FAIL: unknown case_id", file=sys.stderr)
                return 2
        print(
            json.dumps(
                {"mode": "plan_only", "network": "disabled", "plans": plans},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    try:
        code, evidence = execute(args.request)
    except ExecutorError as exc:
        print(f"FAIL: admission denied before execution: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"evidence": evidence, "exit_code": code}, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
