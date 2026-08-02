#!/usr/bin/env python3
"""Compile one provenance-rebased, inert Sparse4D dependency repair."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "repair.json"
SCHEMA_PATH = HERE / "repair.schema.json"
MAX_SOURCE_BYTES = 96_000_000

CANDIDATE_ID = "manifest-entry.warehouse-3d-and-mv3dt.00-sparse4d-3d-warehouse"
CANDIDATE_ORACLE_ID = f"oracle.{CANDIDATE_ID}"
WRONG_DEPENDENCY_ID = "runtime.warehouse.profile-mv3dt-pipeline"
CORRECT_DEPENDENCY_ID = "runtime.warehouse.profile-3d-sparse4d-pipeline"
APPROVAL_LEAF_ID = "sparse4d-custom-data-models"
MANIFEST_POINTER = "/features/26/advertised/0"
ADVERTISED = "Sparse4D 3D warehouse"

HISTORICAL_DIR = (
    "deploy/docker/thor-local/qualification/"
    "sparse4d-candidate-dependency-repair"
)
ACTIVATION_DIR = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-activation-rebase-successor"
)
MIGRATION_DIR = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-migration-rebase-successor"
)
MAPPING_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-approval-mapping-rebase-successor"
)
PROTOCOL_DIR = (
    "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates"
)

SELECTOR_PATH = f"{ACTIVATION_DIR}/projected-selector.json"
SELECTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
DESCRIPTOR_PATH = f"{ACTIVATION_DIR}/projected-live-ready-descriptor.json"
DESCRIPTOR_TARGET_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged-rebase-"
    "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c.json"
)
METADATA_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
MIGRATION_RECEIPT_PATH = f"{MIGRATION_DIR}/migration.json"
MIGRATION_RECEIPT_SCHEMA_PATH = f"{MIGRATION_DIR}/migration.schema.json"
ACTIVATION_RECEIPT_PATH = f"{ACTIVATION_DIR}/activation-rebase.json"
ACTIVATION_RECEIPT_SCHEMA_PATH = f"{ACTIVATION_DIR}/activation-rebase.schema.json"
MANIFEST_PATH = f"{MIGRATION_DIR}/post-state-manifest.json"
LEDGER_PATH = f"{MIGRATION_DIR}/post-state-official-capabilities.json"
LEDGER_SCHEMA_PATH = "deploy/docker/thor-local/parity/official-capabilities.schema.json"
ACCEPTANCE_PATH = f"{MIGRATION_DIR}/post-state-acceptance-inventory.json"
ORACLES_PATH = f"{MIGRATION_DIR}/post-state-capability-oracles.json"
ORACLES_SCHEMA_PATH = f"{MIGRATION_DIR}/post-state-capability-oracles.schema.json"
SOURCE_COMPOSE_PATH = (
    "deploy/docker/industry-profiles/warehouse-operations/warehouse-3d-app/"
    "warehouse-3d-app.yml"
)
THOR_COMPOSE_PATH = "deploy/docker/thor-local/warehouse-sparse4d.compose.yml"
THOR_LAUNCHER_PATH = "deploy/docker/scripts/thor-warehouse-sparse4d.sh"
SPARSE_CONTRACT_PATH = (
    "deploy/docker/thor-local/qualification/sparse4d-entry-oracles/contract.json"
)
SPARSE_CONTRACT_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/sparse4d-entry-oracles/contract.schema.json"
)
BUNDLES_PATH = (
    "deploy/docker/thor-local/qualification/runtime-approval-bundles/contract.json"
)
BUNDLES_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/runtime-approval-bundles/"
    "contract.schema.json"
)
PREDECESSOR_MAPPING_PATH = f"{MAPPING_DIR}/mapping.json"
PREDECESSOR_MAPPING_SCHEMA_PATH = f"{MAPPING_DIR}/mapping.schema.json"
PROTOCOL_PATH = f"{PROTOCOL_DIR}/protocol-cases-v2-candidate.json"
PROTOCOL_SCHEMA_PATH = f"{PROTOCOL_DIR}/protocol-cases-v2-candidate.schema.json"

EXPECTED_SOURCE_HASHES = {
    SELECTOR_PATH: "d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112",
    SELECTOR_SCHEMA_PATH: "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    DESCRIPTOR_PATH: "4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca",
    METADATA_SCHEMA_PATH: "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    MIGRATION_RECEIPT_PATH: "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c",
    MIGRATION_RECEIPT_SCHEMA_PATH: "45c41fc02b60fa466689ab2ece0e87487287a20e3d247ba0f62293c649a349c0",
    ACTIVATION_RECEIPT_PATH: "93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e",
    ACTIVATION_RECEIPT_SCHEMA_PATH: "5a4d3c481577540b21531ca08fbfe3e814b310a5e428b9fd7af8b02f9c9bb85f",
    MANIFEST_PATH: "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    LEDGER_PATH: "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    LEDGER_SCHEMA_PATH: "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    ACCEPTANCE_PATH: "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    ORACLES_PATH: "911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021",
    ORACLES_SCHEMA_PATH: "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    SOURCE_COMPOSE_PATH: "131b01a91d9d6cc495a6f96843cd27e587c84a2f5afd49a93a6e293f61d9d6c8",
    THOR_COMPOSE_PATH: "e385a4a3c78fe3cc35f51f7a5f35fae43746b5172f61c65a53b7ec8a1c05d914",
    THOR_LAUNCHER_PATH: "c1174164a494263e62139e9507e15836b539b133cebae813ec99b5bbc5765f4c",
    SPARSE_CONTRACT_PATH: "e53dc8ce55d252b6dc3679223b553cc344d717cc867472b755a6a67846a9aa48",
    SPARSE_CONTRACT_SCHEMA_PATH: "74b1690194c9409734f3775815f33432aad975a9e79314e83f705550faeba6fd",
    BUNDLES_PATH: "8bfa16650574de7ac1906da4eab048a30680f4094dd62cbea0cd5319b9d24e4f",
    BUNDLES_SCHEMA_PATH: "400b3b8720cd9332c069cc2d5d14aa54722680a4493ccfabef8701db5e98d36e",
    PREDECESSOR_MAPPING_PATH: "dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a",
    PREDECESSOR_MAPPING_SCHEMA_PATH: "41271a9716e1462d789e9e26a98f9d4a49a830157be4d9c0105ea9824bebc3d5",
    PROTOCOL_PATH: "cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7",
    PROTOCOL_SCHEMA_PATH: "399471d0efd73614e507426095390a4a2e731aa4970b916199344b89b0304fbb",
}

IMMUTABLE_HISTORICAL_HASHES = {
    f"{HISTORICAL_DIR}/README.md": "5c55602ce56c2d6819a19c6b9ae190936989786f8382c2cc1a5b454c00ccd4e9",
    f"{HISTORICAL_DIR}/EVIDENCE.md": "7875cac099488a5700e242c25d5f36aaa9ef3e6c29b9feed49a7d741aef7c152",
    f"{HISTORICAL_DIR}/compiler.py": "57c960a00f37e111da66844c862368d40d52626c6c05157bb1ac10eb1b725656",
    f"{HISTORICAL_DIR}/repair.json": "2ed1a2bb1afc7b3e79d4a1a688d770780639f307f06f29d222e13f3d23683ffd",
    f"{HISTORICAL_DIR}/repair.schema.json": "1437c5fd692890df0e55b2cc61d2c214cd7e84b8ac0d3e0540feb8f1f8d5a619",
    f"{HISTORICAL_DIR}/tests/test_compiler.py": "ccf08f954805c672fef50e8a2d0e1ac17201e13a661cbac13f9aeffd23a2ca5a",
    "deploy/docker/thor-local/parity/metadata_sets/selector.json": "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-metadata-500-staged.json": "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
}

EXPECTED_RECORD_HASHES = {
    "correct_capability": "da47b32625aa4c75378a3e1afa8f8c95b276a78da6bf45caab0f57b965451939",
    "wrong_capability": "6f4c15a07410953a524ba5ed92974f66e68ca72a89caf9bd412a1719dee22679",
    "candidate_capability": "8e20dee77f1cc2049ef892a05d086a8a4581c9b04b3d3996eca1d768ac04d7cf",
    "correct_oracle": "9881c395728e8540f49c94157b8d2313ba6895c160da38319e6dafaf77c289ce",
    "wrong_oracle": "cfb536bf724b54a16c12a164df8f6e92975b7e46d68eca2ac149b790481191c6",
    "candidate_oracle": "45ef0ea3e789ce812c8d6345b43e9637caca3e17bee7ba50a90fcada811d0a19",
    "corrected_candidate_capability": "086e0cadd433638f890d86d9c1bf95ec0ecab037fb3c4c52323f7b0ff12afd90",
    "approval_bundle": "163a8dfacbd0e6acace5bca1838f1f0f7bb5358c6a5fa6f3eb3b32bc5226b6ce",
}

EXPECTED_ARTIFACT_PAYLOAD_SHA256 = (
    "8d16d8c768d947d878802d7b9f8259444e6398d81211358011ec0fc547633ca5"
)
EXPECTED_ARTIFACT_RAW_SHA256 = (
    "099b89d6e0b75b01e768b71ebaa6b0a719153185cf7aba5e6d0e5eb50e3247d7"
)


class RepairError(RuntimeError):
    """A source lock or fail-closed repair invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RepairError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                RepairError(f"{label}: non-finite JSON token {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RepairError(f"{label}: root must be an object")
    return value


def _resolve_regular(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise RepairError(f"unsafe source path: {relative}")
    current = REPO_ROOT
    for part in pure.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise RepairError(f"source is missing: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RepairError(f"source path traverses a symlink: {relative}")
    if not stat.S_ISREG(current.stat().st_mode):
        raise RepairError(f"source is not a regular file: {relative}")
    return current


def _load_sources() -> tuple[dict[str, Any], list[dict[str, str]]]:
    sources: dict[str, Any] = {}
    locks: list[dict[str, str]] = []
    for relative, expected_hash in EXPECTED_SOURCE_HASHES.items():
        payload = _resolve_regular(relative).read_bytes()
        if len(payload) > MAX_SOURCE_BYTES:
            raise RepairError(f"source exceeds size bound: {relative}")
        observed_hash = sha256(payload)
        if observed_hash != expected_hash:
            raise RepairError(f"source raw hash drift: {relative}")
        sources[relative] = (
            _strict_json(payload, relative)
            if relative.endswith(".json")
            else payload.decode("utf-8")
        )
        locks.append({"path": relative, "raw_sha256": observed_hash})
    return sources, locks


def _git_blob_oid(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def _assert_immutable_historical() -> list[dict[str, str]]:
    locks: list[dict[str, str]] = []
    for relative, expected_hash in IMMUTABLE_HISTORICAL_HASHES.items():
        payload = _resolve_regular(relative).read_bytes()
        observed_hash = sha256(payload)
        if observed_hash != expected_hash:
            raise RepairError(f"immutable historical/canonical drift: {relative}")
        locks.append({"path": relative, "raw_sha256": observed_hash})
    return locks


def _validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise RepairError(f"{label} schema invalid: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise RepairError(f"{label} schema violation at {location}: {error.message}")


def _by_id(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise RepairError(f"{label}: missing or duplicate {key}: {identity!r}")
        result[identity] = row
    return result


def _require_text(source: str, tokens: tuple[str, ...], label: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise RepairError(f"{label}: required static semantics missing: {missing[0]!r}")


def _validate_selected_set(source: dict[str, Any]) -> None:
    selector = source[SELECTOR_PATH]
    descriptor = source[DESCRIPTOR_PATH]
    _validate_schema(selector, source[SELECTOR_SCHEMA_PATH], "selector")
    _validate_schema(descriptor, source[METADATA_SCHEMA_PATH], "metadata descriptor")
    selected = selector.get("selected_set")
    by_set = {item.get("set_id"): item for item in selector.get("available_sets", [])}
    selected_row = by_set.get(selected)
    if (
        selected != "thor-vss-3.2.1-metadata-500-staged"
        or selected_row is None
        or selected_row.get("descriptor_path") != DESCRIPTOR_TARGET_PATH
        or selected_row.get("descriptor_raw_sha256")
        != EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH]
        or descriptor.get("set_id") != selected
        or descriptor.get("lifecycle") != "live_ready"
        or descriptor.get("expected_counts")
        != {"capabilities": 500, "oracles": 500, "feature_families": 55}
    ):
        raise RepairError("selected Metadata-500 identity or lifecycle drift")
    documents = descriptor.get("documents", {})
    expected_documents = {
        "manifest": (MANIFEST_PATH, EXPECTED_SOURCE_HASHES[MANIFEST_PATH]),
        "official_capabilities": (LEDGER_PATH, EXPECTED_SOURCE_HASHES[LEDGER_PATH]),
        "capability_oracles": (ORACLES_PATH, EXPECTED_SOURCE_HASHES[ORACLES_PATH]),
        "acceptance_inventory": (
            ACCEPTANCE_PATH,
            EXPECTED_SOURCE_HASHES[ACCEPTANCE_PATH],
        ),
    }
    for key, (path, digest) in expected_documents.items():
        item = documents.get(key, {})
        if item.get("path") != path or item.get("raw_sha256") != digest:
            raise RepairError(f"selected Metadata-500 {key} binding drift")


def _validate_rebase_provenance(source: dict[str, Any]) -> None:
    migration = source[MIGRATION_RECEIPT_PATH]
    activation = source[ACTIVATION_RECEIPT_PATH]
    mapping = source[PREDECESSOR_MAPPING_PATH]
    protocol = source[PROTOCOL_PATH]
    _validate_schema(
        migration,
        source[MIGRATION_RECEIPT_SCHEMA_PATH],
        "migration rebase receipt",
    )
    _validate_schema(
        activation,
        source[ACTIVATION_RECEIPT_SCHEMA_PATH],
        "activation rebase receipt",
    )
    _validate_schema(
        mapping,
        source[PREDECESSOR_MAPPING_SCHEMA_PATH],
        "mapping rebase",
    )
    _validate_schema(protocol, source[PROTOCOL_SCHEMA_PATH], "protocol-v2 candidate")

    expected_members = {
        "post-state-manifest.json": MANIFEST_PATH,
        "post-state-official-capabilities.json": LEDGER_PATH,
        "post-state-acceptance-inventory.json": ACCEPTANCE_PATH,
        "post-state-capability-oracles.json": ORACLES_PATH,
        "post-state-capability-oracles.schema.json": ORACLES_SCHEMA_PATH,
    }
    for name, path in expected_members.items():
        if migration.get("artifacts", {}).get(name) != {
            "path": path,
            "raw_sha256": EXPECTED_SOURCE_HASHES[path],
        }:
            raise RepairError(f"migration rebase member binding drift: {name}")
    if (
        migration.get("policy", {}).get("modifies_live_files") is not False
        or migration.get("policy", {}).get("runtime_execution") != "forbidden"
        or migration.get("policy", {}).get("candidate_runtime_promotion") is not False
    ):
        raise RepairError("migration rebase inert boundary drift")

    activation_artifacts = activation.get("artifacts", {})
    if (
        activation_artifacts.get("projected-selector.json")
        != {"path": SELECTOR_PATH, "raw_sha256": EXPECTED_SOURCE_HASHES[SELECTOR_PATH]}
        or activation_artifacts.get("projected-live-ready-descriptor.json", {}).get(
            "path"
        )
        != DESCRIPTOR_PATH
        or activation_artifacts.get("projected-live-ready-descriptor.json", {}).get(
            "raw_sha256"
        )
        != EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH]
        or activation_artifacts.get("projected-live-ready-descriptor.json", {}).get(
            "staged_immutable_target_path"
        )
        != DESCRIPTOR_TARGET_PATH
        or activation.get("source_locks", {}).get("migration_proof")
        != {
            "path": MIGRATION_RECEIPT_PATH,
            "raw_sha256": EXPECTED_SOURCE_HASHES[MIGRATION_RECEIPT_PATH],
        }
        or activation.get("policy", {}).get("runtime_execution") != "forbidden"
        or activation.get("policy", {}).get("candidate_runtime_promotion") is not False
    ):
        raise RepairError("activation rebase provenance or inert boundary drift")

    mapping_locks = {
        item["path"]: item["raw_sha256"] for item in mapping.get("source_locks", [])
    }
    required_mapping_locks = {
        SELECTOR_PATH: EXPECTED_SOURCE_HASHES[SELECTOR_PATH],
        DESCRIPTOR_PATH: EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH],
        ORACLES_PATH: EXPECTED_SOURCE_HASHES[ORACLES_PATH],
        ORACLES_SCHEMA_PATH: EXPECTED_SOURCE_HASHES[ORACLES_SCHEMA_PATH],
        ACTIVATION_RECEIPT_PATH: EXPECTED_SOURCE_HASHES[ACTIVATION_RECEIPT_PATH],
        ACTIVATION_RECEIPT_SCHEMA_PATH: EXPECTED_SOURCE_HASHES[
            ACTIVATION_RECEIPT_SCHEMA_PATH
        ],
        PROTOCOL_PATH: EXPECTED_SOURCE_HASHES[PROTOCOL_PATH],
        PROTOCOL_SCHEMA_PATH: EXPECTED_SOURCE_HASHES[PROTOCOL_SCHEMA_PATH],
    }
    if any(
        mapping_locks.get(path) != digest
        for path, digest in required_mapping_locks.items()
    ):
        raise RepairError("mapping rebase activation/migration/protocol lock drift")
    if (
        mapping.get("summary", {}).get("candidate_count") != 211
        or mapping.get("summary", {}).get("admitted_candidates") != 0
        or mapping.get("summary", {}).get("executable_candidates") != 0
        or mapping.get("summary", {}).get("receipt_count") != 0
        or protocol.get("summary", {}).get("candidate_protocol_cases") != 23
        or protocol.get("summary", {}).get("runtime_evidence_records") != 0
    ):
        raise RepairError("mapping or protocol inert denominator drift")


def _validate_runtime_boundaries(candidate: dict[str, Any]) -> None:
    if (
        candidate.get("runtime_state") != "not_qualified"
        or candidate.get("current_state") != "open_unexecuted"
        or candidate.get("evidence") != []
        or candidate.get("can_promote_runtime_state") is not False
        or candidate.get("readiness")
        != {
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
        or candidate.get("execution_bounds", {}).get("executor") is not None
        or candidate.get("execution_bounds", {}).get("collectors") is not None
        or candidate.get("cleanup", {}).get("executor") is not None
        or candidate.get("fixture", {}).get("materialization") is not None
    ):
        raise RepairError("candidate runtime/evidence/non-execution boundary drift")
    gates = {
        gate.get("id"): gate.get("status")
        for gate in candidate.get("admission_gates", [])
    }
    if gates.get("operator-approval") != "unmet":
        raise RepairError("candidate operator gate is not unmet")
    if (
        candidate.get("execution_bounds", {}).get("warehouse_sample_bundle")
        not in {None, "excluded"}
        or candidate.get("ledger_binding", {})
        .get("contract", {})
        .get("warehouse_sample_bundle")
        != "excluded"
        or candidate.get("fixture", {}).get("warehouse_sample_bundle")
        not in {None, False}
    ):
        raise RepairError("candidate Warehouse sample exclusion drift")


def compile_repair(
    source_override: dict[str, Any] | None = None,
    lock_override: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    historical_locks = _assert_immutable_historical()
    if source_override is None:
        source, source_locks = _load_sources()
    else:
        source = source_override
        source_locks = copy.deepcopy(
            lock_override
            if lock_override is not None
            else [
                {"path": path, "raw_sha256": digest}
                for path, digest in EXPECTED_SOURCE_HASHES.items()
            ]
        )

    _validate_selected_set(source)
    _validate_rebase_provenance(source)
    ledger = source[LEDGER_PATH]
    oracles = source[ORACLES_PATH]
    manifest = source[MANIFEST_PATH]
    predecessor = source[PREDECESSOR_MAPPING_PATH]
    bundles = source[BUNDLES_PATH]
    sparse_contract = source[SPARSE_CONTRACT_PATH]
    _validate_schema(ledger, source[LEDGER_SCHEMA_PATH], "selected ledger")
    _validate_schema(oracles, source[ORACLES_SCHEMA_PATH], "selected oracles")
    _validate_schema(
        predecessor, source[PREDECESSOR_MAPPING_SCHEMA_PATH], "predecessor mapping"
    )
    _validate_schema(bundles, source[BUNDLES_SCHEMA_PATH], "approval bundles")
    _validate_schema(
        sparse_contract,
        source[SPARSE_CONTRACT_SCHEMA_PATH],
        "Sparse4D entry contract",
    )

    if (
        len(ledger.get("capabilities", [])) != 500
        or len(oracles.get("oracles", [])) != 500
    ):
        raise RepairError("selected Metadata-500 denominator drift")
    capabilities = _by_id(ledger["capabilities"], "id", "capability")
    oracle_by_id = _by_id(oracles["oracles"], "capability_id", "oracle")
    candidate = capabilities[CANDIDATE_ID]
    candidate_oracle = oracle_by_id[CANDIDATE_ID]
    wrong = capabilities[WRONG_DEPENDENCY_ID]
    wrong_oracle = oracle_by_id[WRONG_DEPENDENCY_ID]
    correct = capabilities[CORRECT_DEPENDENCY_ID]
    correct_oracle = oracle_by_id[CORRECT_DEPENDENCY_ID]

    indexed_capabilities = ledger["capabilities"]
    indexed_oracles = oracles["oracles"]
    expected_indices = {
        CANDIDATE_ID: 457,
        WRONG_DEPENDENCY_ID: 268,
        CORRECT_DEPENDENCY_ID: 267,
    }
    for capability_id, index in expected_indices.items():
        if (
            indexed_capabilities[index].get("id") != capability_id
            or indexed_oracles[index].get("capability_id") != capability_id
        ):
            raise RepairError(f"selected row index drift: {capability_id}")

    record_values = {
        "correct_capability": correct,
        "wrong_capability": wrong,
        "candidate_capability": candidate,
        "correct_oracle": correct_oracle,
        "wrong_oracle": wrong_oracle,
        "candidate_oracle": candidate_oracle,
    }
    for label, value in record_values.items():
        if sha256(canonical_bytes(value)) != EXPECTED_RECORD_HASHES[label]:
            raise RepairError(f"exact {label} record drift")
    for capability_id, capability, oracle in (
        (CORRECT_DEPENDENCY_ID, correct, correct_oracle),
        (WRONG_DEPENDENCY_ID, wrong, wrong_oracle),
        (CANDIDATE_ID, candidate, candidate_oracle),
    ):
        expected_binding = copy.deepcopy(capability)
        expected_binding.pop("id")
        expected_binding.pop("scenario_ids")
        if oracle.get("ledger_binding") != expected_binding:
            raise RepairError(f"oracle/ledger binding drift: {capability_id}")

    feature = manifest.get("features", [])[26]
    if (
        feature.get("id") != "warehouse-3d-and-mv3dt"
        or feature.get("advertised", [None])[0] != ADVERTISED
        or CANDIDATE_ID not in feature.get("official_capability_ids", [])
        or candidate.get("feature_id") != feature.get("id")
        or candidate.get("title") != ADVERTISED
        or candidate.get("contract", {}).get("manifest_pointer") != MANIFEST_POINTER
        or candidate.get("contract", {}).get("advertised_literal") != ADVERTISED
    ):
        raise RepairError("manifest literal/pointer/candidate identity drift")
    candidate_contract = candidate["contract"]
    if candidate_contract.get("dependency_capability_ids") != [WRONG_DEPENDENCY_ID]:
        raise RepairError("expected wrong MV3DT dependency is absent or changed")
    if candidate_contract.get("implementation_surfaces") != [SOURCE_COMPOSE_PATH]:
        raise RepairError("candidate Sparse4D implementation surface drift")
    if candidate_oracle.get("advertised") != ADVERTISED or candidate_oracle.get(
        "adjacent_negative_observations"
    ) != [
        {
            "id": "adjacent-negative-01",
            "description": (
                "Do not accept successful MV3DT multiview warehouse behavior as proof "
                "of Sparse4D 3D warehouse; its literal-specific observations must pass "
                "independently."
            ),
        }
    ]:
        raise RepairError("candidate Sparse4D/MV3DT adjacent-negative drift")
    _validate_runtime_boundaries(candidate_oracle)

    if (
        correct.get("feature_id") != "warehouse-3d-and-mv3dt"
        or correct.get("title") != "Warehouse Sparse4D 3D pipeline"
        or correct.get("contract", {}).get("perception") != "Sparse4D"
        or correct.get("contract", {}).get("source_topic") != "mdx-bev"
        or correct.get("contract", {}).get("synchronized_camera_timestamps") is not True
        or wrong.get("title") != "Warehouse RT-DETR plus MV3DT pipeline"
        or wrong.get("contract", {}).get("detector") != "RT-DETR"
        or wrong.get("contract", {}).get("tracker") != "MV3DT"
        or wrong.get("contract", {}).get("inter_camera_broker") != "MQTT"
    ):
        raise RepairError("authoritative Sparse4D/MV3DT semantic distinction drift")

    _require_text(
        source[SOURCE_COMPOSE_PATH],
        (
            "  perception-3d:",
            "      service: perception",
            '    profiles: ["bp_wh_kafka_3d","bp_wh_redis_3d"]',
            "    container_name: vss-rtvi-cv",
            "sparse4d_warehouse_v2.2.onnx",
            "_ov_kmeans900_v2.2.npy",
            "      DS_MODEL_FAMILY: sparse4d-warehouse",
            '      DS_MODE_FLAG: "5"',
        ),
        "official Sparse4D source Compose",
    )
    _require_text(
        source[THOR_COMPOSE_PATH],
        (
            "# Thor runtime/offline overrides for a custom-data Redis Sparse4D lane.",
            "  perception-3d:",
            "    runtime: nvidia",
            '      TRANSFORMERS_OFFLINE: "1"',
            '      HF_HUB_OFFLINE: "1"',
        ),
        "Thor Sparse4D overlay",
    )
    _require_text(
        source[THOR_LAUNCHER_PATH],
        (
            'compose_project="thor-wh-sparse4d"',
            "COMPOSE_PROFILES=bp_wh_redis_3d",
            "MODE=3d BP_PROFILE=bp_wh_redis STREAM_TYPE=redis",
            '.services["perception-3d"].environment.DS_MODEL_FAMILY == "sparse4d-warehouse"',
            "--profile bp_wh_redis_3d up -d --no-build --pull never",
        ),
        "Thor Sparse4D launcher",
    )

    admission = sparse_contract.get("admission", {})
    policy = sparse_contract.get("policy", {})
    if (
        admission.get("lane") != THOR_LAUNCHER_PATH
        or admission.get("sparse4d_model") != "sparse4d_warehouse_v2.2.onnx"
        or admission.get("anchor") != "_ov_kmeans900_v2.2.npy"
        or admission.get("anchor_shape") != [900, 11]
        or admission.get("camera_count") != 4
        or admission.get("dataset") != "operator_supplied_custom_slug_only"
        or policy.get("warehouse_sample_bundle") != "excluded"
        or policy.get("candidate_evidence_only") is not True
        or policy.get("advances_live_ledgers") is not False
        or policy.get("runtime_receipts_bundled") is not False
    ):
        raise RepairError("Sparse4D custom-data admission boundary drift")

    bundle_by_id = _by_id(bundles.get("bundles", []), "id", "approval bundle")
    approval_bundle = bundle_by_id[APPROVAL_LEAF_ID]
    if (
        sha256(canonical_bytes(approval_bundle))
        != EXPECTED_RECORD_HASHES["approval_bundle"]
        or approval_bundle.get("depends_on")
        != ["profile-lifecycle", "model-artifact-downloads"]
        or bundles.get("approval_policy", {}).get("approval_inheritance") is not False
        or bundles.get("approval_policy", {}).get("compiler_can_grant_approval")
        is not False
    ):
        raise RepairError("Sparse4D approval leaf or no-inheritance policy drift")

    predecessor_by_id = _by_id(
        predecessor.get("mappings", []), "capability_id", "predecessor mapping"
    )
    predecessor_row = predecessor_by_id[CANDIDATE_ID]
    if (
        predecessor_row.get("oracle_index") != 457
        or predecessor_row.get("candidate_record_canonical_sha256")
        != EXPECTED_RECORD_HASHES["candidate_oracle"]
        or predecessor_row.get("mapping_state") != "unmapped_contract_conflict"
        or predecessor_row.get("leaf_bundle_id") is not None
        or predecessor_row.get("suggested_bundle_id") != APPROVAL_LEAF_ID
        or predecessor_row.get("reason_code")
        != "sparse4d_title_surface_conflicts_with_mv3dt_dependency"
        or predecessor_row.get("approval_state")
        != "no_receipt_not_admitted_not_executable"
    ):
        raise RepairError("predecessor approval-mapping conflict drift")

    corrected_candidate = copy.deepcopy(candidate)
    corrected_candidate["contract"]["dependency_capability_ids"] = [
        CORRECT_DEPENDENCY_ID
    ]
    corrected_hash = sha256(canonical_bytes(corrected_candidate))
    if corrected_hash != EXPECTED_RECORD_HASHES["corrected_candidate_capability"]:
        raise RepairError("single-field corrected candidate identity drift")
    before_without_dependency = copy.deepcopy(candidate)
    after_without_dependency = copy.deepcopy(corrected_candidate)
    before_without_dependency["contract"].pop("dependency_capability_ids")
    after_without_dependency["contract"].pop("dependency_capability_ids")
    if before_without_dependency != after_without_dependency:
        raise RepairError("repair changes more than the dependency capability ID")

    artifact: dict[str, Any] = {
        "schema_version": 1,
        "repair_id": (
            "thor-vss-3.2.1-sparse4d-candidate-dependency-repair-"
            "rebase-successor"
        ),
        "mode": "inert_additive_planning_rebase_successor",
        "target": {
            "product_version": "3.2.1",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "hardware": "NVIDIA Jetson Thor",
        },
        "selected_metadata_set": {
            "set_id": "thor-vss-3.2.1-metadata-500-staged",
            "selector_raw_sha256": EXPECTED_SOURCE_HASHES[SELECTOR_PATH],
            "descriptor_raw_sha256": EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH],
            "candidate_oracle_index": 457,
        },
        "historical_predecessor": {
            "package_path": HISTORICAL_DIR,
            "repair_raw_sha256": IMMUTABLE_HISTORICAL_HASHES[
                f"{HISTORICAL_DIR}/repair.json"
            ],
            "repair_payload_sha256": (
                "ef308921bd58ce44243692a46438d365cc4998cb733b877684d6bf1944deb84b"
            ),
            "repair_git_blob_oid": "388d4059c74d6eace59e63151e5c08a89a6ff7c2",
            "semantic_record_hashes_preserved": True,
            "immutable_locks": historical_locks,
        },
        "rebase_provenance": {
            "mapping_raw_sha256": EXPECTED_SOURCE_HASHES[
                PREDECESSOR_MAPPING_PATH
            ],
            "mapping_schema_raw_sha256": EXPECTED_SOURCE_HASHES[
                PREDECESSOR_MAPPING_SCHEMA_PATH
            ],
            "activation_receipt_raw_sha256": EXPECTED_SOURCE_HASHES[
                ACTIVATION_RECEIPT_PATH
            ],
            "migration_receipt_raw_sha256": EXPECTED_SOURCE_HASHES[
                MIGRATION_RECEIPT_PATH
            ],
            "protocol_raw_sha256": EXPECTED_SOURCE_HASHES[PROTOCOL_PATH],
            "protocol_schema_raw_sha256": EXPECTED_SOURCE_HASHES[
                PROTOCOL_SCHEMA_PATH
            ],
        },
        "repair": {
            "capability_id": CANDIDATE_ID,
            "oracle_id": CANDIDATE_ORACLE_ID,
            "manifest_pointer": MANIFEST_POINTER,
            "advertised_literal": ADVERTISED,
            "field": "ledger_binding.contract.dependency_capability_ids",
            "before": [WRONG_DEPENDENCY_ID],
            "after": [CORRECT_DEPENDENCY_ID],
            "change_count": 1,
            "disposition": "replace_objectively_wrong_mv3dt_dependency_for_planning_classification",
            "candidate_capability_before_canonical_sha256": EXPECTED_RECORD_HASHES[
                "candidate_capability"
            ],
            "candidate_capability_after_canonical_sha256": corrected_hash,
            "candidate_oracle_record_canonical_sha256": EXPECTED_RECORD_HASHES[
                "candidate_oracle"
            ],
        },
        "semantic_proof": {
            "wrong_dependency": {
                "capability_id": WRONG_DEPENDENCY_ID,
                "title": "Warehouse RT-DETR plus MV3DT pipeline",
                "ledger_index": 268,
                "capability_record_canonical_sha256": EXPECTED_RECORD_HASHES[
                    "wrong_capability"
                ],
                "oracle_record_canonical_sha256": EXPECTED_RECORD_HASHES[
                    "wrong_oracle"
                ],
                "detector": "RT-DETR",
                "tracker": "MV3DT",
                "inter_camera_broker": "MQTT",
                "objective_mismatch": (
                    "The advertised literal, implementation surface, required observations, "
                    "and adjacent-negative contract are Sparse4D-specific and explicitly "
                    "reject MV3DT behavior as proof."
                ),
            },
            "correct_dependency": {
                "capability_id": CORRECT_DEPENDENCY_ID,
                "title": "Warehouse Sparse4D 3D pipeline",
                "ledger_index": 267,
                "capability_record_canonical_sha256": EXPECTED_RECORD_HASHES[
                    "correct_capability"
                ],
                "oracle_record_canonical_sha256": EXPECTED_RECORD_HASHES[
                    "correct_oracle"
                ],
                "perception": "Sparse4D",
                "source_topic": "mdx-bev",
                "synchronized_camera_timestamps": True,
            },
            "static_service_identity": {
                "binding_state": "reviewed_static_identity_not_executable_service_binding",
                "source_compose_path": SOURCE_COMPOSE_PATH,
                "source_compose_service": "perception-3d",
                "extends_service": "perception",
                "container_name": "vss-rtvi-cv",
                "source_profiles": ["bp_wh_kafka_3d", "bp_wh_redis_3d"],
                "thor_overlay_path": THOR_COMPOSE_PATH,
                "thor_launcher_path": THOR_LAUNCHER_PATH,
                "thor_compose_project": "thor-wh-sparse4d",
                "thor_profile": "bp_wh_redis_3d",
                "mode": "3d",
                "model_family": "sparse4d-warehouse",
                "sparse4d_model": "sparse4d_warehouse_v2.2.onnx",
                "anchor": "_ov_kmeans900_v2.2.npy",
                "anchor_shape": [900, 11],
                "camera_count": 4,
            },
        },
        "approval_classification": {
            "predecessor_state": "unmapped_contract_conflict",
            "predecessor_mapping_raw_sha256": EXPECTED_SOURCE_HASHES[
                PREDECESSOR_MAPPING_PATH
            ],
            "leaf_bundle_id": APPROVAL_LEAF_ID,
            "leaf_bundle_record_canonical_sha256": EXPECTED_RECORD_HASHES[
                "approval_bundle"
            ],
            "classification_state": "suggested_scope_only_not_approved",
            "approval_state": "no_receipt_not_admitted_not_executable",
            "dependency_disposition": "unresolved_until_separate_exact_receipts",
        },
        "preservation": {
            "selected_metadata_files_modified": 0,
            "historical_package_files_modified": 0,
            "canonical_metadata_files_modified": 0,
            "candidate_runtime_state_before": "not_qualified",
            "candidate_runtime_state_after": "not_qualified",
            "candidate_evidence_records_before": 0,
            "candidate_evidence_records_after": 0,
            "candidate_executor_ready_before": False,
            "candidate_executor_ready_after": False,
            "operator_approval_gate_before": "unmet",
            "operator_approval_gate_after": "unmet",
            "runtime_receipts": 0,
            "runtime_qualification_claims": 0,
        },
        "policy": {
            "repair_scope": "one_exact_candidate_dependency_for_planning_classification_only",
            "canonical_metadata_mutation": False,
            "runtime_state_promotion": False,
            "runtime_evidence_created": 0,
            "receipt_consumer_present": False,
            "approval_granted": False,
            "executor_present": False,
            "runtime_actions": False,
            "network_access": False,
            "docker_access": False,
            "host_inspection": False,
            "model_access": False,
            "downloads": False,
            "warehouse_sample_bundle": "excluded",
            "required_cloud_inference": False,
            "writer_scope": "package_repair_artifact_only",
        },
        "source_locks": source_locks,
    }
    artifact["repair_payload_sha256"] = sha256(canonical_bytes(artifact))
    return artifact


def _load_artifact_schema() -> dict[str, Any]:
    payload = _resolve_regular(str(SCHEMA_PATH.relative_to(REPO_ROOT))).read_bytes()
    return _strict_json(payload, str(SCHEMA_PATH.relative_to(REPO_ROOT)))


def validate_repair(artifact: dict[str, Any]) -> None:
    _validate_schema(artifact, _load_artifact_schema(), "repair artifact")
    payload = copy.deepcopy(artifact)
    observed_payload_hash = payload.pop("repair_payload_sha256")
    if observed_payload_hash != sha256(canonical_bytes(payload)):
        raise RepairError("repair payload hash mismatch")
    if EXPECTED_ARTIFACT_PAYLOAD_SHA256 != observed_payload_hash:
        raise RepairError("repair payload lock drift")


def encoded_artifact(artifact: dict[str, Any]) -> bytes:
    return (json.dumps(artifact, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_artifact(artifact: dict[str, Any]) -> None:
    validate_repair(artifact)
    try:
        package_metadata = HERE.lstat()
    except OSError as exc:
        raise RepairError("package directory is unavailable") from exc
    if stat.S_ISLNK(package_metadata.st_mode) or not stat.S_ISDIR(
        package_metadata.st_mode
    ):
        raise RepairError("package directory must be a regular non-symlink directory")
    try:
        artifact_metadata = ARTIFACT_PATH.lstat()
        if stat.S_ISLNK(artifact_metadata.st_mode) or not stat.S_ISREG(
            artifact_metadata.st_mode
        ):
            raise RepairError("repair output must be a regular non-symlink file")
    except FileNotFoundError:
        pass
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".repair-rebase-", suffix=".tmp", dir=HERE
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded_artifact(artifact))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, ARTIFACT_PATH)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def check_artifact() -> dict[str, Any]:
    artifact = compile_repair()
    validate_repair(artifact)
    expected_bytes = encoded_artifact(artifact)
    path = _resolve_regular(str(ARTIFACT_PATH.relative_to(REPO_ROOT)))
    observed_bytes = path.read_bytes()
    observed_hash = sha256(observed_bytes)
    if EXPECTED_ARTIFACT_RAW_SHA256 != observed_hash:
        raise RepairError("checked repair raw hash drift")
    checked = _strict_json(observed_bytes, str(ARTIFACT_PATH.relative_to(REPO_ROOT)))
    if checked != artifact or observed_bytes != expected_bytes:
        raise RepairError("checked repair differs from deterministic compilation")
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--emit", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifact = compile_repair()
        validate_repair(artifact)
        if args.emit:
            print(json.dumps(artifact, indent=2, sort_keys=True))
        elif args.write:
            write_artifact(artifact)
            print(f"WROTE {ARTIFACT_PATH}")
        else:
            check_artifact()
            print(
                "PASS: one exact Sparse4D planning dependency repair; "
                "metadata_mutations=0, approvals=0, runtime_evidence=0"
            )
        return 0
    except (KeyError, IndexError, RepairError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
