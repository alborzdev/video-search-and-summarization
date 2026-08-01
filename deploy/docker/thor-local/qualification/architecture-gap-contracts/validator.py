#!/usr/bin/env python3
"""Validate inert architecture decisions and future bounded acceptance receipts."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4].resolve(strict=True)
CONTRACT_PATH = LANE / "contract.json"
CONTRACT_SCHEMA_PATH = LANE / "contract.schema.json"
DECISION_SCHEMA_PATH = LANE / "decision.schema.json"
ACCEPTANCE_SCHEMA_PATH = LANE / "acceptance.schema.json"
EXPECTED_CONTRACT_SHA256 = (
    "6246aa315279ceaf2d18046cc607307d9ed18a0c44f5c3d957f144eca1a48379"
)
EXPECTED_CONTRACT_SCHEMA_SHA256 = (
    "6fcbe3b8a04a38ede25443c0f08c8e630b530a1218171318919e45fefc41420a"
)
EXPECTED_DECISION_SCHEMA_SHA256 = (
    "08f67c482a3efbb84b9977fd6dcc3998cb02bd6af4fffcf02fbf8cb4ea9acd12"
)
EXPECTED_ACCEPTANCE_SCHEMA_SHA256 = (
    "03a956448afd2015a7457006eeae37a71d62b4cc7037593d33cf77c2051c704f"
)
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
ROW_IDS = [
    "smartcity-manual-calibration",
    "smartcity-gis-calibration",
    "systems-alert-worker-scaling",
    "systems-vios-scaling",
]
DESIGN_IDS = {
    "smartcity-manual-calibration": "native-arm64-legacy-calibration-v1",
    "smartcity-gis-calibration": "native-provider-free-gis-calibration-v1",
    "systems-alert-worker-scaling": "scalable-alert-compose-v1",
    "systems-vios-scaling": "scalable-vios-compose-v1",
}


class ContractError(RuntimeError):
    """The fail-closed architecture-gap contract was not satisfied."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_finite(value: Any, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"non-finite number at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, f"{path}/{index}")


def _strict_json(raw: bytes, label: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON in {label}") from exc
    _assert_finite(value)
    return value


def _read_regular(path: Path, maximum: int, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ContractError(f"cannot read {label}: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ContractError(f"{label} must be a regular non-symlink file")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise ContractError(f"{label} is outside the bounded size contract")
    return path.read_bytes()


def _read_pinned(path: Path, expected: str, label: str) -> bytes:
    raw = _read_regular(path, MAX_JSON_BYTES, label)
    actual = _sha256(raw)
    if actual != expected:
        raise ContractError(f"{label} raw SHA-256 mismatch: {actual}")
    return raw


def _repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ContractError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in candidate.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ContractError(f"cannot resolve repository path: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ContractError(f"repository path contains a symlink: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise ContractError(f"repository path escapes root: {relative}") from exc
    return current


def _validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = "/".join(str(item) for item in error.path) or "$"
        raise ContractError(f"{label} schema violation at {location}: {error.message}")


def _load_static() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = _strict_json(
        _read_pinned(CONTRACT_PATH, EXPECTED_CONTRACT_SHA256, "architecture contract"),
        "architecture contract",
    )
    contract_schema = _strict_json(
        _read_pinned(
            CONTRACT_SCHEMA_PATH,
            EXPECTED_CONTRACT_SCHEMA_SHA256,
            "contract schema",
        ),
        "contract schema",
    )
    decision_schema = _strict_json(
        _read_pinned(
            DECISION_SCHEMA_PATH,
            EXPECTED_DECISION_SCHEMA_SHA256,
            "decision schema",
        ),
        "decision schema",
    )
    acceptance_schema = _strict_json(
        _read_pinned(
            ACCEPTANCE_SCHEMA_PATH,
            EXPECTED_ACCEPTANCE_SCHEMA_SHA256,
            "acceptance schema",
        ),
        "acceptance schema",
    )
    _validate_schema(contract, contract_schema, "contract")
    _validate_contract_semantics(contract)
    return contract, decision_schema, acceptance_schema


def _validate_contract_semantics(contract: dict[str, Any]) -> None:
    if [row["id"] for row in contract["rows"]] != ROW_IDS:
        raise ContractError("target rows must be exact, unique, and ordered")
    rows = {row["id"]: row for row in contract["rows"]}
    for row_id, design_id in DESIGN_IDS.items():
        if rows[row_id]["required_design"]["design_id"] != design_id:
            raise ContractError(f"required design drifted for {row_id}")
        acceptance = rows[row_id]["acceptance"]
        if (
            not acceptance["runtime_required"]
            or acceptance["static_configuration_is_sufficient"]
        ):
            raise ContractError(f"runtime-only claim gate drifted for {row_id}")

    manual = rows["smartcity-manual-calibration"]
    if manual["current_state"] != "blocked_architecture":
        raise ContractError("manual calibration must remain architecture-blocked")
    manual_forbidden = set(manual["required_design"]["forbidden_shortcuts"])
    if "claim_AMC_is_the_legacy_manual_calibration_toolkit" not in manual_forbidden:
        raise ContractError("AMC/legacy non-equivalence guardrail is absent")
    if (
        manual["required_design"]["implementation_kind"]
        != "native_thor_legacy_ui_and_server"
    ):
        raise ContractError(
            "manual calibration does not require a native legacy implementation"
        )

    gis = rows["smartcity-gis-calibration"]
    gis_forbidden = set(gis["required_design"]["forbidden_shortcuts"])
    if "claim_provider_free_SVG_is_the_official_Google_Maps_UI" not in gis_forbidden:
        raise ContractError("Google Maps/provider-free identity guardrail is absent")
    if (
        gis["required_design"]["implementation_kind"]
        != "native_thor_provider_free_functional_alternate"
    ):
        raise ContractError("GIS design must preserve alternate identity")

    alerts = rows["systems-alert-worker-scaling"]
    alert_changes = set(alerts["required_design"]["required_changes"])
    if not {
        "remove_fixed_container_name_from_the_scaled_service",
        "move_scaled_workers_off_shared_host_networking",
    }.issubset(alert_changes):
        raise ContractError(
            "alert replica topology does not remove both scaling blockers"
        )
    if alerts["acceptance"]["minimum_runtime_replicas"] < 2:
        raise ContractError("alert scale gate needs at least two runtime replicas")

    vios = rows["systems-vios-scaling"]
    vios_changes = set(vios["required_design"]["required_changes"])
    if not {
        "remove_fixed_container_name_from_streamprocessing",
        "move_streamprocessing_replicas_off_the_shared_host_port",
        "keep_exactly_one_sensor_service_instance",
    }.issubset(vios_changes):
        raise ContractError(
            "VIOS topology does not resolve name/port/singleton boundaries"
        )
    if vios["acceptance"]["minimum_runtime_replicas"] < 2:
        raise ContractError("VIOS scale gate needs at least two stream processors")

    paths = [lock["path"] for lock in contract["source_locks"]]
    if len(paths) != len(set(paths)):
        raise ContractError("source-lock paths must be unique")


def _verify_source_locks(contract: dict[str, Any]) -> None:
    for lock in contract["source_locks"]:
        raw = _read_regular(
            _repo_path(lock["path"]), MAX_JSON_BYTES, f"locked source {lock['path']}"
        )
        actual = _sha256(raw)
        if actual != lock["raw_sha256"]:
            raise ContractError(
                f"locked source SHA-256 mismatch for {lock['path']}: {actual}"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(f"locked source is not UTF-8: {lock['path']}") from exc
        missing = [
            fragment for fragment in lock["required_fragments"] if fragment not in text
        ]
        if missing:
            raise ContractError(
                f"locked source is missing fragments for {lock['path']}"
            )


def _load_input(path: Path, label: str) -> dict[str, Any]:
    value = _strict_json(_read_regular(path, MAX_JSON_BYTES, label), label)
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _rows_by_id(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    ids = [row["id"] for row in rows]
    if ids != ROW_IDS:
        raise ContractError(f"{label} rows must be exact, unique, and ordered")
    return {row["id"]: row for row in rows}


def validate_decision(path: Path) -> dict[str, Any]:
    contract, decision_schema, _ = _load_static()
    _verify_source_locks(contract)
    decision = _load_input(path, "implementation decision")
    _validate_schema(decision, decision_schema, "implementation decision")
    decision_rows = _rows_by_id(decision["rows"], "implementation decision")
    contract_rows = {row["id"]: row for row in contract["rows"]}
    for row_id in ROW_IDS:
        proposed = decision_rows[row_id]
        required = contract_rows[row_id]["required_design"]
        if proposed["selected_design_id"] != required["design_id"]:
            raise ContractError(f"unapproved implementation design for {row_id}")
        if set(proposed["planned_changes"]) != set(required["required_changes"]):
            raise ContractError(
                f"implementation decision omits or invents changes for {row_id}"
            )
        if set(proposed["acknowledged_forbidden_shortcuts"]) != set(
            required["forbidden_shortcuts"]
        ):
            raise ContractError(
                f"implementation decision does not acknowledge guardrails for {row_id}"
            )
    return {
        "valid": True,
        "record_type": "implementation_decision",
        "row_count": 4,
        "runtime_evidence_count": 0,
        "can_claim_runtime_qualified": False,
        "status_effect": "none",
    }


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ContractError(f"invalid timestamp for {label}") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"timestamp must include a timezone for {label}")
    return parsed


def validate_acceptance(path: Path) -> dict[str, Any]:
    contract, _, acceptance_schema = _load_static()
    _verify_source_locks(contract)
    receipt = _load_input(path, "runtime acceptance receipt")
    _validate_schema(receipt, acceptance_schema, "runtime acceptance receipt")
    started = _parse_timestamp(receipt["started_at"], "started_at")
    finished = _parse_timestamp(receipt["finished_at"], "finished_at")
    if finished <= started:
        raise ContractError("runtime acceptance must finish after it starts")
    receipt_rows = _rows_by_id(receipt["rows"], "runtime acceptance")
    contract_rows = {row["id"]: row for row in contract["rows"]}
    for row_id in ROW_IDS:
        observed = receipt_rows[row_id]
        required = contract_rows[row_id]
        if observed["design_id"] != required["required_design"]["design_id"]:
            raise ContractError(
                f"runtime acceptance used an unapproved design for {row_id}"
            )
        if (
            observed["runtime_replica_count"]
            < required["acceptance"]["minimum_runtime_replicas"]
        ):
            raise ContractError(f"runtime replica count is insufficient for {row_id}")
        if row_id == "systems-vios-scaling":
            if observed["sensor_replica_count"] != 1:
                raise ContractError(
                    "VIOS acceptance requires exactly one Sensor instance"
                )
        elif observed["sensor_replica_count"] is not None:
            raise ContractError(f"sensor replica count is not applicable to {row_id}")
        expected_ids = required["acceptance"]["required_evidence_ids"]
        actual_ids = [item["evidence_id"] for item in observed["evidence"]]
        if actual_ids != expected_ids:
            raise ContractError(
                f"runtime evidence IDs must be exact and ordered for {row_id}"
            )
        for item in observed["evidence"]:
            observed_at = _parse_timestamp(item["observed_at"], item["evidence_id"])
            if observed_at < started or observed_at > finished:
                raise ContractError(
                    f"evidence timestamp is outside the run for {item['evidence_id']}"
                )
            artifact = _repo_path(item["artifact_path"])
            raw = _read_regular(artifact, MAX_EVIDENCE_BYTES, item["evidence_id"])
            if _sha256(raw) != item["raw_sha256"]:
                raise ContractError(
                    f"runtime evidence digest mismatch for {item['evidence_id']}"
                )
    return {
        "valid": True,
        "record_type": "authorized_runtime_acceptance",
        "row_count": 4,
        "runtime_evidence_count": 24,
        "evidence_contract_satisfied": True,
        "status_effect": "none_until_explicitly_integrated",
    }


def check() -> dict[str, Any]:
    contract, _, _ = _load_static()
    _verify_source_locks(contract)
    return {
        "valid": True,
        "package_id": contract["package_id"],
        "row_count": len(contract["rows"]),
        "source_lock_count": len(contract["source_locks"]),
        "runtime_actions_performed": False,
        "can_claim_runtime_qualified": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="validate the inert source-locked contract")
    decision_parser = subparsers.add_parser(
        "validate-decision", help="validate a future implementation decision"
    )
    decision_parser.add_argument("path", type=Path)
    acceptance_parser = subparsers.add_parser(
        "validate-acceptance", help="validate a future authorized runtime receipt"
    )
    acceptance_parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            result = check()
        elif args.command == "validate-decision":
            result = validate_decision(args.path)
        else:
            result = validate_acceptance(args.path)
    except ContractError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
