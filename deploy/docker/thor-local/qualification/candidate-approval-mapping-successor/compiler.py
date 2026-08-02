#!/usr/bin/env python3
"""Compile the inert 211-candidate approval classification successor.

This module reads only raw-locked repository metadata.  It has no receipt
consumer and no execution facility; a bundle classification is never an
approval or runtime admission.
"""

from __future__ import annotations

import argparse
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
MAX_JSON_BYTES = 96_000_000

SELECTOR_PATH = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
SELECTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
DESCRIPTOR_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged.json"
)
DESCRIPTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
ORACLES_PATH = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
    "post-state-capability-oracles.json"
)
ORACLES_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/"
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

EXPECTED_SOURCE_HASHES = {
    SELECTOR_PATH: "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    SELECTOR_SCHEMA_PATH: "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    DESCRIPTOR_PATH: "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
    DESCRIPTOR_SCHEMA_PATH: "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    ORACLES_PATH: "17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271",
    ORACLES_SCHEMA_PATH: "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    BUNDLES_PATH: "8bfa16650574de7ac1906da4eab048a30680f4094dd62cbea0cd5319b9d24e4f",
    BUNDLES_SCHEMA_PATH: "400b3b8720cd9332c069cc2d5d14aa54722680a4493ccfabef8701db5e98d36e",
    WORKLOADS_PATH: "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    WORKLOADS_SCHEMA_PATH: "736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14",
    PROTOCOL_PATH: "886151fee9ce27b24601499011151e827c4742b32d400c609c8c0b149851db62",
    PROTOCOL_SCHEMA_PATH: "831d982f6912358b8dfae049cd10ed709af299d91cb7196031d28b29a092877d",
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
    "8cc136ea78c7395c534db0c8601b4881ac7982a70e6c43218a6d7cc20b6ef5b4"
)
EXPECTED_WORKLOAD_PAYLOAD_SHA256 = (
    "0e8512e64399af7d8acc0c7136efbd52da4ebf9119ad0826859e6fce6906d847"
)
EXPECTED_PROTOCOL_PAYLOAD_SHA256 = (
    "65715e2ebfbe164ae38a6b20ca7dc23b6f3a65aaa9dd1632bdda746c4c929f24"
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


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _load_locked_sources() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        payload = read_regular(repo_path(relative), relative)
        if sha256(payload) != expected:
            raise MappingError(f"source lock mismatch: {relative}")
        loaded[relative] = strict_json_bytes(payload, relative)
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
    source: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    selector = source[SELECTOR_PATH]
    descriptor = source[DESCRIPTOR_PATH]
    oracles = source[ORACLES_PATH]
    bundles = source[BUNDLES_PATH]
    workloads = source[WORKLOADS_PATH]
    protocol = source[PROTOCOL_PATH]

    validate_schema(selector, source[SELECTOR_SCHEMA_PATH], "metadata selector")
    validate_schema(descriptor, source[DESCRIPTOR_SCHEMA_PATH], "metadata descriptor")
    validate_schema(oracles, source[ORACLES_SCHEMA_PATH], "selected capability oracles")
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
        or selected_entry.get("descriptor_path") != DESCRIPTOR_PATH
        or selected_entry.get("descriptor_raw_sha256")
        != EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH]
    ):
        raise MappingError("selected Metadata-500 identity drift")
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
    source: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
        "mapping_id": "thor-vss-3.2.1-candidate-approval-mapping-successor",
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
    checked = strict_json_bytes(
        read_regular(ARTIFACT_PATH, "checked mapping"), "checked mapping"
    )
    if checked != compiled:
        raise MappingError("checked mapping artifact differs from fresh compilation")
    return compiled


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="validate checked artifact")
    group.add_argument(
        "--emit", action="store_true", help="emit fresh artifact to stdout"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact = compile_mapping() if args.emit else check_artifact()
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
