#!/usr/bin/env python3
"""Compile an inert UI plan and validate only future sanitized evidence."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
EVIDENCE_SCHEMA_PATH = HERE / "evidence.schema.json"
MAX_BYTES = 5_000_000
EXPECTED_PACKAGE_HASHES = {
    "contract.json": "382cb4d3a3fb9d32cbba5566c63de59b70aa31f43e595bd2caa3c3ef9e43880f",
    "contract.schema.json": "df62697d72a3f40e70507f25f22627daede49b46fc305b523e691a0cd7b95cb4",
    "evidence.schema.json": "86a1feb196e2583d2a0a4a9ed42fafe766afd6960bba1911f13457686d71ea5b",
}
EXPECTED_REQUIREMENTS = [
    (
        "ui-alert-api",
        "runtime.ui.alerts-tab",
        "oracle.runtime.ui.alerts-tab",
        "ui-runtime.alerts",
    ),
    (
        "ui-search-api",
        "runtime.ui.search-tab",
        "oracle.runtime.ui.search-tab",
        "ui-runtime.search",
    ),
    (
        "ui-tiny-media",
        "runtime.ui.video-management-tab",
        "oracle.runtime.ui.video-management-tab",
        "ui-runtime.video-management",
    ),
]
EXPECTED_ENDPOINTS = ["ui-origin", "alerts-mock", "search-mock", "video-mock"]
EXPECTED_FIXTURES = [
    "ui-alert-api",
    "ui-search-api",
    "ui-tiny-mp4",
    "ui-tiny-mkv",
    "ui-tiny-rtsp-inventory",
]
SECRET_PATTERN = re.compile(
    r"(?i)(xox[a-z]-|AKIA[0-9A-Z]{12,}|bearer\s+|api[_-]?key\s*[:=]|"
    r"secret\s*[:=]|password\s*[:=]|-----BEGIN [A-Z ]+PRIVATE KEY-----|://)"
)


class UIContractError(RuntimeError):
    """A package identity, canonical binding, or evidence invariant failed."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha256(raw)


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise UIContractError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda token: (_ for _ in ()).throw(
                UIContractError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except UIContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UIContractError(f"invalid JSON in {label}") from exc
    if not isinstance(value, dict):
        raise UIContractError(f"JSON root must be an object in {label}")
    return value


def _read_regular(path: Path, expected_sha256: str | None, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise UIContractError(f"cannot read {label}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise UIContractError(f"{label} must be a regular non-symlink file")
        if before.st_size <= 0 or before.st_size > MAX_BYTES:
            raise UIContractError(f"{label} exceeds bounded size")
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_BYTES:
            chunk = os.read(descriptor, min(131072, MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        stable = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if len(raw) != before.st_size or any(
            getattr(before, field) != getattr(after, field) for field in stable
        ):
            raise UIContractError(f"{label} changed while being read")
    finally:
        os.close(descriptor)
    if expected_sha256 is not None and _sha256(raw) != expected_sha256:
        raise UIContractError(f"{label} raw SHA-256 mismatch")
    return raw


def _package_json(name: str) -> dict[str, Any]:
    return _strict_json(
        _read_regular(HERE / name, EXPECTED_PACKAGE_HASHES[name], name), name
    )


def _repo_json(root: Path, relative: str, expected_sha256: str) -> dict[str, Any]:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise UIContractError(f"unsafe source path: {relative}")
    root = root.resolve(strict=True)
    current = root
    for part in candidate.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise UIContractError(f"cannot resolve source: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise UIContractError(f"symlinked source path: {relative}")
    raw = _read_regular(current, expected_sha256, f"source {relative}")
    return _strict_json(raw, relative)


def _validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise UIContractError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            instance
        ),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise UIContractError(
            f"{label} schema violation at {location}: {error.message}"
        )


def _find_unique(value: Any, key: str, expected: str, label: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get(key) == expected:
                matches.append(item)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    if len(matches) != 1:
        raise UIContractError(f"expected one {label}, found {len(matches)}")
    return matches[0]


def _load_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _package_json("contract.json")
    contract_schema = _package_json("contract.schema.json")
    evidence_schema = _package_json("evidence.schema.json")
    _validate_schema(contract, contract_schema, "contract")
    try:
        Draft202012Validator.check_schema(evidence_schema)
    except SchemaError as exc:
        raise UIContractError("invalid evidence schema") from exc
    return contract, evidence_schema


def _assert_contract_policy(contract: dict[str, Any]) -> None:
    policy = contract["policy"]
    if policy["default_inert"] is not True:
        raise UIContractError("default-inert policy drifted")
    forbidden = [
        "runtime_executor_implemented",
        "browser_allowed",
        "api_calls_allowed",
        "network_allowed",
        "docker_allowed",
        "subprocess_allowed",
        "process_lifecycle_allowed",
        "writes_allowed",
        "downloads_allowed",
        "credentials_allowed",
        "can_promote_live_state",
    ]
    if any(policy[key] is not False for key in forbidden):
        raise UIContractError("inert no-execution policy drifted")
    if (
        policy["runtime_evidence"] != []
        or contract["current_state"]["runtime_evidence"] != []
    ):
        raise UIContractError("package must not contain runtime evidence")
    if contract["current_state"]["live_state_advanced"] is not False:
        raise UIContractError("package must not advance live state")
    gate = contract["future_execution_gate"]
    if gate["executor"] is not None or gate["approval_present_in_package"] is not False:
        raise UIContractError(
            "future execution must remain unimplemented and unapproved"
        )
    boundary = contract["future_network_boundary"]
    if boundary["host"] != "127.0.0.1" or boundary["dns_allowed"] is not False:
        raise UIContractError("numeric-loopback-only boundary drifted")
    if boundary["required_endpoint_ids"] != EXPECTED_ENDPOINTS:
        raise UIContractError("required UI/mock endpoint set drifted")
    if boundary["ui_origin_preexisting"] is not True:
        raise UIContractError("pre-existing UI origin boundary drifted")


def compile_plan(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Validate all locks and return a non-admitting, non-executing plan."""
    contract, _evidence_schema = _load_contract()
    _assert_contract_policy(contract)
    locks = contract["source_locks"]
    if len({row["path"] for row in locks}) != 4:
        raise UIContractError("exact four-source lock denominator drifted")
    loaded = {
        row["path"]: _repo_json(root, row["path"], row["raw_sha256"]) for row in locks
    }
    acceptance = loaded[
        "deploy/docker/thor-local/qualification/acceptance_inventory.json"
    ]
    capabilities = loaded["deploy/docker/thor-local/parity/official-capabilities.json"]
    oracles = loaded["deploy/docker/thor-local/parity/capability-oracles.json"]

    rows = contract["requirements"]
    identities = [
        (
            row["planning_requirement_id"],
            row["capability_id"],
            row["oracle_id"],
            row["case_id"],
        )
        for row in rows
    ]
    if identities != EXPECTED_REQUIREMENTS:
        raise UIContractError("exact three-row canonical binding drifted")
    if [
        row["fixture_id"] for row in contract["fixture_contracts"]
    ] != EXPECTED_FIXTURES:
        raise UIContractError("exact five-fixture denominator drifted")

    compiled_rows = []
    planning_rows = acceptance["wave3_contracts"]["planning_requirements"]
    for row in rows:
        planning_matches = [
            item
            for item in planning_rows
            if item.get("id") == row["planning_requirement_id"]
        ]
        if len(planning_matches) != 1:
            raise UIContractError("expected one top-level planning requirement")
        planning = planning_matches[0]
        if canonical_sha256(planning) != row["planning_requirement_sha256"]:
            raise UIContractError("planning requirement canonical identity drifted")
        if canonical_sha256(planning["payload"]) != row["planning_payload_sha256"]:
            raise UIContractError("planning payload canonical identity drifted")
        if planning["payload_canonical_sha256"] != row["planning_payload_sha256"]:
            raise UIContractError("planning payload self-lock drifted")
        if planning["owner_id"] != row["capability_id"]:
            raise UIContractError("planning owner binding drifted")
        if any(
            (
                planning["materialized"] is not False,
                planning["executor_ready"] is not False,
                planning["runtime_evidence"] != [],
            )
        ):
            raise UIContractError("planning requirement is no longer open/unexecuted")

        capability = _find_unique(
            capabilities,
            "id",
            row["capability_id"],
            f"capability {row['capability_id']}",
        )
        if canonical_sha256(capability) != row["capability_sha256"]:
            raise UIContractError("capability canonical identity drifted")
        if canonical_sha256(capability["contract"]) != row["contract_sha256"]:
            raise UIContractError("capability contract identity drifted")
        if (
            capability["thor_state"] != "partial"
            or capability["runtime_state"] != "not_qualified"
        ):
            raise UIContractError("capability is no longer partial/not-qualified")

        oracle = _find_unique(
            oracles, "oracle_id", row["oracle_id"], f"oracle {row['oracle_id']}"
        )
        if oracle["capability_id"] != row["capability_id"]:
            raise UIContractError("oracle capability binding drifted")
        if canonical_sha256(oracle) != row["oracle_sha256"]:
            raise UIContractError("oracle canonical identity drifted")
        if oracle["current_state"] != "open_unexecuted" or oracle["evidence"] != []:
            raise UIContractError("oracle is no longer open/unexecuted")
        if oracle["acceptance_readiness"]["classification"] != "planning_index_only":
            raise UIContractError("oracle planning-only classification drifted")

        compiled_rows.append(
            {
                "planning_requirement_id": row["planning_requirement_id"],
                "capability_id": row["capability_id"],
                "oracle_id": row["oracle_id"],
                "case_id": row["case_id"],
                "ui_endpoint_id": row["ui_endpoint_id"],
                "api_endpoint_id": row["endpoint_id"],
                "fixture_ids": row["fixture_ids"],
                "bounds": {
                    "max_duration_seconds": row["max_duration_seconds"],
                    "max_browser_actions": row["max_browser_actions"],
                    "max_api_exchanges": row["max_api_exchanges"],
                },
                "owned_resource_suffixes": row["owned_resource_suffixes"],
                "browser_rendering_required": True,
                "api_mock_transcript_alone_admissible": False,
                "current_state": "open_unexecuted",
            }
        )

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": "nonexecuting_future_evidence_plan",
        "source_lock_count": len(locks),
        "requirement_count": len(compiled_rows),
        "fixture_count": len(contract["fixture_contracts"]),
        "required_endpoint_ids": EXPECTED_ENDPOINTS,
        "requirements": compiled_rows,
        "resource_gates": contract["future_resource_gates"],
        "network_boundary": contract["future_network_boundary"],
        "cleanup_contract": contract["cleanup_contract"],
        "acknowledgement_required": contract["future_execution_gate"][
            "acknowledgement_token"
        ],
        "executor": None,
        "runtime_evidence": [],
        "live_state_advanced": False,
        "remaining_blocker": contract["current_state"]["remaining_blocker"],
    }


def _timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UIContractError(f"invalid timestamp: {label}") from exc
    if parsed.tzinfo is None:
        raise UIContractError(f"timestamp must be timezone-aware: {label}")
    return parsed


def _assert_no_sensitive_strings(value: Any) -> None:
    if isinstance(value, str):
        if SECRET_PATTERN.search(value):
            raise UIContractError("evidence contains a URL or secret-like string")
    elif isinstance(value, dict):
        for child in value.values():
            _assert_no_sensitive_strings(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_sensitive_strings(child)


def _assert_resource_gate(snapshot: dict[str, Any], label: str) -> None:
    reserve = (
        snapshot["memory_total_bytes"] * snapshot["memory_reserve_percent"] + 99
    ) // 100
    if snapshot["memory_available_bytes"] < snapshot["memory_required_bytes"] + reserve:
        raise UIContractError(f"{label} memory gate failed")
    if snapshot["disk_free_bytes"] < snapshot["disk_required_bytes"] + 1073741824:
        raise UIContractError(f"{label} disk gate failed")


def _expected_fixture_name(run_id: str, fixture_id: str, media_type: str) -> str:
    extension = {
        "application/json": "json",
        "video/mp4": "mp4",
        "video/x-matroska": "mkv",
    }[media_type]
    return f"{run_id}.{fixture_id}.{extension}"


def validate_evidence(
    evidence: dict[str, Any], root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Validate a future receipt without performing any browser/API operation."""
    contract, evidence_schema = _load_contract()
    plan = compile_plan(root)
    _validate_schema(evidence, evidence_schema, "evidence")
    _assert_no_sensitive_strings(evidence)
    if evidence["plan_sha256"] != canonical_sha256(plan):
        raise UIContractError("evidence plan identity mismatch")

    run_id = evidence["run_id"]
    authorization = evidence["authorization"]
    authorization_id = authorization["authorization_id"]
    target = evidence["target"]
    if authorization["run_id"] != run_id or authorization["scope"]["run_id"] != run_id:
        raise UIContractError("run identity is not authorization-bound")
    if authorization["scope"]["repository_commit"] != target["repository_commit"]:
        raise UIContractError("target commit is not authorization-bound")
    if authorization["scope_sha256"] != canonical_sha256(authorization["scope"]):
        raise UIContractError("authorization scope digest mismatch")

    endpoint_ids = [row["endpoint_id"] for row in evidence["endpoints"]]
    ports = [row["port"] for row in evidence["endpoints"]]
    if endpoint_ids != EXPECTED_ENDPOINTS or len(set(ports)) != 4:
        raise UIContractError("exact ordered four-endpoint loopback boundary failed")
    for endpoint in evidence["endpoints"]:
        if endpoint["scheme"] == "https" and endpoint["tls_verified"] is not True:
            raise UIContractError("HTTPS loopback endpoint lacks TLS verification")
        if endpoint["scheme"] == "http" and endpoint["tls_verified"] is not False:
            raise UIContractError("HTTP loopback endpoint has incoherent TLS evidence")

    fixtures = evidence["fixtures"]
    if [row["fixture_id"] for row in fixtures] != EXPECTED_FIXTURES:
        raise UIContractError("exact ordered five-fixture set failed")
    fixture_contracts = {
        row["fixture_id"]: row for row in contract["fixture_contracts"]
    }
    for fixture in fixtures:
        expected = fixture_contracts[fixture["fixture_id"]]
        if fixture["run_id"] != run_id:
            raise UIContractError("fixture is not run-bound")
        if (fixture["kind"], fixture["media_type"]) != (
            expected["kind"],
            expected["media_type"],
        ):
            raise UIContractError("fixture kind/media identity mismatch")
        if fixture["size_bytes"] > expected["max_size_bytes"]:
            raise UIContractError("fixture exceeds its exact size bound")
        if fixture["artifact_name"] != _expected_fixture_name(
            run_id, fixture["fixture_id"], fixture["media_type"]
        ):
            raise UIContractError("fixture artifact name is not exactly run-bound")
    if fixtures[2]["sha256"] == fixtures[3]["sha256"]:
        raise UIContractError("MP4 and MKV evidence must identify distinct artifacts")

    preflight = evidence["preflight"]
    postflight = evidence["postflight"]
    _assert_resource_gate(preflight, "preflight")
    _assert_resource_gate(postflight, "postflight")
    preflight_at = _timestamp(preflight["captured_at"], "preflight")
    granted_at = _timestamp(authorization["granted_at"], "authorization granted")
    expires_at = _timestamp(authorization["expires_at"], "authorization expires")
    if not granted_at <= preflight_at < expires_at:
        raise UIContractError("preflight is outside authorization window")

    requirements = contract["requirements"]
    cases = evidence["cases"]
    if [row["case_id"] for row in cases] != [row["case_id"] for row in requirements]:
        raise UIContractError("exact ordered three-case set failed")
    all_exchange_ids: set[str] = set()
    all_correlation_ids: set[str] = set()
    previous_finished = preflight_at
    created_by_cases: list[str] = []
    for case, expected in zip(cases, requirements, strict=True):
        identity = (
            case["planning_requirement_id"],
            case["capability_id"],
            case["oracle_id"],
            case["endpoint_id"],
        )
        expected_identity = (
            expected["planning_requirement_id"],
            expected["capability_id"],
            expected["oracle_id"],
            expected["endpoint_id"],
        )
        if identity != expected_identity:
            raise UIContractError("case canonical binding mismatch")
        if case["run_id"] != run_id or case["authorization_id"] != authorization_id:
            raise UIContractError("case is not run/authorization-bound")
        started = _timestamp(case["started_at"], f"{case['case_id']} start")
        finished = _timestamp(case["finished_at"], f"{case['case_id']} finish")
        if started < previous_finished or finished <= started:
            raise UIContractError("case timing is inverted or overlaps prior case")
        if (finished - started).total_seconds() > expected["max_duration_seconds"]:
            raise UIContractError("case duration exceeded")
        previous_finished = finished
        browser = case["browser"]
        if browser["ui_endpoint_id"] != expected["ui_endpoint_id"]:
            raise UIContractError("browser did not use the pinned UI origin")
        if browser["action_count"] > expected["max_browser_actions"]:
            raise UIContractError("browser action bound exceeded")
        if len(case["api_exchanges"]) > expected["max_api_exchanges"]:
            raise UIContractError("API exchange bound exceeded")
        for exchange in case["api_exchanges"]:
            if exchange["endpoint_id"] != expected["endpoint_id"]:
                raise UIContractError("API exchange escaped its case mock endpoint")
            if (
                exchange["run_id"] != run_id
                or exchange["authorization_id"] != authorization_id
            ):
                raise UIContractError("API exchange is not run/authorization-bound")
            requested = _timestamp(exchange["request_at"], "API request")
            responded = _timestamp(exchange["response_at"], "API response")
            if not started <= requested <= responded <= finished:
                raise UIContractError("API exchange timing escaped its case")
            if exchange["exchange_id"] in all_exchange_ids:
                raise UIContractError("duplicate API exchange identity")
            if exchange["correlation_id"] in all_correlation_ids:
                raise UIContractError("duplicate API correlation identity")
            all_exchange_ids.add(exchange["exchange_id"])
            all_correlation_ids.add(exchange["correlation_id"])
        expected_resources = [
            f"{run_id}.{suffix}" for suffix in expected["owned_resource_suffixes"]
        ]
        if case["observations"]["created_resource_ids"] != expected_resources:
            raise UIContractError("case-created resource set is not exact/run-owned")
        created_by_cases.extend(expected_resources)

        if case["case_id"] == "ui-runtime.alerts":
            observations = case["observations"]
            if (
                observations["friendly_catalog_rtsp_url_sha256"]
                != observations["friendly_submitted_sensor_sha256"]
            ):
                raise UIContractError(
                    "friendly sensor did not resolve to catalog RTSP URL"
                )
            if (
                observations["custom_sensor_name_sha256"]
                != observations["custom_submitted_sensor_sha256"]
            ):
                raise UIContractError("custom sensor was not forwarded as name only")
            if (
                observations["friendly_sensor_name_sha256"]
                == observations["friendly_catalog_rtsp_url_sha256"]
            ):
                raise UIContractError(
                    "friendly sensor name and RTSP URL evidence are ambiguous"
                )
        elif case["case_id"] == "ui-runtime.search":
            response_hashes = {
                exchange["response_body_sha256"] for exchange in case["api_exchanges"]
            }
            observations = case["observations"]
            if (
                not {
                    observations["frame_response_sha256"],
                    observations["picture_response_sha256"],
                }
                <= response_hashes
            ):
                raise UIContractError(
                    "image-search browser proof is not API-correlated"
                )
        else:
            progress = case["observations"]["upload_progress_percent"]
            if progress[0] != 0 or progress[-1] != 100 or progress != sorted(progress):
                raise UIContractError(
                    "upload progress must be monotonic from 0 through 100"
                )

    cleanup = evidence["cleanup"]
    cleanup_at = _timestamp(cleanup["completed_at"], "cleanup")
    postflight_at = _timestamp(postflight["captured_at"], "postflight")
    if not previous_finished <= cleanup_at <= postflight_at <= expires_at:
        raise UIContractError("cleanup/postflight timing escaped authorization")
    if (cleanup_at - preflight_at).total_seconds() > 900:
        raise UIContractError("total authorized run duration exceeded")
    if set(cleanup["preexisting_resource_ids"]) & set(created_by_cases):
        raise UIContractError("owned resource collided with preexisting state")
    for key in (
        "owned_resource_ids",
        "deleted_resource_ids",
        "absent_after_resource_ids",
    ):
        if cleanup[key] != created_by_cases:
            raise UIContractError("cleanup exact-owned resource set mismatch")
    if (
        cleanup["preexisting_state_before_sha256"]
        != cleanup["preexisting_state_after_sha256"]
    ):
        raise UIContractError("preexisting resource state was not restored")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "run_id": run_id,
        "authorization_id": authorization_id,
        "validated_case_count": len(cases),
        "validated_fixture_count": len(fixtures),
        "validated_endpoint_count": len(evidence["endpoints"]),
        "validated_api_exchange_count": sum(
            len(case["api_exchanges"]) for case in cases
        ),
        "browser_rendering_required": True,
        "api_mock_transcript_alone_admissible": False,
        "cleanup_verified": True,
        "candidate_evidence_only": True,
        "live_state_advanced": False,
    }


def _read_evidence(path: Path) -> dict[str, Any]:
    return _strict_json(_read_regular(path, None, "evidence"), "evidence")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile an inert UI plan or validate an existing future receipt"
    )
    subparsers = parser.add_subparsers(dest="command")
    plan_parser = subparsers.add_parser("plan", help="compile the inert plan")
    plan_parser.add_argument("--pretty", action="store_true")
    validate_parser = subparsers.add_parser(
        "validate-evidence", help="offline-validate a supplied future receipt"
    )
    validate_parser.add_argument("--evidence", type=Path, required=True)
    validate_parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "plan"):
            result = compile_plan()
            pretty = getattr(args, "pretty", False)
        elif args.command == "validate-evidence":
            result = validate_evidence(_read_evidence(args.evidence))
            pretty = args.pretty
        else:  # pragma: no cover - argparse owns this boundary
            raise UIContractError("unsupported command")
    except UIContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2 if pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
