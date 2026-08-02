#!/usr/bin/env python3
"""Validate the provenance-rebased empty authority registry design."""

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
    "candidate-execution-binding-registry-rebase-successor"
)
ADMISSION_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-admission-receipts-rebase-successor"
)
HISTORICAL_DIR = (
    "deploy/docker/thor-local/qualification/candidate-authority-registry-successor"
)
BINDING_REGISTRY_PATH = f"{BINDING_DIR}/registry.json"
BINDING_LOCATORS_PATH = f"{BINDING_DIR}/locator-locks.json"
ADMISSION_INDEX_PATH = f"{ADMISSION_DIR}/admission-index.json"
ADMISSION_RECEIPTS_PATH = f"{ADMISSION_DIR}/receipt-set.json"

EXPECTED_SOURCE_HASHES = {
    BINDING_REGISTRY_PATH: "af3927c15f9e5c1efb67690ee7ca3f3e6ee9fb77e720767db2264d68a935b6b5",
    f"{BINDING_DIR}/registry.schema.json": (
        "8c2f7fa335340ceaf6870236e11fa2f4d290ba0ee3029f101495b6f66dda1f61"
    ),
    BINDING_LOCATORS_PATH: "d1882d4811bd661fd011f8cf91894951cc8af806c56968218ef0100b500b69a0",
    f"{BINDING_DIR}/locator-locks.schema.json": (
        "3cad143f04ebb9a80b11e180aed9a6ccb573d247d52b617ea8caeb9805075cb2"
    ),
    f"{BINDING_DIR}/compiler.py": (
        "d40400fb1089694b6c83f8700db0fc3fdbc0dd1b2c4333f17d4ea3c668985831"
    ),
    f"{BINDING_DIR}/tests/test_compiler.py": (
        "c9b217b81b05ce8edfe86ff456be429d354f08b3f01c4139c8baac748dcfd8cb"
    ),
    ADMISSION_INDEX_PATH: "74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff",
    f"{ADMISSION_DIR}/admission-index.schema.json": (
        "54cef2f2dc7879f817ff21c2b2472b19629d23c028fc25c3cee04fe9f09926d7"
    ),
    ADMISSION_RECEIPTS_PATH: "e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f",
    f"{ADMISSION_DIR}/receipt-set.schema.json": (
        "63dfd032bb3625fd1d5002f19a10e25f72f1c775c9f2c5ce6ee1121531449c10"
    ),
    f"{ADMISSION_DIR}/compiler.py": (
        "1ea46fc02a95e4d0b270030ee1c57c7c4293d8e46d9f8fcd857d15834c43587d"
    ),
    f"{ADMISSION_DIR}/tests/test_compiler.py": (
        "2c5079cdc254b9c8d2c6b08023707bf5f36ed22738307261edec1856e76c6bc0"
    ),
}

IMMUTABLE_FILES = {
    f"{HISTORICAL_DIR}/README.md": "009cb54d96be76808f1f73385b021da814323855cec647350aedce0e2d535d0f",
    f"{HISTORICAL_DIR}/EVIDENCE.md": "4f4b72e69c1e213d30b432344bb1b774b320407ab8f425ae7fd0811ce1fcdf54",
    f"{HISTORICAL_DIR}/compiler.py": "5f11f9b83308e494d8d2eed5a495bd38ea17630c443cb605c2843d3a1b41dd51",
    f"{HISTORICAL_DIR}/authority-registry.json": "4b3b806509d7dc0c50edcf8dadeec38b4b8aaab3a9d7404f3358922b029abcc2",
    f"{HISTORICAL_DIR}/authority-registry.schema.json": "ddbf500a8c6f4850bbbde0b4e73ad280313a0b4343006870033ba40bf4fa585c",
    f"{HISTORICAL_DIR}/signed-receipt-envelope.schema.json": "3df35e5c82b36a029512f564f99753a05a63f7ba280c98c7a79672dd9d5f94d7",
    f"{HISTORICAL_DIR}/signed-receipt-set.json": "7d891821c71bf9bd3c12eff1913134882f4cf3d0dd656aba29c5de0eceff8ffc",
    f"{HISTORICAL_DIR}/signed-receipt-set.schema.json": "31c9ff69edd42d444b04254b56239290c864e7337344a7993d80cbb1a2561d3e",
    f"{HISTORICAL_DIR}/tests/test_compiler.py": "f38549c5f576ad3f03a56f86d54fb3a4aa00b944ae937612dd6d33ec90535629",
    "deploy/docker/thor-local/parity/metadata_sets/selector.json": "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    (
        "deploy/docker/thor-local/parity/metadata_sets/sets/"
        "thor-vss-3.2.1-metadata-500-staged.json"
    ): "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
}

EXPECTED_OUTPUT_HASHES = {
    "authority-registry.json": "954aa42541f715bdbb25148a322e2e3b3380f27fc4f958e8ba0e7378945acdd4",
    "authority-registry.schema.json": "46593bea289de96c0b9fe799f8a6c6c4087b730977dde6bcd26c016bd58dd297",
    "signed-receipt-envelope.schema.json": "3df35e5c82b36a029512f564f99753a05a63f7ba280c98c7a79672dd9d5f94d7",
    "signed-receipt-set.json": "84ce0c682a49dc930f33fa2bb698e9a7f66a14902cf123e0cba060a8c0f8ed24",
    "signed-receipt-set.schema.json": "05bb7d89d5e0d3648f1ca17a7211540e9083ce0d73ffd073e2a1d5ff0202d27a",
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


def _require_finalized_binding_inputs() -> None:
    pending = {
        path: digest
        for path, digest in EXPECTED_SOURCE_HASHES.items()
        if digest.startswith("PENDING_")
    }
    if pending:
        detail = ", ".join(f"{path}={digest}" for path, digest in pending.items())
        raise AuthorityError(f"execution-binding rebase inputs pending: {detail}")


def _assert_immutable_files() -> None:
    for relative, expected in IMMUTABLE_FILES.items():
        payload = _read_regular(_repo_path(relative), relative)
        if sha256(payload) != expected:
            raise AuthorityError(f"immutable historical/canonical drift: {relative}")


def _load_locked_sources() -> dict[str, dict[str, Any]]:
    _require_finalized_binding_inputs()
    _assert_immutable_files()
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
        != "0d8b334e25330d8f5142a6fff91cc13fc3ebf0c013a371e1f6b41334530c0924"
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
        "authority_registry_id": ("thor-vss-3.2.1-candidate-authority-rebase-empty-v1"),
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
    _validate_historical_registry_semantics(result)
    return result


def _validate_historical_registry_semantics(registry: dict[str, Any]) -> None:
    historical_path = f"{HISTORICAL_DIR}/authority-registry.json"
    historical = strict_json(
        _read_regular(_repo_path(historical_path), historical_path), historical_path
    )
    rebased = json.loads(json.dumps(registry))
    rebased["authority_registry_id"] = historical["authority_registry_id"]
    rebased["source_locks"] = historical["source_locks"]
    rebased["source_identity"] = historical["source_identity"]
    if rebased != historical:
        raise AuthorityError(
            "historical authority semantics drift beyond provenance rebasing"
        )


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


def compile_signed_receipt_set(
    registry_payload: bytes, envelope_schema_payload: bytes
) -> dict[str, Any]:
    return {
        "receipt_set_id": ("thor-vss-3.2.1-candidate-rebase-signed-receipts-empty-v1"),
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


def check() -> dict[str, Any]:
    _require_finalized_binding_inputs()
    for name, expected_hash in EXPECTED_OUTPUT_HASHES.items():
        if expected_hash != "TO_BE_FILLED":
            actual_hash = sha256(_read_regular(HERE / name, f"checked {name}"))
            if actual_hash != expected_hash:
                raise AuthorityError(f"output lock mismatch: {name}")
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
    expected_receipt_set = compile_signed_receipt_set(
        registry_payload, envelope_schema_payload
    )
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
