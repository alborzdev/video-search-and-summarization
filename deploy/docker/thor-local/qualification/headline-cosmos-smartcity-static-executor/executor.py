#!/usr/bin/env python3
"""Provider-free static executor for Cosmos3 and Smart City headline claims."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
DEFAULT_CONTRACT = HERE / "contract.json"
CONTRACT_SCHEMA = HERE / "contract.schema.json"
RESULT_SCHEMA = HERE / "result.schema.json"
CAPABILITIES = REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLES = REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json"
SMARTCITY_CANDIDATE = (
    REPO_ROOT
    / "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json"
)
SYSTEMS_CANDIDATE = (
    REPO_ROOT / "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json"
)
WAVE6_INVENTORY = (
    REPO_ROOT
    / "deploy/docker/thor-local/qualification/planning-requirement-executors-wave6/inventory.json"
)
OFFICIAL_EDGE_MODULE = (
    REPO_ROOT / "deploy/docker/thor-local/official-edge/official_edge.py"
)

CAPABILITY_IDS = {
    "model.rt-vlm.default-cosmos3-nano-bf16",
    "model.edge.cosmos3-nano-served-id",
    "boundary.smart-city.version-skew",
}
EXPECTED_BINDINGS = {
    "model.rt-vlm.default-cosmos3-nano-bf16": {
        "capability_id": "model.rt-vlm.default-cosmos3-nano-bf16",
        "oracle_id": "oracle.model.rt-vlm.default-cosmos3-nano-bf16",
        "expected_acceptance_class": "required_local",
        "expected_thor_state": "partial",
        "expected_runtime_state": "not_qualified",
        "static_outcome": "exact_identity_and_default_wiring_verified",
        "runtime_outcome": "open",
    },
    "model.edge.cosmos3-nano-served-id": {
        "capability_id": "model.edge.cosmos3-nano-served-id",
        "oracle_id": "oracle.model.edge.cosmos3-nano-served-id",
        "expected_acceptance_class": "required_local",
        "expected_thor_state": "partial",
        "expected_runtime_state": "not_qualified",
        "static_outcome": "exact_served_identity_wiring_verified",
        "runtime_outcome": "open",
    },
    "boundary.smart-city.version-skew": {
        "capability_id": "boundary.smart-city.version-skew",
        "oracle_id": "oracle.boundary.smart-city.version-skew",
        "planning_requirement_id": "smartcity-version-lock",
        "expected_acceptance_class": "alternate_local_lane",
        "expected_thor_state": "source_only",
        "expected_runtime_state": "not_qualified",
        "static_outcome": "documented_mismatch_preserved",
        "runtime_outcome": "open",
    },
}
EXPECTED_SOURCE_LOCKS = {
    "deploy/docker/thor-local/official-edge/contract.json": (
        "e632804c98f931661336f3be0e464b5bf4798f807dcd660327a5fdafb8c94055"
    ),
    "deploy/docker/thor-local/official-edge/official-edge.env": (
        "134e4369f21ce80c4fd2261552d83925da900ca80f23d93622cc7bf2756d8074"
    ),
    "deploy/docker/thor-local/official-edge/compose.yml": (
        "8a57b27d6798fa1c4655994fecb1c7abd78a3f738e8d20370f0ecdbefb11369c"
    ),
    "deploy/docker/thor-local/official-edge/config_edge.yml": (
        "4690cd45b8a4498fcd5d2ef9f55837c75b77f249c8abba936b842d4a797ef662"
    ),
    "deploy/docker/thor-local/official-edge/official_edge.py": (
        "779ef64bd134fa00934a7bdfdde3b1066678dd1e8ffa75c11c8b9b5af3f06faa"
    ),
    "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json": (
        "7b544d9aa3d74ab1935f44647026fa4ff85c1dacee3d1c284aa52269bfdca395"
    ),
    "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/EVIDENCE.md": (
        "a52cc9d1fb873924c46a4565bbb235086af1822458864ff91c0ae6dc797b92d0"
    ),
    "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json": (
        "0abc81c383a9db122d2ad74c4dbb6c85cc00caf032abd94c4e7d632ce97ff539"
    ),
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave6/inventory.json": (
        "bdcaf973fddf291fc35a0d27ae7a7a9414e5d62367c9100fef6d80f39d86fec7"
    ),
}
EXPECTED_COSMOS = {
    "artifact_id": "ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final",
    "served_model_id": "nim_nvidia_cosmos3-nano-reasoner_bf16-final",
    "selector": "cosmos-reason3",
    "roles": ["rt-vlm", "agent-vlm"],
    "default": True,
    "release_provenance": "3.2.1",
    "older_default_prose_overridden": True,
}
EXPECTED_SMARTCITY = {
    "docs_container": "3.2.1",
    "toc_claim": "VSS v3.1",
    "release_note_claim": "3.2.0 microservices",
    "deep_dive_claim": "VSS 3.0 architecture",
    "qualification_rule": (
        "pin actual artifact and image digests; never infer runtime version from docs path"
    ),
}
EXPECTED_FUTURE_EVIDENCE = [
    "exact staged Cosmos artifact tree with content digests",
    "served /v1/models identity equals nim_nvidia_cosmos3-nano-reasoner_bf16-final",
    "bounded semantic video inference through the selected default rt-vlm and agent-vlm roles",
    "resolved Smart City component image and artifact versions with immutable digests",
    "bounded Smart City custom-media smoke test; no Warehouse sample bundle required",
]


class QualificationError(RuntimeError):
    """A locked source, canonical binding, or static product check failed."""


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root is not an object: {path}")
    return value


def _validate(instance: Any, schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {location}: {error.message}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise QualificationError(f"cannot hash source {path}: {exc}") from exc
    return digest.hexdigest()


def _safe_repo_file(raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise QualificationError(f"unsafe repository path: {raw}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise QualificationError(f"symlinked repository source: {raw}")
    root = REPO_ROOT.resolve()
    resolved = (REPO_ROOT / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"repository source escapes root: {raw}") from exc
    if not resolved.is_file():
        raise QualificationError(f"repository source is not a file: {raw}")
    return resolved


def _index_unique(items: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise QualificationError(f"{label} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            raise QualificationError(f"invalid {label} entry")
        item_id = item[key]
        if item_id in result:
            raise QualificationError(f"duplicate {label} ID: {item_id}")
        result[item_id] = item
    return result


def _verify_sources(contract: dict[str, Any]) -> None:
    seen: set[str] = set()
    declared: dict[str, str] = {}
    for lock in contract["source_locks"]:
        path_text = lock["path"]
        if path_text in seen:
            raise QualificationError(f"duplicate source lock: {path_text}")
        seen.add(path_text)
        declared[path_text] = lock["sha256"]
        actual = _sha256(_safe_repo_file(path_text))
        if actual != lock["sha256"]:
            raise QualificationError(
                f"source lock drift for {path_text}: {actual} != {lock['sha256']}"
            )
    if declared != EXPECTED_SOURCE_LOCKS:
        raise QualificationError("source-lock declaration differs from executor locks")


def _verify_bindings(contract: dict[str, Any]) -> None:
    bindings = _index_unique(contract["bindings"], "capability_id", "binding")
    if set(bindings) != CAPABILITY_IDS:
        raise QualificationError("contract must bind exactly the three headline IDs")
    if bindings != EXPECTED_BINDINGS:
        raise QualificationError("headline binding contract drifted")

    capabilities_doc = _load_json(CAPABILITIES)
    oracles_doc = _load_json(ORACLES)
    capabilities = _index_unique(
        capabilities_doc.get("capabilities"), "id", "canonical capability"
    )
    oracles = _index_unique(oracles_doc.get("oracles"), "oracle_id", "canonical oracle")

    for capability_id, binding in bindings.items():
        capability = capabilities.get(capability_id)
        oracle = oracles.get(binding["oracle_id"])
        if capability is None or oracle is None:
            raise QualificationError(f"missing canonical binding for {capability_id}")
        if oracle.get("capability_id") != capability_id:
            raise QualificationError(f"cross-mapped oracle for {capability_id}")
        expected_oracle_id = f"oracle.{capability_id}"
        if binding["oracle_id"] != expected_oracle_id:
            raise QualificationError(f"non-canonical oracle ID for {capability_id}")
        for field in ("acceptance_class", "thor_state", "runtime_state"):
            expected = binding[f"expected_{field}"]
            if capability.get(field) != expected:
                raise QualificationError(
                    f"{capability_id}.{field} is {capability.get(field)!r}; expected {expected!r}"
                )
        if oracle.get("current_state") != "open_unexecuted":
            raise QualificationError(f"{expected_oracle_id} must remain open_unexecuted")

    default_contract = capabilities[
        "model.rt-vlm.default-cosmos3-nano-bf16"
    ].get("contract")
    if not isinstance(default_contract, dict):
        raise QualificationError("default Cosmos capability contract is missing")
    for field in (
        "artifact_id",
        "roles",
        "default",
        "release_provenance",
        "older_default_prose_overridden",
    ):
        if default_contract.get(field) != EXPECTED_COSMOS[field]:
            raise QualificationError(f"default Cosmos contract drift: {field}")
    wave3 = default_contract.get("wave3_acceptance")
    if not isinstance(wave3, dict) or wave3.get("materialized") is not False:
        raise QualificationError("default Cosmos Wave 3 evidence must remain nonmaterialized")
    if wave3.get("executor_ready") is not False:
        raise QualificationError("default Cosmos Wave 3 executor must remain not ready")

    served_contract = capabilities["model.edge.cosmos3-nano-served-id"].get(
        "contract"
    )
    if served_contract != {
        "artifact_id": EXPECTED_COSMOS["artifact_id"],
        "served_model_id": EXPECTED_COSMOS["served_model_id"],
    }:
        raise QualificationError("served Cosmos identity contract drifted")

    smart_contract = capabilities["boundary.smart-city.version-skew"].get(
        "contract"
    )
    if not isinstance(smart_contract, dict):
        raise QualificationError("Smart City version contract is missing")
    for field, expected in EXPECTED_SMARTCITY.items():
        if smart_contract.get(field) != expected:
            raise QualificationError(f"Smart City version contract drift: {field}")
    acceptance = smart_contract.get("wave3_acceptance")
    if not isinstance(acceptance, dict):
        raise QualificationError("Smart City Wave 3 acceptance is missing")
    if acceptance != {
        "package": "agent-smartcity",
        "planning_requirement_ids": ["smartcity-version-lock"],
        "materialized": False,
        "executor_ready": False,
    }:
        raise QualificationError("Smart City version-lock readiness was overstated")


def _verify_official_edge_static() -> None:
    module_name = "_thor_headline_official_edge"
    spec = importlib.util.spec_from_file_location(module_name, OFFICIAL_EDGE_MODULE)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot construct official-edge module spec")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        edge_contract = module._load_json(module.DEFAULT_CONTRACT)
        # Deliberately omit verify_source_anchors(): it shells out to git. These
        # five checks are file/config-only and are independently byte locked.
        module.verify_contract_identity(edge_contract)
        module.verify_env_contract()
        module.verify_compose_contract()
        module.verify_agent_prompt_overlay()
        module.verify_operator_guidance(edge_contract)
    except Exception as exc:
        raise QualificationError(f"official-edge static verification failed: {exc}") from exc
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


def _verify_smartcity_sources(contract: dict[str, Any]) -> None:
    candidate = _load_json(SMARTCITY_CANDIDATE)
    capabilities = _index_unique(
        candidate.get("new_capabilities"), "id", "Smart City candidate capability"
    )
    candidate_capability = capabilities.get("boundary.smart-city.version-skew")
    if candidate_capability is None:
        raise QualificationError("Smart City candidate lacks version-skew capability")
    if candidate_capability.get("contract") != EXPECTED_SMARTCITY:
        raise QualificationError("Smart City candidate version statements drifted")
    qualification = candidate_capability.get("qualification")
    fixtures = qualification.get("fixtures") if isinstance(qualification, dict) else None
    if not isinstance(fixtures, list) or not any(
        isinstance(item, dict)
        and item.get("id") == "smartcity-version-lock"
        and item.get("type") == "source_lock"
        for item in fixtures
    ):
        raise QualificationError("Smart City candidate lacks version-lock fixture")

    discrepancies = _index_unique(
        candidate.get("discrepancies"), "id", "Smart City discrepancy"
    )
    expected = contract["smartcity_contract"]
    discrepancy = discrepancies.get(expected["candidate_discrepancy_id"])
    if discrepancy is None:
        raise QualificationError("Smart City version discrepancy is missing")
    if discrepancy.get("must_not_claim") != expected["must_not_claim"]:
        raise QualificationError("Smart City mismatch guardrail drifted")

    systems = _load_json(SYSTEMS_CANDIDATE)
    systems_discrepancies = _index_unique(
        systems.get("discrepancies_and_boundaries"), "id", "Systems discrepancy"
    )
    vague = systems_discrepancies.get(
        "systems.release-smartcity-v320-components-vague"
    )
    if not isinstance(vague, dict):
        raise QualificationError("Systems Smart City component boundary is missing")
    if vague.get("must_not_claim") != (
        "Every Smart City component version from this grouped bullet."
    ):
        raise QualificationError("Smart City component-version boundary drifted")

    wave6 = _load_json(WAVE6_INVENTORY)
    rows = _index_unique(wave6.get("cases"), "case_id", "Wave 6 planning case")
    planning = rows.get("wave6-source-case.smartcity-version-lock")
    if not isinstance(planning, dict):
        raise QualificationError("Wave 6 Smart City version-lock row is missing")
    if (
        planning.get("planning_requirement_id") != "smartcity-version-lock"
        or planning.get("capability_id") != "boundary.smart-city.version-skew"
        or planning.get("boundary_status") != "documented_mismatch_preserved"
        or planning.get("runtime_evidence") != []
    ):
        raise QualificationError("Wave 6 Smart City version-lock binding drifted")
    assertions = planning.get("assertions")
    if not isinstance(assertions, list) or {
        assertion.get("assertion_id")
        for assertion in assertions
        if isinstance(assertion, dict)
    } != {
        "three-version-statements",
        "version-lock-rule",
        "artifact-integrity-is-not-runtime-evidence",
    }:
        raise QualificationError("Wave 6 Smart City version-lock assertions drifted")


def execute(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _load_json(contract_path)
    _validate(contract, CONTRACT_SCHEMA, "contract")
    if contract["cosmos_contract"] != EXPECTED_COSMOS:
        raise QualificationError("executor Cosmos contract drifted")
    if contract["smartcity_contract"] != {
        **EXPECTED_SMARTCITY,
        "candidate_discrepancy_id": "discrepancy.smart-city.version-identity",
        "must_not_claim": (
            "The 3.2.1 documentation path proves one consistent Smart City runtime version."
        ),
    }:
        raise QualificationError("executor Smart City contract drifted")
    if contract["future_runtime_evidence"] != EXPECTED_FUTURE_EVIDENCE:
        raise QualificationError("future runtime evidence boundary drifted")
    _verify_sources(contract)
    _verify_bindings(contract)
    _verify_official_edge_static()
    _verify_smartcity_sources(contract)

    result = {
        "schema_version": 1,
        "executor_id": contract["executor_id"],
        "status": "pass",
        "scope": "static_only",
        "runtime_evidence_created": False,
        "runtime_state_promoted": False,
        "warehouse_sample_required": False,
        "source_lock_count": len(contract["source_locks"]),
        "results": [
            {
                "capability_id": binding["capability_id"],
                "oracle_id": binding["oracle_id"],
                "static_outcome": binding["static_outcome"],
                "runtime_outcome": binding["runtime_outcome"],
                "runtime_state": binding["expected_runtime_state"],
            }
            for binding in contract["bindings"]
        ],
        "future_runtime_evidence": contract["future_runtime_evidence"],
    }
    _validate(result, RESULT_SCHEMA, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = execute(args.contract)
    except QualificationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
