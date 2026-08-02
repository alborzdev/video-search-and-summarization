#!/usr/bin/env python3
"""Compile a non-applying live-ready selector activation for Metadata-500."""

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
PARITY = REPO_ROOT / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(PARITY))

from metadata_sets import resolver as metadata_resolver  # noqa: E402
import verify_metadata_set as bundle_verifier  # noqa: E402


DESCRIPTOR_OUTPUT = PACKAGE / "projected-live-ready-descriptor.json"
SELECTOR_OUTPUT = PACKAGE / "projected-selector.json"
RECEIPT_OUTPUT = PACKAGE / "activation.json"
RECEIPT_SCHEMA_OUTPUT = PACKAGE / "activation.schema.json"
MAX_JSON_BYTES = 96_000_000
SET_ID_289 = "thor-vss-3.2.1-live-289"
SET_ID_500 = "thor-vss-3.2.1-metadata-500-staged"
CANONICAL_SELECTOR_PATH = "deploy/docker/thor-local/parity/metadata_sets/selector.json"
CANONICAL_DESCRIPTOR_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged.json"
)
PRE_SELECTOR_SHA256 = "aafab3b6e665f4f305738ed498ad2fd6dc3399d41f1d4b4b9c4ee670db5bcb15"
PRE_DESCRIPTOR_SHA256 = (
    "dad58ec5c128b38235a3fc135cd1c66a0225fa3a80fa2f1f9b9cb42bce8b385c"
)

INPUTS = {
    "pre_activation_selector": (
        "deploy/docker/thor-local/qualification/live-metadata-500-activation/"
        "pre-activation-selector.json",
        PRE_SELECTOR_SHA256,
    ),
    "selector_schema": (
        "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json",
        "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    ),
    "set_schema": (
        "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json",
        "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    ),
    "descriptor_289": (
        "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-live-289.json",
        "dcae065b6a4ed93a51c92f7a1403f454738bd61c75536d6653ab14e563d59059",
    ),
    "pre_activation_descriptor_500": (
        "deploy/docker/thor-local/qualification/live-metadata-500-activation/"
        "pre-activation-staged-descriptor.json",
        PRE_DESCRIPTOR_SHA256,
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
    "v2_validator": (
        "deploy/docker/thor-local/parity/capability_oracles_v2.py",
        "a4ae44624c55b1b9555f506cf18ea1d916046200f6c1e125612af2678f836ef6",
    ),
    "v2_validator_tests": (
        "deploy/docker/thor-local/parity/tests/test_capability_oracles_v2.py",
        "c79d3067a4f116a768cc7e20c4afe9422ca6f5bd99489cf877151725b686a98e",
    ),
    "bundle_verifier": (
        "deploy/docker/thor-local/parity/verify_metadata_set.py",
        "b26fc78dbc43e5cd6f6a081c3fa7b18af90a7a2261ae3e8f792e56fc2fad1cb7",
    ),
    "bundle_verifier_tests": (
        "deploy/docker/thor-local/parity/tests/test_verify_metadata_set.py",
        "348e8058a65534ebe49c1673ff4d35f195341dde1273296782cece4200b541e5",
    ),
    "v1_validator": (
        "deploy/docker/thor-local/parity/capability_oracles.py",
        "32f18f2d74508a78282cf572c00ba5f7b739b7b0969019f963e04372e791de1c",
    ),
    "official_verifier": (
        "deploy/docker/thor-local/parity/verify_official_capabilities.py",
        "c21fd2910089c6981f0437d41d6c9ef7fff19d55c0153b04b7f7f91b00d79109",
    ),
    "official_schema": (
        "deploy/docker/thor-local/parity/official-capabilities.schema.json",
        "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    ),
    "migration_proof": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/migration.json",
        "39ec1db0d4e42c7d39c237f647f80c15dff12cea15630ef3e8572bf5e32dac0d",
    ),
    "migration_proof_schema": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/migration.schema.json",
        "786b095f40510e87e76405d0b06e3aae63f50530670d9a8453d5d5dee9b47eb7",
    ),
    "migration_tests": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/tests/test_compiler.py",
        "5774c8b3680a0f11bc4be16548807ee65caea7c19dbd088943e7895b6f8c67f4",
    ),
    "manifest_500": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-manifest.json",
        "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    ),
    "ledger_500": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-official-capabilities.json",
        "f1e63b25c607a09f19a3c53aa47d8d152c61ffbd330440b93d54eccfaa49add6",
    ),
    "acceptance_500": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-acceptance-inventory.json",
        "69dc4aca160ae236880f9afe7b873c0b3b423f8981c5d934e4ed647043cd8cb0",
    ),
    "oracles_500": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.json",
        "17091a3c0e9ac4d3aba7b5c6d91f09c8832648f149ac0624f3b63cd2c5e77271",
    ),
    "oracle_schema_500": (
        "deploy/docker/thor-local/qualification/live-metadata-500-migration/post-state-capability-oracles.schema.json",
        "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    ),
}
JSON_INPUTS = {
    "pre_activation_selector",
    "selector_schema",
    "set_schema",
    "descriptor_289",
    "pre_activation_descriptor_500",
    "official_schema",
    "migration_proof",
    "migration_proof_schema",
    "manifest_500",
    "ledger_500",
    "acceptance_500",
    "oracles_500",
    "oracle_schema_500",
}
EXPECTED = {
    "descriptor": "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
    "selector": "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    "receipt": "79de3432908d79ca5861b77c40304f26014f1a704c6bacb1ff5a45ae00208d43",
    "receipt_schema": "396f8b1a5776c20b37cb372ba8dffebf0e97bdacffc28fbcd28d4e2b20ed1bae",
    "receipt_payload": "eabbd6869e139ce3b671b14489e7f2011fbb3dd723667e134e584fec9d51e657",
}


class ActivationError(RuntimeError):
    """An activation lock, invariant, or isolated validation failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode()


def _strict_json(payload: bytes, label: str) -> dict[str, Any]:
    if len(payload) > MAX_JSON_BYTES:
        raise ActivationError(f"oversized JSON input: {label}")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise ActivationError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode(),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ActivationError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except ActivationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActivationError(f"invalid JSON in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ActivationError(f"JSON root is not an object: {label}")
    return value


def _regular_repo_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ActivationError(f"unsafe repository path: {relative}")
    current = root
    for part in path.parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ActivationError(f"missing repository input: {relative}") from exc
        if stat.S_ISLNK(mode):
            raise ActivationError(f"repository input contains symlink: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ActivationError(f"repository input is not regular: {relative}")
    return current


def _repo_file(relative: str) -> Path:
    return _regular_repo_file(REPO_ROOT, relative)


def _load_inputs() -> tuple[dict[str, Any], dict[str, bytes], dict[str, Any]]:
    documents: dict[str, Any] = {}
    payloads: dict[str, bytes] = {}
    locks: dict[str, Any] = {}
    for input_id, (relative, expected) in INPUTS.items():
        payload = _repo_file(relative).read_bytes()
        digest = _sha_bytes(payload)
        if digest != expected:
            raise ActivationError(f"source hash drift: {relative}")
        payloads[input_id] = payload
        documents[input_id] = (
            _strict_json(payload, relative) if input_id in JSON_INPUTS else payload
        )
        locks[input_id] = {"path": relative, "raw_sha256": digest}
    return documents, payloads, locks


def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = "/" + "/".join(str(item) for item in first.absolute_path)
        raise ActivationError(f"{label} schema error at {path}: {first.message}")


def _project_descriptor(staged: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(staged)
    if (
        projected.get("set_id") != SET_ID_500
        or projected.get("lifecycle") != "validation_only"
    ):
        raise ActivationError("staged descriptor identity/lifecycle differs")
    projected["lifecycle"] = "live_ready"
    reconstructed = copy.deepcopy(projected)
    reconstructed["lifecycle"] = "validation_only"
    if reconstructed != staged:
        raise ActivationError("descriptor projection changes more than lifecycle")
    return projected


def _project_selector(
    selector: dict[str, Any], descriptor_sha256: str
) -> dict[str, Any]:
    projected = copy.deepcopy(selector)
    if projected.get("selected_set") != SET_ID_289:
        raise ActivationError("current selector default is not the 289 set")
    entries = {row["set_id"]: row for row in projected.get("available_sets", [])}
    if set(entries) != {SET_ID_289, SET_ID_500}:
        raise ActivationError("selector registry differs")
    projected["selected_set"] = SET_ID_500
    entries[SET_ID_500]["descriptor_raw_sha256"] = descriptor_sha256
    reconstructed = copy.deepcopy(projected)
    reconstructed["selected_set"] = SET_ID_289
    before_500 = next(
        row for row in selector["available_sets"] if row["set_id"] == SET_ID_500
    )
    rebuilt_500 = next(
        row for row in reconstructed["available_sets"] if row["set_id"] == SET_ID_500
    )
    rebuilt_500.update(before_500)
    if reconstructed != selector:
        raise ActivationError("selector projection changes unauthorized fields")
    return projected


def _inspect_live_state(
    projected_selector_payload: bytes,
    projected_descriptor_payload: bytes,
    *,
    repo_root: Path | None = None,
) -> str:
    """Accept only an atomic pre-activation or fully applied control-plane state."""
    root = REPO_ROOT if repo_root is None else repo_root
    selector_digest = _sha_bytes(
        _regular_repo_file(root, CANONICAL_SELECTOR_PATH).read_bytes()
    )
    descriptor_digest = _sha_bytes(
        _regular_repo_file(root, CANONICAL_DESCRIPTOR_PATH).read_bytes()
    )
    projected_selector_digest = _sha_bytes(projected_selector_payload)
    projected_descriptor_digest = _sha_bytes(projected_descriptor_payload)
    pair = (selector_digest, descriptor_digest)
    if pair == (PRE_SELECTOR_SHA256, PRE_DESCRIPTOR_SHA256):
        return "pre_activation"
    if pair == (projected_selector_digest, projected_descriptor_digest):
        return "applied"
    known_selector = selector_digest in {
        PRE_SELECTOR_SHA256,
        projected_selector_digest,
    }
    known_descriptor = descriptor_digest in {
        PRE_DESCRIPTOR_SHA256,
        projected_descriptor_digest,
    }
    if known_selector and known_descriptor:
        raise ActivationError("mixed/partial canonical activation state")
    raise ActivationError("unknown canonical activation state")


def _write_overlay(root: Path, relative: str, payload: bytes) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ActivationError(f"unsafe overlay path: {relative}")
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)


def _isolated_verify(
    descriptor: dict[str, Any],
    descriptor_payload: bytes,
    selector_payload: bytes,
    source_payloads: dict[str, bytes],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vss-metadata-activation-") as name:
        root = Path(name)
        _write_overlay(
            root,
            metadata_resolver.SELECTOR_SCHEMA_PATH,
            source_payloads["selector_schema"],
        )
        _write_overlay(
            root, metadata_resolver.SET_SCHEMA_PATH, source_payloads["set_schema"]
        )
        _write_overlay(root, metadata_resolver.SELECTOR_PATH, selector_payload)
        _write_overlay(root, CANONICAL_DESCRIPTOR_PATH, descriptor_payload)
        path_to_input = {
            relative: input_id for input_id, (relative, _) in INPUTS.items()
        }
        for group in ("schemas", "documents"):
            for member in descriptor[group].values():
                relative = member["path"]
                input_id = path_to_input.get(relative)
                if input_id is None:
                    raise ActivationError(f"unlocked descriptor member: {relative}")
                _write_overlay(root, relative, source_payloads[input_id])
        snapshot = metadata_resolver.resolve_metadata_set(repo_root=root)
        original = bundle_verifier.resolve_metadata_set
        try:
            bundle_verifier.resolve_metadata_set = lambda set_id=None: (
                snapshot
                if set_id in {None, SET_ID_500}
                else (_ for _ in ()).throw(
                    ActivationError(f"unexpected verifier set: {set_id}")
                )
            )
            report = bundle_verifier.verify_metadata_set()
        finally:
            bundle_verifier.resolve_metadata_set = original
    expected_counts = {
        "capabilities": 500,
        "oracles": 500,
        "feature_families": 55,
    }
    if (
        report.get("set_id") != SET_ID_500
        or report.get("descriptor_raw_sha256") != _sha_bytes(descriptor_payload)
        or report.get("oracle_schema_version") != 2
        or report.get("oracle_validator") != "capability_oracles_v2"
        or report.get("counts") != expected_counts
        or report.get("oracle_validator_counts", {}).get("candidate_evidence") != 0
        or report.get("oracle_validator_counts", {}).get("candidate_executor_ready")
        != 0
    ):
        raise ActivationError("isolated authoritative verification report differs")
    return report


def _exact_schema(value: Any) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://developer.nvidia.com/vss/thor-local/live-metadata-500-activation.schema.json",
        "title": "Exact non-applying Metadata-500 activation receipt",
        "const": value,
    }


def compile_activation() -> tuple[
    dict[str, Any], dict[str, Any], dict[Path, bytes], str
]:
    docs, payloads, locks = _load_inputs()
    for schema_id in ("selector_schema", "set_schema", "migration_proof_schema"):
        try:
            Draft202012Validator.check_schema(docs[schema_id])
        except SchemaError as exc:
            raise ActivationError(
                f"invalid locked schema {schema_id}: {exc.message}"
            ) from exc
    _validate(
        docs["pre_activation_selector"],
        docs["selector_schema"],
        "pre-activation selector snapshot",
    )
    _validate(docs["descriptor_289"], docs["set_schema"], "289 descriptor")
    _validate(
        docs["pre_activation_descriptor_500"],
        docs["set_schema"],
        "pre-activation staged descriptor snapshot",
    )
    _validate(
        docs["migration_proof"], docs["migration_proof_schema"], "migration proof"
    )
    if (
        docs["migration_proof"]["policy"]["candidate_runtime_promotion"] is not False
        or docs["migration_proof"]["summary"]["candidate_runtime_evidence_count"] != 0
        or docs["migration_proof"]["summary"]["candidate_promotable_count"] != 0
    ):
        raise ActivationError("migration proof implies candidate promotion")

    descriptor = _project_descriptor(docs["pre_activation_descriptor_500"])
    _validate(descriptor, docs["set_schema"], "projected descriptor")
    descriptor_payload = _encoded(descriptor)
    selector = _project_selector(
        docs["pre_activation_selector"], _sha_bytes(descriptor_payload)
    )
    _validate(selector, docs["selector_schema"], "projected selector")
    selector_payload = _encoded(selector)
    observed_state = _inspect_live_state(selector_payload, descriptor_payload)
    report = _isolated_verify(
        descriptor, descriptor_payload, selector_payload, payloads
    )

    legacy_paths = {
        member["path"]: member["raw_sha256"]
        for member in docs["descriptor_289"]["documents"].values()
    }
    fixed_paths = {
        "deploy/docker/thor-local/parity/manifest.json",
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "deploy/docker/thor-local/parity/capability-oracles.json",
        "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    }
    if set(legacy_paths) != fixed_paths:
        raise ActivationError("legacy fixed-file denominator differs")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "activation_id": "vss-3.2.1-metadata-500-selector-live-ready-candidate",
        "mode": "isolated_non_applying_activation_projection",
        "source_locks": locks,
        "policy": {
            "modifies_current_selector": False,
            "modifies_current_descriptors": False,
            "modifies_fixed_legacy_files": False,
            "creates_git_patch": False,
            "runtime_execution": "forbidden",
            "network_access": False,
            "docker_access": False,
            "host_inspection": False,
            "warehouse_sample_bundle": "excluded",
            "candidate_runtime_promotion": False,
        },
        "projection": {
            "descriptor": {
                "set_id": SET_ID_500,
                "changed_json_pointers": ["/lifecycle"],
                "before_lifecycle": "validation_only",
                "after_lifecycle": "live_ready",
                "before_raw_sha256": _sha_bytes(
                    payloads["pre_activation_descriptor_500"]
                ),
                "after_raw_sha256": _sha_bytes(descriptor_payload),
                "before_canonical_sha256": _sha_json(
                    docs["pre_activation_descriptor_500"]
                ),
                "after_canonical_sha256": _sha_json(descriptor),
            },
            "selector": {
                "changed_json_pointers": [
                    "/selected_set",
                    "/available_sets/1/descriptor_raw_sha256",
                ],
                "before_selected_set": SET_ID_289,
                "after_selected_set": SET_ID_500,
                "before_raw_sha256": _sha_bytes(payloads["pre_activation_selector"]),
                "after_raw_sha256": _sha_bytes(selector_payload),
                "before_canonical_sha256": _sha_json(docs["pre_activation_selector"]),
                "after_canonical_sha256": _sha_json(selector),
            },
        },
        "transition_journal": {
            "canonical_selector_path": CANONICAL_SELECTOR_PATH,
            "canonical_descriptor_path": CANONICAL_DESCRIPTOR_PATH,
            "accepted_repository_states": {
                "pre_activation": {
                    "selector_raw_sha256": PRE_SELECTOR_SHA256,
                    "descriptor_raw_sha256": PRE_DESCRIPTOR_SHA256,
                },
                "applied": {
                    "selector_raw_sha256": _sha_bytes(selector_payload),
                    "descriptor_raw_sha256": _sha_bytes(descriptor_payload),
                },
            },
            "partial_or_unknown_state": "rejected",
            "atomic_pair_transition_required": True,
            "observed_state_in_generated_artifacts": False,
        },
        "authoritative_isolated_validation": report,
        "candidate_boundary": {
            "candidate_count": 211,
            "runtime_evidence_count": 0,
            "executor_ready_count": 0,
            "promotable_count": 0,
        },
        "fixed_legacy_files": {
            "changed_paths": [],
            "unchanged_raw_sha256_by_path": dict(sorted(legacy_paths.items())),
        },
        "rollback": {
            "strategy": "restore_selector_and_validation_only_descriptor",
            "live_apply_authorized": False,
            "restore_selected_set": SET_ID_289,
            "restore_selector_raw_sha256": _sha_bytes(
                payloads["pre_activation_selector"]
            ),
            "restore_descriptor_raw_sha256": _sha_bytes(
                payloads["pre_activation_descriptor_500"]
            ),
            "partial_activation_forbidden": True,
        },
        "artifacts": {
            DESCRIPTOR_OUTPUT.name: {
                "path": str(DESCRIPTOR_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(descriptor_payload),
            },
            SELECTOR_OUTPUT.name: {
                "path": str(SELECTOR_OUTPUT.relative_to(REPO_ROOT)),
                "raw_sha256": _sha_bytes(selector_payload),
            },
        },
        "execution_boundary": {
            "id": "canonical-transition-outside-package",
            "detail": "This package validates but never performs the canonical selector/descriptor pair transition; observed repository state is reported only by the CLI.",
        },
    }
    receipt["activation_payload_sha256"] = _sha_json(receipt)
    receipt_schema = _exact_schema(receipt)
    outputs = {
        DESCRIPTOR_OUTPUT: descriptor_payload,
        SELECTOR_OUTPUT: selector_payload,
        RECEIPT_OUTPUT: _encoded(receipt),
        RECEIPT_SCHEMA_OUTPUT: _encoded(receipt_schema),
    }
    return receipt, receipt_schema, outputs, observed_state


def validate_activation(
    receipt: dict[str, Any], schema: dict[str, Any], outputs: dict[Path, bytes]
) -> None:
    _validate(receipt, schema, "activation receipt")
    payload = dict(receipt)
    observed = payload.pop("activation_payload_sha256")
    if observed != _sha_json(payload):
        raise ActivationError("activation payload hash differs")
    for path in (DESCRIPTOR_OUTPUT, SELECTOR_OUTPUT):
        artifact = receipt["artifacts"].get(path.name)
        if artifact is None or artifact["raw_sha256"] != _sha_bytes(outputs[path]):
            raise ActivationError(f"artifact binding differs: {path.name}")


def _atomic_write(path: Path, payload: bytes) -> None:
    allowed = {
        DESCRIPTOR_OUTPUT.name,
        SELECTOR_OUTPUT.name,
        RECEIPT_OUTPUT.name,
        RECEIPT_SCHEMA_OUTPUT.name,
    }
    if (
        path.parent.resolve(strict=True) != PACKAGE.resolve(strict=True)
        or path.name not in allowed
        or path.parent.is_symlink()
        or path.is_symlink()
        or (path.exists() and not path.is_file())
    ):
        raise ActivationError(f"unsafe package output: {path}")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
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
        receipt, schema, outputs, observed_state = compile_activation()
        validate_activation(receipt, schema, outputs)
        print(f"OBSERVED canonical control state: {observed_state}")
        if args.write:
            for path, payload in outputs.items():
                _atomic_write(path, payload)
                print(f"WROTE: {path.relative_to(REPO_ROOT)}")
            return 0
        expected = {
            DESCRIPTOR_OUTPUT: EXPECTED["descriptor"],
            SELECTOR_OUTPUT: EXPECTED["selector"],
            RECEIPT_OUTPUT: EXPECTED["receipt"],
            RECEIPT_SCHEMA_OUTPUT: EXPECTED["receipt_schema"],
        }
        for path, payload in outputs.items():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ActivationError(f"checked output differs: {path.name}")
            if expected[path] != "PENDING" and _sha_bytes(payload) != expected[path]:
                raise ActivationError(f"checked output hash differs: {path.name}")
        if (
            EXPECTED["receipt_payload"] != "PENDING"
            and receipt["activation_payload_sha256"] != EXPECTED["receipt_payload"]
        ):
            raise ActivationError("checked receipt payload differs")
        print(
            "PASS: isolated Metadata-500 live-ready activation; default=500, capabilities=500, oracles=500, candidate promotion=0"
        )
        return 0
    except (
        ActivationError,
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
