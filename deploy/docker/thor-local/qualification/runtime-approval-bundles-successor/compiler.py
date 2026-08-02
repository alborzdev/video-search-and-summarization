#!/usr/bin/env python3
"""Derive and check the inert 16-bundle Thor approval contract."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "contract.schema.json"
MAX_JSON_BYTES = 8_000_000

PREDECESSOR_DIR = "deploy/docker/thor-local/qualification/runtime-approval-bundles"
CANDIDATE_DIR = (
    "deploy/docker/thor-local/qualification/candidate-approval-mapping-successor"
)
ORACLE_DIR = "deploy/docker/thor-local/qualification/candidate-oracle-adapter"
THOR_LOCAL_PATH = "deploy/docker/scripts/thor-local.sh"
FIREWALL_CAPABILITY_ID = (
    "manifest-entry.offline-security.05-physical-interface-firewall"
)

EXPECTED_SOURCE_LOCKS = {
    f"{PREDECESSOR_DIR}/contract.json": (
        "8bfa16650574de7ac1906da4eab048a30680f4094dd62cbea0cd5319b9d24e4f"
    ),
    f"{PREDECESSOR_DIR}/contract.schema.json": (
        "400b3b8720cd9332c069cc2d5d14aa54722680a4493ccfabef8701db5e98d36e"
    ),
    f"{PREDECESSOR_DIR}/compiler.py": (
        "e196d99fbd48b24c98efb01a02869b8ad5635828c180dbf6d1aa9e0d78697aab"
    ),
    f"{CANDIDATE_DIR}/mapping.json": (
        "4bb8f3a5fba5e201b72e1f1a0f4218bff4b9a999a836c192fca44ca7e35d9cf9"
    ),
    f"{CANDIDATE_DIR}/mapping.schema.json": (
        "09f8610cb7f9cc1d060202f5939b7e451fd78b92f58d80d098939e5ca05b518e"
    ),
    f"{CANDIDATE_DIR}/compiler.py": (
        "7588e8ae49670ad8c0bdf74ad3744d1da510059d07f5b09258e0835474e79fcf"
    ),
    f"{ORACLE_DIR}/adapter.json": (
        "6e77635625a1f6b4b27dfcdc9aa5a0e695d6656adad041604f2b96fa2ac17235"
    ),
    f"{ORACLE_DIR}/adapter.schema.json": (
        "959727de4d57884d67202847cd968e73fd792d1811356755c197a2e34403cbbb"
    ),
    f"{ORACLE_DIR}/compiler.py": (
        "f58f82b18b49a527d0098ffd7c3c7313968fe90928137f5e82cd0adce99b505f"
    ),
    THOR_LOCAL_PATH: (
        "2b67c0b0ee25582ef5acd45ddf12dc02279700ffad065299e6577082fd189df5"
    ),
}

EXPECTED_PACKAGE_HASHES = {
    "contract.json": "74ba837f9e87923ddd48c635a067aeca9929bbf7cd9b3cff5f26157560aa3c0e",
    "contract.schema.json": "67e052501707a2b12c0bd43c055b5cce41367772ff5c263f8a5b3024592f126b",
}

INSPECTION_ID = "physical-interface-firewall-read-only-inspection"
CONFIGURATION_ID = "physical-interface-firewall-configuration"

EXTENSION_BUNDLES = [
    {
        "id": INSPECTION_ID,
        "title": "Physical-interface firewall read-only inspection",
        "approval_placeholder": (
            "<APPROVE_ONLY_READ_ONLY_PHYSICAL_INTERFACE_FIREWALL_INSPECTION>"
        ),
        "acknowledgement_token": (
            "I_ACCEPT_READ_ONLY_VSS_PHYSICAL_INTERFACE_FIREWALL_INSPECTION"
        ),
        "depends_on": [],
        "flags": {
            "host_inspection": True,
            "subprocess": True,
            "network": False,
            "docker": False,
            "writes": False,
            "downloads": False,
            "credentials": False,
            "lifecycle": False,
            "destructive": False,
        },
        "required_inputs": [
            "separately supplied exact read-only inspection acknowledgement token",
            "reviewed bounded list of named physical interfaces and protected VSS ports",
            "future read-only collector with a strict evidence receipt schema",
        ],
        "current_blockers": [
            "the placeholder and token in this contract grant no approval",
            "no firewall-specific read-only collector or receipt is implemented here",
            "no physical-interface firewall host evidence has been collected",
        ],
        "cleanup": "no cleanup is authorized because this bundle is read-only",
        "rollback": "no rollback is authorized because this bundle cannot mutate state",
    },
    {
        "id": CONFIGURATION_ID,
        "title": "Physical-interface firewall exact transaction configuration",
        "approval_placeholder": (
            "<APPROVE_ONLY_EXACT_PHYSICAL_INTERFACE_FIREWALL_TRANSACTION>"
        ),
        "acknowledgement_token": (
            "I_AUTHORIZE_VSS_PHYSICAL_INTERFACE_FIREWALL_APPLY_AND_EXACT_OWNED_ROLLBACK"
        ),
        "recovery_acknowledgement_token": (
            "I_AUTHORIZE_VSS_PHYSICAL_INTERFACE_FIREWALL_FAILURE_RECOVERY"
        ),
        "depends_on": [INSPECTION_ID],
        "flags": {
            "host_inspection": True,
            "subprocess": True,
            "network": False,
            "docker": False,
            "writes": True,
            "downloads": False,
            "credentials": False,
            "lifecycle": True,
            "destructive": True,
        },
        "required_inputs": [
            "separately supplied exact configuration acknowledgement token",
            "separately supplied exact failure-recovery acknowledgement token",
            "reviewed read-only inspection receipt for the exact target state",
            "future transaction executor and strict before-action and after-action receipt schema",
            "exact owned target table identity and lossless prior-state restoration plan",
        ],
        "current_blockers": [
            "the placeholder and both tokens in this contract grant no approval",
            "the existing script deletes a prior product table before replacement and does not preserve it for lossless rollback",
            "the existing failure path removes the table rather than restoring exact prior state",
            "a reviewed bounded transaction executor and strict receipt schema do not exist",
        ],
        "cleanup": (
            "a future executor may remove only transaction-owned state after exact "
            "pre-state and ownership verification"
        ),
        "rollback": (
            "a future executor must restore the exact captured prior table state; "
            "deletion-only rollback is insufficient"
        ),
    },
]


class SuccessorError(RuntimeError):
    """The checked contract, its sources, or its inert boundary drifted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return _sha256(payload)


def _strict_json(data: bytes, label: str) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise SuccessorError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SuccessorError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                SuccessorError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except SuccessorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise SuccessorError(f"JSON root must be an object: {label}")
    return value


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SuccessorError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise SuccessorError(f"symlinked repository path: {relative}")
    try:
        resolved = (REPO_ROOT / path).resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise SuccessorError(
            f"repository source escaped or is absent: {relative}"
        ) from exc
    if not resolved.is_file():
        raise SuccessorError(f"repository source is not a file: {relative}")
    return resolved


def _package_file(name: str) -> Path:
    path = HERE / name
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise SuccessorError(f"missing package file: {name}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SuccessorError(f"package file must be a regular non-symlink: {name}")
    return path


def _validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SuccessorError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(item) for item in first.absolute_path)
        raise SuccessorError(f"{label} schema violation at {location}: {first.message}")


def _checked_source_bytes() -> dict[str, bytes]:
    checked: dict[str, bytes] = {}
    for path, expected in EXPECTED_SOURCE_LOCKS.items():
        data = _repo_file(path).read_bytes()
        if _sha256(data) != expected:
            raise SuccessorError(f"source lock mismatch: {path}")
        checked[path] = data
    return checked


def _load_and_validate_json_pair(
    checked: dict[str, bytes], artifact_path: str, schema_path: str, label: str
) -> dict[str, Any]:
    artifact = _strict_json(checked[artifact_path], artifact_path)
    schema = _strict_json(checked[schema_path], schema_path)
    _validate_schema(artifact, schema, label)
    return artifact


def _validate_bound_sources(checked: dict[str, bytes]) -> tuple[dict[str, Any], ...]:
    predecessor = _load_and_validate_json_pair(
        checked,
        f"{PREDECESSOR_DIR}/contract.json",
        f"{PREDECESSOR_DIR}/contract.schema.json",
        "predecessor contract",
    )
    if len(predecessor["bundles"]) != 14:
        raise SuccessorError("predecessor must contain the exact 14-bundle denominator")

    mapping = _load_and_validate_json_pair(
        checked,
        f"{CANDIDATE_DIR}/mapping.json",
        f"{CANDIDATE_DIR}/mapping.schema.json",
        "candidate approval mapping",
    )
    matching_mappings = [
        row
        for row in mapping["mappings"]
        if row["capability_id"] == FIREWALL_CAPABILITY_ID
    ]
    if len(matching_mappings) != 1:
        raise SuccessorError("exact firewall candidate mapping denominator drift")
    candidate = matching_mappings[0]
    if (
        candidate["mapping_state"] != "unmapped_scope_gap"
        or candidate["reason_code"]
        != "physical_interface_firewall_has_no_generic_bundle"
        or candidate["approval_state"] != "no_receipt_not_admitted_not_executable"
        or candidate["leaf_bundle_id"] is not None
        or candidate["suggested_bundle_id"] is not None
        or candidate["warehouse_sample_bundle"] is not False
    ):
        raise SuccessorError("firewall candidate approval boundary drift")

    oracle = _load_and_validate_json_pair(
        checked,
        f"{ORACLE_DIR}/adapter.json",
        f"{ORACLE_DIR}/adapter.schema.json",
        "candidate oracle adapter",
    )
    adapter = oracle["candidate_adapters_by_capability_id"].get(FIREWALL_CAPABILITY_ID)
    if not isinstance(adapter, dict):
        raise SuccessorError("exact firewall oracle adapter is absent")
    if (
        adapter["current_state"] != "open_unexecuted"
        or adapter["can_promote_runtime_state"] is not False
        or adapter["runtime_state"] != "not_qualified"
        or adapter["implementation_surfaces"] != [THOR_LOCAL_PATH]
        or adapter["execution_bounds"]["executor"] is not None
        or adapter["cleanup"]["executor"] is not None
        or adapter["evidence"] != []
    ):
        raise SuccessorError("firewall candidate oracle boundary drift")

    script = checked[THOR_LOCAL_PATH].decode("utf-8")
    required_legacy_fragments = (
        "firewall-apply)",
        "sudo nft list table inet cti_vss",
        "sudo nft delete table inet cti_vss",
        "Firewall readiness check failed",
        "firewall-remove)",
    )
    if any(fragment not in script for fragment in required_legacy_fragments):
        raise SuccessorError("legacy firewall behavior audit premise drift")
    return predecessor, mapping, oracle


def _derive_contract() -> dict[str, Any]:
    checked = _checked_source_bytes()
    predecessor, mapping, oracle = _validate_bound_sources(checked)
    inherited = copy.deepcopy(predecessor["bundles"])
    result = {
        "schema_version": 1,
        "contract_id": "vss-3.2.1-thor-runtime-approval-bundles-successor",
        "mode": "inert_nonexecuting_successor_approval_contract",
        "predecessor": {
            "contract_path": f"{PREDECESSOR_DIR}/contract.json",
            "contract_sha256": EXPECTED_SOURCE_LOCKS[
                f"{PREDECESSOR_DIR}/contract.json"
            ],
            "schema_sha256": EXPECTED_SOURCE_LOCKS[
                f"{PREDECESSOR_DIR}/contract.schema.json"
            ],
            "compiler_sha256": EXPECTED_SOURCE_LOCKS[f"{PREDECESSOR_DIR}/compiler.py"],
            "inherited_bundle_count": 14,
            "inherited_prefix_canonical_sha256": _canonical_sha256(inherited),
        },
        "default_policy": copy.deepcopy(predecessor["default_policy"]),
        "approval_policy": copy.deepcopy(predecessor["approval_policy"]),
        "audio_dependency_boundary": copy.deepcopy(
            predecessor["audio_dependency_boundary"]
        ),
        "download_review": copy.deepcopy(predecessor["download_review"]),
        "candidate_binding": {
            "capability_id": FIREWALL_CAPABILITY_ID,
            "candidate_mapping_sha256": EXPECTED_SOURCE_LOCKS[
                f"{CANDIDATE_DIR}/mapping.json"
            ],
            "candidate_mapping_state": "unmapped_scope_gap",
            "oracle_adapter_sha256": EXPECTED_SOURCE_LOCKS[
                f"{ORACLE_DIR}/adapter.json"
            ],
            "oracle_state": "open_unexecuted",
            "implementation_surface": THOR_LOCAL_PATH,
            "implementation_surface_sha256": EXPECTED_SOURCE_LOCKS[THOR_LOCAL_PATH],
            "mapping_update_required_before_admission": True,
            "warehouse_sample_bundle": "excluded",
        },
        "successor_policy": {
            "approval_inheritance": False,
            "placeholder_is_not_approval": True,
            "acknowledgement_token_is_not_approval_until_separately_supplied": True,
            "recovery_token_is_not_configuration_authorization": True,
            "dependency_receipt_is_not_dependent_approval": True,
            "compiler_can_execute_actions": False,
            "mutation_commands_published": False,
        },
        "firewall_transaction_boundary": {
            "existing_thor_local_apply_remove_authorization_safe": False,
            "prior_table_deleted_before_replacement": True,
            "prior_table_preserved_for_exact_rollback": False,
            "failure_path_restores_exact_prior_state": False,
            "configuration_state": (
                "blocked_pending_future_transaction_executor_and_receipt_schema"
            ),
            "transaction_executor_implemented": False,
            "receipt_schema_implemented": False,
            "authorized_mutation_commands_published": False,
        },
        "authorization_state": {
            "approval_count": 0,
            "receipt_count": 0,
            "admitted_bundle_count": 0,
            "executable_bundle_count": 0,
            "runtime_evidence_count": 0,
        },
        "bundle_count": 16,
        "bundles": inherited + copy.deepcopy(EXTENSION_BUNDLES),
        "source_locks": [
            {"path": path, "sha256": digest}
            for path, digest in EXPECTED_SOURCE_LOCKS.items()
        ],
        "boundary": (
            "contract_only_no_approval_receipt_admission_execution_or_host_evidence"
        ),
    }
    schema = _strict_json(
        _package_file("contract.schema.json").read_bytes(), str(SCHEMA_PATH)
    )
    _validate_schema(result, schema, "successor contract")
    _validate_semantics(result, predecessor, mapping, oracle)
    return result


def _validate_semantics(
    contract: dict[str, Any],
    predecessor: dict[str, Any],
    mapping: dict[str, Any],
    oracle: dict[str, Any],
) -> None:
    bundles = contract["bundles"]
    if bundles[:14] != predecessor["bundles"]:
        raise SuccessorError("inherited 14-bundle prefix drift")
    if bundles[14:] != EXTENSION_BUNDLES:
        raise SuccessorError("exact firewall extension bundle order or content drift")
    if contract["bundle_count"] != len(bundles) or len(bundles) != 16:
        raise SuccessorError("exact 16-bundle denominator drift")
    ids = [bundle["id"] for bundle in bundles]
    if len(set(ids)) != 16 or ids[-2:] != [INSPECTION_ID, CONFIGURATION_ID]:
        raise SuccessorError("bundle IDs must be exact, unique, and ordered")
    placeholders = [bundle["approval_placeholder"] for bundle in bundles]
    if len(set(placeholders)) != 16:
        raise SuccessorError("approval placeholders must be unique")
    tokens = [
        token
        for bundle in bundles
        for key in ("acknowledgement_token", "recovery_acknowledgement_token")
        if (token := bundle.get(key)) is not None
    ]
    if len(tokens) != len(set(tokens)):
        raise SuccessorError("acknowledgement and recovery tokens must be unique")
    positions = {bundle_id: index for index, bundle_id in enumerate(ids)}
    for bundle in bundles:
        if len(bundle["depends_on"]) != len(set(bundle["depends_on"])):
            raise SuccessorError(f"duplicate dependency: {bundle['id']}")
        for dependency in bundle["depends_on"]:
            if (
                dependency not in positions
                or positions[dependency] >= positions[bundle["id"]]
            ):
                raise SuccessorError(f"dependency DAG/order drift: {bundle['id']}")
    inspection, configuration = bundles[-2:]
    if inspection["depends_on"] != [] or configuration["depends_on"] != [INSPECTION_ID]:
        raise SuccessorError("firewall dependency boundary drift")
    expected_inspection_flags = {
        key: key in {"host_inspection", "subprocess"} for key in inspection["flags"]
    }
    if inspection["flags"] != expected_inspection_flags:
        raise SuccessorError("inspection flags drift")
    expected_configuration_flags = {
        key: key
        in {"host_inspection", "subprocess", "writes", "lifecycle", "destructive"}
        for key in configuration["flags"]
    }
    if configuration["flags"] != expected_configuration_flags:
        raise SuccessorError("configuration flags drift")
    if any(
        key in bundle
        for bundle in bundles[-2:]
        for key in ("authorized_command", "action_command", "recovery_command")
    ):
        raise SuccessorError("firewall bundles must publish no action command")
    extension_text = json.dumps(bundles[-2:], sort_keys=True)
    if any(
        fragment in extension_text
        for fragment in ("sudo nft", "firewall-apply", "firewall-remove")
    ):
        raise SuccessorError("unsafe legacy command leaked into successor bundles")
    if any(contract["authorization_state"].values()):
        raise SuccessorError(
            "authorization, receipt, admission, and evidence counts must be zero"
        )
    if contract["default_policy"]["warehouse_sample_bundle"] != "excluded":
        raise SuccessorError("Warehouse sample bundle boundary drift")
    if contract["successor_policy"]["approval_inheritance"] is not False:
        raise SuccessorError("approval inheritance must remain false")
    if contract["successor_policy"]["mutation_commands_published"] is not False:
        raise SuccessorError("successor cannot publish mutation commands")
    if contract["firewall_transaction_boundary"] != {
        "existing_thor_local_apply_remove_authorization_safe": False,
        "prior_table_deleted_before_replacement": True,
        "prior_table_preserved_for_exact_rollback": False,
        "failure_path_restores_exact_prior_state": False,
        "configuration_state": "blocked_pending_future_transaction_executor_and_receipt_schema",
        "transaction_executor_implemented": False,
        "receipt_schema_implemented": False,
        "authorized_mutation_commands_published": False,
    }:
        raise SuccessorError("firewall transaction safety boundary drift")
    lock_map = {item["path"]: item["sha256"] for item in contract["source_locks"]}
    if lock_map != EXPECTED_SOURCE_LOCKS or len(lock_map) != len(
        contract["source_locks"]
    ):
        raise SuccessorError("exact source lock denominator drift")
    if mapping["mappings"] == [] or oracle["candidate_adapters_by_capability_id"] == {}:
        raise SuccessorError("candidate/oracle identities cannot be empty")


def _load_checked_contract() -> dict[str, Any]:
    for name, expected in EXPECTED_PACKAGE_HASHES.items():
        if expected == "TO_BE_FILLED":
            continue
        if _sha256(_package_file(name).read_bytes()) != expected:
            raise SuccessorError(f"package identity drift: {name}")
    checked = _strict_json(
        _package_file("contract.json").read_bytes(), str(CONTRACT_PATH)
    )
    derived = _derive_contract()
    if checked != derived:
        raise SuccessorError(
            "checked contract artifact differs from deterministic derivation"
        )
    return checked


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="check the inert artifact")
    mode.add_argument(
        "--emit", action="store_true", help="emit the checked inert artifact"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        contract = _load_checked_contract()
    except SuccessorError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    if args.emit:
        print(json.dumps(contract, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "ok": True,
                    "bundle_count": contract["bundle_count"],
                    "contract_sha256": _sha256(CONTRACT_PATH.read_bytes()),
                    "inherited_bundle_count": 14,
                    "extension_bundle_count": 2,
                    **contract["authorization_state"],
                    "warehouse_sample_bundle": "excluded",
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
