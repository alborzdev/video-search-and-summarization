#!/usr/bin/env python3
"""Compile the 211 planning-only candidate oracle records into a strict adapter."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
OUTPUT = PACKAGE / "adapter.json"
SCHEMA = PACKAGE / "adapter.schema.json"

INPUTS = {
    "candidate": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.json",
        "raw_sha256": "a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd",
    },
    "candidate_schema": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/candidate.schema.json",
        "raw_sha256": "e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8",
    },
    "official_capabilities": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.json",
        "raw_sha256": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    },
    "official_capabilities_schema": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "raw_sha256": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    },
    "capability_oracles": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.json",
        "raw_sha256": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
    },
    "capability_oracles_schema": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.schema.json",
        "raw_sha256": "55de87c13e78b4f349e7095232f31c1135155e0bc13ed6bcb8e4abb906f26cf1",
    },
}
SCHEMA_RAW_SHA256 = "959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb"
EXPECTED_OUTPUT_PAYLOAD_SHA256 = (
    "e7b67f4e4c3f25641eeb95fd665b2dc0b0d9224c1fec81007b4b7cdc4a40b541"
)
EXPECTED_OUTPUT_RAW_SHA256 = (
    "6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235"
)
MAX_JSON_BYTES = 32_000_000


class AdapterError(RuntimeError):
    """A source lock, translation invariant, or deterministic artifact failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise AdapterError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdapterError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AdapterError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except AdapterError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"invalid UTF-8 JSON in {label}: {exc}") from exc


def _repo_file(relative_text: str) -> Path:
    relative = Path(relative_text)
    if not relative_text or relative.is_absolute() or ".." in relative.parts:
        raise AdapterError(f"unsafe repository path: {relative_text}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise AdapterError(f"missing repository file: {relative_text}") from exc
        if stat.S_ISLNK(mode):
            raise AdapterError(f"repository path traverses symlink: {relative_text}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise AdapterError(f"repository path is not a regular file: {relative_text}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise AdapterError(f"repository path escapes root: {relative_text}") from exc
    return current


def _load_locked(relative: str, expected_sha256: str) -> tuple[Any, str]:
    path = _repo_file(relative)
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 not in ("TO_BE_PINNED", digest):
        raise AdapterError(f"raw source digest drift: {relative}")
    return _strict_json(payload, relative), digest


def _load_local_schema(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AdapterError(f"schema must be a regular non-symlink: {path}")
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 not in ("TO_BE_PINNED", digest):
        raise AdapterError(f"raw schema digest drift: {path}")
    value = _strict_json(payload, str(path))
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise AdapterError(f"invalid schema {path.name}: {exc.message}") from exc
    return value


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise AdapterError(f"{label} schema error at {location}: {error.message}")


def _unique(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise AdapterError(f"missing or duplicate {label} key: {identity!r}")
        result[identity] = row
    return result


def _validate_surface(surface: str, capability_id: str) -> None:
    path_text = surface.split("#", 1)[0]
    try:
        _repo_file(path_text)
    except AdapterError as exc:
        raise AdapterError(
            f"{capability_id}: invalid implementation surface {surface!r}: {exc}"
        ) from exc


def _assert_candidate_payload(candidate: dict[str, Any]) -> None:
    payload = dict(candidate)
    observed = payload.pop("candidate_payload_sha256")
    if observed != _sha_json(payload):
        raise AdapterError("candidate payload digest mismatch")


def _observation_records(descriptions: list[str], prefix: str) -> list[dict[str, str]]:
    return [
        {
            "id": f"{prefix}-{index:02d}",
            "description": description,
        }
        for index, description in enumerate(descriptions, 1)
    ]


def _candidate_adapter(entry: dict[str, Any]) -> dict[str, Any]:
    capability = entry["proposed_capability"]
    capability_id = capability["id"]
    oracle_id = f"oracle.{capability_id}"
    contract = capability["contract"]
    plan = entry["oracle_plan"]
    execution_boundary = plan["execution_boundary"]
    acceptance_class = capability["acceptance_class"]
    expected_boundary = {
        "required_local": "local",
        "alternate_local_lane": "alternate_local",
        "external_optional": "external",
    }[acceptance_class]
    if execution_boundary != expected_boundary:
        raise AdapterError(f"{capability_id}: acceptance/execution boundary drift")
    expected_runtime_state = (
        "not_applicable" if acceptance_class == "external_optional" else "not_qualified"
    )
    if capability["runtime_state"] != expected_runtime_state:
        raise AdapterError(f"{capability_id}: candidate runtime state drift")
    mode = {
        "api": "api",
        "calibration": "runtime",
        "configuration": "config",
        "deployment": "deploy",
        "evaluation": "runtime",
        "model": "model",
        "model_customization": "runtime",
        "performance": "runtime",
        "protocol": "protocol",
        "runtime_behavior": "runtime",
        "security": "deploy",
        "tooling": "static",
    }[capability["kind"]]

    expected_observations = _observation_records(
        plan["required_observations"], "required-observation"
    )
    adjacent_negatives = _observation_records(
        plan["adjacent_negative"], "adjacent-negative"
    )
    assertions = [
        {
            "id": f"assertion.{observation['id']}",
            "observation_id": observation["id"],
            "operator": "recorded_pass",
            "expected": True,
        }
        for observation in expected_observations
    ] + [
        {
            "id": f"assertion.{observation['id']}",
            "observation_id": observation["id"],
            "operator": "recorded_absent",
            "expected": True,
        }
        for observation in adjacent_negatives
    ]
    namespace = f"vss-candidate-{_sha_bytes(capability_id.encode('utf-8'))[:20]}"
    adapter = {
        "capability_id": capability_id,
        "oracle_id": oracle_id,
        "profile_seed": f"candidate-{capability['kind'].replace('_', '-')}",
        "mode_seed": mode,
        "candidate_entry_sha256": _sha_json(entry),
        "manifest_pointer": entry["manifest_pointer"],
        "feature_id": entry["feature_id"],
        "advertised": entry["advertised"],
        "prior_mapping_class": entry["prior_mapping_class"],
        "acceptance_class": acceptance_class,
        "execution_boundary": execution_boundary,
        "source_claims": copy.deepcopy(capability["source_claims"]),
        "implementation_surfaces": copy.deepcopy(contract["implementation_surfaces"]),
        "ledger_binding": {
            key: copy.deepcopy(capability[key])
            for key in (
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
        },
        "reviewed_scenario_ids": [*capability["scenario_ids"], oracle_id],
        "candidate_oracle_plan": copy.deepcopy(plan),
        "fixture": {
            "id": f"fixture.{capability_id}",
            "kind": "candidate_generated_bounded",
            "availability": "not_staged",
            "strategy": plan["fixture_strategy"],
            "namespace": namespace,
            "materialization": None,
            "input_contract": {
                "capability_id": capability_id,
                "manifest_pointer": entry["manifest_pointer"],
                "advertised_literal": entry["advertised"],
                "dependency_capability_ids": copy.deepcopy(
                    contract["dependency_capability_ids"]
                ),
                "implementation_surfaces": copy.deepcopy(
                    contract["implementation_surfaces"]
                ),
                "required_semantics": copy.deepcopy(contract["required_semantics"]),
                "source_claims": copy.deepcopy(capability["source_claims"]),
            },
        },
        "expected_observations": expected_observations,
        "adjacent_negative_observations": adjacent_negatives,
        "assertions": assertions,
        "admission_gates": [
            {
                "id": "candidate-entry-bound",
                "requirement": "candidate entry, source claims, and implementation surfaces are digest-bound",
                "status": "satisfied_static",
            },
            {
                "id": "fixture-materialized",
                "requirement": "fixture path, generator, and digest are materialized",
                "status": "unmet",
            },
            {
                "id": "executor-implemented",
                "requirement": "capability-specific executor is implemented and reviewed",
                "status": "unmet",
            },
            {
                "id": "collectors-implemented",
                "requirement": "observation and cleanup collectors are implemented and reviewed",
                "status": "unmet",
            },
            {
                "id": "operator-approval",
                "requirement": "explicit approval exists before any runtime or external activity",
                "status": "unmet",
            },
        ],
        "cleanup": {
            "intent": plan["cleanup_boundary"],
            "ownership_boundary": "candidate_owned_resources_only",
            "pre_state_required": True,
            "targets": None,
            "allowlist": None,
            "executor": None,
            "postcondition_collectors": None,
        },
        "execution_bounds": {
            "acceptance_class": acceptance_class,
            "execution_boundary": execution_boundary,
            "namespace": namespace,
            "network_scope": {
                "local": "loopback_or_compose_internal",
                "alternate_local": "operator_selected_local_alternate",
                "external": "operator_approved_external_only",
            }[execution_boundary],
            "max_duration_seconds": None,
            "max_requests": None,
            "max_actions": None,
            "executor": None,
            "collectors": None,
        },
        "readiness": {
            "classification": "planning_index_only",
            "fixture_materialized": False,
            "executor_ready": False,
            "blockers": [
                "fixture_not_materialized",
                "executor_not_implemented",
                "collectors_not_implemented",
                "operator_approval_absent",
            ],
        },
        "current_state": (
            "external_boundary_unexecuted"
            if execution_boundary == "external"
            else "open_unexecuted"
        ),
        "runtime_state": expected_runtime_state,
        "evidence": [],
        "can_promote_runtime_state": False,
    }
    return adapter


def compile_adapter() -> dict[str, Any]:
    documents: dict[str, Any] = {}
    locks: dict[str, dict[str, str]] = {}
    for source_id, specification in INPUTS.items():
        value, digest = _load_locked(specification["path"], specification["raw_sha256"])
        documents[source_id] = value
        locks[source_id] = {
            "path": specification["path"],
            "raw_sha256": digest,
        }

    candidate_schema = documents["candidate_schema"]
    capability_schema = documents["official_capabilities_schema"]
    oracle_schema = documents["capability_oracles_schema"]
    for label, schema in (
        ("candidate schema", candidate_schema),
        ("official capabilities schema", capability_schema),
        ("capability oracles schema", oracle_schema),
    ):
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise AdapterError(f"invalid {label}: {exc.message}") from exc

    candidate = documents["candidate"]
    ledger = documents["official_capabilities"]
    oracles = documents["capability_oracles"]
    _validate(candidate, candidate_schema, "candidate")
    _validate(ledger, capability_schema, "official capabilities")
    _validate(oracles, oracle_schema, "capability oracles")
    _assert_candidate_payload(candidate)

    if candidate["summary"]["candidate_entries"] != 211:
        raise AdapterError("candidate denominator drift")
    current_capabilities = _unique(ledger["capabilities"], "id", "capability")
    current_oracles = _unique(oracles["oracles"], "capability_id", "oracle capability")
    current_oracles_by_id = _unique(oracles["oracles"], "oracle_id", "oracle")
    if len(current_capabilities) != 289 or set(current_oracles) != set(
        current_capabilities
    ):
        raise AdapterError("current 289 capability/oracle binding drift")
    if len(current_oracles_by_id) != 289:
        raise AdapterError("current oracle identity drift")
    if not (
        candidate["target"]["product_version"]
        == ledger["target"]["product_version"]
        == oracles["target"]["product_version"]
        and candidate["target"]["main_commit"]
        == ledger["target"]["main_commit"]
        == oracles["target"]["main_commit"]
    ):
        raise AdapterError("target identity drift")

    source_ids = set(_unique(ledger["sources"], "id", "source"))
    adapters: dict[str, dict[str, Any]] = {}
    for entry in candidate["entries"]:
        capability = entry["proposed_capability"]
        capability_id = capability["id"]
        if capability_id in adapters or capability_id in current_capabilities:
            raise AdapterError(
                f"duplicate or colliding candidate capability key: {capability_id}"
            )
        for claim in capability["source_claims"]:
            if claim["source_id"] not in source_ids:
                raise AdapterError(f"{capability_id}: source claim drift")
            if claim["locator"].lstrip().startswith("Advertised "):
                raise AdapterError(
                    f"{capability_id}: synthetic advertised source locator"
                )
        for surface in capability["contract"]["implementation_surfaces"]:
            _validate_surface(surface, capability_id)
        adapter = _candidate_adapter(entry)
        authoritative = adapter["candidate_oracle_plan"].get(
            "authoritative_gap_requirement"
        )
        gap_binding = entry.get("gap_plan_binding")
        if entry["prior_mapping_class"] == "explicit_missing_entry_gap":
            if authoritative is None or authoritative != gap_binding:
                raise AdapterError(
                    f"{capability_id}: authoritative gap requirement binding drift"
                )
        elif authoritative is not None or gap_binding is not None:
            raise AdapterError(f"{capability_id}: family-only gap binding drift")
        adapters[capability_id] = adapter
    if len(adapters) != 211 or len(set(adapters) | set(current_capabilities)) != 500:
        raise AdapterError("candidate adapter key partition drift")

    preserved: dict[str, dict[str, Any]] = {}
    for capability_id, oracle in current_oracles.items():
        capability = current_capabilities[capability_id]
        expected_ledger_binding = {
            key: capability[key]
            for key in (
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
        }
        if (
            oracle["oracle_id"] != f"oracle.{capability_id}"
            or oracle["ledger_binding"] != expected_ledger_binding
        ):
            raise AdapterError(
                f"{capability_id}: current oracle semantic binding drift"
            )
        preserved[capability_id] = {
            "oracle_id": oracle["oracle_id"],
            "current_state": oracle["current_state"],
            "ledger_runtime_state": capability["runtime_state"],
            "evidence": copy.deepcopy(oracle["evidence"]),
            "state_evidence_sha256": _sha_json(
                {
                    "current_state": oracle["current_state"],
                    "ledger_runtime_state": capability["runtime_state"],
                    "evidence": oracle["evidence"],
                }
            ),
        }

    candidate_state_counts = dict(
        sorted(Counter(row["current_state"] for row in adapters.values()).items())
    )
    candidate_runtime_counts = dict(
        sorted(Counter(row["runtime_state"] for row in adapters.values()).items())
    )
    current_state_counts = dict(
        sorted(Counter(row["current_state"] for row in preserved.values()).items())
    )
    current_runtime_counts = dict(
        sorted(
            Counter(row["ledger_runtime_state"] for row in preserved.values()).items()
        )
    )
    candidate_evidence_count = sum(len(row["evidence"]) for row in adapters.values())
    current_evidence_count = sum(len(row["evidence"]) for row in preserved.values())
    executor_ready_count = sum(
        row["readiness"]["executor_ready"] for row in adapters.values()
    )
    promoted_count = sum(
        row["runtime_state"] in {"passed_current", "passed"}
        for row in adapters.values()
    )
    if candidate_evidence_count or executor_ready_count or promoted_count:
        raise AdapterError(
            "candidate adapter cannot be executor-ready, evidenced, or promoted"
        )

    output = {
        "schema_version": 1,
        "adapter_id": "vss-3.2.1-thor-candidate-oracle-adapter-211",
        "mode": "candidate_only_planning_index",
        "target": copy.deepcopy(candidate["target"]),
        "source_locks": locks,
        "policy": {
            "candidate_only": True,
            "can_modify_live_ledgers_or_oracles": False,
            "can_mark_passed_current": False,
            "runtime_evidence": [],
            "executor_materialization": "absent",
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "candidate_adapter_count": len(adapters),
            "preserved_current_oracle_count": len(preserved),
            "combined_capability_count": len(adapters) + len(preserved),
            "explicit_gap_requirement_count": sum(
                "authoritative_gap_requirement" in row["candidate_oracle_plan"]
                for row in adapters.values()
            ),
            "candidate_execution_boundary_counts": dict(
                sorted(
                    Counter(
                        row["execution_boundary"] for row in adapters.values()
                    ).items()
                )
            ),
            "candidate_state_counts": candidate_state_counts,
            "candidate_runtime_state_counts": candidate_runtime_counts,
            "current_oracle_state_counts": current_state_counts,
            "current_ledger_runtime_state_counts": current_runtime_counts,
            "candidate_evidence_record_count": candidate_evidence_count,
            "current_evidence_record_count": current_evidence_count,
            "candidate_executor_ready_count": executor_ready_count,
            "candidate_promoted_count": promoted_count,
        },
        "current_oracle_preservation": {
            "ledger_records_canonical_sha256": _sha_json(ledger["capabilities"]),
            "oracle_records_canonical_sha256": _sha_json(oracles["oracles"]),
            "state_evidence_projection_sha256": _sha_json(preserved),
            "by_capability_id": preserved,
        },
        "candidate_adapters_by_capability_id": adapters,
    }
    output["adapter_payload_sha256"] = _sha_json(output)
    return output


def validate_adapter(adapter: dict[str, Any]) -> None:
    schema = _load_local_schema(SCHEMA, SCHEMA_RAW_SHA256)
    _validate(adapter, schema, "adapter")
    payload = dict(adapter)
    observed = payload.pop("adapter_payload_sha256")
    if observed != _sha_json(payload):
        raise AdapterError("adapter payload digest mismatch")
    if EXPECTED_OUTPUT_PAYLOAD_SHA256 not in ("TO_BE_PINNED", observed):
        raise AdapterError("adapter payload lock drift")


def _atomic_write_regular(path: Path, payload: bytes) -> None:
    if path.is_symlink():
        raise AdapterError(f"refusing to replace symlink output: {path}")
    if path.exists() and not path.is_file():
        raise AdapterError(f"output is not a regular file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.is_symlink() or not temporary.is_file():
            raise AdapterError(f"temporary output is not a regular file: {temporary}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        adapter = compile_adapter()
        validate_adapter(adapter)
        encoded = _encoded(adapter)
        if args.write:
            _atomic_write_regular(OUTPUT, encoded)
            print(f"WROTE: {OUTPUT.relative_to(REPO_ROOT)}")
            return 0
        checked, digest = _load_locked(
            str(OUTPUT.relative_to(REPO_ROOT)), EXPECTED_OUTPUT_RAW_SHA256
        )
        if checked != adapter or OUTPUT.read_bytes() != encoded:
            raise AdapterError("checked adapter differs from deterministic compile")
        print(
            "PASS: candidate oracle adapter; candidates=211, current_preserved=289, "
            "executor_ready=0, runtime_evidence=0, promoted=0"
        )
        return 0
    except (AdapterError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
