#!/usr/bin/env python3
"""Validate the empty candidate authority registry and receipt-envelope design."""

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
REGISTRY_PATH = HERE / "authority-registry.json"
REGISTRY_SCHEMA_PATH = HERE / "authority-registry.schema.json"
ENVELOPE_SCHEMA_PATH = HERE / "signed-receipt-envelope.schema.json"
RECEIPT_SET_PATH = HERE / "signed-receipt-set.json"
RECEIPT_SET_SCHEMA_PATH = HERE / "signed-receipt-set.schema.json"
MAX_BYTES = 96_000_000

BINDING_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-binding-registry-successor"
)
ADMISSION_DIR = (
    "deploy/docker/thor-local/qualification/candidate-admission-receipts-successor"
)
BINDING_REGISTRY_PATH = f"{BINDING_DIR}/registry.json"
BINDING_LOCATORS_PATH = f"{BINDING_DIR}/locator-locks.json"
ADMISSION_INDEX_PATH = f"{ADMISSION_DIR}/admission-index.json"
ADMISSION_RECEIPTS_PATH = f"{ADMISSION_DIR}/receipt-set.json"

EXPECTED_SOURCE_HASHES = {
    BINDING_REGISTRY_PATH: "59600e64e818b553039dd3d623d1a174714f6f51563da08251560c2994c7f544",
    f"{BINDING_DIR}/registry.schema.json": "04eb378e9891a805069ad293a762c6e71c95498177baf0b5b21cf1db0c46ab7d",
    BINDING_LOCATORS_PATH: "c8311f1dc9eca330a186c43e15766e2daf5418649e41258eb50baa6445a31708",
    f"{BINDING_DIR}/locator-locks.schema.json": "3cad143f04ebb9a80b11e180aed9a6ccb573d247d52b617ea8caeb9805075cb2",
    f"{BINDING_DIR}/compiler.py": "fadfa7ff38585ce0604b0511113f12f1281016a3b39c08188022eda14144973d",
    ADMISSION_INDEX_PATH: "6dc6345f9b057c164929a1046b8ebcfb08fdfbedaa1b7a66180f344915d7d7eb",
    f"{ADMISSION_DIR}/admission-index.schema.json": "bc0603904f159a5759449cd4d6b54a94723cf26332611e25cb58432be6184c46",
    ADMISSION_RECEIPTS_PATH: "7bfeb7e70f9a7c3a2bbbb007c785286146dbfe70e4f63245168cf382b62ec805",
    f"{ADMISSION_DIR}/receipt-set.schema.json": "6cc3e19b809c48d23f8998908a2569d26dc4aad74a8ffdccfb8505914477764f",
    f"{ADMISSION_DIR}/compiler.py": "8254bd9fe13fc7954ed3007f6fbdfb0247079b8f44147434ebed2048e5f27c67",
}

EMPTY_COLLECTIONS = (
    "authorities",
    "trusted_roots",
    "active_keys",
    "revoked_keys",
    "revocations",
    "role_policies",
    "scope_policies",
    "threshold_policies",
    "max_ttl_policies",
    "not_required_edge_policies",
    "spent_receipt_ledger",
)


class AuthorityError(RuntimeError):
    """A source, schema, trust-boundary, or inertness invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    # Integrity-only local canonical form. This is explicitly not RFC 8785 JCS.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise AuthorityError(f"{label}: exceeds size bound")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthorityError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                AuthorityError(f"{label}: non-finite JSON number {token}")
            ),
        )
    except AuthorityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityError(f"{label}: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AuthorityError(f"{label}: JSON root must be an object")
    return value


def _repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise AuthorityError(f"unsafe repository path: {relative}")
    path = REPO_ROOT
    for part in pure.parts:
        path /= part
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise AuthorityError(f"repository path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise AuthorityError(f"repository path contains a symlink: {relative}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise AuthorityError(f"repository source is not a regular file: {relative}")
    return path


def _read_regular(path: Path, label: str) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise AuthorityError(f"{label}: unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise AuthorityError(f"{label}: must be a regular non-symlink")
    if before.st_size > MAX_BYTES:
        raise AuthorityError(f"{label}: exceeds size bound")
    payload = path.read_bytes()
    after = path.lstat()
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(payload) != before.st_size
    ):
        raise AuthorityError(f"{label}: changed while reading")
    return payload


def _validate_schema(value: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AuthorityError(f"{label}: invalid JSON Schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(part) for part in first.absolute_path)
        raise AuthorityError(f"{label}: schema violation at {where}: {first.message}")


def _load_locked_sources() -> dict[str, dict[str, Any]]:
    payloads: dict[str, bytes] = {}
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        payload = _read_regular(_repo_path(relative), relative)
        actual = sha256(payload)
        if actual != expected:
            raise AuthorityError(
                f"source drift for {relative}: expected {expected}, got {actual}"
            )
        payloads[relative] = payload

    specs = {
        "binding_registry": (
            BINDING_REGISTRY_PATH,
            f"{BINDING_DIR}/registry.schema.json",
        ),
        "locator_locks": (
            BINDING_LOCATORS_PATH,
            f"{BINDING_DIR}/locator-locks.schema.json",
        ),
        "admission_index": (
            ADMISSION_INDEX_PATH,
            f"{ADMISSION_DIR}/admission-index.schema.json",
        ),
        "admission_receipts": (
            ADMISSION_RECEIPTS_PATH,
            f"{ADMISSION_DIR}/receipt-set.schema.json",
        ),
    }
    result: dict[str, dict[str, Any]] = {}
    for name, (artifact_path, schema_path) in specs.items():
        artifact = strict_json(payloads[artifact_path], artifact_path)
        schema = strict_json(payloads[schema_path], schema_path)
        _validate_schema(artifact, schema, name)
        result[name] = artifact
    return result


def compile_registry(envelope_schema_raw_sha256: str) -> dict[str, Any]:
    sources = _load_locked_sources()
    binding = sources["binding_registry"]
    admissions = sources["admission_index"]
    old_receipts = sources["admission_receipts"]
    if (
        len(binding["bindings"]) != 208
        or binding["binding_rows_canonical_sha256"]
        != "25b6dc3b2046895b926df837b93560e8f367cc672afdd479eb31438e94cea96c"
        or binding["summary"]["admission_grade_bindings"] != 0
        or any(binding["summary"]["authoritative_binding_counts"].values())
        or binding["policy"]["authoritative_bindings_present"] != 0
    ):
        raise AuthorityError("execution-binding registry identity drifted")
    if (
        admissions["summary"]["candidate_count"] != 211
        or admissions["summary"]["admitted_candidates"] != 0
        or admissions["summary"]["executable_candidates"] != 0
        or old_receipts["receipt_count"] != 0
        or old_receipts["receipts"]
    ):
        raise AuthorityError("source admission state must remain exactly empty")

    source_locks = [
        {"path": path, "raw_sha256": digest}
        for path, digest in EXPECTED_SOURCE_HASHES.items()
    ]
    result: dict[str, Any] = {
        "authority_registry_id": "thor-vss-3.2.1-candidate-authority-empty-v1",
        "schema_version": 1,
        "mode": "read_only_check_no_sign_no_verify_no_accept_no_consume_no_write_no_execute",
        "target": binding["target"],
        "source_locks": source_locks,
        "source_identity": {
            "admission_index_raw_sha256": EXPECTED_SOURCE_HASHES[ADMISSION_INDEX_PATH],
            "binding_registry_raw_sha256": EXPECTED_SOURCE_HASHES[
                BINDING_REGISTRY_PATH
            ],
            "binding_rows_canonical_sha256": binding["binding_rows_canonical_sha256"],
            "candidate_count": 211,
            "locator_locks_raw_sha256": EXPECTED_SOURCE_HASHES[BINDING_LOCATORS_PATH],
            "mapped_binding_count": 208,
        },
        "root_pinning": {
            "registry_epoch": 0,
            "previous_registry_raw_sha256": None,
            "root_set_canonical_sha256": None,
            "trusted_root_count": 0,
        },
        "cryptographic_profile": {
            "algorithm_negotiation": False,
            "canonical_payload": "RFC8785_JCS_required_but_not_implemented",
            "dsse_pae_version": "DSSEv1",
            "envelope_format": "DSSE",
            "key_type": "Ed25519",
            "payload_type": "application/vnd.nvidia.vss.candidate-receipt.v1+json",
            "signature_algorithm": "Ed25519",
            "signed_receipt_envelope_schema_raw_sha256": envelope_schema_raw_sha256,
        },
        "authorities": [],
        "trusted_roots": [],
        "active_keys": [],
        "revoked_keys": [],
        "revocations": [],
        "role_policies": [],
        "scope_policies": [],
        "threshold_policies": [],
        "max_ttl_policies": [],
        "not_required_edge_policies": [],
        "spent_receipt_ledger": [],
        "limitations": {
            "canonical_jcs_implementation_available": False,
            "central_spent_ledger_available": False,
            "cryptographic_verification_dependency_available": False,
            "epoch_rollback_protection_available": False,
            "global_durable_atomic_spent_ledger_available": False,
            "model_signing_dependency_available": False,
            "candidate_authority_qualification_dependency_available": False,
            "revocation_mechanism_available": False,
            "root_key_available": False,
            "sha256_is_integrity_not_authority": True,
            "signature_verifier_available": False,
            "trusted_time_available": False,
        },
        "policy": {
            "all_nonempty_authority_inputs_fail_closed": True,
            "all_nonempty_receipt_inputs_fail_closed": True,
            "authorization_and_completion_receipts_are_distinct": True,
            "compiler_can_accept": False,
            "compiler_can_consume": False,
            "compiler_can_execute": False,
            "compiler_can_sign": False,
            "compiler_can_verify_signatures": False,
            "compiler_can_write": False,
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
        },
        "summary": {
            "active_key_count": 0,
            "authority_count": 0,
            "receipt_count": 0,
            "revocation_count": 0,
            "trusted_root_count": 0,
        },
    }
    return result


def validate_empty_registry(registry: dict[str, Any]) -> None:
    for name in EMPTY_COLLECTIONS:
        if registry[name]:
            raise AuthorityError(f"non-empty {name} is unsupported and fails closed")
    if registry["root_pinning"]["trusted_root_count"] != 0:
        raise AuthorityError("trusted roots must remain zero")
    if any(registry["summary"].values()):
        raise AuthorityError("authority summary must remain exactly zero")


def validate_empty_receipt_set(receipt_set: dict[str, Any]) -> None:
    for name in (
        "authorization_envelopes",
        "completion_receipt_envelopes",
        "accepted_receipt_ids",
        "consumed_receipt_ids",
    ):
        if receipt_set[name]:
            raise AuthorityError(f"non-empty {name} is unsupported and fails closed")
    for name in (
        "authorization_envelope_count",
        "completion_receipt_envelope_count",
        "accepted_receipt_count",
        "consumed_receipt_count",
    ):
        if receipt_set[name] != 0:
            raise AuthorityError(f"{name} must remain zero")
    if receipt_set["warehouse_sample_bundle"] != "excluded":
        raise AuthorityError("Warehouse sample bundle is excluded")


def check() -> dict[str, Any]:
    envelope_schema_payload = _read_regular(
        ENVELOPE_SCHEMA_PATH, "signed receipt envelope schema"
    )
    envelope_schema = strict_json(
        envelope_schema_payload, "signed receipt envelope schema"
    )
    try:
        Draft202012Validator.check_schema(envelope_schema)
    except SchemaError as exc:
        raise AuthorityError("signed receipt envelope schema is invalid") from exc

    registry_payload = _read_regular(REGISTRY_PATH, "authority registry")
    registry_schema_payload = _read_regular(
        REGISTRY_SCHEMA_PATH, "authority registry schema"
    )
    registry = strict_json(registry_payload, "authority registry")
    registry_schema = strict_json(registry_schema_payload, "authority registry schema")
    _validate_schema(registry, registry_schema, "authority registry")
    expected_registry = compile_registry(sha256(envelope_schema_payload))
    canonical_registry = (
        json.dumps(
            expected_registry, indent=2, sort_keys=True, ensure_ascii=True
        ).encode("utf-8")
        + b"\n"
    )
    if registry != expected_registry or registry_payload != canonical_registry:
        raise AuthorityError("checked authority registry is stale or non-canonical")
    validate_empty_registry(registry)

    receipt_payload = _read_regular(RECEIPT_SET_PATH, "signed receipt set")
    receipt_schema_payload = _read_regular(
        RECEIPT_SET_SCHEMA_PATH, "signed receipt set schema"
    )
    receipt_set = strict_json(receipt_payload, "signed receipt set")
    receipt_schema = strict_json(receipt_schema_payload, "signed receipt set schema")
    _validate_schema(receipt_set, receipt_schema, "signed receipt set")
    expected_receipt_set = {
        "receipt_set_id": "thor-vss-3.2.1-candidate-signed-receipts-empty-v1",
        "schema_version": 1,
        "authority_registry_raw_sha256": sha256(registry_payload),
        "binding_registry_raw_sha256": EXPECTED_SOURCE_HASHES[BINDING_REGISTRY_PATH],
        "admission_index_raw_sha256": EXPECTED_SOURCE_HASHES[ADMISSION_INDEX_PATH],
        "signed_receipt_envelope_schema_raw_sha256": sha256(envelope_schema_payload),
        "authorization_envelope_count": 0,
        "authorization_envelopes": [],
        "completion_receipt_envelope_count": 0,
        "completion_receipt_envelopes": [],
        "accepted_receipt_count": 0,
        "accepted_receipt_ids": [],
        "consumed_receipt_count": 0,
        "consumed_receipt_ids": [],
        "warehouse_sample_bundle": "excluded",
    }
    canonical_receipts = (
        json.dumps(
            expected_receipt_set, indent=2, sort_keys=True, ensure_ascii=True
        ).encode("utf-8")
        + b"\n"
    )
    if receipt_set != expected_receipt_set or receipt_payload != canonical_receipts:
        raise AuthorityError("checked signed receipt set is not exactly empty")
    validate_empty_receipt_set(receipt_set)
    return {
        "authority_registry_raw_sha256": sha256(registry_payload),
        "authorization_envelope_count": 0,
        "completion_receipt_envelope_count": 0,
        "signed_receipt_set_raw_sha256": sha256(receipt_payload),
        "trusted_root_count": 0,
        "status": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate artifacts")
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("the only supported mode is --check")
    try:
        print(json.dumps(check(), indent=2, sort_keys=True))
    except (AuthorityError, OSError) as exc:
        print(f"candidate authority validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
