#!/usr/bin/env python3
"""Compile an inert Search plan and validate a closed fake JSON transcript."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[4]
CONTRACT_PATH = PACKAGE_DIR / "contract.json"
CONTRACT_SCHEMA_PATH = PACKAGE_DIR / "contract.schema.json"
PLAN_SCHEMA_PATH = PACKAGE_DIR / "plan.schema.json"
SIMULATION_SCHEMA_PATH = PACKAGE_DIR / "simulation.schema.json"
VALIDATION_RESULT_SCHEMA_PATH = PACKAGE_DIR / "validation-result.schema.json"
MAX_SOURCE_JSON_BYTES = 4 * 1024 * 1024
MAX_SIMULATION_JSON_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_ITEMS = 4096
MAX_JSON_STRING = 16384


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON number rejected: {value}")


class ContractError(ValueError):
    """Raised when a source lock or closed qualification invariant fails."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any, *, sort_keys: bool) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _load_json(path: Path, *, max_bytes: int = MAX_SOURCE_JSON_BYTES) -> Any:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        path_metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(path_metadata.st_mode):
            raise ContractError(f"JSON input is not a regular non-symlink file: {path}")
        descriptor = os.open(path, flags)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractError(f"JSON input is not a regular file: {path}")
        if metadata.st_size > max_bytes:
            raise ContractError(f"JSON exceeds {max_bytes} bytes: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ContractError(f"JSON exceeds {max_bytes} bytes: {path}")
    finally:
        os.close(descriptor)
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ContractError) as exc:
        raise ContractError(f"invalid JSON at {path}: {exc}") from exc


def _validate_schema(instance: Any, schema_path: Path) -> None:
    schema = _load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ContractError(f"schema validation failed at {location}: {error.message}")


def _require_plain_json(value: Any, *, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        raise ContractError("plain JSON exceeds maximum nesting depth")
    if value is None or type(value) in (bool, int):
        return 1
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractError("plain JSON contains a non-finite number")
        return 1
    if type(value) is str:
        if len(value) > MAX_JSON_STRING:
            raise ContractError("plain JSON string exceeds maximum length")
        return 1
    if type(value) is list:
        count = 1
        for item in value:
            count += _require_plain_json(item, depth=depth + 1)
            if count > MAX_JSON_ITEMS:
                raise ContractError("plain JSON exceeds maximum item count")
        return count
    if type(value) is dict:
        count = 1
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError("plain JSON object key is not a built-in string")
            if len(key) > 256:
                raise ContractError("plain JSON object key exceeds maximum length")
            count += _require_plain_json(item, depth=depth + 1)
            if count > MAX_JSON_ITEMS:
                raise ContractError("plain JSON exceeds maximum item count")
        return count
    raise ContractError(f"non-plain JSON value rejected: {type(value).__name__}")


def _resolved_locked_path(relative_path: str) -> Path:
    candidate = REPO_ROOT / relative_path
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractError(
            f"source lock path cannot be resolved: {relative_path}"
        ) from exc
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ContractError(f"source lock escapes repository: {relative_path}") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise ContractError(
            f"source lock is not a regular non-symlink file: {relative_path}"
        )
    return resolved


def _verify_source_locks(contract: dict[str, Any]) -> None:
    expected = _load_json(CONTRACT_PATH)["source_locks"]
    if contract["source_locks"] != expected:
        raise ContractError("source lock set or order differs from the exact contract")
    paths: set[str] = set()
    actual_digests: dict[str, str] = {}
    for lock in contract["source_locks"]:
        relative_path = lock["path"]
        if relative_path in paths:
            raise ContractError(f"duplicate source lock: {relative_path}")
        paths.add(relative_path)
        locked_path = _resolved_locked_path(relative_path)
        actual = _sha256_bytes(locked_path.read_bytes())
        actual_digests[relative_path] = actual
        if actual != lock["sha256"]:
            raise ContractError(
                f"source lock mismatch for {relative_path}: expected {lock['sha256']}, got {actual}"
            )
    fixture = contract["fixture_binding"]
    fixture_path = fixture["fixture_path"]
    if actual_digests.get(fixture_path) != fixture["fixture_sha256"]:
        raise ContractError(
            "fixture binding digest differs from the actual locked fixture"
        )


def _find_exact(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    matches = [item for item in items if item.get(key) == value]
    if len(matches) != 1:
        raise ContractError(
            f"expected exactly one {key}={value!r}, found {len(matches)}"
        )
    return matches[0]


def _verify_canonical_binding(contract: dict[str, Any]) -> None:
    binding = contract["canonical_binding"]
    oracle_doc = _load_json(
        REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json"
    )
    oracles = oracle_doc.get("oracles")
    if type(oracles) is not list or len(oracles) <= binding["canonical_oracle_index"]:
        raise ContractError("canonical oracle index is missing")
    oracle = oracles[binding["canonical_oracle_index"]]
    if type(oracle) is not dict:
        raise ContractError("canonical oracle is not an object")
    if (
        oracle.get("capability_id") != contract["capability_id"]
        or oracle.get("oracle_id") != contract["oracle_id"]
    ):
        raise ContractError("canonical oracle identity mismatch")
    if _canonical_sha256(oracle, sort_keys=False) != binding["canonical_oracle_sha256"]:
        raise ContractError("canonical repository-order oracle digest mismatch")
    if _canonical_sha256(oracle, sort_keys=True) != binding["normalized_oracle_sha256"]:
        raise ContractError("normalized canonical oracle digest mismatch")
    if oracle.get("current_state") != binding["canonical_current_state"]:
        raise ContractError("canonical oracle state advanced unexpectedly")
    if (
        oracle.get("evidence") != []
        or len(oracle["evidence"]) != binding["canonical_evidence_count"]
    ):
        raise ContractError("canonical oracle evidence is not empty")
    ledger = oracle.get("ledger_binding", {})
    if (
        ledger.get("acceptance_class") != "required_local"
        or ledger.get("runtime_state") != "not_qualified"
    ):
        raise ContractError("canonical required-local runtime boundary changed")
    execution = oracle.get("execution_bounds", {})
    if execution.get("max_requests") != 14 or execution.get("max_actions") != 14:
        raise ContractError("canonical execution bounds are not exact 14/14")
    if execution.get("executor") is not None or execution.get("collectors") != []:
        raise ContractError(
            "canonical oracle unexpectedly gained an executor or collector"
        )


def _verify_integrated_bound(contract: dict[str, Any]) -> None:
    path = (
        REPO_ROOT
        / "deploy/docker/thor-local/qualification/runtime-execution-bounds-audit/verified-integrations.json"
    )
    integrations = _load_json(path)
    case = _find_exact(
        integrations.get("cases", []),
        "planning_requirement_id",
        contract["planning_requirement_id"],
    )
    binding = contract["canonical_binding"]
    expected = {
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "canonical_oracle_index": binding["canonical_oracle_index"],
        "canonical_oracle_sha256": binding["canonical_oracle_sha256"],
        "integrated_max_requests": 14,
        "integrated_max_actions": 14,
        "minimum_request_budget": 14,
        "minimum_action_budget": 14,
        "expanded_workflow_sha256": binding["integrated_workflow_sha256"],
        "integration_verified": True,
    }
    for key, value in expected.items():
        if case.get(key) != value:
            raise ContractError(f"verified integration mismatch at {key}")


def _verify_acceptance_binding(contract: dict[str, Any]) -> None:
    path = (
        REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
    )
    acceptance = _load_json(path)
    requirements = acceptance.get("wave3_contracts", {}).get(
        "planning_requirements", []
    )
    requirement = _find_exact(requirements, "id", contract["planning_requirement_id"])
    binding = contract["canonical_binding"]
    expected = {
        "owner_id": contract["capability_id"],
        "payload_canonical_sha256": binding["planning_payload_canonical_sha256"],
        "materialized": False,
        "executor_ready": False,
        "runtime_evidence": [],
    }
    for key, value in expected.items():
        if requirement.get(key) != value:
            raise ContractError(f"acceptance binding mismatch at {key}")


def _verify_fixture(contract: dict[str, Any]) -> None:
    fixture_binding = contract["fixture_binding"]
    fixture = _load_json(REPO_ROOT / fixture_binding["fixture_path"])
    fixture_schema_path = (
        REPO_ROOT
        / "deploy/docker/thor-local/qualification/local20-fixture-pack/fixture.schema.json"
    )
    _validate_schema(fixture, fixture_schema_path)
    if fixture.get("fixture_id") != fixture_binding["fixture_id"]:
        raise ContractError("fixture identity mismatch")
    documents = fixture.get("documents")
    route_cases = fixture.get("route_cases")
    if (
        type(documents) is not list
        or len(documents) != fixture_binding["document_count"]
    ):
        raise ContractError("fixture document count mismatch")
    if (
        type(route_cases) is not list
        or len(route_cases) != fixture_binding["route_case_count"]
    ):
        raise ContractError("fixture route-case count mismatch")
    bbox_cases = [case for case in route_cases if case.get("route") == "selected_bbox"]
    if len(bbox_cases) != 1:
        raise ContractError("fixture must contain exactly one selected-bbox case")
    bbox_case = bbox_cases[0]
    forbidden_material = {"image", "image_bytes", "image_sha256", "image_digest"}
    if forbidden_material.intersection(bbox_case):
        raise ContractError(
            "selected-bbox fixture unexpectedly gained image material; re-review required"
        )
    if not isinstance(bbox_case.get("query_fixture"), str):
        raise ContractError("selected-bbox query fixture frame ID is missing")


def _verify_route_gap(contract: dict[str, Any]) -> None:
    profile_path = (
        REPO_ROOT
        / "deploy/docker/developer-profiles/dev-profile-search/vss-agent/configs/config.yml"
    )
    profile = profile_path.read_text(encoding="utf-8")
    registered = re.findall(r"^\s*- path:\s*(\S+)\s*$", profile, flags=re.MULTILINE)
    route_contract = contract["route_contract"]
    if "/api/v1/search" not in registered:
        raise ContractError("current Search profile no longer registers /api/v1/search")
    absent = route_contract["currently_absent_required_paths"]
    if any(path in registered for path in absent):
        raise ContractError(
            "a previously absent exact Search route is now registered; re-review required"
        )
    aliases = route_contract["forbidden_alias_equivalences"]
    if any(alias not in registered for alias in aliases):
        raise ContractError(
            "current Search alias inventory changed; re-review required"
        )
    if set(absent).intersection(aliases):
        raise ContractError("required exact routes and forbidden aliases overlap")


def _verify_workflow(contract: dict[str, Any]) -> None:
    workflow = contract["workflow"]
    expected_ids = [
        "capture-pre-state",
        "search-route",
        "attribute-route",
        "fusion-route",
        "image-route",
        "same-object-merge",
        "append-multiple-attributes",
        "rerank-or-fallback",
        "fuse-multiple-attributes",
        "same-video-top-k",
        "selected-bbox-knn",
        "reject-invalid-index-family",
        "restore-owned-state",
        "verify-postconditions",
    ]
    if [step["id"] for step in workflow] != expected_ids:
        raise ContractError("workflow IDs or order changed")
    if [step["sequence"] for step in workflow] != list(range(1, 15)):
        raise ContractError("workflow sequence is not exact 1..14")
    if sum(step["request_cost"] for step in workflow) != 14:
        raise ContractError("workflow request cost is not exactly 14")
    if sum(step["action_cost"] for step in workflow) != 14:
        raise ContractError("workflow action cost is not exactly 14")


def _load_and_verify_contract() -> dict[str, Any]:
    contract = _load_json(CONTRACT_PATH)
    _require_plain_json(contract)
    _validate_schema(contract, CONTRACT_SCHEMA_PATH)
    _verify_source_locks(contract)
    _verify_canonical_binding(contract)
    _verify_integrated_bound(contract)
    _verify_acceptance_binding(contract)
    _verify_fixture(contract)
    _verify_route_gap(contract)
    _verify_workflow(contract)
    return contract


def compile_plan() -> dict[str, Any]:
    contract = _load_and_verify_contract()
    binding = contract["canonical_binding"]
    fixture = contract["fixture_binding"]
    plan = {
        "schema_version": 1,
        "collector_id": contract["collector_id"],
        "mode": "offline-inert-plan-only",
        "status": "candidate_plan_valid_non_advancing",
        "promotion_eligible": False,
        "runtime_requests": 0,
        "runtime_actions": 0,
        "simulated_requests": 0,
        "simulated_actions": 0,
        "planning_requirement_id": contract["planning_requirement_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "canonical_binding": {
            "canonical_oracle_index": binding["canonical_oracle_index"],
            "canonical_oracle_sha256": binding["canonical_oracle_sha256"],
            "normalized_oracle_sha256": binding["normalized_oracle_sha256"],
            "integrated_workflow_sha256": binding["integrated_workflow_sha256"],
            "canonical_current_state": binding["canonical_current_state"],
            "canonical_evidence_count": binding["canonical_evidence_count"],
        },
        "fixture": {
            "fixture_id": fixture["fixture_id"],
            "fixture_sha256": fixture["fixture_sha256"],
            "document_count": fixture["document_count"],
            "route_case_count": fixture["route_case_count"],
            "selected_bbox_image_bytes_present": fixture[
                "selected_bbox_image_bytes_present"
            ],
            "selected_bbox_image_digest_present": fixture[
                "selected_bbox_image_digest_present"
            ],
        },
        "route_contract": {
            key: contract["route_contract"][key]
            for key in (
                "required_exact_paths",
                "currently_absent_required_paths",
                "forbidden_alias_equivalences",
                "allowed_index_patterns",
            )
        },
        "execution_bounds": contract["execution_bounds"],
        "workflow": contract["workflow"],
        "ownership": contract["ownership"],
        "adjacent_negative": contract["adjacent_negative"],
        "cleanup": contract["cleanup"],
        "blockers": contract["evidence_scope"]["blockers"],
    }
    _validate_schema(plan, PLAN_SCHEMA_PATH)
    _verify_workflow({"workflow": plan["workflow"]})
    return plan


def validate_simulation(simulation: Any) -> dict[str, Any]:
    plan = compile_plan()
    _require_plain_json(simulation)
    _validate_schema(simulation, SIMULATION_SCHEMA_PATH)
    expected_ids = [step["id"] for step in plan["workflow"]]
    observations = simulation["observations"]
    if [item["step_id"] for item in observations] != expected_ids:
        raise ContractError(
            "simulation observation order differs from canonical workflow"
        )
    required_paths = plan["route_contract"]["required_exact_paths"]
    route_paths = [observations[index]["exact_path"] for index in range(1, 5)]
    if route_paths != required_paths:
        raise ContractError("simulation substituted or reordered an exact Search route")
    forbidden_aliases = set(plan["route_contract"]["forbidden_alias_equivalences"])
    if forbidden_aliases.intersection(route_paths):
        raise ContractError("simulation accepted a forbidden route alias")
    negative = observations[11]
    if negative["index_family"] in plan["route_contract"]["allowed_index_patterns"]:
        raise ContractError("adjacent negative uses an allowed index family")
    if negative["expected_status"] not in plan["adjacent_negative"]["allowed_statuses"]:
        raise ContractError("adjacent negative status is not 400 or 422")
    if negative["backend_query_count"] != 0 or negative["backend_write_count"] != 0:
        raise ContractError("adjacent negative reached a backend query or write")
    registered = plan["ownership"]["registered_documents"]
    cleanup = observations[12]
    if cleanup["registered_documents"] != registered:
        raise ContractError(
            "cleanup registration list differs from the exact ownership allowlist"
        )
    if cleanup["simulated_deleted_documents"] != list(reversed(registered)):
        raise ContractError("cleanup is not exact LIFO")
    prestate = observations[0]
    poststate = observations[13]
    for key in (
        "service_state_digest",
        "configuration_digest",
        "non_owned_indices_digest",
    ):
        if poststate[key] != prestate[key]:
            raise ContractError(f"postcondition digest does not match pre-state: {key}")
    raw = json.dumps(
        simulation, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    result = {
        "schema_version": 1,
        "collector_id": plan["collector_id"],
        "mode": "offline-fake-validation-result",
        "status": "candidate_simulation_valid_non_advancing",
        "valid": True,
        "promotion_eligible": False,
        "runtime_requests": 0,
        "runtime_actions": 0,
        "simulated_requests": 14,
        "simulated_actions": 14,
        "canonical_current_state": "open_unexecuted",
        "canonical_evidence": [],
        "input_canonical_sha256": _sha256_bytes(raw),
        "blockers": plan["blockers"],
    }
    _validate_schema(result, VALIDATION_RESULT_SCHEMA_PATH)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="compile the inert non-advancing plan")
    validate_parser = subparsers.add_parser(
        "validate-simulation",
        help="validate one bounded plain-JSON fake transcript",
    )
    validate_parser.add_argument("input", type=Path, help="fake transcript JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = compile_plan()
        elif args.command == "validate-simulation":
            result = validate_simulation(
                _load_json(args.input, max_bytes=MAX_SIMULATION_JSON_BYTES)
            )
        else:  # pragma: no cover - argparse closes this branch
            raise ContractError(f"unsupported command: {args.command}")
    except ContractError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
