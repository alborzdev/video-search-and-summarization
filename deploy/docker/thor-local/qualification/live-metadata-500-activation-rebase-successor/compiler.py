#!/usr/bin/env python3
"""Compile a check-only immutable Metadata-500 activation rebase."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
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
PARITY = REPO_ROOT / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(PARITY))

from metadata_sets import resolver as metadata_resolver  # noqa: E402
import verify_metadata_set as bundle_verifier  # noqa: E402


SET_ID_289 = "thor-vss-3.2.1-live-289"
SET_ID_500 = "thor-vss-3.2.1-metadata-500-staged"
CANONICAL_SELECTOR = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
CANONICAL_DESCRIPTOR_500 = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged.json"
)
CANONICAL_DESCRIPTOR_289 = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-live-289.json"
)
IMMUTABLE_DESCRIPTOR_PREFIX = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged-rebase-"
)
MIGRATION_REBASE = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-migration-rebase-successor"
)
DESCRIPTOR_OUTPUT = PACKAGE / "projected-live-ready-descriptor.json"
SELECTOR_OUTPUT = PACKAGE / "projected-selector.json"
RECEIPT_OUTPUT = PACKAGE / "activation-rebase.json"
RECEIPT_SCHEMA_OUTPUT = PACKAGE / "activation-rebase.schema.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

INPUTS = {
    "migration_proof": (
        f"{MIGRATION_REBASE}/migration.json",
        "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c",
    ),
    "migration_proof_schema": (
        f"{MIGRATION_REBASE}/migration.schema.json",
        "45c41fc02b60fa466689ab2ece0e87487287a20e3d247ba0f62293c649a349c0",
    ),
    "manifest_500": (
        f"{MIGRATION_REBASE}/post-state-manifest.json",
        "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    ),
    "ledger_500": (
        f"{MIGRATION_REBASE}/post-state-official-capabilities.json",
        "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    ),
    "acceptance_500": (
        f"{MIGRATION_REBASE}/post-state-acceptance-inventory.json",
        "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    ),
    "oracles_500": (
        f"{MIGRATION_REBASE}/post-state-capability-oracles.json",
        "911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021",
    ),
    "oracle_schema_500": (
        f"{MIGRATION_REBASE}/post-state-capability-oracles.schema.json",
        "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    ),
    "selector_schema": (
        "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json",
        "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    ),
    "set_schema": (
        "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json",
        "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    ),
    "official_schema": (
        "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    ),
    "resolver": (
        "deploy/docker/thor-local/parity/metadata_sets/resolver.py",
        "b10564b61c46b2d01894da735c550c5ab315224ba63e1b67df5e9f4b3719a1f3",
    ),
    "resolver_init": (
        "deploy/docker/thor-local/parity/metadata_sets/__init__.py",
        "3205a3070c3068149c70bb12cbe27f983c8437d3ea6a0083ed6201d1ed5a388d",
    ),
    "resolver_tests": (
        "deploy/docker/thor-local/parity/metadata_sets/tests/test_resolver.py",
        "b42140db6c87ba0ed1a9f3d8d67899a8eee70da0f075c48c117490e0387ff742",
    ),
    "bundle_verifier": (
        "deploy/docker/thor-local/parity/verify_metadata_set.py",
        "b26fc78dbc43e5cd6f6a081c3fa7b18af90a7a2261ae3e8f792e56fc2fad1cb7",
    ),
    "bundle_verifier_tests": (
        "deploy/docker/thor-local/parity/tests/test_verify_metadata_set.py",
        "348e8058a65534ebe49c1673ff4d35f195341dde1273296782cece4200b541e5",
    ),
    "v2_validator": (
        "deploy/docker/thor-local/parity/capability_oracles_v2.py",
        "a4ae44624c55b1b9555f506cf18ea1d916046200f6c1e125612af2678f836ef6",
    ),
    "official_verifier": (
        "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        "c21fd2910089c6981f0437d41d6c9ef7fff19d55c0153b04b7f7f91b00d79109",
    ),
}
JSON_INPUTS = {
    "migration_proof",
    "migration_proof_schema",
    "manifest_500",
    "ledger_500",
    "acceptance_500",
    "oracles_500",
    "oracle_schema_500",
    "selector_schema",
    "set_schema",
    "official_schema",
}
EXPECTED = {
    "descriptor": "4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca",
    "selector": "d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112",
    "receipt": "93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e",
    "receipt_schema": "5a4d3c481577540b21531ca08fbfe3e814b310a5e428b9fd7af8b02f9c9bb85f",
    "receipt_payload": "93d6817c811fb66d581a7d2285bfdf4738317871c21513e1e6d0bacbf0161000",
}

EXPECTED_289_ROW = {
    "set_id": SET_ID_289,
    "descriptor_path": CANONICAL_DESCRIPTOR_289,
    "descriptor_raw_sha256": "dcae065b6a4ed93a51c92f7a1403f454738bd61c75536d6653ab14e563d59059",
}
EXPECTED_500_ROW = {
    "set_id": SET_ID_500,
    "descriptor_path": CANONICAL_DESCRIPTOR_500,
    "descriptor_raw_sha256": "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
}

PRESERVED_FILES = {
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/EVIDENCE.md": "55d64391c59b65752a95b37f03945d8a24f60a2eeef53db3cacfeb6f91f8bfe8",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/README.md": "2143af777b5a67523ff226ddef8aaa54897ef1c200a23966b6011923d2c50526",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/compiler.py": "d1eb9d0e59f9939b63f1ff61768747297cc38e65ebdaa4675b2f378616d11f0a",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/migration.json": "39ec1db0d4e42c7d39c237f647f80c15dff12cea15630ef3e8572bf5e32dac0d",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/migration.schema.json": "786b095f40510e87e76405d0b06e3aae63f50530670d9a8453d5d5dee9b47eb7",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-acceptance-inventory.json": "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.json": "17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.schema.json": "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-manifest.json": "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-official-capabilities.json": "f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6",
    "deploy/docker/thor-local/qualification/live-metadata-500-migration/tests/test_compiler.py": "5774c8b3680a0f11bc4be16548807ee65caea7c19dbd088943e7895b6f8c67f4",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/EVIDENCE.md": "2301c5793a35a75c7056254915f4cb9ef0084866649e0ae12ad8a66c0a8b1df3",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/README.md": "147858d135f71e2d537c2b5d0b04f40556401ef7dbcc9fa90e7a361b7a7c0fa5",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/activation.json": "79de3432908d79ca5861b77c40304f26014f1a704c6bacb1ff5a45ae00208d43",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/activation.schema.json": "396f8b1a5776c20b37cb372ba8dffebf0e97bdacffc28fbcd28d4e2b20ed1bae",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/compiler.py": "33af3f61d238600385c7a7264f18b6be940e71d665a8b21e6f0e133aba62aff0",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/pre-activation-selector.json": "aafab3b6e665f4f305738ed498ad2fd6dc3399d41f1d4b4b9c4ee670db5bcb15",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/pre-activation-staged-descriptor.json": "dad58ec5c128b38235a3fc135cd1c66a0225fa3a80fa2f1f9b9cb42bce8b385c",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/projected-live-ready-descriptor.json": "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/projected-selector.json": "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    "deploy/docker/thor-local/qualification/live-metadata-500-activation/tests/test_compiler.py": "b80f16dec631d188abfcb1e9de95f8ff91a6e9f0cb6716b8c222ea78b400c67a",
    CANONICAL_SELECTOR: "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    CANONICAL_DESCRIPTOR_500: "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
    CANONICAL_DESCRIPTOR_289: "dcae065b6a4ed93a51c92f7a1403f454738bd61c75536d6653ab14e563d59059",
}


class RebaseActivationError(RuntimeError):
    """An input lock, preservation boundary, or projection invariant failed."""


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode()


def _regular_file(relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise RebaseActivationError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise RebaseActivationError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise RebaseActivationError(f"repository input traverses symlink: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise RebaseActivationError(f"repository input is not regular: {relative}")
    return current


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise RebaseActivationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                RebaseActivationError(f"non-finite JSON value in {label}: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebaseActivationError(f"invalid JSON input: {label}") from exc
    if not isinstance(value, dict):
        raise RebaseActivationError(f"JSON root is not an object: {label}")
    return value


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = "/" + "/".join(str(item) for item in first.absolute_path)
        raise RebaseActivationError(f"{label} schema error at {path}: {first.message}")


def assert_preserved_bytes() -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in PRESERVED_FILES.items():
        digest = _sha(_regular_file(relative).read_bytes())
        if digest != expected:
            raise RebaseActivationError(f"preserved byte lock drift: {relative}")
        observed[relative] = digest
    return observed


def _load_inputs() -> tuple[dict[str, Any], dict[str, bytes], dict[str, dict[str, str]]]:
    documents: dict[str, Any] = {}
    payloads: dict[str, bytes] = {}
    locks: dict[str, dict[str, str]] = {}
    for input_id, (relative, expected) in INPUTS.items():
        if HEX64.fullmatch(expected) is None:
            raise RebaseActivationError(f"unreviewed input lock: {input_id}")
        payload = _regular_file(relative).read_bytes()
        if _sha(payload) != expected:
            raise RebaseActivationError(f"input hash drift: {relative}")
        payloads[input_id] = payload
        documents[input_id] = (
            _strict_json(payload, relative) if input_id in JSON_INPUTS else payload
        )
        locks[input_id] = {"path": relative, "raw_sha256": expected}
    return documents, payloads, locks


def _immutable_descriptor_path(migration_proof_raw_sha256: str) -> str:
    if HEX64.fullmatch(migration_proof_raw_sha256) is None:
        raise RebaseActivationError("migration proof hash is not lowercase SHA-256")
    return f"{IMMUTABLE_DESCRIPTOR_PREFIX}{migration_proof_raw_sha256}.json"


def _assert_base_descriptor(descriptor: dict[str, Any]) -> None:
    if (
        descriptor.get("set_id") != SET_ID_500
        or descriptor.get("lifecycle") != "live_ready"
        or descriptor.get("expected_counts")
        != {"capabilities": 500, "oracles": 500, "feature_families": 55}
        or list(descriptor.get("documents", {}))
        != [
            "manifest",
            "official_capabilities",
            "capability_oracles",
            "acceptance_inventory",
        ]
    ):
        raise RebaseActivationError("canonical Metadata-500 descriptor identity differs")


def project_descriptor(
    descriptor: dict[str, Any], locks: dict[str, dict[str, str]]
) -> dict[str, Any]:
    _assert_base_descriptor(descriptor)
    required = {
        "migration_proof",
        "migration_proof_schema",
        "manifest_500",
        "ledger_500",
        "acceptance_500",
        "oracles_500",
        "oracle_schema_500",
    }
    if not required <= set(locks):
        raise RebaseActivationError("future migration lock partition differs")
    projected = copy.deepcopy(descriptor)
    members = {
        "manifest": "manifest_500",
        "official_capabilities": "ledger_500",
        "capability_oracles": "oracles_500",
        "acceptance_inventory": "acceptance_500",
    }
    for member_id, input_id in members.items():
        projected["documents"][member_id]["path"] = locks[input_id]["path"]
        projected["documents"][member_id]["raw_sha256"] = locks[input_id][
            "raw_sha256"
        ]
    projected["schemas"]["capability_oracles_schema"]["path"] = locks[
        "oracle_schema_500"
    ]["path"]
    projected["schemas"]["capability_oracles_schema"]["raw_sha256"] = locks[
        "oracle_schema_500"
    ]["raw_sha256"]
    for field in (
        "schema_version",
        "set_id",
        "mode",
        "lifecycle",
        "target",
        "expected_counts",
    ):
        if projected[field] != descriptor[field]:
            raise RebaseActivationError(f"descriptor identity field changed: {field}")
    return projected


def project_selector(
    selector: dict[str, Any], descriptor_path: str, descriptor_raw_sha256: str
) -> dict[str, Any]:
    if (
        selector.get("selected_set") != SET_ID_500
        or HEX64.fullmatch(descriptor_raw_sha256) is None
        or not descriptor_path.startswith(IMMUTABLE_DESCRIPTOR_PREFIX)
        or not descriptor_path.endswith(".json")
    ):
        raise RebaseActivationError("selector rebase input boundary differs")
    rows = selector.get("available_sets")
    if rows != [EXPECTED_289_ROW, EXPECTED_500_ROW]:
        raise RebaseActivationError("selector set rows/order differ")
    projected = copy.deepcopy(selector)
    projected["available_sets"][1]["descriptor_path"] = descriptor_path
    projected["available_sets"][1]["descriptor_raw_sha256"] = descriptor_raw_sha256
    reconstructed = copy.deepcopy(projected)
    reconstructed["available_sets"][1] = copy.deepcopy(selector["available_sets"][1])
    if reconstructed != selector:
        raise RebaseActivationError("selector projection changes unauthorized fields")
    if (
        projected["selected_set"] != selector["selected_set"]
        or projected["available_sets"][0] != selector["available_sets"][0]
    ):
        raise RebaseActivationError("selector identity or 289 row changed")
    return projected


def _validate_migration(
    documents: dict[str, Any], locks: dict[str, dict[str, str]]
) -> None:
    Draft202012Validator.check_schema(documents["migration_proof_schema"])
    _validate(
        documents["migration_proof"],
        documents["migration_proof_schema"],
        "migration-rebase proof",
    )
    proof = documents["migration_proof"]
    if (
        proof.get("policy", {}).get("candidate_runtime_promotion") is not False
        or proof.get("policy", {}).get("modifies_selector_or_descriptors") is not False
        or proof.get("summary", {}).get("candidate_runtime_evidence_count") != 0
        or proof.get("summary", {}).get("candidate_promotable_count") != 0
        or proof.get("summary", {}).get("capability_count") != 500
        or proof.get("summary", {}).get("feature_count") != 55
        or proof.get("rollback", {}).get("selector_or_descriptor_change_included")
        is not False
    ):
        raise RebaseActivationError("migration-rebase boundary differs")
    for name, lock_id in (
        ("post-state-manifest.json", "manifest_500"),
        ("post-state-official-capabilities.json", "ledger_500"),
        ("post-state-acceptance-inventory.json", "acceptance_500"),
        ("post-state-capability-oracles.json", "oracles_500"),
        ("post-state-capability-oracles.schema.json", "oracle_schema_500"),
    ):
        if proof.get("artifacts", {}).get(name) != locks[lock_id]:
            raise RebaseActivationError(f"migration artifact binding differs: {name}")


def _write_overlay(root: Path, relative: str, payload: bytes) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RebaseActivationError(f"unsafe temporary overlay path: {relative}")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _isolated_verify(
    descriptor: dict[str, Any],
    descriptor_path: str,
    descriptor_payload: bytes,
    selector_payload: bytes,
    payloads: dict[str, bytes],
    locks: dict[str, dict[str, str]],
) -> dict[str, Any]:
    payload_by_path = {
        lock["path"]: payloads[input_id] for input_id, lock in locks.items()
    }
    with tempfile.TemporaryDirectory(prefix="vss-metadata-activation-rebase-") as name:
        root = Path(name)
        _write_overlay(root, metadata_resolver.SELECTOR_SCHEMA_PATH, payloads["selector_schema"])
        _write_overlay(root, metadata_resolver.SET_SCHEMA_PATH, payloads["set_schema"])
        _write_overlay(root, metadata_resolver.SELECTOR_PATH, selector_payload)
        _write_overlay(root, descriptor_path, descriptor_payload)
        for group in ("schemas", "documents"):
            for member in descriptor[group].values():
                relative = member["path"]
                payload = payload_by_path.get(relative)
                if payload is None:
                    raise RebaseActivationError(f"unlocked descriptor member: {relative}")
                _write_overlay(root, relative, payload)
        snapshot = metadata_resolver.resolve_metadata_set(repo_root=root)
        original = bundle_verifier.resolve_metadata_set
        try:
            bundle_verifier.resolve_metadata_set = lambda set_id=None: (
                snapshot
                if set_id in {None, SET_ID_500}
                else (_ for _ in ()).throw(
                    RebaseActivationError(f"unexpected verifier set: {set_id}")
                )
            )
            report = bundle_verifier.verify_metadata_set()
        finally:
            bundle_verifier.resolve_metadata_set = original
    if (
        report.get("set_id") != SET_ID_500
        or report.get("descriptor_raw_sha256") != _sha(descriptor_payload)
        or report.get("oracle_schema_version") != 2
        or report.get("oracle_validator") != "capability_oracles_v2"
        or report.get("counts")
        != {"capabilities": 500, "oracles": 500, "feature_families": 55}
        or report.get("official_validator_counts")
        != {
            "sources": 126,
            "capabilities": 500,
            "feature_families": 55,
            "discrepancies": 47,
        }
        or report.get("oracle_validator_counts", {}).get("candidate_evidence") != 0
        or report.get("oracle_validator_counts", {}).get("candidate_executor_ready")
        != 0
    ):
        raise RebaseActivationError("isolated bundle verification report differs")
    return report


def _exact_schema(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://developer.nvidia.com/vss/thor-local/live-metadata-500-activation-rebase-successor.schema.json",
        "title": "Exact check-only Metadata-500 activation-rebase receipt",
        "const": value,
    }


def compile_activation_rebase() -> tuple[
    dict[str, Any], dict[str, Any], dict[Path, bytes]
]:
    preserved = assert_preserved_bytes()
    documents, payloads, locks = _load_inputs()
    for schema_id in (
        "migration_proof_schema",
        "selector_schema",
        "set_schema",
        "official_schema",
        "oracle_schema_500",
    ):
        Draft202012Validator.check_schema(documents[schema_id])
    _validate_migration(documents, locks)
    selector = _strict_json(
        _regular_file(CANONICAL_SELECTOR).read_bytes(), CANONICAL_SELECTOR
    )
    descriptor = _strict_json(
        _regular_file(CANONICAL_DESCRIPTOR_500).read_bytes(),
        CANONICAL_DESCRIPTOR_500,
    )
    _validate(selector, documents["selector_schema"], "canonical selector")
    _validate(descriptor, documents["set_schema"], "canonical descriptor")
    projected_descriptor = project_descriptor(descriptor, locks)
    _validate(projected_descriptor, documents["set_schema"], "projected descriptor")
    descriptor_payload = _encoded(projected_descriptor)
    descriptor_path = _immutable_descriptor_path(locks["migration_proof"]["raw_sha256"])
    projected_selector = project_selector(
        selector, descriptor_path, _sha(descriptor_payload)
    )
    _validate(projected_selector, documents["selector_schema"], "projected selector")
    selector_payload = _encoded(projected_selector)
    report = _isolated_verify(
        projected_descriptor,
        descriptor_path,
        descriptor_payload,
        selector_payload,
        payloads,
        locks,
    )
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "activation_id": "vss-3.2.1-metadata-500-activation-rebase-successor",
        "mode": "isolated_check_only_immutable_descriptor_rebase",
        "source_locks": locks,
        "historical_preservation": {
            "changed_paths": [],
            "byte_lock_count": len(preserved),
            "byte_lock_map_sha256": _sha_json(preserved),
        },
        "policy": {
            "writes_package_files": False,
            "writes_canonical_selector": False,
            "writes_canonical_descriptors": False,
            "modifies_historical_packages": False,
            "runtime_execution": "forbidden",
            "network_access": False,
            "docker_access": False,
            "candidate_runtime_promotion": False,
            "warehouse_sample_bundle": "excluded",
        },
        "projection": {
            "descriptor": {
                "set_id_unchanged": SET_ID_500,
                "lifecycle_unchanged": "live_ready",
                "expected_counts_unchanged": {
                    "capabilities": 500,
                    "oracles": 500,
                    "feature_families": 55,
                },
                "immutable_target_path": descriptor_path,
                "predecessor_path": CANONICAL_DESCRIPTOR_500,
                "predecessor_raw_sha256": PRESERVED_FILES[
                    CANONICAL_DESCRIPTOR_500
                ],
                "projected_raw_sha256": _sha(descriptor_payload),
                "changed_json_pointers": [
                    "/documents/manifest/path",
                    "/documents/official_capabilities/path",
                    "/documents/official_capabilities/raw_sha256",
                    "/documents/capability_oracles/path",
                    "/documents/capability_oracles/raw_sha256",
                    "/documents/acceptance_inventory/path",
                    "/schemas/capability_oracles_schema/path",
                ],
            },
            "selector": {
                "selected_set_unchanged": SET_ID_500,
                "set_id_order_unchanged": [SET_ID_289, SET_ID_500],
                "row_289_unchanged": True,
                "predecessor_raw_sha256": PRESERVED_FILES[CANONICAL_SELECTOR],
                "projected_raw_sha256": _sha(selector_payload),
                "changed_json_pointers": [
                    "/available_sets/1/descriptor_path",
                    "/available_sets/1/descriptor_raw_sha256",
                ],
            },
        },
        "authoritative_isolated_validation": report,
        "candidate_boundary": {
            "candidate_count": 211,
            "runtime_evidence_count": 0,
            "executor_ready_count": 0,
            "promotable_count": 0,
        },
        "rollback": {
            "strategy": "restore_selector_and_remove_exact_rebase_descriptor",
            "live_apply_authorized": False,
            "restore_selector_path": CANONICAL_SELECTOR,
            "restore_selector_raw_sha256": PRESERVED_FILES[CANONICAL_SELECTOR],
            "preserve_predecessor_descriptor_path": CANONICAL_DESCRIPTOR_500,
            "preserve_predecessor_descriptor_raw_sha256": PRESERVED_FILES[
                CANONICAL_DESCRIPTOR_500
            ],
            "remove_only_descriptor_path": descriptor_path,
            "remove_only_descriptor_raw_sha256": _sha(descriptor_payload),
            "requires_projected_selector_raw_sha256": _sha(selector_payload),
            "partial_or_unknown_state": "rejected",
            "atomic_selector_and_descriptor_install_required": True,
        },
        "artifacts": {
            DESCRIPTOR_OUTPUT.name: {
                "path": str(DESCRIPTOR_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha(descriptor_payload),
                "staged_immutable_target_path": descriptor_path,
            },
            SELECTOR_OUTPUT.name: {
                "path": str(SELECTOR_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha(selector_payload),
            },
        },
    }
    receipt["activation_payload_sha256"] = _sha_json(receipt)
    schema = _exact_schema(receipt)
    outputs = {
        DESCRIPTOR_OUTPUT: descriptor_payload,
        SELECTOR_OUTPUT: selector_payload,
        RECEIPT_OUTPUT: _encoded(receipt),
        RECEIPT_SCHEMA_OUTPUT: _encoded(schema),
    }
    return receipt, schema, outputs


def validate_activation(
    receipt: dict[str, Any], schema: dict[str, Any], outputs: dict[Path, bytes]
) -> None:
    _validate(receipt, schema, "activation-rebase receipt")
    payload = dict(receipt)
    observed = payload.pop("activation_payload_sha256")
    if observed != _sha_json(payload):
        raise RebaseActivationError("activation receipt payload hash differs")
    for path in (DESCRIPTOR_OUTPUT, SELECTOR_OUTPUT):
        if receipt["artifacts"][path.name]["raw_sha256"] != _sha(outputs[path]):
            raise RebaseActivationError(f"artifact binding differs: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        receipt, schema, outputs = compile_activation_rebase()
        validate_activation(receipt, schema, outputs)
        expected = {
            DESCRIPTOR_OUTPUT: EXPECTED["descriptor"],
            SELECTOR_OUTPUT: EXPECTED["selector"],
            RECEIPT_OUTPUT: EXPECTED["receipt"],
            RECEIPT_SCHEMA_OUTPUT: EXPECTED["receipt_schema"],
        }
        for path, payload in outputs.items():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise RebaseActivationError(f"checked package output differs: {path.name}")
            if expected[path] != _sha(payload):
                raise RebaseActivationError(f"checked output fingerprint differs: {path.name}")
        if EXPECTED["receipt_payload"] != receipt["activation_payload_sha256"]:
            raise RebaseActivationError("checked receipt payload fingerprint differs")
        print(
            "PASS: immutable Metadata-500 activation rebase; selected=500, "
            "capabilities=500, oracles=500, evidence=0, canonical-writes=0"
        )
        return 0
    except (
        RebaseActivationError,
        SchemaError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
