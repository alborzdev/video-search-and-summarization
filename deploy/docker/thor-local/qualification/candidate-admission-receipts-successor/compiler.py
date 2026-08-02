#!/usr/bin/env python3
"""Validate the inert candidate-admission index and empty receipt set.

This module is deliberately a validator only.  Its CLI has one mode, --check,
and no path that executes an action, grants approval, or writes a receipt.
"""

from __future__ import annotations

import argparse
from collections import Counter
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
INDEX_PATH = HERE / "admission-index.json"
INDEX_SCHEMA_PATH = HERE / "admission-index.schema.json"
RECEIPT_SET_PATH = HERE / "receipt-set.json"
RECEIPT_SCHEMA_PATH = HERE / "receipt-set.schema.json"
MAX_BYTES = 96_000_000

MAPPING_DIR = (
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor-v2"
)
BUNDLE_DIR = "deploy/docker/thor-local/qualification/runtime-approval-bundles-successor"
METADATA_DIR = "deploy/docker/thor-local/qualification/live-metadata-500-migration"
MAPPING_PATH = f"{MAPPING_DIR}/mapping.json"
BUNDLE_PATH = f"{BUNDLE_DIR}/contract.json"
ORACLES_PATH = f"{METADATA_DIR}/post-state-capability-oracles.json"

EXPECTED_SOURCE_HASHES = {
    MAPPING_PATH: "751fd28d59744a709a18eaa6d347e293bb6a665502636e26aaeff65c340f9844",
    f"{MAPPING_DIR}/mapping.schema.json": "b07a5f35c4bbecd6e11fd2d2d0fd20046a90b03bc9747964ef17f18de3d847e0",
    f"{MAPPING_DIR}/compiler.py": "c2e89bf6fa07daf9607bf4f9afcac4874c6150f443f649a837b4afbb03a1ab2e",
    BUNDLE_PATH: "74ba837f9e87923ddd48c635a067aeca9929bbf7cd9b3cff5f26157560aa3c0e",
    f"{BUNDLE_DIR}/contract.schema.json": "67e052501707a2b12c0bd43c055b5cce41367772ff5c263f8a5b3024592f126b",
    f"{BUNDLE_DIR}/compiler.py": "df9727bfe5bb4a67410525b0f3e8fa5f22d1b9a4bd66b22d24174bfa5f39ce31",
    ORACLES_PATH: "17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271",
    f"{METADATA_DIR}/post-state-capability-oracles.schema.json": "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    f"{METADATA_DIR}/compiler.py": "d1eb9d0e59f9939b63f1ff61768747297cc38e65ebdaa4675b2f378616d11f0a",
}

STATIC_STATE = "static_nonactivating_not_applicable"
BLOCKED_STATE = "receipt_and_execution_bindings_missing_not_admitted"
EXTERNAL_STATE = "external_attestation_only_not_local_admissible"
BLOCKERS = [
    "missing_exact_action_contract_binding",
    "missing_exact_service_role_or_profile_binding",
    "missing_exact_cleanup_and_rollback_contract_binding",
    "missing_leaf_and_dependency_receipts_or_reviewed_not_required_determinations",
]


class AdmissionError(RuntimeError):
    """A source, schema, identity, receipt, or fail-closed invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise AdmissionError(f"{label}: exceeds size bound")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdmissionError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AdmissionError(f"{label}: non-finite JSON number {token}")
            ),
        )
    except AdmissionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AdmissionError(f"{label}: JSON root must be an object")
    return value


def _safe_repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise AdmissionError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AdmissionError(f"repository path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise AdmissionError(f"repository path contains a symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise AdmissionError(f"repository source is not a regular file: {relative}")
    return path


def _read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise AdmissionError(f"{label}: unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise AdmissionError(f"{label}: must be a regular non-symlink")
    if before.st_size > MAX_BYTES:
        raise AdmissionError(f"{label}: exceeds size bound")
    payload = path.read_bytes()
    after = path.lstat()
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(payload) != before.st_size
    ):
        raise AdmissionError(f"{label}: changed while reading")
    return payload


def _validate_schema(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AdmissionError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise AdmissionError(f"{label}: schema violation at {where}: {first.message}")


def _load_sources() -> tuple[dict[str, bytes], dict[str, Any]]:
    payloads: dict[str, bytes] = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        payload = _read_regular(_safe_repo_path(relative), relative)
        actual = sha256(payload)
        if actual != expected:
            raise AdmissionError(
                f"source drift for {relative}: expected {expected}, got {actual}"
            )
        payloads[relative] = payload

    mapping = strict_json(payloads[MAPPING_PATH], MAPPING_PATH)
    mapping_schema = strict_json(
        payloads[f"{MAPPING_DIR}/mapping.schema.json"], "mapping schema"
    )
    bundles = strict_json(payloads[BUNDLE_PATH], BUNDLE_PATH)
    bundle_schema = strict_json(
        payloads[f"{BUNDLE_DIR}/contract.schema.json"], "bundle schema"
    )
    oracles = strict_json(payloads[ORACLES_PATH], ORACLES_PATH)
    oracle_schema = strict_json(
        payloads[f"{METADATA_DIR}/post-state-capability-oracles.schema.json"],
        "oracle schema",
    )
    _validate_schema(mapping, mapping_schema, "mapping")
    _validate_schema(bundles, bundle_schema, "bundle contract")
    _validate_schema(oracles, oracle_schema, "selected metadata oracles")
    return payloads, {"mapping": mapping, "bundles": bundles, "oracles": oracles}


def _closure(bundle_by_id: dict[str, dict[str, Any]], leaf: str) -> list[str]:
    included: set[str] = set()
    visiting: set[str] = set()

    def visit(bundle_id: str) -> None:
        if bundle_id in visiting:
            raise AdmissionError(f"bundle dependency cycle at {bundle_id}")
        if bundle_id in included:
            return
        bundle = bundle_by_id.get(bundle_id)
        if bundle is None:
            raise AdmissionError(f"unknown bundle {bundle_id}")
        visiting.add(bundle_id)
        for dependency in bundle["depends_on"]:
            visit(dependency)
        visiting.remove(bundle_id)
        included.add(bundle_id)

    visit(leaf)
    # Mapping-v2 defines closure order as the 16-bundle contract order filtered
    # to the transitive set, not DFS visitation order.
    return [bundle_id for bundle_id in bundle_by_id if bundle_id in included]


def compile_index() -> dict[str, Any]:
    payloads, sources = _load_sources()
    mapping = sources["mapping"]
    bundles = sources["bundles"]
    oracle_document = sources["oracles"]
    rows = mapping["mappings"]
    oracles = oracle_document["oracles"]
    bundle_by_id = {bundle["id"]: bundle for bundle in bundles["bundles"]}
    if len(bundle_by_id) != 16 or len(bundle_by_id) != len(bundles["bundles"]):
        raise AdmissionError("bundle contract must contain exactly 16 unique bundles")
    if len(rows) != 211 or len(oracles) != 500:
        raise AdmissionError("expected exact 211-candidate/500-oracle identity")
    metadata = mapping["selected_metadata_set"]
    if (
        metadata["candidate_count"] != 211
        or metadata["candidate_start_index"] != 289
        or metadata["oracle_count"] != 500
        or metadata["oracle_raw_sha256"] != EXPECTED_SOURCE_HASHES[ORACLES_PATH]
    ):
        raise AdmissionError("selected metadata identity drifted")

    metadata_binding = {
        "candidate_count": 211,
        "candidate_start_index": 289,
        "descriptor_raw_sha256": metadata["descriptor_raw_sha256"],
        "oracle_count": 500,
        "oracle_raw_sha256": metadata["oracle_raw_sha256"],
        "selector_raw_sha256": metadata["selector_raw_sha256"],
        "set_id": metadata["set_id"],
    }
    metadata_binding_hash = sha256(canonical_bytes(metadata_binding))
    admission_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, mapping_row in enumerate(rows):
        candidate_id = mapping_row["capability_id"]
        if candidate_id in seen:
            raise AdmissionError(f"duplicate candidate {candidate_id}")
        seen.add(candidate_id)
        oracle_index = mapping_row["oracle_index"]
        if oracle_index != 289 + position:
            raise AdmissionError(f"candidate order/index drift at {candidate_id}")
        oracle = oracles[oracle_index]
        if (
            oracle["capability_id"] != candidate_id
            or oracle["oracle_id"] != mapping_row["oracle_id"]
            or oracle["manifest_pointer"] != mapping_row["manifest_pointer"]
            or oracle["successor_row_payload_sha256"]
            != mapping_row["candidate_source_payload_sha256"]
        ):
            raise AdmissionError(f"candidate/oracle binding drift at {candidate_id}")
        leaf = mapping_row["leaf_bundle_id"]
        expected_closure = [] if leaf is None else _closure(bundle_by_id, leaf)
        if mapping_row["dependency_closure"] != expected_closure:
            raise AdmissionError(f"dependency closure drift at {candidate_id}")
        static = mapping_row["mapping_state"] == "static_nonactivating"
        if static != (leaf is None):
            raise AdmissionError(f"leaf/static boundary drift at {candidate_id}")
        if (
            mapping_row["service_binding_state"]
            != "unresolved_not_declared_by_candidate"
        ):
            raise AdmissionError(
                f"candidate service binding unexpectedly resolved: {candidate_id}"
            )
        admission_rows.append(
            {
                "admission_state": (
                    STATIC_STATE
                    if static
                    else EXTERNAL_STATE
                    if mapping_row["execution_boundary"] == "external"
                    else BLOCKED_STATE
                ),
                "binding_kind": mapping_row["binding_kind"],
                "blocking_requirements": [] if static else BLOCKERS,
                "bundle_contract_raw_sha256": EXPECTED_SOURCE_HASHES[BUNDLE_PATH],
                "candidate_id": candidate_id,
                "candidate_order_position": position,
                "candidate_record_canonical_sha256": mapping_row[
                    "candidate_record_canonical_sha256"
                ],
                "complete_dependency_closure": expected_closure,
                "execution_boundary": mapping_row["execution_boundary"],
                "leaf_bundle_id": leaf,
                "mapping_artifact_raw_sha256": EXPECTED_SOURCE_HASHES[MAPPING_PATH],
                "mapping_row_canonical_sha256": sha256(canonical_bytes(mapping_row)),
                "metadata_binding_canonical_sha256": metadata_binding_hash,
                "oracle_id": mapping_row["oracle_id"],
                "oracle_index": oracle_index,
                "oracle_record_canonical_sha256": sha256(canonical_bytes(oracle)),
                "receipt_ids": [],
                "runtime_admission_applicable": not static,
                "runtime_admitted": False,
                "runtime_executable": False,
                "warehouse_sample_bundle": "excluded",
            }
        )

    source_locks = [
        {"path": path, "raw_sha256": EXPECTED_SOURCE_HASHES[path]}
        for path in EXPECTED_SOURCE_HASHES
    ]
    state_counts = dict(
        sorted(Counter(row["admission_state"] for row in admission_rows).items())
    )
    result = {
        "admission_index_id": "thor-vss-3.2.1-candidate-admission-receipts-successor",
        "schema_version": 1,
        "mode": "read_only_validation_no_execute_no_write_no_action",
        "target": mapping["target"],
        "source_locks": source_locks,
        "selected_metadata_identity": metadata_binding,
        "selected_metadata_identity_canonical_sha256": metadata_binding_hash,
        "mapping_identity": {
            "mapping_id": mapping["mapping_id"],
            "mapping_raw_sha256": EXPECTED_SOURCE_HASHES[MAPPING_PATH],
            "mapping_records_canonical_sha256": mapping[
                "mapping_records_canonical_sha256"
            ],
        },
        "bundle_contract_identity": {
            "bundle_count": 16,
            "contract_id": bundles["contract_id"],
            "contract_raw_sha256": EXPECTED_SOURCE_HASHES[BUNDLE_PATH],
            "ordered_bundle_ids": [bundle["id"] for bundle in bundles["bundles"]],
        },
        "policy": {
            "approval_inheritance": False,
            "canonical_hash_is_integrity_not_authenticity": True,
            "compiler_can_accept_receipts": False,
            "compiler_can_execute": False,
            "compiler_can_write": False,
            "external_receipts_cannot_qualify_local": True,
            "native_audio_receipts_cannot_satisfy_asr": True,
            "nonempty_receipt_sets_supported": False,
            "reviewed_not_required_edges_supported": 0,
            "receipt_reuse_across_candidates": False,
            "structurally_valid_receipt_is_never_sufficient": True,
            "trusted_authority_roots": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "admissions": admission_rows,
        "admission_rows_canonical_sha256": sha256(canonical_bytes(admission_rows)),
        "summary": {
            "admitted_candidates": 0,
            "blocked_candidates": 208,
            "candidate_count": 211,
            "executable_candidates": 0,
            "receipt_count": 0,
            "state_counts": state_counts,
            "static_nonactivating_candidates": 3,
            "boundary_counts": {
                "alternate_local": 46,
                "external": 6,
                "local": 159,
            },
            "mapped_boundary_counts": {
                "alternate_local": 45,
                "external": 4,
                "local": 159,
            },
        },
    }
    return result


def validate_receipts(
    receipt_set: dict[str, Any],
    index: dict[str, Any],
    receipt_schema: dict[str, Any],
) -> None:
    """Validate the only currently trusted receipt state: the exact empty set.

    The schema publishes a design-only future envelope, but no source-locked
    trust root, signature verifier, spent-ID ledger, run binding, per-edge
    not-required policy, or candidate action binding exists.  Consequently a
    non-empty set always fails closed, regardless of structural validity.
    """
    _validate_schema(receipt_set, receipt_schema, "receipt set")
    receipts = receipt_set["receipts"]
    if receipts or receipt_set["receipt_count"] != 0:
        raise AdmissionError(
            "non-empty receipt consumption is unsupported and fails closed"
        )
    if receipt_set["trusted_review_authority_binding_sha256"]:
        raise AdmissionError(
            "no trusted receipt/review authority roots are source-locked"
        )
    if (
        receipt_set["admitted_candidate_count"]
        or receipt_set["executable_candidate_count"]
    ):
        raise AdmissionError("empty receipt set cannot admit or execute candidates")
    if receipt_set["warehouse_sample_bundle"] != "excluded":
        raise AdmissionError("Warehouse sample bundle is excluded")
    if any(
        row["runtime_admitted"] or row["runtime_executable"]
        for row in index["admissions"]
    ):
        raise AdmissionError("admission index contains an activation claim")


def check() -> dict[str, Any]:
    expected_index = compile_index()
    index_payload = _read_regular(INDEX_PATH, "admission index")
    schema_payload = _read_regular(INDEX_SCHEMA_PATH, "admission index schema")
    receipt_payload = _read_regular(RECEIPT_SET_PATH, "receipt set")
    receipt_schema_payload = _read_regular(RECEIPT_SCHEMA_PATH, "receipt schema")
    index = strict_json(index_payload, "admission index")
    index_schema = strict_json(schema_payload, "admission index schema")
    receipt_set = strict_json(receipt_payload, "receipt set")
    receipt_schema = strict_json(receipt_schema_payload, "receipt schema")
    _validate_schema(index, index_schema, "admission index")
    if (
        index != expected_index
        or index_payload
        != json.dumps(
            expected_index, indent=2, sort_keys=True, ensure_ascii=True
        ).encode("utf-8")
        + b"\n"
    ):
        raise AdmissionError("checked admission index is stale or non-canonical")
    validate_receipts(
        receipt_set,
        index,
        receipt_schema,
    )
    expected_receipt_set = {
        "receipt_set_id": "thor-vss-3.2.1-candidate-admission-empty-receipt-set",
        "schema_version": 1,
        "admission_index_raw_sha256": sha256(index_payload),
        "receipt_envelope_schema_raw_sha256": sha256(receipt_schema_payload),
        "receipt_count": 0,
        "receipts": [],
        "trusted_review_authority_binding_sha256": [],
        "admitted_candidate_count": 0,
        "executable_candidate_count": 0,
        "warehouse_sample_bundle": "excluded",
    }
    if (
        receipt_set != expected_receipt_set
        or receipt_payload
        != json.dumps(
            expected_receipt_set, indent=2, sort_keys=True, ensure_ascii=True
        ).encode("utf-8")
        + b"\n"
    ):
        raise AdmissionError("checked receipt set is not the exact canonical empty set")
    return {
        "admission_index_raw_sha256": sha256(index_payload),
        "admission_rows_canonical_sha256": index["admission_rows_canonical_sha256"],
        "candidate_count": 211,
        "receipt_count": 0,
        "admitted_candidate_count": 0,
        "executable_candidate_count": 0,
        "receipt_set_raw_sha256": sha256(receipt_payload),
        "status": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate checked artifacts"
    )
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("the only supported mode is --check")
    try:
        print(json.dumps(check(), indent=2, sort_keys=True))
    except (AdmissionError, OSError) as exc:
        print(f"candidate admission validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
