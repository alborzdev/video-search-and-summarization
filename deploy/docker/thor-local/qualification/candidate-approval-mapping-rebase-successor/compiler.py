#!/usr/bin/env python3
"""Compile the inert 211-candidate approval mapping rebase successor.

This module reads only raw-locked repository metadata.  It has no receipt
consumer and no execution facility; a bundle classification is never an
approval or runtime admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "mapping.json"
SCHEMA_PATH = HERE / "mapping.schema.json"
MAX_JSON_BYTES = 96_000_000
HEX64 = re.compile(r"[0-9a-f]{64}").fullmatch

HISTORICAL_SELECTOR_PATH = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
HISTORICAL_DESCRIPTOR_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged.json"
)
ACTIVATION_REBASE_DIR = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-activation-rebase-successor"
)
MIGRATION_REBASE_DIR = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-migration-rebase-successor"
)
SELECTOR_PATH = f"{ACTIVATION_REBASE_DIR}/projected-selector.json"
SELECTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
DESCRIPTOR_PATH = f"{ACTIVATION_REBASE_DIR}/projected-live-ready-descriptor.json"
DESCRIPTOR_LOCATOR_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged-rebase-"
    "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c.json"
)
ACTIVATION_RECEIPT_PATH = f"{ACTIVATION_REBASE_DIR}/activation-rebase.json"
ACTIVATION_RECEIPT_SCHEMA_PATH = (
    f"{ACTIVATION_REBASE_DIR}/activation-rebase.schema.json"
)
DESCRIPTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
ORACLES_PATH = (
    f"{MIGRATION_REBASE_DIR}/"
    "post-state-capability-oracles.json"
)
ORACLES_SCHEMA_PATH = (
    f"{MIGRATION_REBASE_DIR}/"
    "post-state-capability-oracles.schema.json"
)
BUNDLES_PATH = (
    "deploy/docker/thor-local/qualification/runtime-approval-bundles/contract.json"
)
BUNDLES_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/runtime-approval-bundles/"
    "contract.schema.json"
)
WORKLOADS_PATH = (
    "deploy/docker/thor-local/qualification/remaining-entry-workloads/workloads.json"
)
WORKLOADS_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/remaining-entry-workloads/"
    "workload.schema.json"
)
PROTOCOL_PATH = (
    "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates/"
    "protocol-cases-v2-candidate.json"
)
PROTOCOL_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates/"
    "protocol-cases-v2-candidate.schema.json"
)
PROTOCOL_COMPILER_PATH = (
    "deploy/docker/thor-local/qualification/protocol-cases-v2-candidates/compiler.py"
)
PROTOCOL_TESTS_PATH = (
    "deploy/docker/thor-local/qualification/"
    "protocol-cases-v2-candidates/tests/test_compiler.py"
)
RAW_SOURCE_PATHS = frozenset({PROTOCOL_COMPILER_PATH, PROTOCOL_TESTS_PATH})

EXPECTED_SOURCE_HASHES = {
    SELECTOR_PATH: "d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112",
    SELECTOR_SCHEMA_PATH: "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    DESCRIPTOR_PATH: "4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca",
    DESCRIPTOR_SCHEMA_PATH: "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    ORACLES_PATH: "911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021",
    ORACLES_SCHEMA_PATH: "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    ACTIVATION_RECEIPT_PATH: "93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e",
    ACTIVATION_RECEIPT_SCHEMA_PATH: "5a4d3c481577540b21531ca08fbfe3e814b310a5e428b9fd7af8b02f9c9bb85f",
    BUNDLES_PATH: "8bfa16650574de7ac1906da4eab048a30680f4094dd62cbea0cd5319b9d24e4f",
    BUNDLES_SCHEMA_PATH: "400b3b8720cd9332c069cc2d5d14aa54722680a4493ccfabef8701db5e98d36e",
    WORKLOADS_PATH: "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    WORKLOADS_SCHEMA_PATH: "736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14",
    PROTOCOL_PATH: "cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7",
    PROTOCOL_SCHEMA_PATH: "399471d0efd73614e507426095390a4a2e731aa4970b916199344b89b0304fbb",
    PROTOCOL_COMPILER_PATH: "87e3fb6b0894c09ad91b2494bf3e4c6838639d3659eba934ea8ea6183bc961af",
    PROTOCOL_TESTS_PATH: "1503edfe00afe90e5eee95dfe7e5edc5225f6df19a92999ce6d6a1e1743c63cd",
}

EXPECTED_OUTPUT_HASHES = {
    "mapping": "dd5be5e9a73245c3599309497b8b3d9e68c750656984fb0f166423730956722a",
    "schema": "41271a9716e1462d789e9e26a98f9d4a49a830157be4d9c0105ea9824bebc3d5",
}
ALLOWED_OUTPUT_NAMES = frozenset({"mapping.json", "mapping.schema.json"})

IMMUTABLE_FILES = {
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/README.md": "0f9ecc8cab57e9da96f0d118e02f77787c1240c555969abcd9e423542eee2780",
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/EVIDENCE.md": "110784636702d5cd61f91462cd1d31c73da08fe724c5aebe5bad3af1fd768460",
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/compiler.py": "7588e8ae49670ad8c0bdf74ad3744d1da510059d07f5b09258e0835474e79fcf",
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/mapping.json": "4bb8f3a5fba5e201b72e1f1a0f4218bff4b9a999a836c192fca44ca7e35d9cf9",
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/mapping.schema.json": "09f8610cb7f9cc1d060202f5939b7e451fd78b92f58d80d098939e5ca05b518e",
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor/tests/test_compiler.py": "5c213ed5d342977f29bcd0a559554808131ad5190104b1672240414dac85eef5",
    HISTORICAL_SELECTOR_PATH: "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    HISTORICAL_DESCRIPTOR_PATH: "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
}

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
)
EXPECTED_CANDIDATE_ORDER_SHA256 = (
    "1c0cc33efa1aa6283e467e5fc78bbed8b4cbe8ff23fdbf6db3190144996a3ef9"
)
EXPECTED_CANDIDATE_ROWS_SHA256 = (
    "3b579c6abded078f2bc4ddd8fdca34f4f577171463c02f7ecca797ce2f2789ab"
)
EXPECTED_WORKLOAD_PAYLOAD_SHA256 = (
    "0e8512e64399af7d8acc0c7136efbd52da4ebf9119ad0826859e6fce6906d847"
)
EXPECTED_PROTOCOL_PAYLOAD_SHA256 = (
    "6667309aefc03eb410651bd11769301be77cc5d9baf40688fa0f75f5752a58d6"
)
EXPECTED_MAPPING_RECORDS_SHA256 = (
    "9ec211afcabe645573a145c7a5e9dbaf5c030eab552da4add0698f15e33b2062"
)
INTEGRITY_REBASE_IDS = frozenset(
    {
        "manifest-entry.video-summarization-file.03-structured-output",
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
    }
)
INTEGRITY_REBASE_FIELDS = (
    "candidate_record_canonical_sha256",
    "candidate_source_payload_sha256",
    "protocol_binding_canonical_sha256",
)

STATIC_NONACTIVATING_IDS = frozenset(
    {
        "manifest-entry.helm.00-helm-for-four-developer-workflows",
        "manifest-entry.helm.01-helm-for-most-standalone-services",
        "manifest-entry.rt-cv-3d-mv3dt.05-associated-skill",
    }
)
CONTRACT_CONFLICT_ID = "manifest-entry.warehouse-3d-and-mv3dt.00-sparse4d-3d-warehouse"
SCOPE_GAP_ID = "manifest-entry.offline-security.05-physical-interface-firewall"
SEARCH_100_ID = "manifest-entry.search-scale.00-configuration-up-to-100-streams"
SEARCH_PROGRESSIVE_ID = (
    "manifest-entry.search-scale.01-16-concurrent-1080p-streams-tested-by-nvidia"
)
NATIVE_AUDIO_IDS = frozenset(
    {
        "manifest-entry.audio-understanding.00-audio-aware-base-workflow",
        "manifest-entry.audio-understanding.02-audio-aware-summarization-and-alerts",
        "manifest-entry.rt-vlm-models.02-nemotron-omni",
    }
)
ASR_IDS = frozenset(
    {
        "manifest-entry.audio-understanding.01-audio-transcript-per-rt-vlm-chunk",
        "manifest-entry.rt-vlm-media.10-audio-transcript",
    }
)
FORBIDDEN_CANDIDATE_KEYS = frozenset(
    {
        "service_roles",
        "runtime_service_roles",
        "profile_ids",
        "profile_paths",
        "compose_paths",
        "authorized_command",
        "action_flags",
        "approval_bundle_id",
        "receipt",
        "receipts",
    }
)


class MappingError(RuntimeError):
    """A source, classification, or inertness invariant failed."""


def pending_final_locks() -> list[str]:
    pending = [
        f"source:{path}"
        for path, digest in sorted(EXPECTED_SOURCE_HASHES.items())
        if path.startswith("PENDING_") or HEX64(digest) is None
    ]
    pending.extend(
        f"output:{name}"
        for name, digest in sorted(EXPECTED_OUTPUT_HASHES.items())
        if HEX64(digest) is None
    )
    return pending


def _require_final_locks() -> None:
    pending = pending_final_locks()
    if pending:
        raise MappingError("final activation/output locks remain pending: " + ", ".join(pending))


def assert_immutable_files() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in sorted(IMMUTABLE_FILES.items()):
        payload = read_regular(repo_path(relative), relative)
        digest = sha256(payload)
        if digest != expected:
            raise MappingError(f"immutable predecessor drift: {relative}")
        observed[relative] = digest
    return observed


def review_scaffold() -> dict[str, Any]:
    preserved = assert_immutable_files()
    return {
        "schema_version": 1,
        "scaffold_id": "thor-vss-3.2.1-candidate-approval-mapping-rebase-successor",
        "status": "final_activation_rebase_bound",
        "pending_locks": pending_final_locks(),
        "immutable_file_count": len(preserved),
        "allowed_source_paths": sorted(EXPECTED_SOURCE_HASHES),
        "allowed_output_names": sorted(ALLOWED_OUTPUT_NAMES),
        "preservation": {
            "mapping_row_count": 211,
            "predecessor_mapping_records_canonical_sha256": "93791e8b9d7b8ec3368ba78c1f55217498260bdb1c3f9777f0d3f6e5ab11c60c",
            "rebased_mapping_records_canonical_sha256": EXPECTED_MAPPING_RECORDS_SHA256,
            "classification_and_mapping_semantics_exact": True,
            "integrity_only_rebased_capability_ids": sorted(INTEGRITY_REBASE_IDS),
            "integrity_only_rebased_fields": list(INTEGRITY_REBASE_FIELDS),
            "zero_approval_semantics_exact": True,
            "historical_package_mutation_authorized": False,
            "canonical_metadata_mutation_authorized": False,
        },
        "rollback": {
            "strategy": "retain_and_reselect_immutable_predecessor",
            "predecessor_mapping_path": (
                "deploy/docker/thor-local/qualification/"
                "candidate-approval-mapping-successor/mapping.json"
            ),
            "predecessor_mapping_raw_sha256": (
                "4bb8f3a5fba5e201b72e1f1a0f4218bff4b9a999a836c192fca44ca7e35d9cf9"
            ),
            "partial_application_forbidden": True,
        },
        "policy": {
            "runtime_execution": "forbidden",
            "network_access": False,
            "docker_access": False,
            "warehouse_sample_bundle": "excluded",
        },
    }


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def strict_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_JSON_BYTES:
        raise MappingError(f"{label}: exceeds size bound")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise MappingError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MappingError(f"{label}: non-finite number {token}")
            ),
        )
    except MappingError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MappingError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MappingError(f"{label}: JSON root must be an object")
    return value


def repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise MappingError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise MappingError(f"repository path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MappingError(f"repository path contains a symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise MappingError(f"repository source is not a regular file: {relative}")
    resolved = path.resolve(strict=True)
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise MappingError(f"repository path escaped root: {relative}")
    return path


def read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise MappingError(f"{label}: unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise MappingError(f"{label}: must be a regular non-symlink")
    if before.st_size > MAX_JSON_BYTES:
        raise MappingError(f"{label}: exceeds size bound")
    payload = path.read_bytes()
    after = path.lstat()
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(payload) != before.st_size
    ):
        raise MappingError(f"{label}: changed while reading")
    return payload


def validate_schema(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise MappingError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise MappingError(f"{label}: schema violation at {where}: {first.message}")


def _load_locked_sources() -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        payload = read_regular(repo_path(relative), relative)
        if sha256(payload) != expected:
            raise MappingError(f"source lock mismatch: {relative}")
        loaded[relative] = (
            payload if relative in RAW_SOURCE_PATHS else strict_json_bytes(payload, relative)
        )
    return loaded


def _contains_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_CANDIDATE_KEYS:
                return key
            found = _contains_forbidden_key(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _contains_forbidden_key(child)
            if found is not None:
                return found
    return None


def _validate_sources(
    source: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    selector = source[SELECTOR_PATH]
    descriptor = source[DESCRIPTOR_PATH]
    oracles = source[ORACLES_PATH]
    activation = source[ACTIVATION_RECEIPT_PATH]
    bundles = source[BUNDLES_PATH]
    workloads = source[WORKLOADS_PATH]
    protocol = source[PROTOCOL_PATH]

    validate_schema(selector, source[SELECTOR_SCHEMA_PATH], "metadata selector")
    validate_schema(descriptor, source[DESCRIPTOR_SCHEMA_PATH], "metadata descriptor")
    validate_schema(oracles, source[ORACLES_SCHEMA_PATH], "selected capability oracles")
    validate_schema(
        activation,
        source[ACTIVATION_RECEIPT_SCHEMA_PATH],
        "activation rebase receipt",
    )
    validate_schema(bundles, source[BUNDLES_SCHEMA_PATH], "approval bundle contract")
    validate_schema(workloads, source[WORKLOADS_SCHEMA_PATH], "candidate workloads")
    validate_schema(protocol, source[PROTOCOL_SCHEMA_PATH], "candidate protocols")

    selected = selector.get("selected_set")
    available = {
        item.get("set_id"): item for item in selector.get("available_sets", [])
    }
    selected_entry = available.get(selected)
    if (
        selected != "thor-vss-3.2.1-metadata-500-staged"
        or selected_entry is None
        or selected_entry.get("descriptor_path") != DESCRIPTOR_LOCATOR_PATH
        or selected_entry.get("descriptor_raw_sha256")
        != EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH]
    ):
        raise MappingError("selected Metadata-500 identity drift")
    activation_artifacts = activation.get("artifacts", {})
    selector_artifact = activation_artifacts.get("projected-selector.json", {})
    descriptor_artifact = activation_artifacts.get(
        "projected-live-ready-descriptor.json", {}
    )
    if (
        activation.get("activation_id")
        != "vss-3.2.1-metadata-500-activation-rebase-successor"
        or activation.get("candidate_boundary")
        != {
            "candidate_count": 211,
            "runtime_evidence_count": 0,
            "executor_ready_count": 0,
            "promotable_count": 0,
        }
        or selector_artifact.get("path") != SELECTOR_PATH
        or selector_artifact.get("raw_sha256")
        != EXPECTED_SOURCE_HASHES[SELECTOR_PATH]
        or descriptor_artifact.get("path") != DESCRIPTOR_PATH
        or descriptor_artifact.get("raw_sha256")
        != EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH]
        or descriptor_artifact.get("staged_immutable_target_path")
        != DESCRIPTOR_LOCATOR_PATH
    ):
        raise MappingError("activation-rebase pair provenance drift")
    oracle_descriptor = descriptor.get("documents", {}).get("capability_oracles", {})
    schema_descriptor = descriptor.get("schemas", {}).get(
        "capability_oracles_schema", {}
    )
    if (
        descriptor.get("lifecycle") != "live_ready"
        or descriptor.get("expected_counts", {}).get("oracles") != 500
        or oracle_descriptor.get("path") != ORACLES_PATH
        or oracle_descriptor.get("raw_sha256") != EXPECTED_SOURCE_HASHES[ORACLES_PATH]
        or schema_descriptor.get("path") != ORACLES_SCHEMA_PATH
        or schema_descriptor.get("raw_sha256")
        != EXPECTED_SOURCE_HASHES[ORACLES_SCHEMA_PATH]
    ):
        raise MappingError("selected Metadata-500 descriptor drift")

    all_rows = oracles.get("oracles")
    if not isinstance(all_rows, list) or len(all_rows) != 500:
        raise MappingError("selected oracle denominator must be exactly 500")
    candidates = all_rows[289:]
    if len(candidates) != 211 or any(
        row.get("origin") != "candidate_successor_planning_only" for row in candidates
    ):
        raise MappingError("exact candidate suffix denominator drift")
    if any("origin" in row for row in all_rows[:289]):
        raise MappingError("candidate rows escaped the exact 211-row suffix")
    candidate_ids = [row.get("capability_id") for row in candidates]
    if (
        len(set(candidate_ids)) != 211
        or sha256(canonical_bytes(candidate_ids)) != EXPECTED_CANDIDATE_ORDER_SHA256
        or sha256(canonical_bytes(candidates)) != EXPECTED_CANDIDATE_ROWS_SHA256
    ):
        raise MappingError("candidate order, uniqueness, or row identity drift")

    bundle_rows = bundles.get("bundles")
    if (
        not isinstance(bundle_rows, list)
        or tuple(item.get("id") for item in bundle_rows) != EXPECTED_BUNDLE_IDS
        or bundles.get("approval_policy", {}).get("approval_inheritance") is not False
        or bundles.get("approval_policy", {}).get("compiler_can_grant_approval")
        is not False
    ):
        raise MappingError("generic approval bundle identity or isolation drift")
    if workloads.get("payload_sha256") != EXPECTED_WORKLOAD_PAYLOAD_SHA256:
        raise MappingError("workload payload identity drift")
    if protocol.get("candidate_payload_sha256") != EXPECTED_PROTOCOL_PAYLOAD_SHA256:
        raise MappingError("protocol payload identity drift")
    return candidates, bundles, workloads, protocol


def _classification(row: dict[str, Any]) -> tuple[str, str | None, str | None, str]:
    capability_id = row["capability_id"]
    feature_id = row["feature_id"]
    boundary = row["execution_boundary"]
    if capability_id in STATIC_NONACTIVATING_IDS:
        return (
            "static_nonactivating",
            None,
            None,
            "exact_static_nonactivating_exception",
        )
    if capability_id == CONTRACT_CONFLICT_ID:
        return (
            "unmapped_contract_conflict",
            None,
            "sparse4d-custom-data-models",
            "sparse4d_title_surface_conflicts_with_mv3dt_dependency",
        )
    if capability_id == SCOPE_GAP_ID:
        return (
            "unmapped_scope_gap",
            None,
            None,
            "physical_interface_firewall_has_no_generic_bundle",
        )
    if boundary == "external":
        return "mapped", "external-attestations", None, "external_optional_boundary"
    if capability_id == SEARCH_100_ID:
        return "mapped", "search-scale-100", None, "separate_search_100_scope"
    if capability_id == SEARCH_PROGRESSIVE_ID:
        return (
            "mapped",
            "search-scale-progressive-2-4-8-16",
            None,
            "progressive_search_scope",
        )
    if feature_id == "rt-cv-3d-sparse4d":
        return (
            "mapped",
            "sparse4d-custom-data-models",
            None,
            "sparse4d_custom_data_scope",
        )
    if feature_id in {"rt-cv-3d-mv3dt", "warehouse-3d-and-mv3dt"}:
        return "mapped", "mv3dt-custom-data", None, "mv3dt_custom_data_scope"
    if capability_id in NATIVE_AUDIO_IDS:
        return "mapped", "audio-native-runtime", None, "native_audio_scope"
    if capability_id in ASR_IDS:
        return (
            "mapped",
            "audio-asr-transcript-runtime",
            None,
            "local_asr_transcript_scope",
        )
    if boundary not in {"local", "alternate_local"}:
        raise MappingError(f"unclassified execution boundary: {capability_id}")
    return "mapped", "profile-lifecycle", None, "generic_local_profile_scope"


def _dependency_closure(leaf: str | None, bundles: dict[str, Any]) -> list[str]:
    if leaf is None:
        return []
    by_id = {item["id"]: item for item in bundles["bundles"]}
    reachable: set[str] = set()

    def visit(bundle_id: str) -> None:
        if bundle_id in reachable:
            return
        if bundle_id not in by_id:
            raise MappingError(f"unknown approval bundle: {bundle_id}")
        reachable.add(bundle_id)
        for dependency in by_id[bundle_id]["depends_on"]:
            visit(dependency)

    visit(leaf)
    return [bundle_id for bundle_id in EXPECTED_BUNDLE_IDS if bundle_id in reachable]


def _assert_candidate_boundary(row: dict[str, Any]) -> None:
    capability_id = row.get("capability_id", "<unknown>")
    external = row.get("execution_boundary") == "external"
    expected_current_state = (
        "external_boundary_unexecuted" if external else "open_unexecuted"
    )
    expected_runtime_state = "not_applicable" if external else "not_qualified"
    if (
        row.get("current_state") != expected_current_state
        or row.get("runtime_state") != expected_runtime_state
        or row.get("evidence") != []
        or row.get("can_promote_runtime_state") is not False
        or row.get("readiness", {}).get("classification") != "planning_index_only"
        or row.get("readiness", {}).get("executor_ready") is not False
        or row.get("readiness", {}).get("fixture_materialized") is not False
        or row.get("execution_bounds", {}).get("executor") is not None
        or row.get("execution_bounds", {}).get("collectors") is not None
        or row.get("cleanup", {}).get("executor") is not None
        or row.get("fixture", {}).get("materialization") is not None
    ):
        raise MappingError(f"candidate non-execution boundary drift: {capability_id}")
    gate = [
        item
        for item in row.get("admission_gates", [])
        if item.get("id") == "operator-approval"
    ]
    if len(gate) != 1 or gate[0].get("status") != "unmet":
        raise MappingError(f"operator approval gate drift: {capability_id}")
    forbidden = _contains_forbidden_key(row)
    if forbidden is not None:
        raise MappingError(
            f"candidate invented executable/approval field {forbidden}: {capability_id}"
        )
    if (
        row.get("execution_bounds", {}).get("warehouse_sample_bundle")
        not in {None, "excluded"}
        or row.get("ledger_binding", {})
        .get("contract", {})
        .get("warehouse_sample_bundle")
        != "excluded"
        or row.get("fixture", {}).get("warehouse_sample_bundle") not in {None, False}
    ):
        raise MappingError(f"Warehouse sample exclusion drift: {capability_id}")


def _assert_predecessor_equivalence(artifact: dict[str, Any]) -> None:
    predecessor_path = (
        "deploy/docker/thor-local/qualification/"
        "candidate-approval-mapping-successor/mapping.json"
    )
    predecessor = strict_json_bytes(
        read_regular(repo_path(predecessor_path), predecessor_path), predecessor_path
    )
    for field in (
        "schema_version",
        "mode",
        "target",
        "generic_approval_contract",
        "policy",
        "summary",
    ):
        if artifact.get(field) != predecessor.get(field):
            raise MappingError(f"predecessor semantic field drift: {field}")
    candidate_integrity = artifact.get("candidate_integrity", {})
    predecessor_integrity = predecessor.get("candidate_integrity", {})
    for field in ("candidate_order_canonical_sha256", "workloads_payload_sha256"):
        if candidate_integrity.get(field) != predecessor_integrity.get(field):
            raise MappingError(f"predecessor candidate-integrity drift: {field}")
    if (
        candidate_integrity.get("candidate_rows_canonical_sha256")
        != EXPECTED_CANDIDATE_ROWS_SHA256
        or candidate_integrity.get("protocol_payload_sha256")
        != EXPECTED_PROTOCOL_PAYLOAD_SHA256
        or artifact.get("mapping_records_canonical_sha256")
        != EXPECTED_MAPPING_RECORDS_SHA256
    ):
        raise MappingError("rebased candidate/mapping integrity digest drift")
    old_rows = predecessor.get("mappings", [])
    new_rows = artifact.get("mappings", [])
    if len(old_rows) != 211 or len(new_rows) != 211:
        raise MappingError("predecessor mapping-row denominator drift")
    changed_ids: set[str] = set()
    for old_row, new_row in zip(old_rows, new_rows, strict=True):
        capability_id = old_row.get("capability_id")
        if new_row.get("capability_id") != capability_id:
            raise MappingError("predecessor mapping-row order or identity drift")
        old_semantics = dict(old_row)
        new_semantics = dict(new_row)
        for field in INTEGRITY_REBASE_FIELDS:
            old_semantics.pop(field, None)
            new_semantics.pop(field, None)
        if new_semantics != old_semantics:
            raise MappingError(f"predecessor mapping semantics drift: {capability_id}")
        changed_fields = {
            field
            for field in INTEGRITY_REBASE_FIELDS
            if new_row.get(field) != old_row.get(field)
        }
        if changed_fields:
            changed_ids.add(str(capability_id))
            if changed_fields != set(INTEGRITY_REBASE_FIELDS) or any(
                HEX64(str(new_row.get(field, ""))) is None
                for field in INTEGRITY_REBASE_FIELDS
            ):
                raise MappingError(
                    f"predecessor mapping integrity rebase drift: {capability_id}"
                )
    if changed_ids != set(INTEGRITY_REBASE_IDS):
        raise MappingError("integrity-only mapping rebase capability set drift")
    selected = artifact.get("selected_metadata_set", {})
    old_selected = predecessor.get("selected_metadata_set", {})
    for field in (
        "set_id",
        "oracle_count",
        "candidate_start_index",
        "candidate_count",
    ):
        if selected.get(field) != old_selected.get(field):
            raise MappingError(f"predecessor selected-set field drift: {field}")
    if len(artifact.get("mappings", [])) != 211 or any(
        row.get("approval_state") != "no_receipt_not_admitted_not_executable"
        or row.get("required_cloud_inference") is not False
        or row.get("warehouse_sample_bundle") is not False
        for row in artifact["mappings"]
    ):
        raise MappingError("mapping-row zero-approval boundary drift")
    policy = artifact.get("policy", {})
    summary = artifact.get("summary", {})
    if (
        policy.get("receipt_consumer_present") is not False
        or any(
            policy.get(field) != 0
            for field in (
                "receipts_present",
                "approvals_granted",
                "admitted_candidates",
                "executable_candidates",
            )
        )
        or any(
            summary.get(field) != 0
            for field in (
                "receipt_count",
                "admitted_candidates",
                "executable_candidates",
            )
        )
    ):
        raise MappingError("aggregate zero-approval boundary drift")


def _validate_special_cases(
    rows_by_id: dict[str, dict[str, Any]], workloads_by_id: dict[str, dict[str, Any]]
) -> None:
    for helm_id in sorted(STATIC_NONACTIVATING_IDS & set(workloads_by_id)):
        workload = workloads_by_id[helm_id]
        if (
            workload.get("activation") != "external_non_activating"
            or workload.get("max_actions") != 0
            or workload.get("calculated_max_requests") != 0
        ):
            raise MappingError(f"static Helm workload became activating: {helm_id}")
    skill = rows_by_id["manifest-entry.rt-cv-3d-mv3dt.05-associated-skill"]
    if skill.get("mode") != "static" or skill.get("workload_binding") is not None:
        raise MappingError("MV3DT associated-skill static boundary drift")
    conflict = rows_by_id[CONTRACT_CONFLICT_ID]
    dependencies = conflict["ledger_binding"]["contract"].get(
        "dependency_capability_ids", []
    )
    if (
        conflict.get("advertised") != "Sparse4D 3D warehouse"
        or dependencies != ["runtime.warehouse.profile-mv3dt-pipeline"]
        or conflict.get("implementation_surfaces")
        != [
            "deploy/docker/industry-profiles/warehouse-operations/"
            "warehouse-3d-app/warehouse-3d-app.yml"
        ]
    ):
        raise MappingError("expected Sparse4D/MV3DT contract conflict drifted")
    firewall = rows_by_id[SCOPE_GAP_ID]
    if (
        firewall.get("mode") != "deploy"
        or firewall.get("profile") != "candidate-security"
        or firewall.get("implementation_surfaces")
        != ["deploy/docker/scripts/thor-local.sh"]
    ):
        raise MappingError("physical-interface firewall scope-gap boundary drift")


def compile_mapping(
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_final_locks()
    assert_immutable_files()
    source = _load_locked_sources() if source is None else source
    candidates, bundles, workloads, protocol = _validate_sources(source)
    workloads_by_id = {
        item["candidate_id"]: item for item in workloads.get("workloads", [])
    }
    protocol_by_id = {
        item["capability_id"]: item
        for item in protocol.get("bindings", [])
        if str(item.get("capability_id", "")).startswith("manifest-entry.")
    }
    if len(workloads_by_id) != 60 or len(protocol_by_id) != 23:
        raise MappingError("workload or protocol candidate denominator drift")
    if set(workloads_by_id) & set(protocol_by_id):
        raise MappingError("candidate cannot have both workload and protocol binding")

    rows_by_id = {row["capability_id"]: row for row in candidates}
    _validate_special_cases(rows_by_id, workloads_by_id)
    mappings: list[dict[str, Any]] = []
    for index, row in enumerate(candidates, start=289):
        _assert_candidate_boundary(row)
        capability_id = row["capability_id"]
        workload = workloads_by_id.get(capability_id)
        protocol_binding = protocol_by_id.get(capability_id)
        if row.get("workload_binding") != workload:
            raise MappingError(f"workload binding drift: {capability_id}")
        if row.get("protocol_v2_binding") != protocol_binding:
            raise MappingError(f"protocol binding drift: {capability_id}")
        workload_hash = sha256(canonical_bytes(workload)) if workload else None
        protocol_hash = (
            sha256(canonical_bytes(protocol_binding)) if protocol_binding else None
        )
        integrity = row.get("binding_integrity", {})
        if (
            integrity.get("workload_binding_canonical_sha256") != workload_hash
            or integrity.get("protocol_v2_binding_canonical_sha256") != protocol_hash
        ):
            raise MappingError(f"candidate binding-integrity drift: {capability_id}")
        state, leaf, suggested, reason = _classification(row)
        if leaf is not None and leaf not in EXPECTED_BUNDLE_IDS:
            raise MappingError(f"mapping selected an unknown bundle: {capability_id}")
        if leaf == "external-attestations" and row["execution_boundary"] != "external":
            raise MappingError(
                f"local candidate mapped to external bundle: {capability_id}"
            )
        if (
            row["execution_boundary"] == "external"
            and state == "mapped"
            and leaf != "external-attestations"
        ):
            raise MappingError(
                f"external candidate mapped to local bundle: {capability_id}"
            )
        surfaces = row.get("implementation_surfaces")
        if not isinstance(surfaces, list) or not surfaces:
            raise MappingError(
                f"candidate implementation surfaces absent: {capability_id}"
            )
        mappings.append(
            {
                "oracle_index": index,
                "capability_id": capability_id,
                "oracle_id": row["oracle_id"],
                "manifest_pointer": row["manifest_pointer"],
                "feature_id": row["feature_id"],
                "candidate_record_canonical_sha256": sha256(canonical_bytes(row)),
                "candidate_source_payload_sha256": row["successor_row_payload_sha256"],
                "mode": row["mode"],
                "profile": row["profile"],
                "execution_boundary": row["execution_boundary"],
                "acceptance_class": row["acceptance_class"],
                "implementation_surface_count": len(surfaces),
                "implementation_surfaces_canonical_sha256": sha256(
                    canonical_bytes(surfaces)
                ),
                "binding_kind": (
                    "workload"
                    if workload is not None
                    else "protocol"
                    if protocol_binding is not None
                    else "none"
                ),
                "workload_binding_canonical_sha256": workload_hash,
                "protocol_binding_canonical_sha256": protocol_hash,
                "mapping_state": state,
                "leaf_bundle_id": leaf,
                "suggested_bundle_id": suggested,
                "reason_code": reason,
                "dependency_closure": _dependency_closure(leaf, bundles),
                "service_binding_state": "unresolved_not_declared_by_candidate",
                "approval_state": "no_receipt_not_admitted_not_executable",
                "required_cloud_inference": False,
                "warehouse_sample_bundle": False,
            }
        )

    state_counts = {
        key: sum(item["mapping_state"] == key for item in mappings)
        for key in (
            "mapped",
            "static_nonactivating",
            "unmapped_contract_conflict",
            "unmapped_scope_gap",
        )
    }
    leaf_counts = {
        bundle_id: sum(item["leaf_bundle_id"] == bundle_id for item in mappings)
        for bundle_id in EXPECTED_BUNDLE_IDS
    }
    closure_counts = {
        bundle_id: sum(
            any(dependency == bundle_id for dependency in item["dependency_closure"])
            for item in mappings
        )
        for bundle_id in EXPECTED_BUNDLE_IDS
    }
    binding_counts = {
        key: sum(item["binding_kind"] == key for item in mappings)
        for key in ("workload", "protocol", "none")
    }
    expected_state_counts = {
        "mapped": 206,
        "static_nonactivating": 3,
        "unmapped_contract_conflict": 1,
        "unmapped_scope_gap": 1,
    }
    expected_leaf_counts = {
        "host-prerequisite-evidence-collection": 0,
        "read-only-docker-runtime-inspection": 0,
        "cgroupfs-remediation": 0,
        "tiny-audio-fixture-generation": 0,
        "model-artifact-downloads": 0,
        "profile-lifecycle": 184,
        "search-scale-progressive-2-4-8-16": 1,
        "search-scale-100": 1,
        "mv3dt-custom-data": 9,
        "sparse4d-custom-data-models": 2,
        "audio-native-runtime": 3,
        "audio-asr-transcript-runtime": 2,
        "official-edge-staging": 0,
        "external-attestations": 4,
    }
    expected_closure_counts = {
        "host-prerequisite-evidence-collection": 202,
        "read-only-docker-runtime-inspection": 202,
        "cgroupfs-remediation": 202,
        "tiny-audio-fixture-generation": 5,
        "model-artifact-downloads": 202,
        "profile-lifecycle": 202,
        "search-scale-progressive-2-4-8-16": 2,
        "search-scale-100": 1,
        "mv3dt-custom-data": 9,
        "sparse4d-custom-data-models": 2,
        "audio-native-runtime": 3,
        "audio-asr-transcript-runtime": 2,
        "official-edge-staging": 0,
        "external-attestations": 4,
    }
    if state_counts != expected_state_counts:
        raise MappingError(f"mapping state counts drift: {state_counts}")
    if leaf_counts != expected_leaf_counts:
        raise MappingError(f"direct leaf counts drift: {leaf_counts}")
    if closure_counts != expected_closure_counts:
        raise MappingError(f"dependency closure counts drift: {closure_counts}")
    if binding_counts != {"workload": 60, "protocol": 23, "none": 128}:
        raise MappingError(f"binding coverage counts drift: {binding_counts}")
    if NATIVE_AUDIO_IDS & ASR_IDS:
        raise MappingError("native-audio and ASR capability sets overlap")
    if any(
        item["leaf_bundle_id"] == "audio-native-runtime"
        for item in mappings
        if item["capability_id"] in ASR_IDS
    ):
        raise MappingError("native audio cannot prove an ASR transcript capability")

    artifact: dict[str, Any] = {
        "schema_version": 1,
        "mapping_id": "thor-vss-3.2.1-candidate-approval-mapping-rebase-successor",
        "mode": "inert_classification_only_no_receipt_consumer",
        "target": {
            "product_version": "3.2.1",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "hardware": "NVIDIA Jetson Thor",
        },
        "selected_metadata_set": {
            "set_id": "thor-vss-3.2.1-metadata-500-staged",
            "selector_raw_sha256": EXPECTED_SOURCE_HASHES[SELECTOR_PATH],
            "descriptor_raw_sha256": EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH],
            "oracle_raw_sha256": EXPECTED_SOURCE_HASHES[ORACLES_PATH],
            "oracle_count": 500,
            "candidate_start_index": 289,
            "candidate_count": 211,
        },
        "source_locks": [
            {"path": path, "raw_sha256": digest}
            for path, digest in EXPECTED_SOURCE_HASHES.items()
        ],
        "candidate_integrity": {
            "candidate_order_canonical_sha256": EXPECTED_CANDIDATE_ORDER_SHA256,
            "candidate_rows_canonical_sha256": EXPECTED_CANDIDATE_ROWS_SHA256,
            "workloads_payload_sha256": EXPECTED_WORKLOAD_PAYLOAD_SHA256,
            "protocol_payload_sha256": EXPECTED_PROTOCOL_PAYLOAD_SHA256,
        },
        "generic_approval_contract": {
            "contract_id": bundles["contract_id"],
            "raw_sha256": EXPECTED_SOURCE_HASHES[BUNDLES_PATH],
            "bundle_count": 14,
            "ordered_bundle_ids": list(EXPECTED_BUNDLE_IDS),
            "approval_inheritance": False,
        },
        "policy": {
            "classification_only": True,
            "dependency_disposition": (
                "unresolved_until_separate_receipt_or_reviewed_not_required_determination"
            ),
            "receipt_consumer_present": False,
            "receipts_present": 0,
            "approvals_granted": 0,
            "admitted_candidates": 0,
            "executable_candidates": 0,
            "commands_invented": 0,
            "action_flag_vectors_invented": 0,
            "service_roles_invented": 0,
            "profile_ids_invented": 0,
            "compose_paths_invented": 0,
            "approval_inheritance": False,
            "external_can_qualify_local": False,
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "candidate_count": 211,
            "state_counts": state_counts,
            "direct_leaf_counts": leaf_counts,
            "dependency_closure_link_counts": closure_counts,
            "binding_counts": binding_counts,
            "receipt_count": 0,
            "admitted_candidates": 0,
            "executable_candidates": 0,
        },
        "mapping_records_canonical_sha256": sha256(canonical_bytes(mappings)),
        "mappings": mappings,
    }
    _assert_predecessor_equivalence(artifact)
    validate_schema(
        artifact,
        strict_json_bytes(
            read_regular(SCHEMA_PATH, "mapping schema"), "mapping schema"
        ),
        "candidate approval mapping",
    )
    return artifact


def check_artifact() -> dict[str, Any]:
    compiled = compile_mapping()
    _validate_output_pins(_output_payloads(compiled))
    checked = strict_json_bytes(
        read_regular(ARTIFACT_PATH, "checked mapping"), "checked mapping"
    )
    if checked != compiled:
        raise MappingError("checked mapping artifact differs from fresh compilation")
    return compiled


def _output_payloads(artifact: dict[str, Any]) -> dict[Path, bytes]:
    return {
        ARTIFACT_PATH: encoded(artifact),
        SCHEMA_PATH: read_regular(SCHEMA_PATH, "mapping schema"),
    }


def _validate_output_pins(outputs: dict[Path, bytes]) -> None:
    expected = {
        ARTIFACT_PATH: EXPECTED_OUTPUT_HASHES["mapping"],
        SCHEMA_PATH: EXPECTED_OUTPUT_HASHES["schema"],
    }
    if set(outputs) != set(expected):
        raise MappingError("output allowlist denominator drift")
    for path, digest in expected.items():
        if sha256(outputs[path]) != digest:
            raise MappingError(f"generated output hash differs from pin: {path.name}")


def _preflight_output(path: Path) -> None:
    if (
        path.parent.resolve(strict=True) != HERE.resolve(strict=True)
        or path.name not in ALLOWED_OUTPUT_NAMES
        or path.parent.is_symlink()
        or not path.parent.is_dir()
        or path.is_symlink()
        or (path.exists() and not path.is_file())
    ):
        raise MappingError(f"unsafe or non-allowlisted output path: {path}")


def _stage(path: Path, payload: bytes, tag: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.{tag}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_package() -> None:
    descriptor = os.open(HERE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _transactional_write(outputs: dict[Path, bytes]) -> None:
    expected_paths = {HERE / name for name in ALLOWED_OUTPUT_NAMES}
    if set(outputs) != expected_paths or len(outputs) != 2:
        raise MappingError("transaction requires exact mapping/schema outputs")
    ordered = [HERE / ARTIFACT_PATH.name, HERE / SCHEMA_PATH.name]
    for path in ordered:
        _preflight_output(path)
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    try:
        for path in ordered:
            staged[path] = _stage(path, outputs[path], "stage")
            backups[path] = (
                _stage(path, path.read_bytes(), "backup") if path.exists() else None
            )
        try:
            for path in ordered:
                os.replace(staged[path], path)
                committed.append(path)
            _fsync_package()
        except BaseException as exc:
            rollback_errors: list[str] = []
            for path in reversed(committed):
                backup = backups[path]
                try:
                    if backup is None:
                        path.unlink(missing_ok=True)
                    else:
                        os.replace(backup, path)
                        backups[path] = None
                except OSError as rollback_exc:
                    rollback_errors.append(f"{path.name}: {rollback_exc}")
            try:
                _fsync_package()
            except OSError as rollback_exc:
                rollback_errors.append(f"directory fsync: {rollback_exc}")
            if rollback_errors:
                raise MappingError(
                    "mapping transaction rollback failed: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise MappingError(
                "mapping transaction failed; prior state restored"
            ) from exc
    finally:
        for temporary in [*staged.values(), *backups.values()]:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--review", action="store_true", help="review pending scaffold")
    group.add_argument("--check", action="store_true", help="validate checked artifact")
    group.add_argument(
        "--emit", action="store_true", help="emit fresh artifact to stdout"
    )
    group.add_argument(
        "--write", action="store_true", help="transactionally write pinned outputs"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.review:
            print(json.dumps(review_scaffold(), indent=2, sort_keys=True))
            return 0
        if args.emit or args.write:
            artifact = compile_mapping()
            outputs = _output_payloads(artifact)
            _validate_output_pins(outputs)
            if args.write:
                _transactional_write(outputs)
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "written": sorted(path.name for path in outputs),
                        },
                        sort_keys=True,
                    )
                )
                return 0
        else:
            artifact = check_artifact()
    except MappingError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    if args.emit:
        print(json.dumps(artifact, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "ok": True,
                    "mapping_id": artifact["mapping_id"],
                    "candidate_count": artifact["summary"]["candidate_count"],
                    "state_counts": artifact["summary"]["state_counts"],
                    "receipt_count": 0,
                    "admitted_candidates": 0,
                    "executable_candidates": 0,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
