#!/usr/bin/env python3
"""Compile and fake-simulate a bounded future VIOS remediation collector.

This module deliberately has no live execution path.  The command-line surface
only emits an inert plan. ``simulate_fake_transport`` consumes bounded plain
built-in transcript data; it never invokes a caller callback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
SIMULATION_SCHEMA_PATH = HERE / "simulation.schema.json"
MAX_JSON_BYTES = 32 * 1024 * 1024


class CollectorError(RuntimeError):
    """Fail-closed configuration or fake-simulation error."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    # Preserve parsed key order to match the canonical runtime-bound audit.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _bounded_read(path: Path, maximum: int = MAX_JSON_BYTES) -> bytes:
    if type(maximum) is not int or not 1 <= maximum <= MAX_JSON_BYTES:
        raise CollectorError("invalid read bound")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CollectorError(f"cannot open locked source: {path.name}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise CollectorError(f"invalid locked source: {path.name}")
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
            raise CollectorError(f"locked source changed while reading: {path.name}")
        return raw
    finally:
        os.close(descriptor)


def _strict_json_bytes(raw: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CollectorError(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        return json.loads(
            raw.decode(),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                CollectorError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except CollectorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectorError(f"invalid JSON: {label}") from exc


def _json(path: Path, label: str) -> Any:
    return _strict_json_bytes(_bounded_read(path), label)


def _validate(instance: Any, schema_path: Path, label: str) -> None:
    schema = _json(schema_path, f"{label} schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CollectorError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: [str(item) for item in error.absolute_path],
    )
    if errors:
        location = "/" + "/".join(str(item) for item in errors[0].absolute_path)
        raise CollectorError(f"{label} schema violation at {location}")


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise CollectorError("unsafe source lock path")
    current = REPO_ROOT
    for part in candidate.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise CollectorError(f"missing source lock: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise CollectorError(f"symlinked source lock: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise CollectorError(f"source lock escaped repository: {relative}") from exc
    return current


def _unique(items: Any, key: str, expected: Any, label: str) -> dict[str, Any]:
    if not isinstance(items, list):
        raise CollectorError(f"invalid {label} collection")
    matches = [
        item for item in items if isinstance(item, dict) and item.get(key) == expected
    ]
    if len(matches) != 1:
        raise CollectorError(f"expected exactly one {label}")
    return matches[0]


def _load_contract() -> dict[str, Any]:
    contract = _json(CONTRACT_PATH, "contract")
    _validate(contract, CONTRACT_SCHEMA_PATH, "contract")
    return contract


def _load_locked_sources(contract: dict[str, Any]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for lock in contract["source_locks"]:
        relative = lock["path"]
        raw = _bounded_read(_repo_file(relative))
        if _sha256(raw) != lock["sha256"]:
            raise CollectorError(f"source lock digest drift: {relative}")
        result[relative] = raw
    return result


def _assert_exact_bindings(
    contract: dict[str, Any], sources: dict[str, bytes]
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = contract["canonical_binding"]
    oracle_path = binding["capability_oracles_path"]
    oracle_doc = _strict_json_bytes(sources[oracle_path], "capability oracles")
    index = binding["canonical_oracle_index"]
    try:
        oracle = oracle_doc["oracles"][index]
    except (KeyError, IndexError, TypeError) as exc:
        raise CollectorError("canonical oracle index does not resolve") from exc
    if (
        oracle.get("oracle_id") != contract["oracle_id"]
        or oracle.get("capability_id") != contract["capability_id"]
        or _sha256(_canonical_bytes(oracle)) != binding["canonical_oracle_sha256"]
    ):
        raise CollectorError("canonical oracle binding drift")

    bounds = oracle.get("execution_bounds", {})
    if (
        bounds.get("max_requests") != 8
        or bounds.get("max_actions") != 9
        or bounds.get("warehouse_sample_bundle") != "excluded"
        or bounds.get("workload", {}).get("phases")
        != ["pre_state", "positive", "adjacent_negative", "restore", "postcondition"]
    ):
        raise CollectorError("canonical execution bounds drift")

    integrations_path = binding["verified_integrations_path"]
    integrations = _strict_json_bytes(
        sources[integrations_path], "verified integrations"
    )
    integration = _unique(
        integrations.get("cases"),
        "planning_requirement_id",
        contract["planning_requirement_id"],
        "verified integration",
    )
    required = {
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "canonical_oracle_index": index,
        "canonical_oracle_sha256": binding["canonical_oracle_sha256"],
        "integrated_max_requests": 8,
        "integrated_max_actions": 9,
        "integration_verified": True,
    }
    if any(integration.get(key) != value for key, value in required.items()):
        raise CollectorError("verified integration binding drift")

    acceptance_path = binding["acceptance_inventory_path"]
    acceptance = _strict_json_bytes(sources[acceptance_path], "acceptance inventory")
    requirement = _unique(
        acceptance.get("wave3_contracts", {}).get("planning_requirements"),
        "id",
        contract["planning_requirement_id"],
        "planning requirement",
    )
    if (
        requirement.get("owner_id") != contract["capability_id"]
        or requirement.get("payload_canonical_sha256")
        != binding["planning_payload_canonical_sha256"]
    ):
        raise CollectorError("planning requirement binding drift")
    return oracle, integration


def _assert_fixture(
    contract: dict[str, Any], sources: dict[str, bytes]
) -> tuple[dict[str, Any], str]:
    fixture_binding = contract["fixture_binding"]
    manifest = _strict_json_bytes(
        sources[fixture_binding["manifest_path"]], "local20 manifest"
    )
    fixture = _strict_json_bytes(
        sources[fixture_binding["fixture_path"]], "VIOS remediation fixture"
    )
    schema_path = fixture_binding["fixture_schema_path"]
    schema = _strict_json_bytes(sources[schema_path], "local20 fixture schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CollectorError("invalid locked local20 fixture schema") from exc
    if list(Draft202012Validator(schema).iter_errors(fixture)):
        raise CollectorError("VIOS remediation fixture schema drift")

    entry = _unique(
        manifest.get("json_fixtures"),
        "fixture_id",
        fixture_binding["fixture_id"],
        "local20 fixture manifest entry",
    )
    fixture_digest = _sha256(sources[fixture_binding["fixture_path"]])
    if (
        entry.get("path") != "fixtures/vios-remediation.json"
        or entry.get("raw_sha256") != fixture_digest
        or contract["planning_requirement_id"] not in entry.get("covers", [])
        or fixture.get("fixture_id") != fixture_binding["fixture_id"]
    ):
        raise CollectorError("local20 VIOS fixture binding drift")

    expected_fixture = {
        "schema_version": 1,
        "fixture_id": "local20-vios-remediation-v1",
        "failing_media_recipe_id": "tiny-bframe-failing-mp4-v1",
        "reference_media_recipe_id": "tiny-bframe-reference-mp4-v1",
        "expected_failure": {
            "stage": "vios_playback",
            "reason_code": "b_frames_not_supported",
            "retryable_without_transcode": False,
        },
        "remediation": {
            "operation": "local_transcode",
            "input_recipe_id": "tiny-bframe-failing-mp4-v1",
            "output_recipe_id": "tiny-bframe-reference-mp4-v1",
            "preserve_source": True,
        },
        "expected_result": {
            "playback": "ready",
            "source_identity_unchanged": True,
            "derived_identity_distinct": True,
        },
    }
    if fixture != expected_fixture:
        raise CollectorError("VIOS remediation fixture semantics drift")
    return fixture, fixture_digest


def compile_plan() -> dict[str, Any]:
    """Compile a source-locked, non-promoting future workflow plan."""
    contract = _load_contract()
    sources = _load_locked_sources(contract)
    oracle, integration = _assert_exact_bindings(contract, sources)
    _, fixture_digest = _assert_fixture(contract, sources)
    workflow = contract["workflow"]
    if (
        len(workflow) != 9
        or sum(step["request_cost"] for step in workflow) != 8
        or len({step["id"] for step in workflow}) != 9
    ):
        raise CollectorError("workflow does not match exact canonical bounds")

    plan = {
        "schema_version": 1,
        "collector_id": contract["collector_id"],
        "mode": "offline-inert-plan-only",
        "status": "pass",
        "promotion_eligible": False,
        "runtime_actions": 0,
        "runtime_requests": 0,
        "planning_requirement_id": contract["planning_requirement_id"],
        "capability_id": contract["capability_id"],
        "oracle_id": contract["oracle_id"],
        "canonical_binding": {
            "canonical_oracle_index": contract["canonical_binding"][
                "canonical_oracle_index"
            ],
            "canonical_oracle_sha256": _sha256(_canonical_bytes(oracle)),
            "integrated_workflow_sha256": integration["expanded_workflow_sha256"],
        },
        "fixture": {
            "fixture_id": contract["fixture_binding"]["fixture_id"],
            "fixture_sha256": fixture_digest,
            "media_materialized": False,
        },
        "execution_bounds": contract["execution_bounds"],
        "workflow": workflow,
        "ownership": contract["ownership"],
        "cleanup": contract["cleanup"],
        "evidence_scope": contract["evidence_scope"],
    }
    _validate(plan, PLAN_SCHEMA_PATH, "plan")
    return plan


def _plain_json(value: Any) -> bool:
    if value is None or type(value) in {str, int, bool}:
        return True
    if type(value) is list:
        return all(_plain_json(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _plain_json(item) for key, item in value.items()
        )
    return False


def simulate_fake_transport(transcript: dict[str, Any]) -> dict[str, Any]:
    """Validate a bounded plain-data fake transcript; never call caller code."""
    plan = compile_plan()
    expected_ids = [step["id"] for step in plan["workflow"]]
    if (
        type(transcript) is not dict
        or set(transcript) != {"transport_kind", "observations"}
        or transcript.get("transport_kind") != "offline-test-transcript-v1"
        or type(transcript.get("observations")) is not dict
        or list(transcript["observations"]) != expected_ids
        or not _plain_json(transcript)
        or len(json.dumps(transcript, separators=(",", ":")).encode()) > 65536
    ):
        raise CollectorError(
            "only an exact bounded plain-data fake transcript is admitted"
        )
    observations: list[dict[str, Any]] = []
    for step in plan["workflow"]:
        observed = transcript["observations"][step["id"]]
        if type(observed) is not dict:
            raise CollectorError(f"fake observation is not an object: {step['id']}")
        observations.append(
            {"sequence": step["sequence"], "step_id": step["id"], **observed}
        )

    result = {
        "schema_version": 1,
        "collector_id": plan["collector_id"],
        "mode": "offline-fake-simulation",
        "status": "pass",
        "promotion_eligible": False,
        "runtime_actions": 0,
        "runtime_requests": 0,
        "simulated_actions": len(observations),
        "simulated_requests": sum(step["request_cost"] for step in plan["workflow"]),
        "planning_requirement_id": plan["planning_requirement_id"],
        "capability_id": plan["capability_id"],
        "oracle_id": plan["oracle_id"],
        "fixture_sha256": plan["fixture"]["fixture_sha256"],
        "observations": observations,
        "blockers": plan["evidence_scope"]["late_effect_blockers"],
    }
    _validate(result, SIMULATION_SCHEMA_PATH, "fake simulation")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile the offline-only VIOS playback remediation plan"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("plan",),
        default="plan",
        help="Only inert plan compilation is supported",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        print(json.dumps(compile_plan(), indent=2, sort_keys=True))
    except CollectorError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
