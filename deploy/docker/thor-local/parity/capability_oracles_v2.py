#!/usr/bin/env python3
"""Validate a static schema-v2 live-root capability-oracle registry.

The v2 registry keeps the exact existing v1 oracle rows as its prefix and adds
planning-only successor rows. It never executes an oracle.
"""

from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

import capability_oracles as v1_oracles


sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
STAGED_ROOT = "deploy/docker/thor-local/qualification/live-metadata-500-migration"
STAGED_SCHEMA_PATH = f"{STAGED_ROOT}/post-state-capability-oracles.schema.json"
STAGED_SCHEMA_RAW_SHA256 = (
    "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233"
)
STAGED_ACCEPTANCE_PATH = f"{STAGED_ROOT}/post-state-acceptance-inventory.json"
STAGED_ACCEPTANCE_RAW_SHA256 = (
    "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0"
)
MAX_JSON_BYTES = 64_000_000
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
PRESERVED_COUNT = 289
CANDIDATE_COUNT = 211
TOTAL_COUNT = PRESERVED_COUNT + CANDIDATE_COUNT
LEDGER_BINDING_FIELDS = (
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
CANDIDATE_KEYS = {
    "acceptance_class",
    "adjacent_negative_observations",
    "admission_gates",
    "advertised",
    "assertions",
    "binding_integrity",
    "can_promote_runtime_state",
    "candidate_entry_sha256",
    "candidate_oracle_plan",
    "capability_id",
    "cleanup",
    "current_state",
    "evidence",
    "execution_boundary",
    "execution_bounds",
    "expected_observations",
    "feature_id",
    "fixture",
    "implementation_surfaces",
    "ledger_binding",
    "manifest_pointer",
    "mode",
    "mode_seed",
    "oracle_id",
    "origin",
    "prior_mapping_class",
    "profile",
    "profile_seed",
    "protocol_v2_binding",
    "readiness",
    "reviewed_scenario_ids",
    "runtime_state",
    "source_claims",
    "successor_row_payload_sha256",
    "successor_schema_version",
    "workload_binding",
}
EXPECTED_READINESS = {
    "blockers": [
        "fixture_not_materialized",
        "executor_not_implemented",
        "collectors_not_implemented",
        "operator_approval_absent",
    ],
    "classification": "planning_index_only",
    "executor_ready": False,
    "fixture_materialized": False,
}
EXPECTED_OPERATOR_GATE = {
    "id": "operator-approval",
    "requirement": ("explicit approval exists before any runtime or external activity"),
    "status": "unmet",
}


class OracleV2ContractError(ValueError):
    """The v2 oracle registry is not an exact, non-activating 289+211 set."""


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_JSON_BYTES:
        raise OracleV2ContractError(f"{label}: JSON exceeds bounded size")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OracleV2ContractError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                OracleV2ContractError(f"{label}: non-finite JSON number {token}")
            ),
        )
    except OracleV2ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OracleV2ContractError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise OracleV2ContractError(f"{label}: JSON root must be an object")
    return value


def _read_locked_json(
    relative: str, expected_sha256: str, label: str
) -> dict[str, Any]:
    path = Path(relative)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not relative.startswith("deploy/docker/thor-local/")
    ):
        raise OracleV2ContractError(f"{label}: unsafe repository path")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise OracleV2ContractError(f"{label}: locked file is missing") from exc
        if stat.S_ISLNK(mode):
            raise OracleV2ContractError(f"{label}: locked path contains a symlink")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise OracleV2ContractError(f"{label}: locked path is not a regular file")
    payload = current.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise OracleV2ContractError(f"{label}: raw hash differs")
    return _strict_json(payload, label)


def _schema_validate(plan: dict[str, Any], schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise OracleV2ContractError("v2 schema must be an object")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise OracleV2ContractError("v2 schema must declare draft 2020-12")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise OracleV2ContractError(
            f"invalid v2 capability-oracle schema: {exc.message}"
        ) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(plan),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise OracleV2ContractError(
            f"v2 oracle schema violation at {path}: {first.message}"
        )


def _ledger_binding(capability: dict[str, Any]) -> dict[str, Any]:
    try:
        return {key: copy.deepcopy(capability[key]) for key in LEDGER_BINDING_FIELDS}
    except KeyError as exc:
        raise OracleV2ContractError(
            f"{capability.get('id')}: ledger binding source is incomplete"
        ) from exc


def _unique_ids(rows: Any, key: str, label: str) -> list[str]:
    if not isinstance(rows, list):
        raise OracleV2ContractError(f"{label}: expected a list")
    result: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise OracleV2ContractError(f"{label}: every row must be an object")
        value = row.get(key)
        if not isinstance(value, str) or PLAIN_ID.fullmatch(value) is None:
            raise OracleV2ContractError(f"{label}: invalid id {value!r}")
        result.append(value)
    if len(result) != len(set(result)):
        raise OracleV2ContractError(f"{label}: duplicate ids")
    return result


def _acceptance_contract(
    acceptance: dict[str, Any], capabilities: list[dict[str, Any]]
) -> None:
    if not isinstance(acceptance, dict) or acceptance.get("schema_version") != 1:
        raise OracleV2ContractError("acceptance inventory must use schema_version 1")
    scenario_ids = set(_unique_ids(acceptance.get("scenarios"), "id", "scenarios"))
    coverage_rows = acceptance.get("coverage", {}).get("features")
    coverage_ids = _unique_ids(coverage_rows, "feature_id", "feature coverage")
    coverage = dict(zip(coverage_ids, coverage_rows, strict=True))
    required: dict[str, set[str]] = {}
    for capability in capabilities:
        linked = capability.get("scenario_ids")
        if (
            not isinstance(linked, list)
            or len(linked) != len(set(linked))
            or not set(linked) <= scenario_ids
        ):
            raise OracleV2ContractError(
                f"{capability.get('id')}: acceptance scenario identity drift"
            )
        required.setdefault(capability["feature_id"], set()).update(linked)
    for feature_id, linked in required.items():
        row = coverage.get(feature_id)
        if row is None or not linked <= set(row.get("scenario_ids", [])):
            raise OracleV2ContractError(
                f"{feature_id}: acceptance coverage is incomplete"
            )


def _candidate_boundary(capability: dict[str, Any]) -> tuple[str, str, str]:
    acceptance_class = capability["acceptance_class"]
    if acceptance_class == "external_optional":
        return (
            "external",
            "operator_approved_external_only",
            "external_boundary_unexecuted",
        )
    if acceptance_class == "alternate_local_lane":
        return (
            "alternate_local",
            "operator_selected_local_alternate",
            "open_unexecuted",
        )
    if acceptance_class != "required_local":
        raise OracleV2ContractError(
            f"{capability['id']}: unknown acceptance class {acceptance_class!r}"
        )
    return "local", "loopback_or_compose_internal", "open_unexecuted"


def _validate_candidate(
    capability: dict[str, Any], oracle: dict[str, Any], scenario_ids: set[str]
) -> tuple[bool, bool]:
    capability_id = capability["id"]
    if set(oracle) != CANDIDATE_KEYS:
        raise OracleV2ContractError(
            f"{capability_id}: candidate discriminator or property set differs"
        )
    external = capability["acceptance_class"] == "external_optional"
    expected_boundary, expected_network, expected_state = _candidate_boundary(
        capability
    )
    expected_runtime = "not_applicable" if external else "not_qualified"
    oracle_id = f"oracle.{capability_id}"
    if (
        capability.get("runtime_state") != expected_runtime
        or oracle["successor_schema_version"] != 1
        or oracle["origin"] != "candidate_successor_planning_only"
        or oracle["capability_id"] != capability_id
        or oracle["oracle_id"] != oracle_id
        or oracle["feature_id"] != capability["feature_id"]
        or oracle["acceptance_class"] != capability["acceptance_class"]
        or oracle["runtime_state"] != expected_runtime
        or oracle["source_claims"] != capability["source_claims"]
        or oracle["implementation_surfaces"]
        != capability["contract"]["implementation_surfaces"]
        or oracle["manifest_pointer"] != capability["contract"]["manifest_pointer"]
        or oracle["advertised"] != capability["contract"]["advertised_literal"]
        or oracle["profile"] != oracle["profile_seed"]
        or oracle["mode"] != oracle["mode_seed"]
        or oracle["fixture"]["id"] != f"fixture.{capability_id}"
        or oracle["reviewed_scenario_ids"] != [*capability["scenario_ids"], oracle_id]
        or not set(capability["scenario_ids"]) <= scenario_ids
    ):
        raise OracleV2ContractError(f"{capability_id}: candidate identity drift")
    if (
        oracle["readiness"] != EXPECTED_READINESS
        or oracle["can_promote_runtime_state"] is not False
        or oracle["evidence"] != []
        or oracle["fixture"]["materialization"] is not None
        or oracle["execution_boundary"] != expected_boundary
        or oracle["current_state"] != expected_state
    ):
        raise OracleV2ContractError(f"{capability_id}: candidate implies promotion")
    bounds = oracle["execution_bounds"]
    cleanup = oracle["cleanup"]
    if (
        bounds["acceptance_class"] != capability["acceptance_class"]
        or bounds["execution_boundary"] != expected_boundary
        or bounds["network_scope"] != expected_network
        or bounds["namespace"] != oracle["fixture"]["namespace"]
        or any(
            bounds[key] is not None
            for key in (
                "executor",
                "collectors",
                "max_actions",
                "max_duration_seconds",
                "max_requests",
            )
        )
        or any(
            cleanup[key] is not None
            for key in (
                "targets",
                "allowlist",
                "executor",
                "postcondition_collectors",
            )
        )
    ):
        raise OracleV2ContractError(f"{capability_id}: candidate implies activation")
    operator_gates = [
        gate
        for gate in oracle["admission_gates"]
        if gate.get("id") == "operator-approval"
    ]
    if operator_gates != [EXPECTED_OPERATOR_GATE]:
        raise OracleV2ContractError(f"{capability_id}: operator gate differs")

    observations = [
        *oracle["expected_observations"],
        *oracle["adjacent_negative_observations"],
    ]
    observation_ids = _unique_ids(observations, "id", f"{capability_id} observations")
    assertion_ids = _unique_ids(
        oracle["assertions"], "id", f"{capability_id} assertions"
    )
    assertion_observations = [row.get("observation_id") for row in oracle["assertions"]]
    if (
        len(assertion_ids) != len(observation_ids)
        or len(assertion_observations) != len(set(assertion_observations))
        or set(assertion_observations) != set(observation_ids)
    ):
        raise OracleV2ContractError(f"{capability_id}: assertion coverage differs")

    protocol = oracle["protocol_v2_binding"]
    workload = oracle["workload_binding"]
    is_protocol = capability["kind"] == "protocol"
    is_workload = capability["kind"] in {"api", "deployment"}
    if is_protocol:
        if (
            not isinstance(protocol, dict)
            or workload is not None
            or protocol["capability_id"] != capability_id
            or protocol["activation_supported"] is not False
            or protocol["readiness"] != "planning_only"
            or protocol["boundary"] != expected_boundary
            or protocol["vector_projection"]["contract"]
            != oracle["candidate_oracle_plan"]
        ):
            raise OracleV2ContractError(f"{capability_id}: protocol binding differs")
    elif is_workload:
        if (
            protocol is not None
            or not isinstance(workload, dict)
            or workload["workload_type"] != capability["kind"]
            or workload["candidate_id"] != capability_id
            or workload["acceptance_class"] != capability["acceptance_class"]
            or workload["manifest_pointer"]
            != capability["contract"]["manifest_pointer"]
            or workload["advertised"] != capability["contract"]["advertised_literal"]
        ):
            raise OracleV2ContractError(f"{capability_id}: workload binding differs")
    elif protocol is not None or workload is not None:
        raise OracleV2ContractError(f"{capability_id}: unexpected planning binding")
    return is_protocol, is_workload


def validate(
    plan: dict[str, Any],
    ledger: dict[str, Any],
    acceptance: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Validate a 500-row v2 registry; no runtime action is performed.

    When ``schema`` or ``acceptance`` is omitted, the exact hash-pinned staged
    v2 schema or staged acceptance inventory is loaded from this checkout.
    Explicit injection is intended for tests and reviewed future bundles.
    """

    if not isinstance(plan, dict) or not isinstance(ledger, dict):
        raise OracleV2ContractError("plan and ledger must be objects")
    selected_schema = (
        _read_locked_json(
            STAGED_SCHEMA_PATH, STAGED_SCHEMA_RAW_SHA256, "staged v2 schema"
        )
        if schema is None
        else schema
    )
    selected_acceptance = (
        _read_locked_json(
            STAGED_ACCEPTANCE_PATH,
            STAGED_ACCEPTANCE_RAW_SHA256,
            "staged acceptance inventory",
        )
        if acceptance is None
        else acceptance
    )
    _schema_validate(plan, selected_schema)
    if set(plan) != {"schema_version", "target", "policy", "oracles"}:
        raise OracleV2ContractError("v2 root property set differs")
    if plan["schema_version"] != 2 or ledger.get("schema_version") != 1:
        raise OracleV2ContractError("unsupported v2 plan or ledger schema version")
    capabilities = ledger.get("capabilities")
    oracles = plan.get("oracles")
    capability_ids = _unique_ids(capabilities, "id", "capabilities")
    oracle_ids = _unique_ids(oracles, "capability_id", "oracles")
    if (
        len(capability_ids) != TOTAL_COUNT
        or len(oracle_ids) != TOTAL_COUNT
        or capability_ids != oracle_ids
    ):
        raise OracleV2ContractError("ledger/oracle exact 500-row order differs")
    spatial_stage1_ids: set[str] = set()
    for capability, oracle in zip(capabilities, oracles, strict=True):
        if oracle.get("ledger_binding") == _ledger_binding(capability):
            continue
        if v1_oracles.is_spatial_ai_core_stage1_binding(capability, oracle):
            spatial_stage1_ids.add(capability["id"])
        else:
            raise OracleV2ContractError(
                f"{capability['id']}: nine-field ledger binding differs"
            )
    if spatial_stage1_ids and spatial_stage1_ids != set(v1_oracles.SPATIAL_AI_CORE_IDS):
        raise OracleV2ContractError("SpatialAI Stage-1 binding denominator differs")
    _acceptance_contract(selected_acceptance, capabilities)
    scenario_ids = set(_unique_ids(selected_acceptance["scenarios"], "id", "scenarios"))

    prefix_plan = {
        "schema_version": 1,
        "target": copy.deepcopy(plan["target"]),
        "policy": copy.deepcopy(plan["policy"]),
        "oracles": copy.deepcopy(oracles[:PRESERVED_COUNT]),
    }
    prefix_ledger = copy.deepcopy(ledger)
    prefix_ledger["capabilities"] = copy.deepcopy(capabilities[:PRESERVED_COUNT])
    try:
        prefix_counts = v1_oracles.validate(prefix_plan, prefix_ledger)
    except v1_oracles.OracleContractError as exc:
        raise OracleV2ContractError(f"preserved v1 prefix is invalid: {exc}") from exc
    if prefix_counts["capabilities"] != PRESERVED_COUNT:
        raise OracleV2ContractError("preserved v1 prefix denominator differs")

    protocol_count = 0
    workload_count = 0
    candidate_oracles = oracles[PRESERVED_COUNT:]
    for capability, oracle in zip(
        capabilities[PRESERVED_COUNT:], candidate_oracles, strict=True
    ):
        protocol, workload = _validate_candidate(capability, oracle, scenario_ids)
        protocol_count += protocol
        workload_count += workload
    if (protocol_count, workload_count) != (23, 60):
        raise OracleV2ContractError("candidate protocol/workload counts differ")
    candidate_states = Counter(row["current_state"] for row in candidate_oracles)
    if candidate_states != {
        "open_unexecuted": 205,
        "external_boundary_unexecuted": 6,
    }:
        raise OracleV2ContractError("candidate state denominator differs")
    return {
        "capabilities": TOTAL_COUNT,
        "oracles": TOTAL_COUNT,
        "preserved_v1": PRESERVED_COUNT,
        "candidates": CANDIDATE_COUNT,
        "candidate_evidence": 0,
        "candidate_executor_ready": 0,
        "candidate_protocol_bindings": protocol_count,
        "candidate_workload_bindings": workload_count,
    }


__all__ = ["OracleV2ContractError", "validate"]
