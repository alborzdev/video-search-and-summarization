#!/usr/bin/env python3
"""Compile the inert 211-candidate approval mapping successor v2.

The compiler preserves 209 predecessor rows exactly and applies two reviewed,
source-locked classification resolutions.  It cannot consume receipts, grant
approval, admit candidates, or execute runtime/host actions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "mapping.json"
SCHEMA_PATH = HERE / "mapping.schema.json"
MAX_SOURCE_BYTES = 96_000_000

V1_DIR = "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor"
BUNDLES_DIR = (
    "deploy/docker/thor-local/qualification/runtime-approval-bundles-successor"
)
REPAIR_DIR = (
    "deploy/docker/thor-local/qualification/sparse4d-candidate-dependency-repair"
)
ORACLES_DIR = "deploy/docker/thor-local/qualification/live-metadata-500-migration"

V1_MAPPING_PATH = f"{V1_DIR}/mapping.json"
V1_SCHEMA_PATH = f"{V1_DIR}/mapping.schema.json"
V1_COMPILER_PATH = f"{V1_DIR}/compiler.py"
BUNDLES_PATH = f"{BUNDLES_DIR}/contract.json"
BUNDLES_SCHEMA_PATH = f"{BUNDLES_DIR}/contract.schema.json"
BUNDLES_COMPILER_PATH = f"{BUNDLES_DIR}/compiler.py"
REPAIR_PATH = f"{REPAIR_DIR}/repair.json"
REPAIR_SCHEMA_PATH = f"{REPAIR_DIR}/repair.schema.json"
REPAIR_COMPILER_PATH = f"{REPAIR_DIR}/compiler.py"
ORACLES_PATH = f"{ORACLES_DIR}/post-state-capability-oracles.json"
ORACLES_SCHEMA_PATH = f"{ORACLES_DIR}/post-state-capability-oracles.schema.json"

# Every dependency is pinned only after its own checked compiler passes.
EXPECTED_SOURCE_HASHES = {
    V1_MAPPING_PATH: "4bb8f3a5fba5e201b72e1f1a0f4218bff4b9a999a836c192fca44ca7e35d9cf9",
    V1_SCHEMA_PATH: "09f8610cb7f9cc1d060202f5939b7e451fd78b92f58d80d098939e5ca05b518e",
    V1_COMPILER_PATH: "7588e8ae49670ad8c0bdf74ad3744d1da510059d07f5b09258e0835474e79fcf",
    BUNDLES_PATH: "74ba837f9e87923ddd48c635a067aeca9929bbf7cd9b3cff5f26157560aa3c0e",
    BUNDLES_SCHEMA_PATH: "67e052501707a2b12c0bd43c055b5cce41367772ff5c263f8a5b3024592f126b",
    BUNDLES_COMPILER_PATH: "df9727bfe5bb4a67410525b0f3e8fa5f22d1b9a4bd66b22d24174bfa5f39ce31",
    REPAIR_PATH: "2ed1a2bb1afc7b3e79d4a1a688d770780639f307f06f29d222e13f3d23683ffd",
    REPAIR_SCHEMA_PATH: "1437c5fd692890df0e55b2cc61d2c214cd7e84b8ac0d3e0540feb8f1f8d5a619",
    REPAIR_COMPILER_PATH: "57c960a00f37e111da66844c862368d40d52626c6c05157bb1ac10eb1b725656",
    ORACLES_PATH: "17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271",
    ORACLES_SCHEMA_PATH: "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
}

SPARSE_ID = "manifest-entry.warehouse-3d-and-mv3dt.00-sparse4d-3d-warehouse"
FIREWALL_ID = "manifest-entry.offline-security.05-physical-interface-firewall"
SPARSE_LEAF = "sparse4d-custom-data-models"
FIREWALL_INSPECTION = "physical-interface-firewall-read-only-inspection"
FIREWALL_CONFIGURATION = "physical-interface-firewall-configuration"
WRONG_DEPENDENCY = "runtime.warehouse.profile-mv3dt-pipeline"
CORRECT_DEPENDENCY = "runtime.warehouse.profile-3d-sparse4d-pipeline"
CORRECTED_SPARSE_CAPABILITY_SHA256 = (
    "086e0cadd433638f890d86d9c1bf95ec0ecab037fb3c4c52323f7b0ff12afd90"
)
RESOLVED_IDS = frozenset({SPARSE_ID, FIREWALL_ID})

EXPECTED_BUNDLE_IDS = (
    "host-prerequisite-evidence-collection",
    "read-only-docker-runtime-inspection",
    "cgroupfs-remediation",
    "tiny-audio-fixture-generation",
    "model-artifact-downloads",
    "profile-lifecycle",
    "search-scale-progressive-2-4-8-16",
    "search-scale-100",
    "mv3dt-custom-data",
    "sparse4d-custom-data-models",
    "audio-native-runtime",
    "audio-asr-transcript-runtime",
    "official-edge-staging",
    "external-attestations",
    FIREWALL_INSPECTION,
    FIREWALL_CONFIGURATION,
)
EXPECTED_CANDIDATE_ORDER_SHA256 = (
    "1c0cc33efa1aa6283e467e5fc78bbed8b4cbe8ff23fdbf6db3190144996a3ef9"
)
EXPECTED_CANDIDATE_ROWS_SHA256 = (
    "8cc136ea78c7395c534db0c8601b4881ac7982a70e6c43218a6d7cc20b6ef5b4"
)
EXPECTED_UNAFFECTED_ROWS_SHA256 = (
    "de1907e019b0908c3acd9a0785e29e177367d16d2667e8a49d798e8940cf77d8"
)
EXPECTED_MAPPING_ROWS_SHA256 = (
    "a7290d1ff2791b095789a5c2076115a54e2cdedfe14c744897d9674f3add6f94"
)

EXPECTED_STATE_COUNTS = {
    "mapped": 208,
    "static_nonactivating": 3,
    "unmapped_contract_conflict": 0,
    "unmapped_scope_gap": 0,
}
EXPECTED_DIRECT_COUNTS = {
    "host-prerequisite-evidence-collection": 0,
    "read-only-docker-runtime-inspection": 0,
    "cgroupfs-remediation": 0,
    "tiny-audio-fixture-generation": 0,
    "model-artifact-downloads": 0,
    "profile-lifecycle": 184,
    "search-scale-progressive-2-4-8-16": 1,
    "search-scale-100": 1,
    "mv3dt-custom-data": 9,
    "sparse4d-custom-data-models": 3,
    "audio-native-runtime": 3,
    "audio-asr-transcript-runtime": 2,
    "official-edge-staging": 0,
    "external-attestations": 4,
    FIREWALL_INSPECTION: 0,
    FIREWALL_CONFIGURATION: 1,
}
EXPECTED_CLOSURE_COUNTS = {
    "host-prerequisite-evidence-collection": 203,
    "read-only-docker-runtime-inspection": 203,
    "cgroupfs-remediation": 203,
    "tiny-audio-fixture-generation": 5,
    "model-artifact-downloads": 203,
    "profile-lifecycle": 203,
    "search-scale-progressive-2-4-8-16": 2,
    "search-scale-100": 1,
    "mv3dt-custom-data": 9,
    "sparse4d-custom-data-models": 3,
    "audio-native-runtime": 3,
    "audio-asr-transcript-runtime": 2,
    "official-edge-staging": 0,
    "external-attestations": 4,
    FIREWALL_INSPECTION: 1,
    FIREWALL_CONFIGURATION: 1,
}


class MappingV2Error(RuntimeError):
    """A source, preservation, classification, or inertness invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_SOURCE_BYTES:
        raise MappingV2Error(f"{label}: exceeds size bound")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise MappingV2Error(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MappingV2Error(f"{label}: non-finite JSON number {token}")
            ),
        )
    except MappingV2Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MappingV2Error(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MappingV2Error(f"{label}: JSON root must be an object")
    return value


def repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise MappingV2Error(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise MappingV2Error(f"repository path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MappingV2Error(f"repository path contains a symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise MappingV2Error(f"repository source is not a regular file: {relative}")
    return path


def read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise MappingV2Error(f"{label}: unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise MappingV2Error(f"{label}: must be a regular non-symlink")
    if before.st_size > MAX_SOURCE_BYTES:
        raise MappingV2Error(f"{label}: exceeds size bound")
    payload = path.read_bytes()
    after = path.lstat()
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(payload) != before.st_size
    ):
        raise MappingV2Error(f"{label}: changed while reading")
    return payload


def validate_schema(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise MappingV2Error(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise MappingV2Error(f"{label}: schema violation at {where}: {first.message}")


def _load_locked_sources() -> dict[str, bytes]:
    loaded: dict[str, bytes] = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        payload = read_regular(repo_path(relative), relative)
        if sha256(payload) != expected:
            raise MappingV2Error(f"source lock mismatch: {relative}")
        loaded[relative] = payload
    return loaded


def _json_source(source: dict[str, bytes], path: str) -> dict[str, Any]:
    return strict_json(source[path], path)


def _dependency_closure(leaf: str, bundles: dict[str, Any]) -> list[str]:
    by_id = {item["id"]: item for item in bundles["bundles"]}
    reachable: set[str] = set()

    def visit(bundle_id: str) -> None:
        if bundle_id in reachable:
            return
        if bundle_id not in by_id:
            raise MappingV2Error(f"unknown approval bundle: {bundle_id}")
        reachable.add(bundle_id)
        for dependency in by_id[bundle_id]["depends_on"]:
            visit(dependency)

    visit(leaf)
    return [bundle_id for bundle_id in EXPECTED_BUNDLE_IDS if bundle_id in reachable]


def _validate_sources(
    source: dict[str, bytes],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    predecessor = _json_source(source, V1_MAPPING_PATH)
    predecessor_schema = _json_source(source, V1_SCHEMA_PATH)
    bundles = _json_source(source, BUNDLES_PATH)
    bundles_schema = _json_source(source, BUNDLES_SCHEMA_PATH)
    repair = _json_source(source, REPAIR_PATH)
    repair_schema = _json_source(source, REPAIR_SCHEMA_PATH)
    oracles = _json_source(source, ORACLES_PATH)
    oracles_schema = _json_source(source, ORACLES_SCHEMA_PATH)
    validate_schema(predecessor, predecessor_schema, "predecessor mapping")
    validate_schema(bundles, bundles_schema, "successor approval contract")
    validate_schema(repair, repair_schema, "Sparse4D dependency repair")
    validate_schema(oracles, oracles_schema, "candidate oracles")

    if (
        predecessor.get("mapping_id")
        != "thor-vss-3.2.1-candidate-approval-mapping-successor"
        or predecessor.get("summary", {}).get("candidate_count") != 211
        or predecessor.get("summary", {}).get("state_counts")
        != {
            "mapped": 206,
            "static_nonactivating": 3,
            "unmapped_contract_conflict": 1,
            "unmapped_scope_gap": 1,
        }
        or predecessor.get("policy", {}).get("approval_inheritance") is not False
        or predecessor.get("summary", {}).get("receipt_count") != 0
        or predecessor.get("summary", {}).get("admitted_candidates") != 0
        or predecessor.get("summary", {}).get("executable_candidates") != 0
    ):
        raise MappingV2Error("predecessor mapping identity or inert boundary drift")
    predecessor_rows = predecessor.get("mappings")
    if not isinstance(predecessor_rows, list) or len(predecessor_rows) != 211:
        raise MappingV2Error("predecessor mapping denominator drift")
    if predecessor.get("mapping_records_canonical_sha256") != sha256(
        canonical_bytes(predecessor_rows)
    ):
        raise MappingV2Error("predecessor mapping-record identity drift")

    bundle_rows = bundles.get("bundles")
    if (
        bundles.get("contract_id")
        != "vss-3.2.1-thor-runtime-approval-bundles-successor"
        or bundles.get("bundle_count") != 16
        or not isinstance(bundle_rows, list)
        or tuple(item.get("id") for item in bundle_rows) != EXPECTED_BUNDLE_IDS
        or bundles.get("successor_policy", {}).get("approval_inheritance") is not False
        or any(bundles.get("authorization_state", {}).values())
    ):
        raise MappingV2Error(
            "16-bundle successor identity or no-authorization boundary drift"
        )
    by_bundle = {item["id"]: item for item in bundle_rows}
    if (
        by_bundle[FIREWALL_INSPECTION].get("depends_on") != []
        or by_bundle[FIREWALL_CONFIGURATION].get("depends_on") != [FIREWALL_INSPECTION]
        or any(
            key in by_bundle[bundle_id]
            for bundle_id in (FIREWALL_INSPECTION, FIREWALL_CONFIGURATION)
            for key in ("authorized_command", "action_command", "recovery_command")
        )
    ):
        raise MappingV2Error("firewall bundle scope or nonactivation boundary drift")

    repair_row = repair.get("repair", {})
    classification = repair.get("approval_classification", {})
    preservation = repair.get("preservation", {})
    policy = repair.get("policy", {})
    if (
        repair.get("repair_id") != "thor-vss-3.2.1-sparse4d-candidate-dependency-repair"
        or repair.get("mode") != "inert_additive_planning_overlay"
        or repair_row.get("capability_id") != SPARSE_ID
        or repair_row.get("field")
        != "ledger_binding.contract.dependency_capability_ids"
        or repair_row.get("before") != [WRONG_DEPENDENCY]
        or repair_row.get("after") != [CORRECT_DEPENDENCY]
        or repair_row.get("change_count") != 1
        or repair_row.get("candidate_capability_after_canonical_sha256")
        != CORRECTED_SPARSE_CAPABILITY_SHA256
        or classification.get("leaf_bundle_id") != SPARSE_LEAF
        or classification.get("predecessor_state") != "unmapped_contract_conflict"
        or classification.get("approval_state")
        != "no_receipt_not_admitted_not_executable"
        or preservation.get("candidate_runtime_state_before") != "not_qualified"
        or preservation.get("candidate_runtime_state_after") != "not_qualified"
        or preservation.get("runtime_receipts") != 0
        or preservation.get("runtime_qualification_claims") != 0
        or policy.get("runtime_state_promotion") is not False
        or policy.get("approval_granted") is not False
        or policy.get("executor_present") is not False
        or policy.get("warehouse_sample_bundle") != "excluded"
    ):
        raise MappingV2Error("Sparse4D repair identity or inert boundary drift")

    rows = oracles.get("oracles")
    if not isinstance(rows, list) or len(rows) != 500:
        raise MappingV2Error("oracle denominator drift")
    candidates = rows[289:]
    candidate_ids = [row.get("capability_id") for row in candidates]
    if (
        len(candidates) != 211
        or len(set(candidate_ids)) != 211
        or sha256(canonical_bytes(candidate_ids)) != EXPECTED_CANDIDATE_ORDER_SHA256
        or sha256(canonical_bytes(candidates)) != EXPECTED_CANDIDATE_ROWS_SHA256
    ):
        raise MappingV2Error("candidate oracle identity drift")
    oracle_by_id = {row["capability_id"]: row for row in candidates}
    sparse_oracle = oracle_by_id[SPARSE_ID]
    firewall_oracle = oracle_by_id[FIREWALL_ID]
    if (
        sparse_oracle.get("ledger_binding", {})
        .get("contract", {})
        .get("dependency_capability_ids")
        != [WRONG_DEPENDENCY]
        or repair_row.get("candidate_oracle_record_canonical_sha256")
        != sha256(canonical_bytes(sparse_oracle))
        or sparse_oracle.get("runtime_state") != "not_qualified"
        or sparse_oracle.get("evidence") != []
        or firewall_oracle.get("runtime_state") != "not_qualified"
        or firewall_oracle.get("evidence") != []
    ):
        raise MappingV2Error("resolved candidate oracle boundary drift")
    return predecessor, bundles, repair, oracles


def _resolved_row(
    predecessor_row: dict[str, Any], bundles: dict[str, Any]
) -> dict[str, Any]:
    row = copy.deepcopy(predecessor_row)
    capability_id = row["capability_id"]
    if capability_id == SPARSE_ID:
        if (
            row.get("mapping_state") != "unmapped_contract_conflict"
            or row.get("leaf_bundle_id") is not None
            or row.get("suggested_bundle_id") != SPARSE_LEAF
            or row.get("reason_code")
            != "sparse4d_title_surface_conflicts_with_mv3dt_dependency"
        ):
            raise MappingV2Error("predecessor Sparse4D conflict boundary drift")
        row.update(
            {
                "mapping_state": "mapped",
                "leaf_bundle_id": SPARSE_LEAF,
                "suggested_bundle_id": None,
                "reason_code": "sparse4d_dependency_repaired_custom_data_scope",
                "dependency_closure": _dependency_closure(SPARSE_LEAF, bundles),
            }
        )
        return row
    if capability_id == FIREWALL_ID:
        if (
            row.get("mapping_state") != "unmapped_scope_gap"
            or row.get("leaf_bundle_id") is not None
            or row.get("suggested_bundle_id") is not None
            or row.get("reason_code")
            != "physical_interface_firewall_has_no_generic_bundle"
        ):
            raise MappingV2Error("predecessor firewall scope-gap boundary drift")
        row.update(
            {
                "mapping_state": "mapped",
                "leaf_bundle_id": FIREWALL_CONFIGURATION,
                "suggested_bundle_id": None,
                "reason_code": "physical_interface_firewall_bounded_bundle_scope",
                "dependency_closure": _dependency_closure(
                    FIREWALL_CONFIGURATION, bundles
                ),
            }
        )
        return row
    raise MappingV2Error(f"unexpected resolution target: {capability_id}")


def compile_mapping(
    source: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    source = _load_locked_sources() if source is None else source
    predecessor, bundles, repair, _oracles = _validate_sources(source)
    predecessor_rows = predecessor["mappings"]
    mappings = [
        _resolved_row(row, bundles)
        if row["capability_id"] in RESOLVED_IDS
        else copy.deepcopy(row)
        for row in predecessor_rows
    ]
    if len(mappings) != 211:
        raise MappingV2Error("mapping denominator drift")

    unaffected_before = [
        row for row in predecessor_rows if row["capability_id"] not in RESOLVED_IDS
    ]
    unaffected_after = [
        row for row in mappings if row["capability_id"] not in RESOLVED_IDS
    ]
    if len(unaffected_before) != 209 or unaffected_after != unaffected_before:
        raise MappingV2Error("209 unaffected mapping rows were not preserved exactly")
    unaffected_hash = sha256(canonical_bytes(unaffected_after))
    if unaffected_hash != EXPECTED_UNAFFECTED_ROWS_SHA256:
        raise MappingV2Error("unaffected mapping-row identity drift")

    state_counts = {
        state: sum(row["mapping_state"] == state for row in mappings)
        for state in EXPECTED_STATE_COUNTS
    }
    direct_counts = {
        bundle_id: sum(row["leaf_bundle_id"] == bundle_id for row in mappings)
        for bundle_id in EXPECTED_BUNDLE_IDS
    }
    closure_counts = {
        bundle_id: sum(bundle_id in row["dependency_closure"] for row in mappings)
        for bundle_id in EXPECTED_BUNDLE_IDS
    }
    binding_counts = {
        kind: sum(row["binding_kind"] == kind for row in mappings)
        for kind in ("workload", "protocol", "none")
    }
    if state_counts != EXPECTED_STATE_COUNTS:
        raise MappingV2Error(f"mapping state counts drift: {state_counts}")
    if direct_counts != EXPECTED_DIRECT_COUNTS:
        raise MappingV2Error(f"direct leaf counts drift: {direct_counts}")
    if closure_counts != EXPECTED_CLOSURE_COUNTS:
        raise MappingV2Error(f"dependency closure counts drift: {closure_counts}")
    if binding_counts != {"workload": 60, "protocol": 23, "none": 128}:
        raise MappingV2Error(f"binding coverage counts drift: {binding_counts}")

    by_id = {row["capability_id"]: row for row in mappings}
    if by_id[FIREWALL_ID]["dependency_closure"] != [
        FIREWALL_INSPECTION,
        FIREWALL_CONFIGURATION,
    ]:
        raise MappingV2Error("firewall closure exceeds the two exact firewall bundles")
    if by_id[SPARSE_ID]["dependency_closure"] != [
        "host-prerequisite-evidence-collection",
        "read-only-docker-runtime-inspection",
        "cgroupfs-remediation",
        "model-artifact-downloads",
        "profile-lifecycle",
        SPARSE_LEAF,
    ]:
        raise MappingV2Error("Sparse4D repaired dependency closure drift")
    for row in mappings:
        if (
            row.get("approval_state") != "no_receipt_not_admitted_not_executable"
            or row.get("required_cloud_inference") is not False
            or row.get("warehouse_sample_bundle") is not False
        ):
            raise MappingV2Error(
                f"candidate nonactivation drift: {row['capability_id']}"
            )

    mapping_hash = sha256(canonical_bytes(mappings))
    if mapping_hash != EXPECTED_MAPPING_ROWS_SHA256:
        raise MappingV2Error("v2 mapping-record identity drift")
    artifact: dict[str, Any] = {
        "schema_version": 2,
        "mapping_id": "thor-vss-3.2.1-candidate-approval-mapping-successor-v2",
        "mode": "inert_classification_only_no_receipt_consumer",
        "target": copy.deepcopy(predecessor["target"]),
        "selected_metadata_set": copy.deepcopy(predecessor["selected_metadata_set"]),
        "source_locks": [
            {"path": path, "raw_sha256": digest}
            for path, digest in EXPECTED_SOURCE_HASHES.items()
        ],
        "candidate_integrity": copy.deepcopy(predecessor["candidate_integrity"]),
        "predecessor_mapping": {
            "mapping_id": predecessor["mapping_id"],
            "raw_sha256": EXPECTED_SOURCE_HASHES[V1_MAPPING_PATH],
            "mapping_records_canonical_sha256": predecessor[
                "mapping_records_canonical_sha256"
            ],
            "preserved_mapping_count": 209,
            "preserved_mapping_records_canonical_sha256": unaffected_hash,
        },
        "approval_contract": {
            "contract_id": bundles["contract_id"],
            "raw_sha256": EXPECTED_SOURCE_HASHES[BUNDLES_PATH],
            "bundle_count": 16,
            "ordered_bundle_ids": list(EXPECTED_BUNDLE_IDS),
            "approval_inheritance": False,
        },
        "resolution_provenance": {
            "resolved_capability_ids": [SPARSE_ID, FIREWALL_ID],
            "sparse4d_repair_id": repair["repair_id"],
            "sparse4d_repair_raw_sha256": EXPECTED_SOURCE_HASHES[REPAIR_PATH],
            "sparse4d_dependency_before": [WRONG_DEPENDENCY],
            "sparse4d_dependency_after": [CORRECT_DEPENDENCY],
            "sparse4d_corrected_candidate_capability_canonical_sha256": (
                CORRECTED_SPARSE_CAPABILITY_SHA256
            ),
            "firewall_direct_leaf": FIREWALL_CONFIGURATION,
            "firewall_exact_closure": [FIREWALL_INSPECTION, FIREWALL_CONFIGURATION],
        },
        "policy": copy.deepcopy(predecessor["policy"]),
        "summary": {
            "candidate_count": 211,
            "state_counts": state_counts,
            "direct_leaf_counts": direct_counts,
            "dependency_closure_link_counts": closure_counts,
            "binding_counts": binding_counts,
            "preserved_mapping_count": 209,
            "resolved_mapping_count": 2,
            "receipt_count": 0,
            "approvals_granted": 0,
            "admitted_candidates": 0,
            "executable_candidates": 0,
        },
        "mapping_records_canonical_sha256": mapping_hash,
        "mappings": mappings,
    }
    schema = strict_json(read_regular(SCHEMA_PATH, "mapping schema"), "mapping schema")
    validate_schema(artifact, schema, "candidate approval mapping v2")
    return artifact


def check_artifact() -> dict[str, Any]:
    compiled = compile_mapping()
    payload = read_regular(ARTIFACT_PATH, "checked mapping")
    expected = (json.dumps(compiled, indent=2, sort_keys=True) + "\n").encode("utf-8")
    checked = strict_json(payload, "checked mapping")
    if checked != compiled or payload != expected:
        raise MappingV2Error("checked mapping differs from deterministic compilation")
    return compiled


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check the inert artifact")
    mode.add_argument(
        "--emit", action="store_true", help="emit fresh artifact to stdout"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = compile_mapping()
        if args.emit:
            print(json.dumps(artifact, indent=2, sort_keys=True))
        else:
            check_artifact()
            print(
                json.dumps(
                    {
                        "ok": True,
                        "mapping_id": artifact["mapping_id"],
                        "candidate_count": 211,
                        "preserved_mapping_count": 209,
                        "resolved_mapping_count": 2,
                        "receipt_count": 0,
                        "admitted_candidates": 0,
                        "executable_candidates": 0,
                    },
                    sort_keys=True,
                )
            )
        return 0
    except (KeyError, MappingV2Error, TypeError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
