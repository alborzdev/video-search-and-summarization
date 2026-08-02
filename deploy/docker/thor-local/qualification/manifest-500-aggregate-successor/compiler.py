#!/usr/bin/env python3
"""Compile the isolated 500-capability aggregate-status manifest successor."""

from __future__ import annotations

import argparse
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
PROOF_OUTPUT = PACKAGE / "projection.json"
MANIFEST_OUTPUT = PACKAGE / "projected-manifest.json"
PROOF_SCHEMA = PACKAGE / "projection.schema.json"
MANIFEST_SCHEMA = PACKAGE / "projected-manifest.schema.json"

INPUTS = {
    "ledger_500_projection": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projection.json",
        "raw_sha256": "135e39a9f557f175536282329a3f9a6a8003c634ef2f9f5905b78d0607fe646d",
    },
    "ledger_500_projection_schema": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projection.schema.json",
        "raw_sha256": "9ed414c6e1c40d8afc27e8e0bd635d826536994375037efc947098dc089f98b2",
    },
    "ledger_500_manifest": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-manifest.json",
        "raw_sha256": "075a859219dfee4982338ca04244b6d444e0c23c9666c88e58e8f5fe58c366e8",
    },
    "ledger_500_manifest_schema": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-manifest.schema.json",
        "raw_sha256": "90b0452d8e19f7770b1ed13d6a5a7f1040612cc6e99edf8f4cd2d32ed86582c5",
    },
    "ledger_500_capabilities": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-official-capabilities.json",
        "raw_sha256": "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    },
    "official_capabilities_schema": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "raw_sha256": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    },
    "live_manifest": {
        "path": "deploy/docker/thor-local/parity/manifest.json",
        "raw_sha256": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    },
    "acceptance_inventory": {
        "path": "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        "raw_sha256": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    },
    "live_capability_verifier": {
        "path": "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        "raw_sha256": "c21fd2910089c6981f0437d41d6c9ef7fff19d55c0153b04b7f7f91b00d79109",
        "json": False,
    },
    "live_manifest_verifier": {
        "path": "deploy/docker/thor-local/parity/verify_manifest.py",
        "raw_sha256": "5e9e7551853b4606a95131d1ca46da3d15fea7e307b49d1fbf06b25dacb9a5e2",
        "json": False,
    },
}

PROOF_SCHEMA_RAW_SHA256 = (
    "1e579c84754c3ce674c32a8d1264a8c537143c8f5f89faf2506ab03d1debb72e"
)
MANIFEST_SCHEMA_RAW_SHA256 = (
    "95d981d86879a2ac6e5a69c2f0a2c154d826f54ce15d87f773c0048f39c7ed48"
)
EXPECTED_PROOF_PAYLOAD_SHA256 = (
    "0a1a6db835adf397b4036e22e14d6d9d4afeb67b0ab1d790ffcef4a8a9383d23"
)
EXPECTED_PROOF_RAW_SHA256 = (
    "809f03f5bdfdcb949e584c7bb40419e4069e3520fb073dd852c640ec11758154"
)
EXPECTED_MANIFEST_RAW_SHA256 = (
    "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93"
)
MAX_JSON_BYTES = 48_000_000
STATUS_FIELDS = ("acceptance_class", "thor_state", "runtime_state")


class ProjectionError(RuntimeError):
    """A lock, aggregate derivation, preservation rule, or projection failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode()


def _strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise ProjectionError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProjectionError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ProjectionError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except ProjectionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionError(f"invalid UTF-8 JSON in {label}: {exc}") from exc


def _repo_file(relative_text: str) -> Path:
    relative = Path(relative_text)
    if not relative_text or relative.is_absolute() or ".." in relative.parts:
        raise ProjectionError(f"unsafe repository path: {relative_text}")
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ProjectionError(f"missing repository file: {relative_text}") from exc
        if stat.S_ISLNK(mode):
            raise ProjectionError(f"repository path traverses symlink: {relative_text}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ProjectionError(f"repository path is not a regular file: {relative_text}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectionError(f"repository path escapes root: {relative_text}") from exc
    return current


def _load_locked(relative: str, expected_sha256: str) -> tuple[Any, str]:
    payload = _repo_file(relative).read_bytes()
    digest = _sha_bytes(payload)
    if digest != expected_sha256:
        raise ProjectionError(f"raw source digest drift: {relative}")
    return _strict_json(payload, relative), digest


def _lock_raw(relative: str, expected_sha256: str) -> str:
    payload = _repo_file(relative).read_bytes()
    digest = _sha_bytes(payload)
    if digest != expected_sha256:
        raise ProjectionError(f"raw source digest drift: {relative}")
    return digest


def _load_local_schema(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProjectionError(f"schema must be a regular non-symlink: {path}")
    payload = path.read_bytes()
    if _sha_bytes(payload) != expected_sha256:
        raise ProjectionError(f"raw schema digest drift: {path}")
    schema = _strict_json(payload, str(path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ProjectionError(f"invalid schema {path.name}: {exc.message}") from exc
    return schema


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ProjectionError(f"{label} schema error at {location}: {error.message}")


def _assert_payload(value: dict[str, Any], field: str, label: str) -> None:
    payload = dict(value)
    observed = payload.pop(field)
    if observed != _sha_json(payload):
        raise ProjectionError(f"{label} payload digest mismatch")


def _unique(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ProjectionError(
                f"missing or duplicate {label} identity: {identity!r}"
            )
        result[identity] = row
    return result


def _derive_legacy_status(group: list[dict[str, Any]]) -> dict[str, str]:
    classes = {row["acceptance_class"] for row in group}
    acceptance_class = (
        "required_local"
        if "required_local" in classes
        else (
            "external_optional"
            if classes == {"external_optional"}
            else "alternate_local_lane"
        )
    )
    thor_states = {row["thor_state"] for row in group}
    thor_state = next(iter(thor_states)) if len(thor_states) == 1 else "partial"
    runtime_states = {row["runtime_state"] for row in group}
    runtime_state = (
        next(iter(runtime_states)) if len(runtime_states) == 1 else "not_qualified"
    )
    return {
        "acceptance_class": acceptance_class,
        "thor_state": thor_state,
        "runtime_state": runtime_state,
    }


def _derive_status(group: list[dict[str, Any]]) -> dict[str, str]:
    """Mirror the current live reducer, including its external-family boundary."""
    derived = _derive_legacy_status(group)
    if derived["acceptance_class"] == "external_optional":
        derived["thor_state"] = "external_optional"
    return derived


def _aggregate_drift(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    legacy_reducer: bool = False,
) -> list[dict[str, Any]]:
    by_feature: dict[str, list[dict[str, Any]]] = {}
    for capability in ledger["capabilities"]:
        by_feature.setdefault(capability["feature_id"], []).append(capability)
    if set(by_feature) != {feature["id"] for feature in manifest["features"]}:
        raise ProjectionError("manifest/ledger feature identity partition drift")
    result = []
    for feature_index, feature in enumerate(manifest["features"]):
        reducer = _derive_legacy_status if legacy_reducer else _derive_status
        derived = reducer(by_feature[feature["id"]])
        differences = [
            field for field in STATUS_FIELDS if feature[field] != derived[field]
        ]
        if differences:
            result.append(
                {
                    "feature_index": feature_index,
                    "feature_id": feature["id"],
                    "differing_fields": differences,
                    "before": {field: feature[field] for field in STATUS_FIELDS},
                    "after": derived,
                }
            )
    return result


def _coverage_gaps(
    ledger: dict[str, Any], acceptance: dict[str, Any]
) -> list[dict[str, Any]]:
    scenarios = _unique(acceptance["scenarios"], "id", "acceptance scenario")
    coverage_rows = _unique(
        acceptance["coverage"]["features"], "feature_id", "feature coverage"
    )
    by_feature: dict[str, set[str]] = {}
    for capability in ledger["capabilities"]:
        unknown = set(capability["scenario_ids"]) - set(scenarios)
        if unknown:
            raise ProjectionError(
                f"{capability['id']}: unknown scenarios {sorted(unknown)}"
            )
        by_feature.setdefault(capability["feature_id"], set()).update(
            capability["scenario_ids"]
        )
    gaps = []
    for feature_id, required in by_feature.items():
        covered = set(coverage_rows.get(feature_id, {}).get("scenario_ids", []))
        missing = sorted(required - covered)
        if missing:
            gaps.append({"feature_id": feature_id, "missing_scenario_ids": missing})
    return gaps


def _verify_base_against_live(live: dict[str, Any], base: dict[str, Any]) -> None:
    if set(live) != set(base):
        raise ProjectionError("live/base manifest root key-set drift")
    for key in live:
        if key != "features" and live[key] != base[key]:
            raise ProjectionError(f"live/base manifest root drift: {key}")
    if len(live["features"]) != len(base["features"]):
        raise ProjectionError("live/base feature count drift")
    for before, after in zip(live["features"], base["features"], strict=True):
        if before["id"] != after["id"]:
            raise ProjectionError("live/base feature order drift")
        if {k: v for k, v in before.items() if k != "official_capability_ids"} != {
            k: v for k, v in after.items() if k != "official_capability_ids"
        }:
            raise ProjectionError(
                f"{before['id']}: base changed a non-capability-id field"
            )
        old_ids = before.get("official_capability_ids", [])
        if after["official_capability_ids"][: len(old_ids)] != old_ids:
            raise ProjectionError(f"{before['id']}: base capability-id prefix drift")


def _project(base: dict[str, Any], updates: list[dict[str, Any]]) -> dict[str, Any]:
    projected = copy.deepcopy(base)
    feature_by_id = _unique(projected["features"], "id", "manifest feature")
    for update in updates:
        feature = feature_by_id[update["feature_id"]]
        for field in update["differing_fields"]:
            feature[field] = update["after"][field]
    return projected


def _assert_only_exact_updates(
    base: dict[str, Any], projected: dict[str, Any], updates: list[dict[str, Any]]
) -> None:
    allowed = {
        (row["feature_id"], field)
        for row in updates
        for field in row["differing_fields"]
    }
    observed: set[tuple[str, str]] = set()
    if list(base) != list(projected):
        raise ProjectionError("projected root key/order drift")
    for key in base:
        if key != "features" and base[key] != projected[key]:
            raise ProjectionError(f"projected root field drift: {key}")
    for before, after in zip(base["features"], projected["features"], strict=True):
        if list(before) != list(after) or before["id"] != after["id"]:
            raise ProjectionError("projected feature key/order drift")
        for field in before:
            if before[field] != after[field]:
                observed.add((before["id"], field))
    if observed != allowed:
        raise ProjectionError(
            f"projected changed-field set drift: {sorted(observed ^ allowed)}"
        )


def compile_projection() -> tuple[dict[str, Any], dict[str, Any]]:
    documents: dict[str, Any] = {}
    locks: dict[str, dict[str, str]] = {}
    for source_id, specification in INPUTS.items():
        if specification.get("json", True):
            document, digest = _load_locked(
                specification["path"], specification["raw_sha256"]
            )
            documents[source_id] = document
        else:
            digest = _lock_raw(specification["path"], specification["raw_sha256"])
        locks[source_id] = {"path": specification["path"], "raw_sha256": digest}

    ledger_proof = documents["ledger_500_projection"]
    ledger_proof_schema = documents["ledger_500_projection_schema"]
    base = documents["ledger_500_manifest"]
    base_schema = documents["ledger_500_manifest_schema"]
    ledger = documents["ledger_500_capabilities"]
    official_schema = documents["official_capabilities_schema"]
    live = documents["live_manifest"]
    acceptance = documents["acceptance_inventory"]
    for schema in (ledger_proof_schema, base_schema, official_schema):
        Draft202012Validator.check_schema(schema)
    _validate(ledger_proof, ledger_proof_schema, "ledger-500 proof")
    _validate(base, base_schema, "ledger-500 manifest")
    _validate(ledger, official_schema, "ledger-500 capabilities")
    _assert_payload(ledger_proof, "projection_payload_sha256", "ledger-500 proof")
    if (
        ledger_proof["projection_payload_sha256"]
        != "a6142381bbec4c81fd14780dac46ffa018e4a5e077bd85d0d69572d5ec4ba7e4"
    ):
        raise ProjectionError("ledger-500 proof payload lock drift")
    if ledger_proof["artifacts"]["projected_manifest"] != {
        "path": INPUTS["ledger_500_manifest"]["path"],
        "raw_sha256": INPUTS["ledger_500_manifest"]["raw_sha256"],
        "canonical_sha256": _sha_json(base),
    }:
        raise ProjectionError("ledger-500 manifest artifact binding drift")
    if ledger_proof["artifacts"]["projected_official_capabilities"] != {
        "path": INPUTS["ledger_500_capabilities"]["path"],
        "raw_sha256": INPUTS["ledger_500_capabilities"]["raw_sha256"],
        "canonical_sha256": _sha_json(ledger),
    }:
        raise ProjectionError("ledger-500 capabilities artifact binding drift")
    if len(base["features"]) != 55 or len(ledger["capabilities"]) != 500:
        raise ProjectionError("500-successor denominator drift")
    _verify_base_against_live(live, base)

    legacy_drift = _aggregate_drift(base, ledger, legacy_reducer=True)
    upstream_drift = ledger_proof["merge_readiness"]["blockers"][
        "family_status_aggregate_drift"
    ]
    normalized_upstream = [
        {
            "feature_index": next(
                i
                for i, f in enumerate(base["features"])
                if f["id"] == row["feature_id"]
            ),
            "feature_id": row["feature_id"],
            "differing_fields": row["differing_fields"],
            "before": row["preserved"],
            "after": row["derived_from_500"],
        }
        for row in upstream_drift
    ]
    if legacy_drift != normalized_upstream or len(legacy_drift) != 9:
        raise ProjectionError("exact legacy aggregate regression projection mismatch")

    gaps = _coverage_gaps(ledger, acceptance)
    upstream_gaps = ledger_proof["merge_readiness"]["blockers"][
        "acceptance_scenario_coverage_gaps"
    ]
    if gaps != upstream_gaps or len(gaps) != 8:
        raise ProjectionError("acceptance coverage projection mismatch")
    distinctions = ledger_proof["merge_readiness"]["reviewed_nonblocking_distinctions"][
        "external_candidate_thor_states"
    ]
    if len(distinctions) != 6:
        raise ProjectionError("external distinction denominator drift")

    external_ids = {"alert-notifications-slack", "helm", "enterprise-rag"}
    external_policy_preservations = [
        row for row in legacy_drift if row["feature_id"] in external_ids
    ]
    applied_updates = _aggregate_drift(base, ledger)
    if len(applied_updates) != 6 or len(external_policy_preservations) != 3:
        raise ProjectionError("six-update/external-policy partition drift")
    if applied_updates != [
        row for row in legacy_drift if row["feature_id"] not in external_ids
    ]:
        raise ProjectionError("current live reducer six-update projection drift")

    legacy_raw_nine_projection = _project(base, legacy_drift)
    legacy_raw_nine_policy_conflicts = [
        {
            "feature_id": feature["id"],
            "acceptance_class": feature["acceptance_class"],
            "legacy_projected_thor_state": feature["thor_state"],
            "required_thor_state": "external_optional",
            "policy": "verify_manifest_external_optional_state_v1",
        }
        for feature in legacy_raw_nine_projection["features"]
        if feature["acceptance_class"] == "external_optional"
        and feature["thor_state"] != "external_optional"
    ]
    if [row["feature_id"] for row in legacy_raw_nine_policy_conflicts] != [
        "alert-notifications-slack",
        "helm",
        "enterprise-rag",
    ]:
        raise ProjectionError("legacy raw-nine external-family policy conflict drift")
    projected = _project(base, applied_updates)
    _assert_only_exact_updates(base, projected, applied_updates)
    legacy_drift_after = _aggregate_drift(projected, ledger, legacy_reducer=True)
    if legacy_drift_after != external_policy_preservations:
        raise ProjectionError(
            "legacy reducer residual must be the three external preservations"
        )
    if _aggregate_drift(projected, ledger):
        raise ProjectionError("current live aggregate drift remains after projection")
    local_manifest_schema = _load_local_schema(
        MANIFEST_SCHEMA, MANIFEST_SCHEMA_RAW_SHA256
    )
    _validate(projected, local_manifest_schema, "projected manifest")
    manifest_encoded = _encoded(projected)
    proof: dict[str, Any] = {
        "schema_version": 1,
        "projection_id": "vss-3.2.1-thor-manifest-500-aggregate-successor",
        "mode": "isolated_static_aggregate_reconciliation",
        "target": copy.deepcopy(ledger_proof["target"]),
        "source_locks": locks,
        "policy": {
            "candidate_only": True,
            "modifies_live_files": False,
            "runtime_actions": [],
            "network_access": False,
            "docker_access": False,
            "host_mutation": False,
            "model_execution": False,
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
        },
        "aggregate_algorithm": {
            "acceptance_class": "required_local if present; else external_optional only for an all-external family; else alternate_local_lane",
            "thor_state": "external_optional for an external_optional family; otherwise the sole capability state, otherwise partial",
            "runtime_state": "the sole capability state, otherwise not_qualified",
            "implementation": "verify_official_capabilities_family_aggregate_v2_external_boundary",
            "legacy_regression_diagnostic": "v1 used the sole thor capability state or partial even for external_optional families",
        },
        "summary": {
            "manifest_feature_count": 55,
            "capability_count": 500,
            "legacy_reducer_regression_diagnostic_count": 9,
            "external_policy_preservation_count": 3,
            "aggregate_update_count": 6,
            "changed_field_count": sum(
                len(row["differing_fields"]) for row in applied_updates
            ),
            "current_reducer_delta_count_before": 6,
            "current_reducer_delta_count_after": 0,
            "legacy_reducer_residual_count_after": 3,
            "acceptance_coverage_gap_count": 8,
            "acceptance_coverage_remains_open": True,
            "external_nonblocking_distinction_count": 6,
            "legacy_raw_nine_live_manifest_policy_conflict_count": 3,
            "remaining_blocker_category_count": 1,
            "warehouse_sample_bundle_entries": 0,
        },
        "preservation": {
            "live_manifest_canonical_sha256": _sha_json(live),
            "base_manifest_canonical_sha256": _sha_json(base),
            "base_feature_order_sha256": _sha_json(
                [row["id"] for row in base["features"]]
            ),
            "projected_feature_order_sha256": _sha_json(
                [row["id"] for row in projected["features"]]
            ),
            "base_skills_canonical_sha256": _sha_json(base["skills"]),
            "projected_skills_canonical_sha256": _sha_json(projected["skills"]),
            "base_capability_id_arrays_sha256": _sha_json(
                [row["official_capability_ids"] for row in base["features"]]
            ),
            "projected_capability_id_arrays_sha256": _sha_json(
                [row["official_capability_ids"] for row in projected["features"]]
            ),
            "base_non_target_fields_sha256": _sha_json(
                [
                    {
                        k: v
                        for k, v in row.items()
                        if (row["id"], k)
                        not in {
                            (u["feature_id"], f)
                            for u in applied_updates
                            for f in u["differing_fields"]
                        }
                    }
                    for row in base["features"]
                ]
            ),
            "projected_non_target_fields_sha256": _sha_json(
                [
                    {
                        k: v
                        for k, v in row.items()
                        if (row["id"], k)
                        not in {
                            (u["feature_id"], f)
                            for u in applied_updates
                            for f in u["differing_fields"]
                        }
                    }
                    for row in projected["features"]
                ]
            ),
        },
        "legacy_reducer_regression_diagnostic": legacy_drift,
        "external_policy_preservations": external_policy_preservations,
        "aggregate_updates": applied_updates,
        "remaining_merge_readiness": {
            "current_reducer_drift_after": [],
            "legacy_reducer_residual_after": legacy_drift_after,
            "acceptance_scenario_coverage_gaps": gaps,
            "legacy_raw_nine_live_manifest_policy_conflicts": legacy_raw_nine_policy_conflicts,
            "reviewed_nonblocking_external_distinctions": distinctions,
        },
        "artifacts": {
            "projected_manifest": {
                "path": str(MANIFEST_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(manifest_encoded),
                "canonical_sha256": _sha_json(projected),
            }
        },
    }
    proof["projection_payload_sha256"] = _sha_json(proof)
    validate_projection(proof, projected, ledger=ledger, base=base)
    return proof, projected


def validate_projection(
    proof: dict[str, Any],
    projected: dict[str, Any],
    *,
    ledger: dict[str, Any] | None = None,
    base: dict[str, Any] | None = None,
) -> None:
    schema = _load_local_schema(PROOF_SCHEMA, PROOF_SCHEMA_RAW_SHA256)
    _validate(proof, schema, "projection proof")
    payload = dict(proof)
    observed = payload.pop("projection_payload_sha256")
    if observed != _sha_json(payload):
        raise ProjectionError("projection payload digest mismatch")
    if observed != EXPECTED_PROOF_PAYLOAD_SHA256:
        raise ProjectionError("projection payload lock drift")
    if ledger is None:
        ledger = _load_locked(
            INPUTS["ledger_500_capabilities"]["path"],
            INPUTS["ledger_500_capabilities"]["raw_sha256"],
        )[0]
    if base is None:
        base = _load_locked(
            INPUTS["ledger_500_manifest"]["path"],
            INPUTS["ledger_500_manifest"]["raw_sha256"],
        )[0]
    _assert_only_exact_updates(base, projected, proof["aggregate_updates"])
    if _aggregate_drift(projected, ledger):
        raise ProjectionError("projected manifest has current live aggregate drift")
    artifact = proof["artifacts"]["projected_manifest"]
    if artifact["raw_sha256"] != _sha_bytes(_encoded(projected)) or artifact[
        "canonical_sha256"
    ] != _sha_json(projected):
        raise ProjectionError("projected manifest artifact binding drift")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ProjectionError(f"unsafe output parent: {path.parent}")
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ProjectionError(f"unsafe output path: {path}")
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
            raise ProjectionError(f"unsafe temporary output: {temporary}")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        proof, manifest = compile_projection()
        outputs = {MANIFEST_OUTPUT: _encoded(manifest), PROOF_OUTPUT: _encoded(proof)}
        if args.write:
            for path, payload in outputs.items():
                _atomic_write(path, payload)
                print(f"WROTE: {path.relative_to(REPO_ROOT)}")
            return 0
        expected = {
            PROOF_OUTPUT: EXPECTED_PROOF_RAW_SHA256,
            MANIFEST_OUTPUT: EXPECTED_MANIFEST_RAW_SHA256,
        }
        for path, payload in outputs.items():
            if not path.is_file() or path.is_symlink() or path.read_bytes() != payload:
                raise ProjectionError(f"checked output drift: {path}")
            if _sha_bytes(payload) != expected[path]:
                raise ProjectionError(f"checked output raw digest drift: {path}")
        print(
            "PASS: current-live six-update successor is deterministic; current aggregate blockers=0; acceptance gaps=8"
        )
        return 0
    except (
        ProjectionError,
        SchemaError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
