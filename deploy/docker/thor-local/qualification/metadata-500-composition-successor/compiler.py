#!/usr/bin/env python3
"""Compile a static proof for the composed VSS 500-capability metadata plane."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
OUTPUT = PACKAGE / "composition.json"
SCHEMA = PACKAGE / "composition.schema.json"
MAX_JSON_BYTES = 64_000_000

# The aggregate and verifier locks are replaced only after the policy patch settles.
INPUTS = {
    "ledger_proof": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projection.json",
        "raw_sha256": "4e206240795e2cf739f595811920ae66a7868ebe92031feb73b7fcbbe5a971d0",
        "json": True,
    },
    "ledger_proof_schema": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projection.schema.json",
        "raw_sha256": "8f74b849581029c303a1e7a927f1f31b7458ed87e529d14e25134e52396f4ec9",
        "json": True,
    },
    "ledger_manifest": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-manifest.json",
        "raw_sha256": "075a859219dfee4982338ca04244b6d444e0c23c9666c88e58e8f5fe58c366e8",
        "json": True,
    },
    "ledger": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-official-capabilities.json",
        "raw_sha256": "f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6",
        "json": True,
    },
    "official_schema": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "raw_sha256": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
        "json": True,
    },
    "oracle_proof": {
        "path": "deploy/docker/thor-local/qualification/oracle-500-successor/capability-oracles-500.json",
        "raw_sha256": "75a7c6b6ecc5bcfee0eece99a10ca29c0258717887c59847252629ac4d21e364",
        "json": True,
    },
    "oracle_schema": {
        "path": "deploy/docker/thor-local/qualification/oracle-500-successor/capability-oracles-500.schema.json",
        "raw_sha256": "fcbe27337accc57c5a57a3ce7bf26d1e532c9001f7841134ec22db8663d41024",
        "json": True,
    },
    "aggregate_proof": {
        "path": "deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/projection.json",
        "raw_sha256": "65583c243381ab36f9804d66fa58299bf0cb3d1a3685d76d8af70c2fd5b029a3",
        "json": True,
    },
    "aggregate_proof_schema": {
        "path": "deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/projection.schema.json",
        "raw_sha256": "b1794e3ebeada0dfede9f96195b47c4eecda4fad6676f0080ced0036090da2cf",
        "json": True,
    },
    "aggregate_manifest": {
        "path": "deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/projected-manifest.json",
        "raw_sha256": "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
        "json": True,
    },
    "aggregate_manifest_schema": {
        "path": "deploy/docker/thor-local/qualification/manifest-500-aggregate-successor/projected-manifest.schema.json",
        "raw_sha256": "95d981d86879a2ac6e5a69c2f0a2c154d826f54ce15d87f773c0048f39c7ed48",
        "json": True,
    },
    "acceptance_proof": {
        "path": "deploy/docker/thor-local/qualification/acceptance-500-successor/projection.json",
        "raw_sha256": "dd65544dc587e01f0bb1ffd50442c9903a6d6200b0722d83a709902ec99d598c",
        "json": True,
    },
    "acceptance_proof_schema": {
        "path": "deploy/docker/thor-local/qualification/acceptance-500-successor/projection.schema.json",
        "raw_sha256": "4c744244333382200fc2d551e9c02ff2d01c3d5dd2d839353c4ffa0ca793ea0c",
        "json": True,
    },
    "acceptance": {
        "path": "deploy/docker/thor-local/qualification/acceptance-500-successor/projected-acceptance-inventory.json",
        "raw_sha256": "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
        "json": True,
    },
    "acceptance_schema": {
        "path": "deploy/docker/thor-local/qualification/acceptance-500-successor/projected-acceptance-inventory.schema.json",
        "raw_sha256": "848d84b976906c3059b67218cf1d6bf3960b8b91c620c663bba398f5b302278a",
        "json": True,
    },
    "official_verifier": {
        "path": "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        "raw_sha256": "c21fd2910089c6981f0437d41d6c9ef7fff19d55c0153b04b7f7f91b00d79109",
        "json": False,
    },
    "live_manifest": {
        "path": "deploy/docker/thor-local/parity/manifest.json",
        "raw_sha256": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
        "json": True,
    },
    "live_ledger": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.json",
        "raw_sha256": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
        "json": True,
    },
    "live_oracles": {
        "path": "deploy/docker/thor-local/parity/capability-oracles.json",
        "raw_sha256": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
        "json": True,
    },
    "live_acceptance": {
        "path": "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        "raw_sha256": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
        "json": True,
    },
}

EXPECTED_OUTPUT_RAW_SHA256 = (
    "600f2ee62b19862c81c23f2a7f2e95ff40f8a5c6e400ce5129f661f5f1a8538c"
)
EXPECTED_SCHEMA_RAW_SHA256 = (
    "fcb09884ecc345cedafdbb63997783bbb87c6f8336d9e9813a8ba9869887c12e"
)
EXPECTED_PAYLOAD_SHA256 = (
    "37f8b32b77e849d4328d8dfdc24428fc97f998f0eb70f473e87cc3ffeace3570"
)


class CompositionError(RuntimeError):
    """A source lock or composition invariant failed."""


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
        raise CompositionError(f"oversized JSON input: {label}")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise CompositionError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise CompositionError(f"non-finite JSON number in {label}: {value}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise CompositionError(f"invalid UTF-8 JSON input: {label}") from exc
    except json.JSONDecodeError as exc:
        raise CompositionError(f"invalid JSON input: {label}: {exc.msg}") from exc


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise CompositionError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise CompositionError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise CompositionError(f"repository input contains symlink: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise CompositionError(f"repository input escapes root: {relative}") from exc
    if not stat.S_ISREG(current.stat().st_mode):
        raise CompositionError(f"repository input is not regular: {relative}")
    return current


def _load_locked(relative: str, expected: str, *, parse_json: bool) -> tuple[Any, str]:
    payload = _repo_file(relative).read_bytes()
    digest = _sha_bytes(payload)
    if digest != expected:
        raise CompositionError(f"raw source digest drift: {relative}")
    return (_strict_json(payload, relative) if parse_json else payload), digest


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(item) for item in error.absolute_path)
        raise CompositionError(f"{label} schema error at {location}: {error.message}")


def _assert_payload(value: dict[str, Any], field: str, label: str) -> None:
    payload = dict(value)
    observed = payload.pop(field)
    if observed != _sha_json(payload):
        raise CompositionError(f"{label} payload digest mismatch")


def _unique(rows: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CompositionError(f"invalid rows: {label}")
    result = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise CompositionError(f"invalid or duplicate identity: {label}")
        result[identity] = row
    return result


def _derive_family_status(group: list[dict[str, Any]]) -> dict[str, str]:
    classes = {row["acceptance_class"] for row in group}
    acceptance_class = (
        "required_local"
        if "required_local" in classes
        else "external_optional"
        if classes == {"external_optional"}
        else "alternate_local_lane"
    )
    thor_states = {row["thor_state"] for row in group}
    thor_state = next(iter(thor_states)) if len(thor_states) == 1 else "partial"
    if acceptance_class == "external_optional":
        thor_state = "external_optional"
    runtime_states = {row["runtime_state"] for row in group}
    runtime_state = (
        next(iter(runtime_states)) if len(runtime_states) == 1 else "not_qualified"
    )
    return {
        "acceptance_class": acceptance_class,
        "thor_state": thor_state,
        "runtime_state": runtime_state,
    }


def _policy_aggregate_drift(
    manifest: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for capability in ledger["capabilities"]:
        groups.setdefault(capability["feature_id"], []).append(capability)
    result = []
    for index, feature in enumerate(manifest["features"]):
        derived = _derive_family_status(groups[feature["id"]])
        differing = [
            field
            for field in ("acceptance_class", "thor_state", "runtime_state")
            if feature[field] != derived[field]
        ]
        if differing:
            result.append(
                {
                    "feature_index": index,
                    "feature_id": feature["id"],
                    "differing_fields": differing,
                    "derived": derived,
                }
            )
    return result


def _acceptance_gaps(
    ledger: dict[str, Any], acceptance: dict[str, Any]
) -> list[dict[str, Any]]:
    scenarios = set(_unique(acceptance["scenarios"], "id", "scenario"))
    coverage = _unique(
        acceptance["coverage"]["features"], "feature_id", "feature coverage"
    )
    required: dict[str, set[str]] = {}
    for capability in ledger["capabilities"]:
        linked = capability["scenario_ids"]
        if len(linked) != len(set(linked)) or not set(linked) <= scenarios:
            raise CompositionError(f"{capability['id']}: scenario identity drift")
        required.setdefault(capability["feature_id"], set()).update(linked)
    result = []
    for feature_id, scenario_ids in required.items():
        missing = sorted(scenario_ids - set(coverage[feature_id]["scenario_ids"]))
        if missing:
            result.append({"feature_id": feature_id, "missing_scenario_ids": missing})
    return result


def _load_official_verifier() -> Any:
    parity = REPO_ROOT / "deploy/docker/thor-local/parity"
    path = _repo_file(INPUTS["official_verifier"]["path"])
    specification = importlib.util.spec_from_file_location(
        "metadata_500_authoritative_official_verifier", path
    )
    if specification is None or specification.loader is None:
        raise CompositionError("cannot load authoritative official verifier")
    module = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(parity))
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _authoritative_validate(
    ledger: dict[str, Any], manifest: dict[str, Any], acceptance: dict[str, Any]
) -> dict[str, int]:
    verifier = _load_official_verifier()
    try:
        counts = verifier.validate(
            ledger=ledger,
            manifest=manifest,
            acceptance=acceptance,
            repo_root=REPO_ROOT,
        )
    except Exception as exc:
        raise CompositionError(
            f"authoritative official validation failed: {exc}"
        ) from exc
    expected = {
        "sources": 126,
        "capabilities": 500,
        "feature_families": 55,
        "discrepancies": 47,
    }
    if counts != expected:
        raise CompositionError("authoritative official validation count drift")
    return counts


def _validate_source_packages(documents: dict[str, Any]) -> None:
    pairs = (
        ("ledger_proof", "ledger_proof_schema"),
        ("ledger", "official_schema"),
        ("oracle_proof", "oracle_schema"),
        ("aggregate_proof", "aggregate_proof_schema"),
        ("aggregate_manifest", "aggregate_manifest_schema"),
        ("acceptance_proof", "acceptance_proof_schema"),
        ("acceptance", "acceptance_schema"),
    )
    for document_name, schema_name in pairs:
        schema = documents[schema_name]
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise CompositionError(
                f"invalid source schema {schema_name}: {exc.message}"
            ) from exc
        _validate(documents[document_name], schema, document_name)
    for name, field in (
        ("ledger_proof", "projection_payload_sha256"),
        ("oracle_proof", "successor_payload_sha256"),
        ("aggregate_proof", "projection_payload_sha256"),
        ("acceptance_proof", "projection_payload_sha256"),
    ):
        _assert_payload(documents[name], field, name)


def _validate_cross_bindings(documents: dict[str, Any]) -> dict[str, Any]:
    ledger = documents["ledger"]
    manifest = documents["aggregate_manifest"]
    acceptance = documents["acceptance"]
    ledger_proof = documents["ledger_proof"]
    aggregate_proof = documents["aggregate_proof"]
    acceptance_proof = documents["acceptance_proof"]
    if ledger_proof["artifacts"]["projected_official_capabilities"] != {
        "path": INPUTS["ledger"]["path"],
        "raw_sha256": INPUTS["ledger"]["raw_sha256"],
        "canonical_sha256": _sha_json(ledger),
    }:
        raise CompositionError("ledger successor artifact cross-binding drift")
    if aggregate_proof["artifacts"]["projected_manifest"] != {
        "path": INPUTS["aggregate_manifest"]["path"],
        "raw_sha256": INPUTS["aggregate_manifest"]["raw_sha256"],
        "canonical_sha256": _sha_json(manifest),
    }:
        raise CompositionError("aggregate successor artifact cross-binding drift")
    if acceptance_proof["artifacts"]["projected_acceptance_inventory"] != {
        "path": INPUTS["acceptance"]["path"],
        "raw_sha256": INPUTS["acceptance"]["raw_sha256"],
    }:
        raise CompositionError("acceptance successor artifact cross-binding drift")
    oracles = documents["oracle_proof"]["projected_oracles"]
    capabilities = ledger["capabilities"]
    if len(capabilities) != 500 or len(oracles) != 500:
        raise CompositionError("500 capability/oracle denominator drift")
    capability_ids = [row["id"] for row in capabilities]
    oracle_ids = [row["capability_id"] for row in oracles]
    if capability_ids != oracle_ids or len(set(capability_ids)) != 500:
        raise CompositionError("500 capability/oracle identity-order drift")
    for capability, oracle in zip(capabilities, oracles, strict=True):
        if oracle["ledger_binding"] != {
            key: capability[key]
            for key in (
                "title",
                "feature_id",
                "kind",
                "thor_state",
                "acceptance_class",
                "runtime_state",
                "source_claims",
                "gap",
                "contract",
            )
        }:
            raise CompositionError(f"{capability['id']}: oracle ledger binding drift")
    ledger_manifest = documents["ledger_manifest"]
    if [row["id"] for row in manifest["features"]] != [
        row["id"] for row in ledger_manifest["features"]
    ]:
        raise CompositionError("aggregate/ledger manifest feature order drift")
    for before, after in zip(
        ledger_manifest["features"], manifest["features"], strict=True
    ):
        for key in before:
            if (
                key not in {"acceptance_class", "thor_state", "runtime_state"}
                and before[key] != after[key]
            ):
                raise CompositionError(f"{before['id']}: aggregate cross-swap drift")
    aggregate_drift = _policy_aggregate_drift(manifest, ledger)
    acceptance_gaps = _acceptance_gaps(ledger, acceptance)
    if aggregate_drift or acceptance_gaps:
        raise CompositionError("composed metadata retains aggregate/acceptance drift")
    counts = _authoritative_validate(ledger, manifest, acceptance)
    return {
        "capability_ids": capability_ids,
        "oracle_ids": oracle_ids,
        "aggregate_drift": aggregate_drift,
        "acceptance_gaps": acceptance_gaps,
        "authoritative_counts": counts,
    }


def _validate_live_predecessor(documents: dict[str, Any]) -> dict[str, Any]:
    live_ledger = documents["live_ledger"]
    live_manifest = documents["live_manifest"]
    live_oracles = documents["live_oracles"]
    live_acceptance = documents["live_acceptance"]
    if (
        len(live_ledger["capabilities"]) != 289
        or len(live_oracles["oracles"]) != 289
        or len(live_manifest["features"]) != 55
        or len(live_acceptance["coverage"]["features"]) != 55
    ):
        raise CompositionError("live predecessor denominator drift")
    if [row["id"] for row in live_ledger["capabilities"]] != [
        row["capability_id"] for row in live_oracles["oracles"]
    ]:
        raise CompositionError("live ledger/oracle identity order drift")
    return {
        "capability_count": 289,
        "oracle_count": 289,
        "feature_count": 55,
        "acceptance_feature_count": 55,
        "live_capability_order_sha256": _sha_json(
            [row["id"] for row in live_ledger["capabilities"]]
        ),
        "live_oracle_order_sha256": _sha_json(
            [row["capability_id"] for row in live_oracles["oracles"]]
        ),
    }


def _candidate_boundary(documents: dict[str, Any]) -> dict[str, Any]:
    rows = documents["oracle_proof"]["projected_oracles"][289:]
    if len(rows) != 211:
        raise CompositionError("candidate oracle denominator drift")
    if any(
        row["evidence"]
        or row["can_promote_runtime_state"]
        or row["readiness"]["executor_ready"]
        or row["fixture"]["materialization"] is not None
        or any(
            row["execution_bounds"][key] is not None
            for key in (
                "max_duration_seconds",
                "max_requests",
                "max_actions",
                "executor",
                "collectors",
            )
        )
        or any(
            row["cleanup"][key] is not None
            for key in ("targets", "allowlist", "executor", "postcondition_collectors")
        )
        or (
            row["protocol_v2_binding"] is not None
            and row["protocol_v2_binding"]["activation_supported"] is not False
        )
        for row in rows
    ):
        raise CompositionError("candidate oracle executable/evidence boundary drift")
    return {
        "candidate_oracle_count": 211,
        "candidate_executor_ready_count": 0,
        "candidate_evidence_record_count": 0,
        "candidate_promotable_count": 0,
        "candidate_fixture_materialized_count": 0,
        "historical_live_oracle_migration_pending": True,
    }


def compile_composition() -> tuple[dict[str, Any], dict[str, Any]]:
    documents: dict[str, Any] = {}
    locks: dict[str, dict[str, str]] = {}
    for source_id, specification in INPUTS.items():
        value, digest = _load_locked(
            specification["path"],
            specification["raw_sha256"],
            parse_json=specification["json"],
        )
        documents[source_id] = value
        locks[source_id] = {
            "path": specification["path"],
            "raw_sha256": digest,
        }
    _validate_source_packages(documents)
    composition = _validate_cross_bindings(documents)
    predecessor = _validate_live_predecessor(documents)
    candidate_boundary = _candidate_boundary(documents)
    output = {
        "schema_version": 1,
        "composition_id": "vss-3.2.1-thor-metadata-500-successor",
        "mode": "isolated_static_metadata_composition",
        "source_locks": locks,
        "policy": {
            "candidate_only": True,
            "modifies_live_files": False,
            "live_merge_ready": False,
            "runtime_execution": "forbidden",
            "network_access": False,
            "docker_access": False,
            "host_inspection": False,
            "model_execution": False,
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
        },
        "authoritative_validation": {
            "verifier_source_id": "official_verifier",
            "result": "passed",
            **composition["authoritative_counts"],
            "policy_aggregate_drift": composition["aggregate_drift"],
            "acceptance_scenario_coverage_gaps": composition["acceptance_gaps"],
        },
        "identity_order": {
            "projected_capability_count": len(composition["capability_ids"]),
            "projected_oracle_count": len(composition["oracle_ids"]),
            "projected_capability_order_sha256": _sha_json(
                composition["capability_ids"]
            ),
            "projected_oracle_order_sha256": _sha_json(composition["oracle_ids"]),
            "orders_equal": True,
        },
        "live_predecessor": predecessor,
        "candidate_oracle_boundary": candidate_boundary,
        "remaining_blockers": [
            {
                "id": "live-metadata-merge-pending",
                "classification": "metadata_migration",
                "detail": "The composed 500-row artifacts remain isolated successors; live manifest, ledger, acceptance inventory, and oracle registry remain predecessor files.",
            },
            {
                "id": "candidate-oracle-execution-pending",
                "classification": "runtime_qualification",
                "detail": "All 211 candidate oracles remain non-executable planning records with no runtime evidence or promotion authority.",
            },
            {
                "id": "historical-live-oracle-migration-pending",
                "classification": "oracle_registry_migration",
                "detail": "The live oracle registry remains at 289 records; the ordered 500-row successor has not replaced it.",
            },
        ],
        "summary": {
            "metadata_plane_validation_passed": True,
            "capability_count": 500,
            "feature_family_count": 55,
            "source_discrepancy_count": 47,
            "policy_aggregate_drift_count": 0,
            "acceptance_coverage_gap_count": 0,
            "projected_oracle_count": 500,
            "candidate_oracle_count": 211,
            "candidate_evidence_record_count": 0,
            "remaining_blocker_count": 3,
            "live_capability_count": 289,
            "live_oracle_count": 289,
        },
    }
    output["composition_payload_sha256"] = _sha_json(output)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://developer.nvidia.com/vss/thor-local/metadata-500-composition.schema.json",
        "title": "VSS Thor-local exact metadata-500 composition proof",
        "const": output,
    }
    Draft202012Validator.check_schema(schema)
    _validate(output, schema, "metadata composition")
    return output, schema


def validate_composition(output: dict[str, Any], schema: dict[str, Any]) -> None:
    _validate(output, schema, "metadata composition")
    payload = dict(output)
    observed = payload.pop("composition_payload_sha256")
    if observed != _sha_json(payload) or observed != EXPECTED_PAYLOAD_SHA256:
        raise CompositionError("composition payload lock drift")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise CompositionError(f"unsafe output parent: {path.parent}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CompositionError(f"unsafe output path: {path}")
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
            raise CompositionError(f"unsafe temporary output: {temporary}")
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        output, schema = compile_composition()
        validate_composition(output, schema)
        outputs = {OUTPUT: _encoded(output), SCHEMA: _encoded(schema)}
        if args.write:
            for path, payload in outputs.items():
                _atomic_write(path, payload)
                print(f"WROTE: {path.relative_to(REPO_ROOT)}")
            return 0
        expected = {
            OUTPUT: EXPECTED_OUTPUT_RAW_SHA256,
            SCHEMA: EXPECTED_SCHEMA_RAW_SHA256,
        }
        for path, payload in outputs.items():
            if path.is_symlink() or not path.is_file():
                raise CompositionError(f"checked output is missing or unsafe: {path}")
            checked = path.read_bytes()
            if checked != payload or _sha_bytes(checked) != expected[path]:
                raise CompositionError(f"checked output differs: {path.name}")
        print(
            "PASS: metadata-500 composition; official=500/55/47, aggregate=0, "
            "acceptance=0, candidate-evidence=0, live=289"
        )
        return 0
    except (
        CompositionError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
        SchemaError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
