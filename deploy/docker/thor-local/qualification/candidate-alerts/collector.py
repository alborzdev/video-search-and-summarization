#!/usr/bin/env python3
"""Offline-only candidate-alert completion evidence scaffold.

This module intentionally has no live execution command and opens no socket.
It validates the proposed two-fixture, terminal-result, bounded-query, and
ownership contracts using pure functions suitable for injected fakes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
TERMINAL_SCHEMA_PATH = HERE / "terminal-result.schema.json"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_MEDIA_BYTES = 64 * 1024 * 1024
PLAIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
UTC_TIMESTAMP = re.compile(
    r"(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-"
    r"(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:"
    r"[0-5]\d(?:\.\d{1,6})?Z\Z"
)


class ScaffoldError(RuntimeError):
    """Stable offline validation error."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ScaffoldError("canonicalization_failed") from exc


def _sha256(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise ScaffoldError("bytes_required")
    return hashlib.sha256(value).hexdigest()


def _strict_json_bytes(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ScaffoldError("duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _token: (_ for _ in ()).throw(
                ScaffoldError("non_finite_json")
            ),
        )
    except ScaffoldError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScaffoldError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ScaffoldError("json_object_required")
    return value


def _bounded_read(path: Path, maximum: int = MAX_SOURCE_BYTES) -> bytes:
    if type(maximum) is not int or not 1 <= maximum <= MAX_MEDIA_BYTES:
        raise ScaffoldError("invalid_read_bound")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScaffoldError("source_open_failed") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ScaffoldError("source_not_bounded_regular_file")
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
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise ScaffoldError("source_changed_during_read")
        return raw
    finally:
        os.close(descriptor)


def _json(path: Path) -> dict[str, Any]:
    return _strict_json_bytes(_bounded_read(path))


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: list(error.absolute_path),
        )
    except Exception as exc:
        raise ScaffoldError("schema_invalid") from exc
    if errors:
        raise ScaffoldError("schema_validation_failed")


def load_contract() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH)
    _validate(contract, _json(CONTRACT_SCHEMA_PATH))
    return contract


def _repo_path(relative: str) -> Path:
    if not isinstance(relative, str):
        raise ScaffoldError("invalid_source_path")
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ScaffoldError("invalid_source_path")
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ScaffoldError("source_symlink_rejected")
        except OSError as exc:
            raise ScaffoldError("source_missing") from exc
    return current


def validate_bound_accounting(contract: Mapping[str, Any]) -> dict[str, int]:
    bounds = contract.get("execution_bounds")
    if not isinstance(bounds, dict):
        raise ScaffoldError("bounds_missing")
    requests = bounds.get("request_accounting")
    actions = bounds.get("action_accounting")
    if not isinstance(requests, dict) or not isinstance(actions, dict):
        raise ScaffoldError("accounting_missing")
    calculated_requests = sum(requests.values())
    calculated_actions = sum(actions.values())
    cleanup_requests = requests.get(
        "config_cleanup_and_postcondition", 0
    ) + requests.get("two_sink_document_cleanup_and_postconditions", 0)
    cleanup_actions = actions.get("cleanup_and_postconditions")
    if (
        calculated_requests != bounds.get("max_requests")
        or calculated_actions != bounds.get("max_actions")
        or cleanup_requests != bounds.get("cleanup_reserve_requests")
        or cleanup_actions != bounds.get("cleanup_reserve_actions")
        or requests.get("polls") != bounds.get("max_poll_requests")
    ):
        raise ScaffoldError("bound_accounting_mismatch")
    return {
        "max_requests": calculated_requests,
        "max_actions": calculated_actions,
        "cleanup_reserve_requests": cleanup_requests,
        "cleanup_reserve_actions": cleanup_actions,
    }


def validate_fixture_descriptors(
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    fixtures = contract.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 2:
        raise ScaffoldError("fixture_pair_required")
    loaded: list[dict[str, Any]] = []
    identities: set[str] = set()
    verdicts: set[str] = set()
    for declared in fixtures:
        if not isinstance(declared, dict):
            raise ScaffoldError("invalid_fixture_declaration")
        raw = _bounded_read(_repo_path(declared.get("descriptor_path")))
        if _sha256(raw) != declared.get("descriptor_sha256"):
            raise ScaffoldError("fixture_descriptor_digest_mismatch")
        descriptor = _strict_json_bytes(raw)
        required = {
            "fixture_id",
            "materialized_media",
            "media_type",
            "semantic_scene",
            "visible_identity_token",
            "expected_verdict",
            "expected_sink_delivery",
        }
        if (
            set(descriptor) != required
            or descriptor["fixture_id"] != declared.get("fixture_id")
            or descriptor["visible_identity_token"]
            != declared.get("visible_identity_token")
            or descriptor["expected_verdict"] != declared.get("expected_verdict")
            or descriptor["materialized_media"] is not False
            or descriptor["expected_sink_delivery"] is not True
            or descriptor["media_type"] != "video"
        ):
            raise ScaffoldError("fixture_descriptor_identity_mismatch")
        identities.add(descriptor["fixture_id"])
        verdicts.add(descriptor["expected_verdict"])
        loaded.append(descriptor)
    if identities != {
        "candidate-alert-positive-v1",
        "candidate-alert-negative-v1",
    } or verdicts != {"confirmed", "rejected"}:
        raise ScaffoldError("fixture_boundary_pair_mismatch")
    return loaded[0], loaded[1]


@dataclass(frozen=True)
class FixtureIdentity:
    """Run-bound identity for one future materialized media artifact."""

    fixture_id: str
    descriptor_sha256: str
    media_sha256: str
    media_bytes: int
    visible_identity_token_sha256: str
    fixture_server_identity_sha256: str
    capability_path: str

    @classmethod
    def build(
        cls,
        *,
        run_id: str,
        fixture: Mapping[str, Any],
        descriptor_sha256: str,
        media: bytes,
        pair_descriptor_sha256: Sequence[str],
    ) -> "FixtureIdentity":
        if not isinstance(run_id, str) or PLAIN_ID.fullmatch(run_id) is None:
            raise ScaffoldError("invalid_run_id")
        fixture_id = fixture.get("fixture_id")
        token = fixture.get("visible_identity_token")
        if (
            not isinstance(fixture_id, str)
            or PLAIN_ID.fullmatch(fixture_id) is None
            or not isinstance(token, str)
            or not token
            or SHA256.fullmatch(descriptor_sha256) is None
            or not isinstance(media, bytes)
            or not 0 < len(media) <= MAX_MEDIA_BYTES
            or len(pair_descriptor_sha256) != 2
            or any(SHA256.fullmatch(value) is None for value in pair_descriptor_sha256)
        ):
            raise ScaffoldError("invalid_fixture_identity_input")
        media_sha = _sha256(media)
        server_sha = _sha256(
            _canonical_bytes(
                {
                    "fixture_descriptors": sorted(pair_descriptor_sha256),
                    "run_id": run_id,
                    "transport": "numeric-loopback-http",
                }
            )
        )
        capability_token = _sha256(
            _canonical_bytes(
                {
                    "fixture_id": fixture_id,
                    "media_sha256": media_sha,
                    "run_id": run_id,
                    "server_sha256": server_sha,
                }
            )
        )[:32]
        capability_path = (
            f"/vss-candidate-fixtures/{capability_token}/{fixture_id}/{media_sha}.mp4"
        )
        return cls(
            fixture_id=fixture_id,
            descriptor_sha256=descriptor_sha256,
            media_sha256=media_sha,
            media_bytes=len(media),
            visible_identity_token_sha256=_sha256(token.encode("utf-8")),
            fixture_server_identity_sha256=server_sha,
            capability_path=capability_path,
        )


def canonical_incident_query(
    *,
    sensor_id: str,
    category: str,
    start_time: str,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Build the one admitted filtered incident-query path.

    Values are scalar, bounded, and encoded in a fixed order. This does not
    perform I/O; live transport integration is an explicit blocker.
    """
    for value in (sensor_id, category):
        if not isinstance(value, str) or PLAIN_ID.fullmatch(value) is None:
            raise ScaffoldError("invalid_query_identity")
    if not isinstance(start_time, str) or UTC_TIMESTAMP.fullmatch(start_time) is None:
        raise ScaffoldError("invalid_query_timestamp")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ScaffoldError("invalid_query_limit")
    if type(offset) is not int or offset != 0:
        raise ScaffoldError("invalid_query_offset")
    query = urlencode(
        [
            ("sensor_id", sensor_id),
            ("category", category),
            ("start_time", start_time),
            ("limit", str(limit)),
            ("offset", "0"),
        ],
        doseq=False,
        safe="",
    )
    path = f"/api/v1/realtime/incidents?{query}"
    if len(path.encode("ascii")) > 1024:
        raise ScaffoldError("query_too_large")
    return path


def validate_terminal_receipt(
    receipt: Mapping[str, Any],
    *,
    fixture: FixtureIdentity,
    expected_verdict: str,
    correlation_id: str,
    run_marker: str,
    allowed_sink: str,
) -> None:
    """Validate schema plus cross-object identity and semantic bindings."""
    if not isinstance(receipt, dict):
        raise ScaffoldError("terminal_receipt_object_required")
    _validate(receipt, _json(TERMINAL_SCHEMA_PATH))
    if (
        not isinstance(correlation_id, str)
        or PLAIN_ID.fullmatch(correlation_id) is None
        or not isinstance(run_marker, str)
        or PLAIN_ID.fullmatch(run_marker) is None
        or expected_verdict not in {"confirmed", "rejected"}
        or allowed_sink not in {"elasticsearch", "kafka"}
    ):
        raise ScaffoldError("invalid_terminal_expectation")
    fixture_receipt = receipt["fixture"]
    verification = receipt["verification"]
    media_fetch = receipt["media_fetch"]
    sink = receipt["sink"]
    expected = {
        "correlation_id_sha256": _sha256(correlation_id.encode("utf-8")),
        "fixture_id": fixture.fixture_id,
        "descriptor_sha256": fixture.descriptor_sha256,
        "media_sha256": fixture.media_sha256,
        "visible_identity_token_sha256": fixture.visible_identity_token_sha256,
        "fixture_server_identity_sha256": fixture.fixture_server_identity_sha256,
        "capability_path_sha256": _sha256(fixture.capability_path.encode("ascii")),
        "run_marker_sha256": _sha256(run_marker.encode("utf-8")),
    }
    if (
        receipt["state"] != "succeeded"
        or receipt["correlation_id_sha256"] != expected["correlation_id_sha256"]
        or fixture_receipt["fixture_id"] != expected["fixture_id"]
        or fixture_receipt["descriptor_sha256"] != expected["descriptor_sha256"]
        or fixture_receipt["media_sha256"] != expected["media_sha256"]
        or verification["verdict"] != expected_verdict
        or verification["response_code"] != 200
        or verification["visible_identity_token_sha256"]
        != expected["visible_identity_token_sha256"]
        or media_fetch["fixture_server_identity_sha256"]
        != expected["fixture_server_identity_sha256"]
        or media_fetch["capability_path_sha256"] != expected["capability_path_sha256"]
        or media_fetch["served_artifact_sha256"] != expected["media_sha256"]
        or sink["backend"] != allowed_sink
        or sink["delivered"] is not True
        or sink["run_marker_sha256"] != expected["run_marker_sha256"]
    ):
        raise ScaffoldError("terminal_receipt_identity_or_semantics_mismatch")


@dataclass(frozen=True)
class CleanupRecord:
    resource_type: str
    cleanup: str
    postcondition: str


class OfflineOwnershipLedger:
    """Pure fake-backed model of exact proof-gated LIFO ownership."""

    def __init__(self, registration_order: Sequence[str]) -> None:
        if len(registration_order) != 4 or len(set(registration_order)) != 4:
            raise ScaffoldError("invalid_registration_order")
        self._expected = tuple(registration_order)
        self._owned: list[str] = []
        self.transitions = 0

    @property
    def active_count(self) -> int:
        return len(self._owned)

    def register(self, resource_type: str, *, ownership_proven: bool) -> None:
        position = len(self._owned)
        if (
            ownership_proven is not True
            or position >= len(self._expected)
            or resource_type != self._expected[position]
        ):
            raise ScaffoldError("ownership_registration_rejected")
        self._owned.append(resource_type)

    def cleanup(
        self,
        action: Callable[[str], bool],
        postcondition: Callable[[str], bool],
    ) -> list[CleanupRecord]:
        records: list[CleanupRecord] = []
        while self._owned:
            resource = self._owned[-1]
            self.transitions += 2
            action_ok = action(resource) is True
            post_ok = action_ok and postcondition(resource) is True
            records.append(
                CleanupRecord(
                    resource_type=resource,
                    cleanup="pass" if action_ok else "fail",
                    postcondition="pass" if post_ok else "fail",
                )
            )
            if not post_ok:
                break
            self._owned.pop()
        return records


def reversibility_assessment(
    *,
    terminal_status_observed: bool,
    cancellation_available: bool,
    sink_receipt_observed: bool,
    exact_sink_cleanup_available: bool,
) -> dict[str, Any]:
    """Return the explicit late-publication decision; never infer safety."""
    late_publication_blocked = (
        terminal_status_observed is True
        and sink_receipt_observed is True
        and exact_sink_cleanup_available is True
    ) or (cancellation_available is True and exact_sink_cleanup_available is True)
    return {
        "promotion_eligible": False,
        "late_publication_possible": not late_publication_blocked,
        "blocker_id": (
            None if late_publication_blocked else "late-publication-not-reversible"
        ),
        "terminal_status_observed": terminal_status_observed is True,
        "cancellation_available": cancellation_available is True,
        "sink_receipt_observed": sink_receipt_observed is True,
        "exact_sink_cleanup_available": exact_sink_cleanup_available is True,
    }


def compile_plan() -> dict[str, Any]:
    contract = load_contract()
    fixtures = validate_fixture_descriptors(contract)
    bounds = validate_bound_accounting(contract)
    blockers = contract["blockers"]
    if (
        not blockers
        or any(item.get("active") is not True for item in blockers)
        or not any(
            item.get("blocker_id") == "late-publication-not-reversible"
            for item in blockers
        )
    ):
        raise ScaffoldError("required_blocker_missing")
    plan = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": contract["mode"],
        "status": "pass",
        "runtime_actions": 0,
        "default_execution_enabled": False,
        "promotion_eligible": False,
        "fixture_count": len(fixtures),
        "materialized_media_count": sum(
            item["materialized_media"] is True for item in fixtures
        ),
        "expected_verdicts": sorted(item["expected_verdict"] for item in fixtures),
        "bounds": bounds,
        "active_blockers": [item["blocker_id"] for item in blockers],
        "sink_lanes": contract["intended_runtime"]["sink_lanes"],
        "kafka_is_separate_lane": True,
        "contract_sha256": _sha256(_bounded_read(CONTRACT_PATH)),
        "terminal_schema_sha256": _sha256(_bounded_read(TERMINAL_SCHEMA_PATH)),
    }
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("plan",),
        default="plan",
        help="validate and print the inert offline plan (the only command)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        result = compile_plan()
    except ScaffoldError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
