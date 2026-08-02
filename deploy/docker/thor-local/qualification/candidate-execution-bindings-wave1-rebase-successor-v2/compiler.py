#!/usr/bin/env python3
"""Fail-closed compiler for a static qualification source-rebase successor."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[4]


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_file(relative: str) -> Path:
    path = (REPO_ROOT / relative).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"path escapes repository: {relative}") from exc
    if not path.is_file():
        raise ValueError(f"locked file is missing: {relative}")
    return path


def _pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw_part in pointer.strip("/").split("/") if pointer != "/" else []:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _check_hash_entries(manifest: dict[str, Any], field: str) -> None:
    entries = manifest.get(field, [])
    paths = [entry.get("path") for entry in entries]
    if not entries or len(paths) != len(set(paths)):
        raise ValueError(f"{field} must be nonempty with unique paths")
    for entry in entries:
        expected = entry.get("raw_sha256")
        actual = _sha256(_repo_file(entry["path"]))
        if actual != expected:
            raise ValueError(
                f"hash mismatch for {entry['path']}: expected {expected}, got {actual}"
            )


def _check_policy(manifest: dict[str, Any]) -> None:
    if manifest.get("mode") != "static_source_rebase_only_no_execution":
        raise ValueError("mode must remain static and non-executing")
    policy = manifest.get("policy", {})
    for key in (
        "runtime_evidence_created",
        "runtime_activity_performed",
        "candidate_admitted",
        "candidate_promoted",
        "historical_executor_invoked",
    ):
        if policy.get(key) is not False:
            raise ValueError(f"policy.{key} must be false")
    if policy.get("warehouse_sample_bundle") != "excluded":
        raise ValueError("Warehouse must remain excluded")
    blockers = " ".join(manifest.get("retained_blockers", [])).lower()
    for token in ("runtime", "cleanup", "admission"):
        if token not in blockers:
            raise ValueError(f"retained blockers must explicitly include {token}")


def _check_order_locks(manifest: dict[str, Any]) -> None:
    locks = manifest.get("order_locks", [])
    if not locks:
        raise ValueError("at least one semantic order lock is required")
    for lock in locks:
        document = json.loads(_repo_file(lock["path"]).read_text())
        values = _pointer(document, lock["pointer"])
        if not isinstance(values, list):
            raise ValueError(f"order pointer is not a list: {lock['pointer']}")
        identity_field = lock.get("identity_field")
        identities = [
            item if identity_field is None else item[identity_field] for item in values
        ]
        excluded = [text.lower() for text in lock.get("exclude_substrings", [])]
        if excluded:
            identities = [
                identity
                for identity in identities
                if not any(text in str(identity).lower() for text in excluded)
            ]
        actual = hashlib.sha256(_canonical(identities)).hexdigest()
        if actual != lock.get("ordered_identities_sha256"):
            raise ValueError(f"semantic order drift for {lock['path']} {lock['pointer']}")
        if len(identities) != lock.get("count"):
            raise ValueError(f"semantic count drift for {lock['path']} {lock['pointer']}")


def _check_facts(manifest: dict[str, Any]) -> None:
    for fact in manifest.get("facts", []):
        document = json.loads(_repo_file(fact["path"]).read_text())
        actual = _pointer(document, fact["pointer"])
        if actual != fact["equals"]:
            raise ValueError(
                f"fact drift for {fact['path']} {fact['pointer']}: {actual!r}"
            )


def check(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    required = {
        "schema_version",
        "package_id",
        "mode",
        "predecessors",
        "source_overrides",
        "manifest_locks",
        "order_locks",
        "facts",
        "constraints",
        "policy",
        "retained_blockers",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"manifest missing fields: {missing}")
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    _check_policy(manifest)
    for field in ("predecessors", "source_overrides", "manifest_locks"):
        _check_hash_entries(manifest, field)
    expected_count = manifest["constraints"].get("source_override_count")
    if len(manifest["source_overrides"]) != expected_count:
        raise ValueError("source override count drift")
    for entry in manifest["source_overrides"]:
        if "warehouse" in entry["path"].lower():
            raise ValueError("Warehouse source override is prohibited")
    _check_order_locks(manifest)
    _check_facts(manifest)
    return {
        "package_id": manifest["package_id"],
        "predecessor_locks": len(manifest["predecessors"]),
        "source_overrides": len(manifest["source_overrides"]),
        "manifest_locks": len(manifest["manifest_locks"]),
        "order_locks": len(manifest["order_locks"]),
        "runtime_evidence_created": False,
        "candidate_admitted": False,
        "candidate_promoted": False,
        "warehouse_sample_bundle": "excluded",
        "status": "static_rebase_contract_valid",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--manifest", type=Path, default=PACKAGE_DIR / "rebase.json")
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.manifest.resolve()), sort_keys=True))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
