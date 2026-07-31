#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile the safe, plan-only Thor VSS stateful acceptance contract.

Phase 0 deliberately has no execution mode.  It validates the complete plan,
expands coverage against the current parity/API ledgers, and emits a redacted
JSON plan.  Small transport and ledger primitives live here so their safety
properties can be qualified before a later execution phase uses them.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
DEFAULT_INVENTORY = SCRIPT_DIR / "acceptance_inventory.json"
DEFAULT_FIXTURES = SCRIPT_DIR / "fixtures.json"
DEFAULT_PARITY_MANIFEST = REPO_ROOT / "deploy/docker/thor-local/parity/manifest.json"
DEFAULT_API_INVENTORY = SCRIPT_DIR / "api_inventory.json"
DEFAULT_EXPECTED_DIR = SCRIPT_DIR / "expected"
DEFAULT_RUNTIME_INVENTORY = SCRIPT_DIR / "runtime_inventory.json"
DEFAULT_PHASE1_INVENTORY = SCRIPT_DIR / "acceptance_phase1_inventory.json"

PLAIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RESOURCE_TEMPLATE_RE = re.compile(r"^\$\{namespace\}-[a-z0-9][a-z0-9-]{0,13}$")
TARGET_FROM_RE = re.compile(
    r"^(?P<action>[a-z0-9][a-z0-9-]{0,62})\.(?:request|response)\."
    r"(?P<field>[a-zA-Z][a-zA-Z0-9_.]{0,127})$"
)
SAFE_PATH_RE = re.compile(r"^/[^\x00-\x20\x7f?#]*$")

MAX_FIXTURE_BYTES = 2 * 1024 * 1024
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_LEDGER_RECORD_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SSE_EVENTS = 1024
MAX_SSE_SECONDS = 60

SAFETY_CLASSES = {
    "observe",
    "owned-create",
    "owned-update",
    "owned-delete",
    "service-lifecycle",
    "external-side-effect",
    "unclassified-blocked",
}
MUTATING_CLASSES = {
    "owned-create",
    "owned-update",
    "owned-delete",
    "service-lifecycle",
    "external-side-effect",
}
ACTION_KINDS = {
    "external-check",
    "http",
    "offline-check",
    "service-lifecycle",
    "surface-matrix",
    "ui-check",
}
LEDGER_EVENTS = {
    "cleanup-failed",
    "cleanup-started",
    "cleanup-succeeded",
    "created",
    "run-finished",
    "run-started",
    "updated",
}
RESOURCE_LEDGER_EVENTS = LEDGER_EVENTS - {"run-finished", "run-started"}


class AcceptanceConfigError(ValueError):
    """Raised when the stateful acceptance contract is unsafe or incomplete."""


class ResponseBoundError(ValueError):
    """Raised when a bounded response or SSE stream exceeds its declaration."""


class LedgerError(ValueError):
    """Raised when the append-only acceptance ledger cannot be trusted."""


class NoRedirects(HTTPRedirectHandler):
    """Refuse redirects instead of following a loopback response elsewhere."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise AcceptanceConfigError("configuration_error")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceConfigError("configuration_error") from exc
    if not isinstance(value, dict):
        raise AcceptanceConfigError("configuration_error")
    return value


def _plain_id(value: Any) -> str:
    if not isinstance(value, str) or not PLAIN_ID_RE.fullmatch(value):
        raise AcceptanceConfigError("configuration_error")
    return value


def _unique_ids(values: Any, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(values, list) or (not values and not allow_empty):
        raise AcceptanceConfigError("configuration_error")
    result = [_plain_id(value) for value in values]
    if len(result) != len(set(result)):
        raise AcceptanceConfigError("configuration_error")
    return result


def _positive_int(value: Any, *, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value <= maximum
    ):
        raise AcceptanceConfigError("configuration_error")
    return value


def validate_origin(value: Any) -> str:
    """Accept only an HTTP origin containing a numeric loopback address."""

    if not isinstance(value, str):
        raise AcceptanceConfigError("configuration_error")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise AcceptanceConfigError("configuration_error") from exc
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
        raise AcceptanceConfigError("configuration_error")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise AcceptanceConfigError("configuration_error") from exc
    if not address.is_loopback or not 1 <= port <= 65535:
        raise AcceptanceConfigError("configuration_error")
    literal = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"http://{literal}:{port}"


def build_safe_opener() -> Any:
    """Build an opener with ambient proxies disabled and redirects refused."""

    return build_opener(ProxyHandler({}), NoRedirects())


def read_bounded(response: BinaryIO, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` and fail closed on one additional byte."""

    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 0 < max_bytes <= MAX_RESPONSE_BYTES
    ):
        raise ResponseBoundError("invalid_limit")
    body = response.read(max_bytes + 1)
    if not isinstance(body, bytes):
        raise ResponseBoundError("invalid_response")
    if len(body) > max_bytes:
        raise ResponseBoundError("response_too_large")
    return body


def read_sse_bounded(
    response: BinaryIO,
    *,
    max_bytes: int,
    max_events: int,
    max_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    """Read an SSE prefix with byte, event, and wall-clock bounds."""

    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 0 < max_bytes <= MAX_RESPONSE_BYTES
        or isinstance(max_events, bool)
        or not isinstance(max_events, int)
        or not 0 < max_events <= MAX_SSE_EVENTS
        or isinstance(max_seconds, bool)
        or not isinstance(max_seconds, (int, float))
        or not 0 < max_seconds <= MAX_SSE_SECONDS
    ):
        raise ResponseBoundError("invalid_limit")
    started = clock()
    body = bytearray()
    event_count = 0
    frame = bytearray()
    previous_was_cr = False

    def accept_byte(value: int) -> None:
        nonlocal event_count
        frame.append(value)
        if frame.endswith(b"\n\n"):
            candidate = frame[:-2]
            if any(
                line and not line.startswith(b":") for line in candidate.split(b"\n")
            ):
                event_count += 1
                if event_count > max_events:
                    raise ResponseBoundError("too_many_sse_events")
            frame.clear()

    while True:
        if clock() - started > max_seconds:
            raise ResponseBoundError("sse_timeout")
        remaining = max_bytes - len(body)
        chunk = response.read(min(4096, remaining + 1))
        if not isinstance(chunk, bytes):
            raise ResponseBoundError("invalid_response")
        if clock() - started > max_seconds:
            raise ResponseBoundError("sse_timeout")
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ResponseBoundError("response_too_large")
        for value in chunk:
            if previous_was_cr:
                accept_byte(ord("\n"))
                previous_was_cr = False
                if value == ord("\n"):
                    continue
            if value == ord("\r"):
                previous_was_cr = True
            else:
                accept_byte(value)
    if previous_was_cr:
        accept_byte(ord("\n"))
    return bytes(body)


def build_namespace(run_id: str) -> str:
    """Return the only namespace shape accepted for owned test resources."""

    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise AcceptanceConfigError("configuration_error")
    namespace = f"thor-vss-accept-{run_id}"
    if len(namespace) > 63:
        raise AcceptanceConfigError("configuration_error")
    return namespace


def _validate_ffprobe_oracle(oracle: Any) -> None:
    if not isinstance(oracle, dict) or oracle.get("schema_version") != 1:
        raise AcceptanceConfigError("configuration_error")
    if not set(oracle) <= {"duration_ms", "format_names", "schema_version", "streams"}:
        raise AcceptanceConfigError("configuration_error")
    format_names = oracle.get("format_names")
    if (
        not isinstance(format_names, list)
        or not format_names
        or any(not isinstance(item, str) or not item for item in format_names)
        or len(format_names) != len(set(format_names))
    ):
        raise AcceptanceConfigError("configuration_error")
    duration = oracle.get("duration_ms")
    if duration is not None and (
        not isinstance(duration, dict)
        or isinstance(duration.get("min"), bool)
        or isinstance(duration.get("max"), bool)
        or not isinstance(duration.get("min"), int)
        or not isinstance(duration.get("max"), int)
        or not 0 <= duration["min"] <= duration["max"] <= 60_000
    ):
        raise AcceptanceConfigError("configuration_error")
    streams = oracle.get("streams")
    if not isinstance(streams, list) or not streams:
        raise AcceptanceConfigError("configuration_error")
    indices: set[int] = set()
    for stream in streams:
        if not isinstance(stream, dict):
            raise AcceptanceConfigError("configuration_error")
        if not set(stream) <= {
            "channels",
            "codec_name",
            "codec_type",
            "frame_count",
            "frame_rate",
            "height",
            "index",
            "sample_rate",
            "width",
        }:
            raise AcceptanceConfigError("configuration_error")
        index = stream.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise AcceptanceConfigError("configuration_error")
        if index in indices:
            raise AcceptanceConfigError("configuration_error")
        indices.add(index)
        if stream.get("codec_type") not in {"audio", "video"}:
            raise AcceptanceConfigError("configuration_error")
        if not isinstance(stream.get("codec_name"), str) or not stream["codec_name"]:
            raise AcceptanceConfigError("configuration_error")
        for field in ("width", "height", "channels", "sample_rate", "frame_count"):
            if field in stream and (
                isinstance(stream[field], bool)
                or not isinstance(stream[field], int)
                or stream[field] <= 0
            ):
                raise AcceptanceConfigError("configuration_error")
        if "frame_rate" in stream and not re.fullmatch(
            r"[1-9]\d*/[1-9]\d*", str(stream["frame_rate"])
        ):
            raise AcceptanceConfigError("configuration_error")


def validate_fixture_catalog(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if catalog.get("schema_version") != 1:
        raise AcceptanceConfigError("configuration_error")
    policy = catalog.get("policy")
    if not isinstance(policy, dict):
        raise AcceptanceConfigError("configuration_error")
    if (
        policy.get("content_source") != "embedded-base64"
        or policy.get("hash_algorithm") != "sha256"
        or policy.get("network_protocols") is not False
        or policy.get("materialize_only_below_owned_temp") is not True
    ):
        raise AcceptanceConfigError("configuration_error")
    maximum = _positive_int(policy.get("max_decoded_bytes"), maximum=MAX_FIXTURE_BYTES)
    command = policy.get("ffprobe_command")
    if command != [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        "--",
        "${fixture_path}",
    ]:
        raise AcceptanceConfigError("configuration_error")

    fixtures = catalog.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise AcceptanceConfigError("configuration_error")
    result: dict[str, dict[str, Any]] = {}
    file_names: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise AcceptanceConfigError("configuration_error")
        fixture_id = _plain_id(fixture.get("id"))
        file_name = fixture.get("file_name")
        if (
            fixture_id in result
            or not isinstance(file_name, str)
            or Path(file_name).name != file_name
            or file_name in {".", ".."}
            or file_name in file_names
        ):
            raise AcceptanceConfigError("configuration_error")
        if fixture.get("content_encoding") != "base64":
            raise AcceptanceConfigError("configuration_error")
        content = fixture.get("content_base64")
        if not isinstance(content, str) or not content:
            raise AcceptanceConfigError("configuration_error")
        try:
            decoded = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AcceptanceConfigError("configuration_error") from exc
        if len(decoded) > maximum or fixture.get("byte_length") != len(decoded):
            raise AcceptanceConfigError("configuration_error")
        digest = fixture.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise AcceptanceConfigError("configuration_error")
        if not hashlib.sha256(decoded).hexdigest() == digest:
            raise AcceptanceConfigError("configuration_error")
        media_type = fixture.get("media_type")
        if media_type not in {"image/png", "video/mp4"}:
            raise AcceptanceConfigError("configuration_error")
        if media_type == "image/png" and not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AcceptanceConfigError("configuration_error")
        if media_type == "video/mp4" and (len(decoded) < 12 or decoded[4:8] != b"ftyp"):
            raise AcceptanceConfigError("configuration_error")
        _validate_ffprobe_oracle(fixture.get("ffprobe_oracle"))
        if media_type == "video/mp4" and "duration_ms" not in fixture["ffprobe_oracle"]:
            raise AcceptanceConfigError("configuration_error")
        _unique_ids(fixture.get("use_cases"))
        result[fixture_id] = fixture
        file_names.add(file_name)
    return result


def _validate_transport_policy(policy: Any) -> dict[str, int]:
    if not isinstance(policy, dict):
        raise AcceptanceConfigError("configuration_error")
    if (
        policy.get("loopback_only") is not True
        or policy.get("numeric_ip_only") is not True
        or policy.get("allowed_schemes") != ["http"]
        or policy.get("ambient_proxies") is not False
        or policy.get("follow_redirects") is not False
    ):
        raise AcceptanceConfigError("configuration_error")
    limits = {
        "max_body_bytes": _positive_int(
            policy.get("max_body_bytes"), maximum=MAX_RESPONSE_BYTES
        ),
        "max_sse_bytes": _positive_int(
            policy.get("max_sse_bytes"), maximum=MAX_RESPONSE_BYTES
        ),
        "max_sse_events": _positive_int(
            policy.get("max_sse_events"), maximum=MAX_SSE_EVENTS
        ),
        "max_sse_seconds": _positive_int(
            policy.get("max_sse_seconds"), maximum=MAX_SSE_SECONDS
        ),
    }
    return limits


def _validate_safety_classes(value: Any) -> None:
    if not isinstance(value, list):
        raise AcceptanceConfigError("configuration_error")
    by_id: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise AcceptanceConfigError("configuration_error")
        item_id = _plain_id(item.get("id"))
        if item_id in by_id:
            raise AcceptanceConfigError("configuration_error")
        if item.get("phase0_executable") is not False:
            raise AcceptanceConfigError("configuration_error")
        expected_mutation: bool | None = item_id in MUTATING_CLASSES
        if item_id == "unclassified-blocked":
            expected_mutation = None
        if item.get("mutates") is not expected_mutation:
            raise AcceptanceConfigError("configuration_error")
        if item.get("approval") not in {"none", "explicit-run", "operator"}:
            raise AcceptanceConfigError("configuration_error")
        by_id[item_id] = item
    if set(by_id) != SAFETY_CLASSES:
        raise AcceptanceConfigError("configuration_error")
    if by_id["observe"]["approval"] != "none":
        raise AcceptanceConfigError("configuration_error")
    for item_id in MUTATING_CLASSES:
        if by_id[item_id]["approval"] == "none":
            raise AcceptanceConfigError("configuration_error")


def _validate_action(
    action: Any,
    *,
    blockers: set[str],
    resources: set[str],
    limits: dict[str, int],
    operation_bindings: dict[str, tuple[str, str]],
    cleanup: bool,
) -> str:
    if not isinstance(action, dict):
        raise AcceptanceConfigError("configuration_error")
    action_id = _plain_id(action.get("id"))
    if action.get("kind") not in ACTION_KINDS:
        raise AcceptanceConfigError("configuration_error")
    safety_class = action.get("safety_class")
    if safety_class not in SAFETY_CLASSES:
        raise AcceptanceConfigError("configuration_error")
    action_blockers = set(_unique_ids(action.get("blocker_ids")))
    if (
        not action_blockers <= blockers
        or "phase1-execution-disabled" not in action_blockers
    ):
        raise AcceptanceConfigError("configuration_error")
    resource_id = action.get("owned_resource")
    if safety_class in {"owned-create", "owned-update", "owned-delete"}:
        if resource_id not in resources:
            raise AcceptanceConfigError("configuration_error")
    elif resource_id is not None:
        raise AcceptanceConfigError("configuration_error")
    if cleanup != (safety_class == "owned-delete"):
        raise AcceptanceConfigError("configuration_error")
    if safety_class != "owned-create" and any(
        key in action for key in ("register_target_from", "request_name_from")
    ):
        raise AcceptanceConfigError("configuration_error")
    if safety_class not in {"owned-update", "owned-delete"} and (
        "exact_target_from" in action
    ):
        raise AcceptanceConfigError("configuration_error")
    if safety_class in {
        "service-lifecycle",
        "external-side-effect",
        "unclassified-blocked",
    }:
        if len(action_blockers - {"phase1-execution-disabled"}) == 0:
            raise AcceptanceConfigError("configuration_error")

    if action["kind"] == "http":
        transport = action.get("transport")
        if not isinstance(transport, dict):
            raise AcceptanceConfigError("configuration_error")
        validate_origin(transport.get("origin"))
        if (
            transport.get("proxies") is not False
            or transport.get("redirects") is not False
        ):
            raise AcceptanceConfigError("configuration_error")
        if transport.get("max_body_bytes") != limits["max_body_bytes"]:
            raise AcceptanceConfigError("configuration_error")
        method = action.get("method")
        if method not in {"DELETE", "GET", "PATCH", "POST", "PUT"}:
            raise AcceptanceConfigError("configuration_error")
        path = action.get("path")
        if not isinstance(path, str) or not SAFE_PATH_RE.fullmatch(path):
            raise AcceptanceConfigError("configuration_error")
        operation_ref = action.get("operation_ref")
        if not isinstance(operation_ref, str) or operation_bindings.get(
            operation_ref
        ) != (method, path):
            raise AcceptanceConfigError("configuration_error")
        sse = action.get("sse")
        if sse is not None:
            if sse != {
                "max_bytes": limits["max_sse_bytes"],
                "max_events": limits["max_sse_events"],
                "max_seconds": limits["max_sse_seconds"],
            }:
                raise AcceptanceConfigError("configuration_error")
    elif any(key in action for key in ("method", "path", "transport", "sse")):
        raise AcceptanceConfigError("configuration_error")
    return action_id


def _validate_scenario(
    scenario: Any,
    *,
    blocker_ids: set[str],
    fixture_ids: set[str],
    limits: dict[str, int],
    operation_bindings: dict[str, tuple[str, str]],
) -> str:
    if not isinstance(scenario, dict):
        raise AcceptanceConfigError("configuration_error")
    scenario_id = _plain_id(scenario.get("id"))
    if not isinstance(scenario.get("description"), str) or not scenario["description"]:
        raise AcceptanceConfigError("configuration_error")
    scenario_blockers = set(_unique_ids(scenario.get("blocker_ids")))
    if (
        not scenario_blockers <= blocker_ids
        or "phase1-execution-disabled" not in scenario_blockers
    ):
        raise AcceptanceConfigError("configuration_error")
    if (
        not set(_unique_ids(scenario.get("fixture_ids"), allow_empty=True))
        <= fixture_ids
    ):
        raise AcceptanceConfigError("configuration_error")

    resources_value = scenario.get("owned_resources")
    if not isinstance(resources_value, list):
        raise AcceptanceConfigError("configuration_error")
    resources: dict[str, dict[str, Any]] = {}
    for resource in resources_value:
        if not isinstance(resource, dict):
            raise AcceptanceConfigError("configuration_error")
        resource_id = _plain_id(resource.get("id"))
        if resource_id in resources:
            raise AcceptanceConfigError("configuration_error")
        if not RESOURCE_TEMPLATE_RE.fullmatch(str(resource.get("name_template", ""))):
            raise AcceptanceConfigError("configuration_error")
        if not isinstance(resource.get("kind"), str) or not resource["kind"]:
            raise AcceptanceConfigError("configuration_error")
        resources[resource_id] = resource

    actions = scenario.get("actions")
    cleanup_actions = scenario.get("cleanup")
    if (
        not isinstance(actions, list)
        or not actions
        or not isinstance(cleanup_actions, list)
    ):
        raise AcceptanceConfigError("configuration_error")
    action_ids: list[str] = []
    action_by_id: dict[str, dict[str, Any]] = {}
    for action in actions:
        action_id = _validate_action(
            action,
            blockers=scenario_blockers,
            resources=set(resources),
            limits=limits,
            operation_bindings=operation_bindings,
            cleanup=False,
        )
        if action_id in action_by_id:
            raise AcceptanceConfigError("configuration_error")
        action_ids.append(action_id)
        action_by_id[action_id] = action
    cleanup_ids: list[str] = []
    for action in cleanup_actions:
        action_id = _validate_action(
            action,
            blockers=scenario_blockers,
            resources=set(resources),
            limits=limits,
            operation_bindings=operation_bindings,
            cleanup=True,
        )
        if action_id in action_by_id:
            raise AcceptanceConfigError("configuration_error")
        cleanup_ids.append(action_id)
        action_by_id[action_id] = action
    if len(cleanup_ids) != len(set(cleanup_ids)):
        raise AcceptanceConfigError("configuration_error")

    creation_order: list[str] = []
    for resource_id, resource in resources.items():
        create_id = _plain_id(resource.get("created_by"))
        cleanup_id = _plain_id(resource.get("cleaned_by"))
        if create_id not in action_ids or cleanup_id not in cleanup_ids:
            raise AcceptanceConfigError("configuration_error")
        create_action = action_by_id[create_id]
        cleanup_action = action_by_id[cleanup_id]
        if (
            create_action.get("safety_class") != "owned-create"
            or create_action.get("owned_resource") != resource_id
            or create_action.get("request_name_from") != f"{resource_id}.name_template"
            or cleanup_action.get("safety_class") != "owned-delete"
            or cleanup_action.get("owned_resource") != resource_id
        ):
            raise AcceptanceConfigError("configuration_error")
        registered = resource.get("target_from")
        match = TARGET_FROM_RE.fullmatch(str(registered))
        if match is None or match.group("action") != create_id:
            raise AcceptanceConfigError("configuration_error")
        if create_action.get("register_target_from") != registered:
            raise AcceptanceConfigError("configuration_error")
        if cleanup_action.get("exact_target_from") != registered:
            raise AcceptanceConfigError("configuration_error")
        creation_order.append(resource_id)
    creation_order.sort(
        key=lambda item: action_ids.index(resources[item]["created_by"])
    )
    expected_cleanup = [
        resources[item]["cleaned_by"] for item in reversed(creation_order)
    ]
    if (
        cleanup_ids != expected_cleanup
        or scenario.get("cleanup_order") != expected_cleanup
    ):
        raise AcceptanceConfigError("configuration_error")

    for action in actions:
        if action.get("safety_class") == "owned-update":
            resource_id = action["owned_resource"]
            create_id = resources[resource_id]["created_by"]
            if (
                action_ids.index(create_id) >= action_ids.index(action["id"])
                or action.get("exact_target_from")
                != resources[resource_id]["target_from"]
            ):
                raise AcceptanceConfigError("configuration_error")
    return scenario_id


def _items_fingerprint(items: list[Any]) -> str:
    canonical_items = sorted(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in items
    )
    return hashlib.sha256(
        json.dumps(canonical_items, separators=(",", ":")).encode()
    ).hexdigest()


def _build_operation_bindings(
    api_inventory: dict[str, Any],
    runtime_inventory: dict[str, Any],
    expected_dir: Path,
) -> dict[str, tuple[str, str]]:
    """Bind each executable HTTP declaration to one reviewed operation."""

    result: dict[str, tuple[str, str]] = {}
    surfaces = api_inventory.get("surfaces")
    if not isinstance(surfaces, list):
        raise AcceptanceConfigError("configuration_error")
    for surface in surfaces:
        if not isinstance(surface, dict) or surface.get("kind") != "rest":
            continue
        surface_id = _plain_id(surface.get("id"))
        expected_name = surface.get("expected_manifest")
        if (
            not isinstance(expected_name, str)
            or Path(expected_name).name != expected_name
        ):
            raise AcceptanceConfigError("configuration_error")
        expected = load_json(expected_dir / expected_name)
        operations = expected.get("operations")
        if not isinstance(operations, list):
            raise AcceptanceConfigError("configuration_error")
        for operation in operations:
            if not isinstance(operation, dict):
                raise AcceptanceConfigError("configuration_error")
            method = operation.get("method")
            path = operation.get("path")
            if not isinstance(method, str) or not isinstance(path, str):
                raise AcceptanceConfigError("configuration_error")
            ref = f"rest:{surface_id}:{method}:{path}"
            if ref in result:
                raise AcceptanceConfigError("configuration_error")
            result[ref] = (method, path)

    services = runtime_inventory.get("services")
    if not isinstance(services, list):
        raise AcceptanceConfigError("configuration_error")
    for service in services:
        if not isinstance(service, dict):
            raise AcceptanceConfigError("configuration_error")
        service_id = _plain_id(service.get("id"))
        probes = service.get("probes")
        if not isinstance(probes, list):
            raise AcceptanceConfigError("configuration_error")
        for probe in probes:
            if not isinstance(probe, dict):
                raise AcceptanceConfigError("configuration_error")
            probe_id = _plain_id(probe.get("id"))
            method = probe.get("method", "GET")
            path = probe.get("path")
            if not isinstance(method, str) or not isinstance(path, str):
                raise AcceptanceConfigError("configuration_error")
            ref = f"runtime:{service_id}:{probe_id}"
            if ref in result:
                raise AcceptanceConfigError("configuration_error")
            result[ref] = (method, path)
    return result


def _validate_coverage(
    coverage: Any,
    *,
    manifest: dict[str, Any],
    api_inventory: dict[str, Any],
    expected_dir: Path,
    scenarios: dict[str, set[str]],
    blockers: dict[str, dict[str, Any]],
) -> dict[str, int]:
    if not isinstance(coverage, dict):
        raise AcceptanceConfigError("configuration_error")
    blocker_ids = set(blockers)

    features = manifest.get("features")
    skills = manifest.get("skills")
    surfaces = api_inventory.get("surfaces")
    if (
        not isinstance(features, list)
        or not isinstance(skills, list)
        or not isinstance(surfaces, list)
    ):
        raise AcceptanceConfigError("configuration_error")

    feature_by_id = {_plain_id(item.get("id")): item for item in features}
    if len(feature_by_id) != len(features):
        raise AcceptanceConfigError("configuration_error")
    feature_records = coverage.get("features")
    if not isinstance(feature_records, list):
        raise AcceptanceConfigError("configuration_error")
    seen_features: set[str] = set()
    for record in feature_records:
        if not isinstance(record, dict):
            raise AcceptanceConfigError("configuration_error")
        feature_id = _plain_id(record.get("feature_id"))
        if feature_id in seen_features or feature_id not in feature_by_id:
            raise AcceptanceConfigError("configuration_error")
        seen_features.add(feature_id)
        if record.get("selector") != "all-current-capabilities":
            raise AcceptanceConfigError("configuration_error")
        scenario_ids = set(_unique_ids(record.get("scenario_ids")))
        if not scenario_ids <= set(scenarios):
            raise AcceptanceConfigError("configuration_error")
        record_blockers = set(_unique_ids(record.get("blocker_ids")))
        if (
            not record_blockers <= blocker_ids
            or "phase1-execution-disabled" not in record_blockers
        ):
            raise AcceptanceConfigError("configuration_error")
        assigned_blockers = set().union(*(scenarios[item] for item in scenario_ids))
        if not record_blockers <= assigned_blockers:
            raise AcceptanceConfigError("configuration_error")
        feature = feature_by_id[feature_id]
        external = feature.get("acceptance_class") == "external_optional"
        expected_disposition = "external-optional" if external else "planned"
        if record.get("disposition") != expected_disposition:
            raise AcceptanceConfigError("configuration_error")
        if external:
            if not any(
                blockers[item]["scope"] == "external" for item in record_blockers
            ):
                raise AcceptanceConfigError("configuration_error")
        elif feature.get("runtime_state") != "passed_current" and not (
            record_blockers - {"phase1-execution-disabled"}
        ):
            raise AcceptanceConfigError("configuration_error")
        advertised = feature.get("advertised")
        if (
            not isinstance(advertised, list)
            or not advertised
            or any(not isinstance(item, str) or not item for item in advertised)
            or len(advertised) != len(set(advertised))
            or record.get("expected_capability_count") != len(advertised)
            or record.get("capabilities_sha256") != _items_fingerprint(advertised)
        ):
            raise AcceptanceConfigError("configuration_error")
    if seen_features != set(feature_by_id):
        raise AcceptanceConfigError("configuration_error")

    skill_by_id = {_plain_id(item.get("id")): item for item in skills}
    if len(skill_by_id) != len(skills):
        raise AcceptanceConfigError("configuration_error")
    skill_records = coverage.get("skills")
    if not isinstance(skill_records, list):
        raise AcceptanceConfigError("configuration_error")
    seen_skills: set[str] = set()
    for record in skill_records:
        if not isinstance(record, dict):
            raise AcceptanceConfigError("configuration_error")
        skill_id = _plain_id(record.get("skill_id"))
        if skill_id in seen_skills or skill_id not in skill_by_id:
            raise AcceptanceConfigError("configuration_error")
        seen_skills.add(skill_id)
        if record.get("selector") != "complete-skill-workflow":
            raise AcceptanceConfigError("configuration_error")
        scenario_id = record.get("scenario_id")
        if scenario_id not in scenarios:
            raise AcceptanceConfigError("configuration_error")
        record_blockers = set(_unique_ids(record.get("blocker_ids")))
        if (
            not record_blockers <= blocker_ids
            or "phase1-execution-disabled" not in record_blockers
        ):
            raise AcceptanceConfigError("configuration_error")
        if not record_blockers <= scenarios[scenario_id]:
            raise AcceptanceConfigError("configuration_error")
        if skill_by_id[skill_id].get("runtime_state") != "passed_current" and not (
            record_blockers - {"phase1-execution-disabled"}
        ):
            raise AcceptanceConfigError("configuration_error")
    if seen_skills != set(skill_by_id):
        raise AcceptanceConfigError("configuration_error")

    surface_by_id = {_plain_id(item.get("id")): item for item in surfaces}
    if len(surface_by_id) != len(surfaces):
        raise AcceptanceConfigError("configuration_error")
    surface_records = coverage.get("api_surfaces")
    if not isinstance(surface_records, list):
        raise AcceptanceConfigError("configuration_error")
    seen_surfaces: set[str] = set()
    rest_count = 0
    tool_count = 0
    prompt_count = 0
    for record in surface_records:
        if not isinstance(record, dict):
            raise AcceptanceConfigError("configuration_error")
        surface_id = _plain_id(record.get("surface_id"))
        if surface_id in seen_surfaces or surface_id not in surface_by_id:
            raise AcceptanceConfigError("configuration_error")
        seen_surfaces.add(surface_id)
        surface = surface_by_id[surface_id]
        selector = (
            "all-current-operations"
            if surface.get("kind") == "rest"
            else "all-current-tools-and-prompts"
        )
        scenario_id = record.get("scenario_id")
        if record.get("selector") != selector or scenario_id not in scenarios:
            raise AcceptanceConfigError("configuration_error")
        record_blockers = set(_unique_ids(record.get("blocker_ids")))
        if (
            not record_blockers <= blocker_ids
            or "phase1-execution-disabled" not in record_blockers
            or "operation-classification-required" not in record_blockers
        ):
            raise AcceptanceConfigError("configuration_error")
        if not record_blockers <= scenarios[scenario_id]:
            raise AcceptanceConfigError("configuration_error")
        expected_name = surface.get("expected_manifest")
        if (
            not isinstance(expected_name, str)
            or Path(expected_name).name != expected_name
        ):
            raise AcceptanceConfigError("configuration_error")
        expected = load_json(expected_dir / expected_name)
        if expected.get("surface") != surface_id or expected.get("kind") != surface.get(
            "kind"
        ):
            raise AcceptanceConfigError("configuration_error")
        if surface["kind"] == "rest":
            operations = expected.get("operations")
            if not isinstance(operations, list) or len(operations) != surface.get(
                "expected_operation_count"
            ):
                raise AcceptanceConfigError("configuration_error")
            if record.get("expected_item_count") != len(operations) or record.get(
                "items_sha256"
            ) != _items_fingerprint(operations):
                raise AcceptanceConfigError("configuration_error")
            rest_count += len(operations)
        elif surface["kind"] == "mcp":
            tools = expected.get("tools")
            if not isinstance(tools, list) or len(tools) != surface.get(
                "expected_tool_count"
            ):
                raise AcceptanceConfigError("configuration_error")
            if record.get("expected_item_count") != len(tools) or record.get(
                "items_sha256"
            ) != _items_fingerprint(tools):
                raise AcceptanceConfigError("configuration_error")
            tool_count += len(tools)
            prompts = expected.get("prompts")
            prompt_names = (
                sorted(item.get("name") for item in prompts)
                if isinstance(prompts, list)
                and all(
                    isinstance(item, dict) and isinstance(item.get("name"), str)
                    for item in prompts
                )
                else None
            )
            if (
                prompt_names is None
                or len(prompt_names) != len(set(prompt_names))
                or len(prompts) != surface.get("expected_prompt_count")
                or expected.get("prompt_count") != len(prompts)
                or record.get("expected_prompt_count") != len(prompts)
                or record.get("prompt_names") != prompt_names
                or record.get("prompts_sha256") != _items_fingerprint(prompts)
            ):
                raise AcceptanceConfigError("configuration_error")
            prompt_count += len(prompts)
        else:
            raise AcceptanceConfigError("configuration_error")
    if seen_surfaces != set(surface_by_id):
        raise AcceptanceConfigError("configuration_error")
    totals = api_inventory.get("expected_totals")
    if (
        not isinstance(totals, dict)
        or rest_count != totals.get("declared_rest_operations")
        or tool_count != totals.get("mcp_tools")
        or prompt_count != totals.get("mcp_prompts")
    ):
        raise AcceptanceConfigError("configuration_error")
    return {
        "api_surfaces": len(seen_surfaces),
        "feature_capabilities": sum(len(item["advertised"]) for item in features),
        "feature_families": len(seen_features),
        "mcp_prompts": prompt_count,
        "mcp_tools": tool_count,
        "rest_operations": rest_count,
        "skills": len(seen_skills),
    }


def validate_inventory(
    inventory: dict[str, Any],
    fixture_catalog: dict[str, Any],
    manifest: dict[str, Any],
    api_inventory: dict[str, Any],
    expected_dir: Path,
    runtime_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if inventory.get("schema_version") != 1 or inventory.get("mode") != "plan-only":
        raise AcceptanceConfigError("configuration_error")
    if inventory.get("execution_enabled") is not False:
        raise AcceptanceConfigError("configuration_error")
    fixture_by_id = validate_fixture_catalog(fixture_catalog)
    policies = inventory.get("policies")
    if not isinstance(policies, dict):
        raise AcceptanceConfigError("configuration_error")
    limits = _validate_transport_policy(policies.get("transport"))
    if runtime_inventory is None:
        runtime_inventory = load_json(DEFAULT_RUNTIME_INVENTORY)
    operation_bindings = _build_operation_bindings(
        api_inventory, runtime_inventory, expected_dir
    )
    namespace_policy = policies.get("namespace")
    if namespace_policy != {
        "prefix": "thor-vss-accept-",
        "resource_template": "${namespace}-<resource>",
        "owned_resources_only": True,
        "max_length": 63,
    }:
        raise AcceptanceConfigError("configuration_error")
    ledger_policy = policies.get("ledger")
    if ledger_policy != {
        "format": "jsonl-sha256-chain-v1",
        "mode": "0600",
        "append_only_writes": True,
        "fsync_each_record": True,
        "refuse_symlink_or_hardlink": True,
    }:
        raise AcceptanceConfigError("configuration_error")
    cleanup_policy = policies.get("cleanup")
    if cleanup_policy != {
        "order": "strict-lifo",
        "exact_created_target_only": True,
        "record_every_attempt": True,
        "stop_on_top_failure": True,
    }:
        raise AcceptanceConfigError("configuration_error")
    _validate_safety_classes(policies.get("safety_classes"))

    blocker_values = inventory.get("blockers")
    if not isinstance(blocker_values, list) or not blocker_values:
        raise AcceptanceConfigError("configuration_error")
    blockers: dict[str, dict[str, Any]] = {}
    for blocker in blocker_values:
        if not isinstance(blocker, dict):
            raise AcceptanceConfigError("configuration_error")
        blocker_id = _plain_id(blocker.get("id"))
        if blocker_id in blockers or blocker.get("scope") not in {
            "asset",
            "capacity",
            "classification",
            "external",
            "phase0",
            "runtime",
        }:
            raise AcceptanceConfigError("configuration_error")
        if not isinstance(blocker.get("reason"), str) or not blocker["reason"]:
            raise AcceptanceConfigError("configuration_error")
        blockers[blocker_id] = blocker
    if blockers.get("phase1-execution-disabled", {}).get("scope") != "phase0":
        raise AcceptanceConfigError("configuration_error")
    if (
        blockers.get("operation-classification-required", {}).get("scope")
        != "classification"
    ):
        raise AcceptanceConfigError("configuration_error")

    scenarios_value = inventory.get("scenarios")
    if not isinstance(scenarios_value, list) or not scenarios_value:
        raise AcceptanceConfigError("configuration_error")
    scenarios: dict[str, set[str]] = {}
    for scenario in scenarios_value:
        scenario_id = _validate_scenario(
            scenario,
            blocker_ids=set(blockers),
            fixture_ids=set(fixture_by_id),
            limits=limits,
            operation_bindings=operation_bindings,
        )
        if scenario_id in scenarios:
            raise AcceptanceConfigError("configuration_error")
        scenarios[scenario_id] = set(scenario["blocker_ids"])
    counts = _validate_coverage(
        inventory.get("coverage"),
        manifest=manifest,
        api_inventory=api_inventory,
        expected_dir=expected_dir,
        scenarios=scenarios,
        blockers=blockers,
    )
    return {
        "blocker_count": len(blockers),
        "counts": counts,
        "fixture_count": len(fixture_by_id),
        "scenario_count": len(scenarios),
    }


def compile_plan(
    *,
    inventory_path: Path = DEFAULT_INVENTORY,
    fixtures_path: Path = DEFAULT_FIXTURES,
    manifest_path: Path = DEFAULT_PARITY_MANIFEST,
    api_inventory_path: Path = DEFAULT_API_INVENTORY,
    runtime_inventory_path: Path = DEFAULT_RUNTIME_INVENTORY,
    phase1_inventory_path: Path = DEFAULT_PHASE1_INVENTORY,
    expected_dir: Path = DEFAULT_EXPECTED_DIR,
    run_id: str = "plan-000001",
) -> dict[str, Any]:
    namespace = build_namespace(run_id)
    inventory = load_json(inventory_path)
    fixtures = load_json(fixtures_path)
    manifest = load_json(manifest_path)
    api_inventory = load_json(api_inventory_path)
    runtime_inventory = load_json(runtime_inventory_path)
    phase1_inventory = load_json(phase1_inventory_path)
    validation = validate_inventory(
        inventory,
        fixtures,
        manifest,
        api_inventory,
        expected_dir,
        runtime_inventory,
    )
    scenario_plans = []
    for scenario in inventory["scenarios"]:
        scenario_plans.append(
            {
                "action_count": len(scenario["actions"]),
                "blocker_ids": sorted(scenario["blocker_ids"]),
                "cleanup_order": list(scenario["cleanup_order"]),
                "fixture_ids": sorted(scenario["fixture_ids"]),
                "id": scenario["id"],
                "owned_resource_count": len(scenario["owned_resources"]),
            }
        )
    source_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "api": api_inventory,
                "fixtures": fixtures,
                "inventory": inventory,
                "manifest": manifest,
                "phase1": phase1_inventory,
                "runtime": runtime_inventory,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "coverage": validation["counts"],
        "execution_enabled": False,
        "fixture_count": validation["fixture_count"],
        "mode": "plan-only",
        "namespace": namespace,
        "network_requests_made": 0,
        "processes_started": 0,
        "resources_mutated": 0,
        "run_id": run_id,
        "safety": {
            "ambient_proxies": False,
            "container_lifecycle": False,
            "follow_redirects": False,
            "loopback_only": True,
            "strict_lifo_cleanup": True,
        },
        "scenario_count": validation["scenario_count"],
        "scenarios": scenario_plans,
        "schema_version": 1,
        "source_fingerprint": source_fingerprint,
        "tier": "stateful-acceptance-phase0",
    }


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_ledger_records(raw: bytes) -> tuple[int, str]:
    if len(raw) > MAX_LEDGER_BYTES:
        raise LedgerError("ledger_too_large")
    if not raw:
        return 0, "0" * 64
    if not raw.endswith(b"\n"):
        raise LedgerError("invalid_ledger")
    previous = "0" * 64
    sequence = 0
    ledger_run_id: str | None = None
    ledger_namespace: str | None = None
    previous_timestamp: str | None = None
    active_resources: dict[str, str] = {}
    creation_order: list[str] = []
    cleanup_started: set[str] = set()
    finished = False
    for line in raw.splitlines():
        if not line or len(line) > MAX_LEDGER_RECORD_BYTES:
            raise LedgerError("invalid_ledger")
        try:
            record = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, AcceptanceConfigError) as exc:
            raise LedgerError("invalid_ledger") from exc
        if not isinstance(record, dict):
            raise LedgerError("invalid_ledger")
        digest = record.get("record_sha256")
        event = record.get("event")
        resource_event = event in RESOURCE_LEDGER_EVENTS
        required_keys = {
            "action_id",
            "event",
            "namespace",
            "previous_sha256",
            "record_sha256",
            "recorded_at",
            "run_id",
            "scenario_id",
            "schema_version",
            "sequence",
        }
        if resource_event:
            required_keys |= {"resource_id", "target_sha256"}
        if set(record) != required_keys:
            raise LedgerError("invalid_ledger")
        try:
            run_id = _safe_ledger_value(record.get("run_id"), identifier=True)
            namespace = _safe_ledger_value(record.get("namespace"))
            _safe_ledger_value(record.get("scenario_id"), identifier=True)
            _safe_ledger_value(record.get("action_id"), identifier=True)
        except LedgerError as exc:
            raise LedgerError("invalid_ledger") from exc
        try:
            expected_namespace = build_namespace(run_id)
        except AcceptanceConfigError as exc:
            raise LedgerError("invalid_ledger") from exc
        if namespace != expected_namespace:
            raise LedgerError("invalid_ledger")
        timestamp = record.get("recorded_at")
        if not isinstance(timestamp, str) or not UTC_RE.fullmatch(timestamp):
            raise LedgerError("invalid_ledger")
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise LedgerError("invalid_ledger")
        previous_timestamp = timestamp
        if ledger_run_id is None:
            ledger_run_id = run_id
            ledger_namespace = namespace
        elif run_id != ledger_run_id or namespace != ledger_namespace:
            raise LedgerError("invalid_ledger")
        if event not in LEDGER_EVENTS or finished:
            raise LedgerError("invalid_ledger")
        unsigned = dict(record)
        unsigned.pop("record_sha256")
        if (
            record.get("schema_version") != 1
            or isinstance(record.get("sequence"), bool)
            or record.get("sequence") != sequence + 1
            or record.get("previous_sha256") != previous
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            or hashlib.sha256(_canonical_json(unsigned)).hexdigest() != digest
        ):
            raise LedgerError("invalid_ledger")
        if sequence == 0 and event != "run-started":
            raise LedgerError("invalid_ledger")
        if sequence > 0 and event == "run-started":
            raise LedgerError("invalid_ledger")
        if resource_event:
            try:
                resource_id = _safe_ledger_value(
                    record.get("resource_id"), identifier=True
                )
            except LedgerError as exc:
                raise LedgerError("invalid_ledger") from exc
            target_sha256 = record.get("target_sha256")
            if not isinstance(target_sha256, str) or not SHA256_RE.fullmatch(
                target_sha256
            ):
                raise LedgerError("invalid_ledger")
            if event == "created":
                if resource_id in active_resources or cleanup_started:
                    raise LedgerError("invalid_ledger")
                active_resources[resource_id] = target_sha256
                creation_order.append(resource_id)
            else:
                if active_resources.get(resource_id) != target_sha256:
                    raise LedgerError("invalid_ledger")
                if event == "updated" and cleanup_started:
                    raise LedgerError("invalid_ledger")
                if event == "cleanup-started":
                    if (
                        not creation_order
                        or creation_order[-1] != resource_id
                        or resource_id in cleanup_started
                    ):
                        raise LedgerError("invalid_ledger")
                    cleanup_started.add(resource_id)
                elif event == "cleanup-failed":
                    if resource_id not in cleanup_started:
                        raise LedgerError("invalid_ledger")
                    cleanup_started.remove(resource_id)
                elif event == "cleanup-succeeded":
                    if resource_id not in cleanup_started:
                        raise LedgerError("invalid_ledger")
                    cleanup_started.remove(resource_id)
                    creation_order.pop()
                    del active_resources[resource_id]
        elif event == "run-finished":
            if active_resources or cleanup_started:
                raise LedgerError("invalid_ledger")
            finished = True
        previous = digest
        sequence += 1
    return sequence, previous


def _safe_ledger_value(value: Any, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise LedgerError("invalid_record")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise LedgerError("invalid_record")
    if identifier and not PLAIN_ID_RE.fullmatch(value):
        raise LedgerError("invalid_record")
    return value


def append_ledger_event(
    path: Path,
    *,
    run_id: str,
    namespace: str,
    event: str,
    scenario_id: str,
    action_id: str,
    resource_id: str | None = None,
    target_sha256: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Append one hash-chained event to an exact mode-0600 regular file."""

    try:
        expected_namespace = build_namespace(run_id)
    except AcceptanceConfigError as exc:
        raise LedgerError("invalid_record") from exc
    if namespace != expected_namespace or event not in LEDGER_EVENTS:
        raise LedgerError("invalid_record")
    scenario_id = _safe_ledger_value(scenario_id, identifier=True)
    action_id = _safe_ledger_value(action_id, identifier=True)
    if event in RESOURCE_LEDGER_EVENTS:
        if resource_id is None or target_sha256 is None:
            raise LedgerError("invalid_record")
        resource_id = _safe_ledger_value(resource_id, identifier=True)
        if not SHA256_RE.fullmatch(target_sha256):
            raise LedgerError("invalid_record")
    elif resource_id is not None or target_sha256 is not None:
        raise LedgerError("invalid_record")
    timestamp = recorded_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not UTC_RE.fullmatch(timestamp):
        raise LedgerError("invalid_record")

    path = Path(path)
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise LedgerError("unsafe_ledger_path") from exc
    if parent != path.parent.absolute() or path.name in {"", ".", ".."}:
        raise LedgerError("unsafe_ledger_path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = (
        os.O_RDWR
        | os.O_APPEND
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )
    created = False
    try:
        try:
            descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        except FileExistsError:
            descriptor = os.open(path, flags)
    except OSError as exc:
        raise LedgerError("unsafe_ledger_path") from exc

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        if created:
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
        ):
            raise LedgerError("unsafe_ledger_file")
        if metadata.st_size > MAX_LEDGER_BYTES:
            raise LedgerError("ledger_too_large")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                raise LedgerError("invalid_ledger")
            chunks.append(chunk)
            remaining -= len(chunk)
        sequence, previous = _validate_ledger_records(b"".join(chunks))
        record: dict[str, Any] = {
            "action_id": action_id,
            "event": event,
            "namespace": namespace,
            "previous_sha256": previous,
            "recorded_at": timestamp,
            "run_id": run_id,
            "scenario_id": scenario_id,
            "schema_version": 1,
            "sequence": sequence + 1,
        }
        if resource_id is not None and target_sha256 is not None:
            record["resource_id"] = resource_id
            record["target_sha256"] = target_sha256
        record["record_sha256"] = hashlib.sha256(_canonical_json(record)).hexdigest()
        line = _canonical_json(record) + b"\n"
        if len(line) > MAX_LEDGER_RECORD_BYTES:
            raise LedgerError("invalid_record")
        _validate_ledger_records(b"".join(chunks) + line)
        offset = 0
        while offset < len(line):
            written = os.write(descriptor, line[offset:])
            if written <= 0:
                raise LedgerError("short_write")
            offset += written
        os.fsync(descriptor)
        return record
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in {"execute", "recover"}:
        from acceptance_executor import main as executor_main

        return executor_main(argv)
    if argv and argv[0] == "plan":
        argv = argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PARITY_MANIFEST)
    parser.add_argument("--api-inventory", type=Path, default=DEFAULT_API_INVENTORY)
    parser.add_argument(
        "--runtime-inventory", type=Path, default=DEFAULT_RUNTIME_INVENTORY
    )
    parser.add_argument(
        "--phase1-inventory", type=Path, default=DEFAULT_PHASE1_INVENTORY
    )
    parser.add_argument("--expected-dir", type=Path, default=DEFAULT_EXPECTED_DIR)
    parser.add_argument("--run-id", default="plan-000001")
    args = parser.parse_args(argv)
    try:
        report = compile_plan(
            inventory_path=args.inventory,
            fixtures_path=args.fixtures,
            manifest_path=args.manifest,
            api_inventory_path=args.api_inventory,
            runtime_inventory_path=args.runtime_inventory,
            phase1_inventory_path=args.phase1_inventory,
            expected_dir=args.expected_dir,
            run_id=args.run_id,
        )
    except (
        AcceptanceConfigError,
        LedgerError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ):
        print(
            json.dumps(
                {
                    "error": "configuration_error",
                    "execution_enabled": False,
                    "mode": "plan-only",
                    "result": "fail",
                    "schema_version": 1,
                },
                sort_keys=True,
            )
        )
        return 1
    report["result"] = "pass"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
