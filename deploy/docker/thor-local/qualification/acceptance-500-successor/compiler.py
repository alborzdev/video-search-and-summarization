#!/usr/bin/env python3
"""Compile the isolated eight-link acceptance inventory successor."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4].resolve(strict=True)
INVENTORY_OUTPUT = PACKAGE / "projected-acceptance-inventory.json"
INVENTORY_SCHEMA_OUTPUT = PACKAGE / "projected-acceptance-inventory.schema.json"
PROOF_OUTPUT = PACKAGE / "projection.json"
PROOF_SCHEMA_OUTPUT = PACKAGE / "projection.schema.json"
MAX_JSON_BYTES = 64_000_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")

INPUTS = {
    "acceptance_inventory": {
        "path": "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        "raw_sha256": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
        "json": True,
    },
    "projected_manifest": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-manifest.json",
        "raw_sha256": "075a859219dfee4982338ca04244b6d444e0c23c9666c88e58e8f5fe58c366e8",
        "json": True,
    },
    "projected_manifest_schema": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-manifest.schema.json",
        "raw_sha256": "90b0452d8e19f7770b1ed13d6a5a7f1040612cc6e99edf8f4cd2d32ed86582c5",
        "json": True,
    },
    "projected_ledger": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projected-official-capabilities.json",
        "raw_sha256": "f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6",
        "json": True,
    },
    "official_capabilities_schema": {
        "path": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "raw_sha256": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
        "json": True,
    },
    "ledger_projection_proof": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projection.json",
        "raw_sha256": "4e206240795e2cf739f595811920ae66a7868ebe92031feb73b7fcbbe5a971d0",
        "json": True,
    },
    "ledger_projection_proof_schema": {
        "path": "deploy/docker/thor-local/qualification/ledger-500-successor/projection.schema.json",
        "raw_sha256": "8f74b849581029c303a1e7a927f1f31b7458ed87e529d14e25134e52396f4ec9",
        "json": True,
    },
    "official_capability_verifier": {
        "path": "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        "raw_sha256": "930ed6caa04eea6dc79984ceb0ee8babe39db6074ac6c74a1e43349dcbc8e8e7",
        "json": False,
    },
    "acceptance_verifier": {
        "path": "deploy/docker/thor-local/qualification/acceptance.py",
        "raw_sha256": "673873746cb3f23fb35fd9dac445df4a181566ae320eb7e4090ac7837b7c024f",
        "json": False,
    },
}

EXPECTED_ADDITIONS = (
    ("rt-cv-2d", "official-capability-contracts"),
    ("video-summarization-live", "mcp-tool-operation-matrix"),
    ("search-scale", "official-capability-contracts"),
    ("alert-notifications-slack", "openclaw-workflows"),
    ("rt-vlm-media", "rest-api-operation-matrix"),
    ("rt-vlm-models", "official-capability-contracts"),
    ("rt-vlm-performance-observability", "official-capability-contracts"),
    ("audio-understanding", "core-agent-workflows"),
)
EXPECTED_FAMILY_BLOCKERS = (
    "video-summarization-live",
    "alert-notifications-slack",
    "rt-vlm-media",
    "vios-codecs-audio",
    "audio-understanding",
    "vios-ui",
    "agent-and-mcp-apis",
    "helm",
    "enterprise-rag",
)

EXPECTED_INVENTORY_RAW_SHA256 = (
    "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0"
)
EXPECTED_INVENTORY_SCHEMA_RAW_SHA256 = (
    "848d84b976906c3059b67218cf1d6bf3960b8b91c620c663bba398f5b302278a"
)
EXPECTED_PROOF_RAW_SHA256 = (
    "2cb717b64fe578bbc051a0791908cb708005a488335b3e40116bbf173a79f235"
)
EXPECTED_PROOF_SCHEMA_RAW_SHA256 = (
    "37466f37c43e35f157c1f0c2d93fd75cfdd38b30a3657a53804e52ec546a5737"
)
EXPECTED_PROOF_PAYLOAD_SHA256 = (
    "71303ac410a83686f348c3327383007d7f93633dae54034e6e3b38e12830cb26"
)


class ProjectionError(RuntimeError):
    """A source lock, preservation boundary, or acceptance invariant failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _items_fingerprint(items: list[Any]) -> str:
    canonical_items = sorted(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in items
    )
    return _sha_json(canonical_items)


def _encoded(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _strict_json(payload: bytes, label: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise ProjectionError(f"oversized JSON input: {label}")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ProjectionError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ProjectionError(f"non-finite JSON number in {label}: {value}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise ProjectionError(f"invalid UTF-8 JSON input: {label}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectionError(f"invalid JSON input: {label}: {exc.msg}") from exc


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ProjectionError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ProjectionError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise ProjectionError(f"repository input contains symlink: {relative}")
    try:
        current.resolve(strict=True).relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise ProjectionError(f"repository input escapes root: {relative}") from exc
    if not stat.S_ISREG(current.stat().st_mode):
        raise ProjectionError(f"repository input is not regular: {relative}")
    return current


def _load_locked(relative: str, expected: str, *, parse_json: bool) -> tuple[Any, str]:
    path = _repo_file(relative)
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if digest != expected:
        raise ProjectionError(f"raw source digest drift: {relative}")
    return (_strict_json(payload, relative) if parse_json else payload), digest


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(item) for item in error.absolute_path)
        raise ProjectionError(f"{label} schema error at {location}: {error.message}")


def _unique_ids(values: Any, label: str) -> list[str]:
    if (
        not isinstance(values, list)
        or any(not isinstance(value, str) or not value for value in values)
        or len(values) != len(set(values))
    ):
        raise ProjectionError(f"invalid or duplicate IDs: {label}")
    return values


def _by_id(rows: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ProjectionError(f"invalid record list: {label}")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ProjectionError(f"invalid or duplicate identity: {label}")
        result[identity] = row
    return result


def _scenario_blockers(inventory: dict[str, Any]) -> dict[str, set[str]]:
    blocker_rows = _by_id(inventory.get("blockers"), "id", "blockers")
    scenario_rows = _by_id(inventory.get("scenarios"), "id", "scenarios")
    blocker_ids = set(blocker_rows)
    result: dict[str, set[str]] = {}
    for scenario_id, scenario in scenario_rows.items():
        linked = set(_unique_ids(scenario.get("blocker_ids"), scenario_id))
        if not linked <= blocker_ids:
            raise ProjectionError(f"{scenario_id}: unknown blocker")
        result[scenario_id] = linked
    return result


def _validate_inventory_semantics(
    inventory: dict[str, Any], manifest: dict[str, Any]
) -> None:
    if inventory.get("execution_enabled") is not False:
        raise ProjectionError("acceptance execution must remain disabled")
    scenarios = _scenario_blockers(inventory)
    blockers = _by_id(inventory["blockers"], "id", "blockers")
    features = _by_id(manifest.get("features"), "id", "manifest features")
    coverage = inventory.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != {
        "features",
        "skills",
        "api_surfaces",
    }:
        raise ProjectionError("invalid acceptance coverage sections")
    records = coverage["features"]
    covered = _by_id(records, "feature_id", "acceptance feature coverage")
    if list(covered) != [row["id"] for row in manifest["features"]]:
        raise ProjectionError("acceptance feature identity/order drift")
    for feature_id, record in covered.items():
        if record.get("selector") != "all-current-capabilities":
            raise ProjectionError(f"{feature_id}: invalid feature selector")
        scenario_ids = _unique_ids(record.get("scenario_ids"), feature_id)
        if not set(scenario_ids) <= set(scenarios):
            raise ProjectionError(f"{feature_id}: unknown scenario")
        record_blockers = set(_unique_ids(record.get("blocker_ids"), feature_id))
        if (
            not record_blockers <= set(blockers)
            or "phase1-execution-disabled" not in record_blockers
            or not record_blockers
            <= set().union(*(scenarios[item] for item in scenario_ids))
        ):
            raise ProjectionError(f"{feature_id}: blocker/scenario semantic drift")
        feature = features[feature_id]
        advertised = feature.get("advertised")
        if (
            not isinstance(advertised, list)
            or record.get("expected_capability_count") != len(advertised)
            or record.get("capabilities_sha256") != _items_fingerprint(advertised)
        ):
            raise ProjectionError(f"{feature_id}: advertised coverage digest drift")


def _coverage_gaps(
    ledger: dict[str, Any], inventory: dict[str, Any]
) -> list[dict[str, Any]]:
    records = _by_id(
        inventory["coverage"]["features"],
        "feature_id",
        "acceptance feature coverage",
    )
    requirements: dict[str, set[str]] = {}
    for capability in ledger.get("capabilities", []):
        feature_id = capability.get("feature_id")
        scenario_ids = _unique_ids(
            capability.get("scenario_ids"), f"{capability.get('id')}.scenario_ids"
        )
        requirements.setdefault(feature_id, set()).update(scenario_ids)
    gaps = []
    for feature_id, required in requirements.items():
        record = records.get(feature_id)
        if record is None:
            missing = sorted(required)
        else:
            missing = sorted(required - set(record["scenario_ids"]))
        if missing:
            gaps.append({"feature_id": feature_id, "missing_scenario_ids": missing})
    return gaps


def _project_inventory(
    current: dict[str, Any],
    ledger: dict[str, Any],
    manifest: dict[str, Any],
    ledger_proof: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    _validate_inventory_semantics(current, manifest)
    before_gaps = _coverage_gaps(ledger, current)
    proof_gaps = ledger_proof["merge_readiness"]["blockers"][
        "acceptance_scenario_coverage_gaps"
    ]
    expected_gaps = [
        {"feature_id": feature_id, "missing_scenario_ids": [scenario_id]}
        for feature_id, scenario_id in EXPECTED_ADDITIONS
    ]
    if before_gaps != expected_gaps or proof_gaps != expected_gaps:
        raise ProjectionError("exact eight acceptance gap source drift")

    family_rows = ledger_proof["merge_readiness"]["blockers"][
        "family_status_aggregate_drift"
    ]
    if tuple(row["feature_id"] for row in family_rows) != EXPECTED_FAMILY_BLOCKERS:
        raise ProjectionError("family aggregate blocker separation drift")

    projected = copy.deepcopy(current)
    records = _by_id(
        projected["coverage"]["features"],
        "feature_id",
        "projected feature coverage",
    )
    transitions = []
    index_by_id = {
        row["feature_id"]: index
        for index, row in enumerate(projected["coverage"]["features"])
    }
    for feature_id, scenario_id in EXPECTED_ADDITIONS:
        record = records[feature_id]
        before = list(record["scenario_ids"])
        if scenario_id in before:
            raise ProjectionError(f"{feature_id}: scenario addition already present")
        record["scenario_ids"].append(scenario_id)
        transitions.append(
            {
                "feature_id": feature_id,
                "scenario_id": scenario_id,
                "feature_record_index": index_by_id[feature_id],
                "json_pointer": (
                    f"/coverage/features/{index_by_id[feature_id]}/scenario_ids/"
                    f"{len(before)}"
                ),
                "before_scenario_ids": before,
                "after_scenario_ids": list(record["scenario_ids"]),
            }
        )
    _verify_projection(current, projected, transitions)
    _validate_inventory_semantics(projected, manifest)
    after_gaps = _coverage_gaps(ledger, projected)
    if after_gaps:
        raise ProjectionError("projected acceptance coverage remains incomplete")
    return projected, transitions, family_rows


def _verify_projection(
    current: dict[str, Any],
    projected: dict[str, Any],
    transitions: list[dict[str, Any]],
) -> None:
    if current.keys() != projected.keys():
        raise ProjectionError("acceptance top-level key drift")
    for key in current:
        if key != "coverage" and projected[key] != current[key]:
            raise ProjectionError(f"acceptance non-coverage preservation drift: {key}")
    for key in current["coverage"]:
        if key != "features" and projected["coverage"][key] != current["coverage"][key]:
            raise ProjectionError(f"acceptance coverage preservation drift: {key}")
    if len(current["coverage"]["features"]) != len(projected["coverage"]["features"]):
        raise ProjectionError("acceptance feature count drift")
    allowed = {(row["feature_id"], row["scenario_id"]) for row in transitions}
    observed = set()
    for before, after in zip(
        current["coverage"]["features"],
        projected["coverage"]["features"],
        strict=True,
    ):
        if before["feature_id"] != after["feature_id"]:
            raise ProjectionError("acceptance feature order drift")
        for key in before:
            if key != "scenario_ids" and after.get(key) != before[key]:
                raise ProjectionError(f"{before['feature_id']}: feature field drift")
        before_ids = before["scenario_ids"]
        after_ids = after["scenario_ids"]
        if after_ids == before_ids:
            continue
        if (
            len(after_ids) != len(before_ids) + 1
            or after_ids[:-1] != before_ids
            or (before["feature_id"], after_ids[-1]) not in allowed
        ):
            raise ProjectionError(
                f"{before['feature_id']}: non-minimal scenario mutation"
            )
        observed.add((before["feature_id"], after_ids[-1]))
    if observed != allowed or len(observed) != 8:
        raise ProjectionError("exact eight acceptance additions not observed")


def _surgical_inventory_bytes(
    source: bytes, current: dict[str, Any], projected: dict[str, Any]
) -> bytes:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectionError("acceptance inventory is not UTF-8") from exc

    def feature_block(row: dict[str, Any]) -> str:
        rendered = json.dumps(row, ensure_ascii=True, indent=2, sort_keys=True)
        return "\n".join(f"      {line}" for line in rendered.splitlines())

    replacements = 0
    for before, after in zip(
        current["coverage"]["features"],
        projected["coverage"]["features"],
        strict=True,
    ):
        if before == after:
            continue
        old = feature_block(before)
        new = feature_block(after)
        if text.count(old) != 1:
            raise ProjectionError(
                f"{before['feature_id']}: byte-preserving source block is not unique"
            )
        text = text.replace(old, new, 1)
        replacements += 1
    if replacements != 8:
        raise ProjectionError("byte-preserving replacement denominator drift")
    payload = text.encode("utf-8")
    if _strict_json(payload, "projected acceptance inventory bytes") != projected:
        raise ProjectionError("byte-preserving projection semantic drift")
    return payload


def _inventory_output_bytes(projected: dict[str, Any]) -> bytes:
    specification = INPUTS["acceptance_inventory"]
    current, digest = _load_locked(
        specification["path"], specification["raw_sha256"], parse_json=True
    )
    source = _repo_file(specification["path"]).read_bytes()
    if _sha_bytes(source) != digest:
        raise ProjectionError("acceptance inventory changed during compilation")
    return _surgical_inventory_bytes(source, current, projected)


def _inventory_schema(
    current: dict[str, Any], projected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://developer.nvidia.com/vss/thor-local/acceptance-500-successor.schema.json",
        "title": "VSS Thor-local exact acceptance-500 successor",
        "type": "object",
        "additionalProperties": False,
        "required": list(projected.keys()),
        "properties": {
            **{
                key: {"const": value}
                for key, value in projected.items()
                if key != "coverage"
            },
            "coverage": {
                "type": "object",
                "additionalProperties": False,
                "required": list(projected["coverage"].keys()),
                "properties": {
                    "api_surfaces": {"const": current["coverage"]["api_surfaces"]},
                    "skills": {"const": current["coverage"]["skills"]},
                    "features": {
                        "type": "array",
                        "minItems": 55,
                        "maxItems": 55,
                        "prefixItems": [
                            {"const": row} for row in projected["coverage"]["features"]
                        ],
                        "items": False,
                    },
                },
            },
        },
    }


def _proof_schema(proof: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://developer.nvidia.com/vss/thor-local/acceptance-500-projection.schema.json",
        "title": "VSS Thor-local exact acceptance-500 projection proof",
        "const": proof,
    }


def compile_projection() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
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

    for name in (
        "projected_manifest_schema",
        "official_capabilities_schema",
        "ledger_projection_proof_schema",
    ):
        try:
            Draft202012Validator.check_schema(documents[name])
        except SchemaError as exc:
            raise ProjectionError(
                f"invalid locked schema {name}: {exc.message}"
            ) from exc
    _validate(
        documents["projected_manifest"],
        documents["projected_manifest_schema"],
        "projected manifest",
    )
    _validate(
        documents["projected_ledger"],
        documents["official_capabilities_schema"],
        "projected official capabilities",
    )
    _validate(
        documents["ledger_projection_proof"],
        documents["ledger_projection_proof_schema"],
        "ledger projection proof",
    )
    if len(documents["projected_ledger"]["capabilities"]) != 500:
        raise ProjectionError("projected ledger denominator is not 500")

    projected, transitions, family_rows = _project_inventory(
        documents["acceptance_inventory"],
        documents["projected_ledger"],
        documents["projected_manifest"],
        documents["ledger_projection_proof"],
    )
    inventory_schema = _inventory_schema(documents["acceptance_inventory"], projected)
    Draft202012Validator.check_schema(inventory_schema)
    _validate(projected, inventory_schema, "projected acceptance inventory")

    inventory_bytes = _inventory_output_bytes(projected)
    inventory_schema_bytes = _encoded(inventory_schema)
    proof = {
        "schema_version": 1,
        "projection_id": "vss-3.2.1-thor-acceptance-500-successor",
        "mode": "isolated_static_acceptance_projection",
        "source_locks": locks,
        "policy": {
            "candidate_only": True,
            "modifies_live_files": False,
            "runtime_execution": "forbidden",
            "runtime_evidence_added": False,
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
            "custom_data_warehouse_capability": "preserved",
        },
        "summary": {
            "projected_capability_count": 500,
            "feature_coverage_record_count": len(projected["coverage"]["features"]),
            "scenario_addition_count": len(transitions),
            "acceptance_coverage_blocker_count_before": 8,
            "acceptance_coverage_blocker_count_after": 0,
            "family_aggregate_blocker_count": len(family_rows),
            "live_merge_ready": False,
        },
        "scenario_additions": transitions,
        "remaining_blockers": {
            "acceptance_scenario_coverage_gaps": [],
            "family_status_aggregate_drift": copy.deepcopy(family_rows),
        },
        "preservation": {
            "current_inventory_canonical_sha256": _sha_json(
                documents["acceptance_inventory"]
            ),
            "projected_inventory_canonical_sha256": _sha_json(projected),
            "unchanged_top_level_canonical_sha256": _sha_json(
                {key: value for key, value in projected.items() if key != "coverage"}
            ),
            "unchanged_coverage_sections_canonical_sha256": _sha_json(
                {
                    key: value
                    for key, value in projected["coverage"].items()
                    if key != "features"
                }
            ),
            "projected_feature_records_canonical_sha256": _sha_json(
                projected["coverage"]["features"]
            ),
        },
        "artifacts": {
            "projected_acceptance_inventory": {
                "path": str(INVENTORY_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(inventory_bytes),
            },
            "projected_acceptance_inventory_schema": {
                "path": str(INVENTORY_SCHEMA_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(inventory_schema_bytes),
            },
        },
    }
    proof["projection_payload_sha256"] = _sha_json(proof)
    proof_schema = _proof_schema(proof)
    Draft202012Validator.check_schema(proof_schema)
    _validate(proof, proof_schema, "acceptance projection proof")
    return proof, proof_schema, projected, inventory_schema


def validate_projection(
    proof: dict[str, Any],
    proof_schema: dict[str, Any],
    inventory: dict[str, Any],
    inventory_schema: dict[str, Any],
) -> None:
    _validate(proof, proof_schema, "acceptance projection proof")
    _validate(inventory, inventory_schema, "projected acceptance inventory")
    payload = dict(proof)
    observed = payload.pop("projection_payload_sha256")
    if observed != _sha_json(payload) or observed != EXPECTED_PROOF_PAYLOAD_SHA256:
        raise ProjectionError("projection payload lock drift")
    if proof["artifacts"]["projected_acceptance_inventory"]["raw_sha256"] != _sha_bytes(
        _inventory_output_bytes(inventory)
    ):
        raise ProjectionError("projected inventory artifact binding drift")
    if proof["artifacts"]["projected_acceptance_inventory_schema"][
        "raw_sha256"
    ] != _sha_bytes(_encoded(inventory_schema)):
        raise ProjectionError("projected inventory schema binding drift")


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
        proof, proof_schema, inventory, inventory_schema = compile_projection()
        validate_projection(proof, proof_schema, inventory, inventory_schema)
        outputs = {
            INVENTORY_OUTPUT: _inventory_output_bytes(inventory),
            INVENTORY_SCHEMA_OUTPUT: _encoded(inventory_schema),
            PROOF_OUTPUT: _encoded(proof),
            PROOF_SCHEMA_OUTPUT: _encoded(proof_schema),
        }
        if args.write:
            for path, payload in outputs.items():
                _atomic_write(path, payload)
                print(f"WROTE: {path.relative_to(REPO_ROOT)}")
            return 0
        expected = {
            INVENTORY_OUTPUT: EXPECTED_INVENTORY_RAW_SHA256,
            INVENTORY_SCHEMA_OUTPUT: EXPECTED_INVENTORY_SCHEMA_RAW_SHA256,
            PROOF_OUTPUT: EXPECTED_PROOF_RAW_SHA256,
            PROOF_SCHEMA_OUTPUT: EXPECTED_PROOF_SCHEMA_RAW_SHA256,
        }
        for path, payload in outputs.items():
            if path.is_symlink() or not path.is_file():
                raise ProjectionError(f"checked output is missing or unsafe: {path}")
            checked = path.read_bytes()
            if checked != payload or _sha_bytes(checked) != expected[path]:
                raise ProjectionError(f"checked output differs: {path.name}")
        print(
            "PASS: acceptance-500 successor; additions=8, coverage-blockers=0, "
            "family-blockers=9, live-merge-ready=false"
        )
        return 0
    except (
        ProjectionError,
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
