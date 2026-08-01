#!/usr/bin/env python3
"""Compile authoritative service-binding resolutions without runtime actions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
MAPPING = HERE / "mapping.json"
MAPPING_SCHEMA = HERE / "mapping.schema.json"
PLAN = HERE / "resolution-plan.json"
SCHEMA = HERE / "resolution-plan.schema.json"
LEDGER = "deploy/docker/thor-local/parity/official-capabilities.json"
LEDGER_SHA256 = "32befd108b8e4f3eb10c066c3a28a936b277ff68d2b4940cf9e1ef40107e1873"
SOURCE_LOCK = "deploy/docker/thor-local/parity/source-lock/source-lock.json"
SOURCE_LOCK_SHA256 = "fbf21f64f13dc22328c4a01c79e427042c3112885073dc32bb0ebd6700f0fd07"
EXPECTED_CAPABILITY_IDS = {
    "customization.embedding-reindex-validation",
    "protocol.nvschema.format-selection",
    "protocol.nvschema.json-frame",
    "protocol.nvschema.protobuf-messages",
}
OFFICIAL_DOC_LOCKS = {
    "https://docs.nvidia.com/vss/3.2.1/JSON-Schema.html": "e80b60f3ea2714b333dc6a9c41cce6f88faa4f6087737d2b43a585195c836583",
    "https://docs.nvidia.com/vss/3.2.1/NvSchema.html": "7f3437cca71f7dcbdb85ffa14f50e9bb627ca22d2b558ce2aaf0075d875cd4d4",
    "https://docs.nvidia.com/vss/3.2.1/Protobuf-Schema.html": "735b6d674b498c123ff9d8c30365eef92fec4b741b1f90c95c567522bc90e02a",
    "https://docs.nvidia.com/vss/3.2.1/models/clip-object-embeddings.html": "2d8c1ac181dd1d49c705be3a793703242f5ad0c77223747764791c6b2047dd79",
    "https://docs.nvidia.com/vss/3.2.1/models/cosmos-embed1.html": "75daf59eb3da4bab85784a7167c6857cb724facef528c7ce3c5eef2ed6e1f5e8",
    "https://docs.nvidia.com/vss/3.2.1/models/model-customization.html": "d1d6de0ae5b91545bea03a50b0d8458abcb8e70aa89e654bbdcd221e6662ca47",
}


class ResolutionError(ValueError):
    """The checked service-binding resolution contract drifted."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResolutionError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResolutionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ResolutionError(f"JSON root must be object: {path}")
    return value


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def _pointer(value: Any, pointer: str) -> Any:
    current = value
    if pointer == "":
        return current
    if not pointer.startswith("/"):
        raise ResolutionError(f"invalid JSON pointer: {pointer}")
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            else:
                current = current[token]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ResolutionError(f"unresolved JSON pointer: {pointer}") from exc
    return current


def _check_file(
    repo_root: Path, path: str, digest: str, literals: list[str]
) -> dict[str, Any]:
    absolute = repo_root / path
    try:
        actual = _raw_sha256(absolute)
        text = absolute.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResolutionError(f"missing or unreadable source: {path}") from exc
    if actual != digest:
        raise ResolutionError(
            f"source drift for {path}: expected {digest}, got {actual}"
        )
    for literal in literals:
        if literal not in text:
            raise ResolutionError(f"required literal absent from {path}: {literal!r}")
    return {
        "path": path,
        "raw_sha256": digest,
        "required_literals": copy.deepcopy(literals),
    }


def build_plan(
    repo_root: Path = REPO_ROOT, mapping_path: Path | None = None
) -> dict[str, Any]:
    mapping_file = mapping_path or (repo_root / MAPPING.relative_to(REPO_ROOT))
    mapping = _load(mapping_file)
    mapping_schema = _load(repo_root / MAPPING_SCHEMA.relative_to(REPO_ROOT))
    Draft202012Validator.check_schema(mapping_schema)
    mapping_errors = sorted(
        Draft202012Validator(mapping_schema).iter_errors(mapping),
        key=lambda error: list(error.absolute_path),
    )
    if mapping_errors:
        first = mapping_errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise ResolutionError(
            f"mapping schema validation failed at {where}: {first.message}"
        )
    ledger_path = repo_root / LEDGER
    source_lock_path = repo_root / SOURCE_LOCK
    if _raw_sha256(ledger_path) != LEDGER_SHA256:
        raise ResolutionError("official capability ledger source drift")
    if _raw_sha256(source_lock_path) != SOURCE_LOCK_SHA256:
        raise ResolutionError("official document source-lock drift")
    ledger = _load(ledger_path)
    source_lock = _load(source_lock_path)

    locked_docs = {
        item["url"]: item["sha256"]
        for item in source_lock.get("records", [])
        if item.get("outcome") == "success"
    }
    for url, digest in OFFICIAL_DOC_LOCKS.items():
        if locked_docs.get(url) != digest:
            raise ResolutionError(f"official document byte lock drift: {url}")

    rules = mapping.get("capabilities")
    capabilities = ledger.get("capabilities")
    if not isinstance(rules, list) or not isinstance(capabilities, list):
        raise ResolutionError("mapping or ledger capability array malformed")
    rule_ids = [item.get("capability_id") for item in rules]
    if len(rule_ids) != len(set(rule_ids)) or set(rule_ids) != EXPECTED_CAPABILITY_IDS:
        raise ResolutionError("exact four-capability mapping denominator drift")

    source_bindings: dict[str, dict[str, Any]] = {
        LEDGER: {"path": LEDGER, "raw_sha256": LEDGER_SHA256, "required_literals": []},
        SOURCE_LOCK: {
            "path": SOURCE_LOCK,
            "raw_sha256": SOURCE_LOCK_SHA256,
            "required_literals": [],
        },
        str(mapping_file.relative_to(repo_root)): {
            "path": str(mapping_file.relative_to(repo_root)),
            "raw_sha256": _raw_sha256(mapping_file),
            "required_literals": [],
        },
    }
    resolutions: list[dict[str, Any]] = []
    for rule in rules:
        capability = _pointer(ledger, rule["ledger_pointer"])
        if capability.get("id") != rule["capability_id"]:
            raise ResolutionError(
                f"{rule['capability_id']}: ledger pointer identity drift"
            )
        contract = capability.get("contract")
        if not isinstance(contract, dict):
            raise ResolutionError(f"{rule['capability_id']}: contract malformed")
        for assertion in rule["required_contract_assertions"]:
            actual = _pointer(contract, assertion["json_pointer"])
            if actual != assertion["equals"]:
                raise ResolutionError(
                    f"{rule['capability_id']}: contract assertion drift at "
                    f"{assertion['json_pointer']}"
                )
        forbidden = sorted(set(rule["forbidden_contract_role_keys"]) & set(contract))
        if forbidden:
            raise ResolutionError(
                f"{rule['capability_id']}: authoritative contract now selects roles: {forbidden}"
            )
        evidence: list[dict[str, Any]] = []
        for item in rule["source_evidence"]:
            checked = _check_file(
                repo_root,
                item["path"],
                item["raw_sha256"],
                item["required_literals"],
            )
            previous = source_bindings.get(item["path"])
            if previous is not None:
                if previous["raw_sha256"] != checked["raw_sha256"]:
                    raise ResolutionError(
                        f"inconsistent source binding: {item['path']}"
                    )
                checked_for_index = copy.deepcopy(checked)
                checked_for_index["required_literals"] = sorted(
                    set(previous["required_literals"])
                    | set(checked["required_literals"])
                )
                source_bindings[item["path"]] = checked_for_index
            else:
                source_bindings[item["path"]] = checked
            evidence.append(checked)
        if rule["resolution_state"] != (
            "open_authoritative_contract_does_not_select_unique_runtime_role_set"
        ):
            raise ResolutionError(
                f"{rule['capability_id']}: unsupported resolution state"
            )
        if rule["runtime_service_roles"] != []:
            raise ResolutionError(
                f"{rule['capability_id']}: open binding cannot claim runtime roles"
            )
        resolutions.append(
            {
                "capability_id": rule["capability_id"],
                "ledger_pointer": rule["ledger_pointer"],
                "contract_sha256": _canonical_sha256(contract),
                "source_claims_sha256": _canonical_sha256(capability["source_claims"]),
                "resolution_state": rule["resolution_state"],
                "runtime_service_roles": [],
                "static_support_roles": copy.deepcopy(rule["static_support_roles"]),
                "observed_non_authoritative_roles": copy.deepcopy(
                    rule["observed_non_authoritative_roles"]
                ),
                "proof_code": rule["proof_code"],
                "required_contract_assertions": copy.deepcopy(
                    rule["required_contract_assertions"]
                ),
                "forbidden_contract_role_keys": copy.deepcopy(
                    rule["forbidden_contract_role_keys"]
                ),
                "source_evidence": evidence,
                "runtime_lanes_update_allowed": False,
                "runtime_evidence": [],
            }
        )

    resolutions.sort(key=lambda item: item["capability_id"])
    return {
        "schema_version": 1,
        "plan_id": "thor-vss-service-binding-resolution-four",
        "mode": "static_authoritative_contract_audit",
        "policy": {
            "observed_repository_roles_are_authoritative": False,
            "open_bindings_may_update_runtime_lanes": False,
            "runtime_evidence_created": False,
            "live_parity_artifacts_mutated": False,
        },
        "source_bindings": [source_bindings[path] for path in sorted(source_bindings)],
        "official_document_byte_locks": [
            {"url": url, "sha256": OFFICIAL_DOC_LOCKS[url]}
            for url in sorted(OFFICIAL_DOC_LOCKS)
        ],
        "summary": {
            "target_capabilities": 4,
            "resolved_unique_runtime_role_sets": 0,
            "open_authoritative_ambiguities": 4,
            "runtime_lanes_updates_allowed": 0,
            "runtime_evidence_records": 0,
        },
        "resolutions": resolutions,
    }


def validate_plan(plan: dict[str, Any], repo_root: Path = REPO_ROOT) -> None:
    schema = _load(repo_root / SCHEMA.relative_to(REPO_ROOT))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(plan),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise ResolutionError(f"schema validation failed at {where}: {first.message}")
    if plan != build_plan(repo_root):
        raise ResolutionError("checked plan differs from deterministic compiler output")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        expected = build_plan()
        validate_plan(expected)
        if args.write:
            PLAN.write_bytes(_encoded(expected))
            print(f"WROTE: {PLAN.relative_to(REPO_ROOT)}")
            return 0
        actual = _load(PLAN)
        validate_plan(actual)
        if PLAN.read_bytes() != _encoded(expected):
            raise ResolutionError("checked plan is not canonically encoded")
        print(
            "PASS: four authoritative service-binding audits; "
            "resolved=0, open=4, runtime_updates=0"
        )
        return 0
    except (OSError, ResolutionError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
