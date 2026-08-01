#!/usr/bin/env python3
"""Compile a static execution-bound audit; never execute a runtime workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
VERIFIED_PATH = HERE / "verified-integrations.json"
MAX_JSON_BYTES = 8_000_000

EXPECTED_IDS = [
    "tiny-agent-media",
    "hitl-state-transcript",
    "lvs-multi-file",
    "search-documents-and-bboxes",
    "candidate-alerts",
    "tiny-alert-stream",
    "ui-alert-api",
    "ui-search-api",
    "ui-tiny-media",
    "nemoclaw-lifecycle-mocks",
    "nemoclaw-policy-network",
    "smartcity-ui-incidents",
    "smartcity-synthetic-tracks",
    "smartcity-agent-pages",
    "smartcity-manual-calibration",
    "smartcity-gis-calibration",
    "systems-alert-worker-scaling",
    "systems-vios-scaling",
    "systems-elk-recovery",
    "systems-vios-playback-remediation",
]
EXPECTED_BUDGETS = {
    "tiny-agent-media": (8, 8),
    "hitl-state-transcript": (11, 11),
    "lvs-multi-file": (14, 14),
    "search-documents-and-bboxes": (14, 14),
    "candidate-alerts": (8, 8),
    "tiny-alert-stream": (12, 12),
    "ui-alert-api": (9, 9),
    "ui-search-api": (13, 13),
    "ui-tiny-media": (11, 11),
    "nemoclaw-lifecycle-mocks": (7, 9),
    "nemoclaw-policy-network": (9, 9),
    "smartcity-ui-incidents": (8, 8),
    "smartcity-synthetic-tracks": (14, 14),
    "smartcity-agent-pages": (12, 12),
    "smartcity-manual-calibration": (8, 8),
    "smartcity-gis-calibration": (8, 8),
    "systems-alert-worker-scaling": (8, 8),
    "systems-vios-scaling": (7, 9),
    "systems-elk-recovery": (13, 13),
    "systems-vios-playback-remediation": (8, 9),
}
PHASES = ["pre_state", "positive", "adjacent_negative", "restore", "postcondition"]


class AuditError(RuntimeError):
    """The static audit contract or a locked canonical input drifted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise AuditError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuditError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AuditError(f"non-finite number in {label}: {token}")
            ),
        )
    except AuditError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON: {label}") from exc


def _regular_file(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise AuditError(f"missing file: {label}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise AuditError(f"file must be a regular non-symlink: {label}")
    return path


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AuditError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise AuditError(f"symlinked repository source: {relative}")
    try:
        resolved = (REPO_ROOT / candidate).resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise AuditError(f"repository source escaped or is absent: {relative}") from exc
    return _regular_file(resolved, relative)


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(_regular_file(schema_path, label).read_bytes(), label)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AuditError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(item) for item in first.absolute_path)
        raise AuditError(f"{label} schema violation at {location}: {first.message}")


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for raw in pointer.lstrip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            else:
                current = current[token]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise AuditError(
                f"canonical basis pointer does not resolve: {pointer}"
            ) from exc
    return current


def _expanded_steps(
    contract: dict[str, Any], case: dict[str, Any]
) -> list[dict[str, Any]]:
    pre, restore, post = contract["mandatory_envelope"]
    expanded: list[tuple[str, dict[str, Any]]] = [("pre_state", pre)]
    expanded.extend(("positive", step) for step in case["positive_steps"])
    expanded.append(("adjacent_negative", case["adjacent_negative"]))
    expanded.extend([("restore", restore), ("postcondition", post)])
    return [
        {
            "sequence": index,
            "id": step["id"],
            "phase": phase,
            "request_cost": step["request_cost"],
            "canonical_basis": step["canonical_basis"],
        }
        for index, (phase, step) in enumerate(expanded, start=1)
    ]


def compile_audit(
    contract: dict[str, Any], canonical: dict[str, Any]
) -> dict[str, Any]:
    """Derive an inert override proposal from locked canonical oracle inputs."""
    if [case["planning_requirement_id"] for case in contract["cases"]] != EXPECTED_IDS:
        raise AuditError("exact ordered 20-case denominator drift")
    if len({case["oracle_id"] for case in contract["cases"]}) != len(EXPECTED_IDS):
        raise AuditError("oracle IDs must be unique")
    if set(EXPECTED_BUDGETS) != set(EXPECTED_IDS):
        raise AuditError("internal expected budget denominator drift")

    oracles = canonical.get("oracles")
    if not isinstance(oracles, list):
        raise AuditError("canonical source does not contain an oracle list")

    results: list[dict[str, Any]] = []
    for case in contract["cases"]:
        requirement_id = case["planning_requirement_id"]
        index = case["canonical_oracle_index"]
        if index >= len(oracles):
            raise AuditError(
                f"canonical oracle index is out of range: {requirement_id}"
            )
        oracle = oracles[index]
        if oracle.get("oracle_id") != case["oracle_id"]:
            raise AuditError(f"canonical oracle ID/index drift: {requirement_id}")
        if oracle.get("capability_id") != case["capability_id"]:
            raise AuditError(f"canonical capability binding drift: {requirement_id}")
        if (
            oracle.get("current_state") != "open_unexecuted"
            or oracle.get("evidence") != []
        ):
            raise AuditError(
                f"official oracle must remain open and evidence-free: {requirement_id}"
            )

        bounds = oracle.get("execution_bounds", {})
        workload = bounds.get("workload", {})
        if bounds.get("executor") is not None or bounds.get("collectors") != []:
            raise AuditError(f"expected unimplemented runtime bounds: {requirement_id}")
        planning_ids = (
            oracle.get("fixture", {})
            .get("input", {})
            .get("contract", {})
            .get("wave3_acceptance", {})
            .get("planning_requirement_ids")
        )
        if planning_ids != [requirement_id]:
            raise AuditError(
                f"canonical planning requirement binding drift: {requirement_id}"
            )
        if oracle.get("fixture", {}).get("warehouse_sample_bundle") is not False:
            raise AuditError(
                f"Warehouse fixture entered local runtime audit: {requirement_id}"
            )

        expanded = _expanded_steps(contract, case)
        step_ids = [step["id"] for step in expanded]
        if len(step_ids) != len(set(step_ids)):
            raise AuditError(f"workflow step IDs must be unique: {requirement_id}")
        for step in expanded:
            for pointer in step["canonical_basis"]:
                _resolve_pointer(oracle, pointer)

        request_budget = sum(step["request_cost"] for step in expanded)
        action_budget = len(expanded)
        if (request_budget, action_budget) != EXPECTED_BUDGETS[requirement_id]:
            raise AuditError(f"derived budget drift: {requirement_id}")

        integrated_workload = {
            "units": 1,
            "requests_per_unit": request_budget,
            "overhead_requests": 0,
            "calculated_max_requests": request_budget,
            "phases": PHASES,
        }
        if (
            bounds.get("max_requests") != request_budget
            or bounds.get("max_actions") != action_budget
            or workload != integrated_workload
        ):
            raise AuditError(f"canonical exact execution bounds differ: {requirement_id}")
        results.append(
            {
                "planning_requirement_id": requirement_id,
                "capability_id": case["capability_id"],
                "oracle_id": case["oracle_id"],
                "canonical_oracle_index": index,
                "canonical_oracle_sha256": _sha256(_canonical_bytes(oracle)),
                "prior_baseline_oracle_sha256": case["prior_baseline_oracle_sha256"],
                "prior_max_requests": contract["baseline_provenance"]["max_requests"],
                "integrated_max_requests": bounds["max_requests"],
                "integrated_max_actions": bounds["max_actions"],
                "minimum_request_budget": request_budget,
                "minimum_action_budget": action_budget,
                "prior_max_requests_2_inadequate": request_budget > 2,
                "integration_verified": True,
                "expanded_workflow_sha256": _sha256(_canonical_bytes(expanded)),
                "integration_target": f"/oracles/{index}/execution_bounds",
                "integrated_bounds": {
                    "max_requests": request_budget,
                    "max_actions": action_budget,
                    "workload": integrated_workload,
                },
            }
        )

    return {
        "schema_version": "1.0.0",
        "artifact_kind": "verified_execution_bound_integrations",
        "mode": "static_inert_planning_only",
        "source": contract["canonical_source"],
        "baseline_provenance": contract["baseline_provenance"],
        "official_states_preserved": True,
        "cases": results,
        "summary": {
            "case_count": len(results),
            "prior_two_request_cases": len(results),
            "prior_two_request_inadequate_cases": sum(
                case["prior_max_requests_2_inadequate"] for case in results
            ),
            "integrated_exact_cases": sum(case["integration_verified"] for case in results),
            "minimum_request_budget_total": sum(
                case["minimum_request_budget"] for case in results
            ),
            "minimum_action_budget_total": sum(
                case["minimum_action_budget"] for case in results
            ),
        },
    }


def _load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _strict_json_bytes(
        _regular_file(CONTRACT_PATH, "contract.json").read_bytes(), "contract.json"
    )
    _validate_schema(contract, CONTRACT_SCHEMA_PATH, "contract")
    source_path = _repo_file(contract["canonical_source"]["path"])
    source_bytes = source_path.read_bytes()
    if _sha256(source_bytes) != contract["canonical_source"]["sha256"]:
        raise AuditError("canonical capability-oracles source digest drift")
    canonical = _strict_json_bytes(source_bytes, contract["canonical_source"]["path"])
    if not isinstance(canonical, dict):
        raise AuditError("canonical source root must be an object")
    return contract, canonical


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed proposal is byte-for-byte deterministic",
    )
    args = parser.parse_args(argv)
    try:
        contract, canonical = _load_inputs()
        result = compile_audit(contract, canonical)
        _validate_schema(result, RESULT_SCHEMA_PATH, "result")
        rendered = _canonical_bytes(result).decode("utf-8") + "\n"
        if args.check:
            committed = _regular_file(
                VERIFIED_PATH, "verified-integrations.json"
            ).read_bytes()
            if committed != rendered.encode("utf-8"):
                raise AuditError("committed verified integration artifact drift")
            print(
                "PASS: exact 20 local-runtime execution bounds are integrated and reproducible"
            )
        else:
            sys.stdout.write(rendered)
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
