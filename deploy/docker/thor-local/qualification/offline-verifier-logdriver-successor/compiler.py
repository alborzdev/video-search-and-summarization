#!/usr/bin/env python3
"""Static successor for safe streaming of large offline-verifier archives."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"


class ContractError(RuntimeError):
    pass


def _bytes(relative: str) -> bytes:
    path = REPO_ROOT / relative
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"invalid source path: {relative}")
    return path.read_bytes()


def compile_contract() -> dict[str, object]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if (
        contract.get("schema_version") != 1
        or contract.get("approval_scope_changed") is not False
        or contract.get("predecessor_bundle_count") != 16
        or contract.get("warehouse_sample_bundle") != "excluded"
        or contract.get("runtime_activity_performed") is not False
    ):
        raise ContractError("contract boundary mismatch")

    seen: set[str] = set()
    for lock in contract.get("source_locks", []):
        if set(lock) != {"path", "sha256"} or lock["path"] in seen:
            raise ContractError("invalid or duplicate source lock")
        seen.add(lock["path"])
        actual = hashlib.sha256(_bytes(lock["path"])).hexdigest()
        if actual != lock["sha256"]:
            raise ContractError(f"source lock mismatch: {lock['path']}")

    predecessor = json.loads(
        _bytes(
            "deploy/docker/thor-local/qualification/"
            "runtime-approval-bundles-rebase-successor/contract.json"
        ).decode("utf-8")
    )
    predecessor_locks = {
        row["path"]: row["sha256"] for row in predecessor.get("source_locks", [])
    }
    if predecessor_locks.get("deploy/docker/scripts/thor-local.sh") != contract.get(
        "predecessor_live_source_sha256"
    ):
        raise ContractError("predecessor live-source identity mismatch")

    source = _bytes("deploy/docker/scripts/thor-local.sh").decode("utf-8")
    match = re.search(
        r"^stream_embedding_volume_tree\(\) \{\n(?P<body>.*?)^\}\n",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ContractError("streaming verifier function missing")
    body = match.group("body")
    required = [
        "docker run --rm --pull never --network none --read-only --log-driver none",
        "--cap-drop ALL --security-opt no-new-privileges:true",
        "readonly,volume-nocopy",
        '"${image}" -C /artifact -cf - "${archive_root}"',
    ]
    if any(item not in body for item in required) or body.count("--log-driver none") != 1:
        raise ContractError("safe streaming helper contract mismatch")

    for test_path in (
        "deploy/docker/test-scripts/test-dev-profile.sh",
        "deploy/docker/test-scripts/test-thor-local-security-models.sh",
    ):
        if "--log-driver none" not in _bytes(test_path).decode("utf-8"):
            raise ContractError(f"missing regression assertion: {test_path}")

    return {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "status": "static_safety_successor_verified",
        "predecessor_bundle_count": 16,
        "approval_scope_changed": False,
        "runtime_activity_performed": False,
        "warehouse_sample_bundle": "excluded",
        "log_driver": "none",
        "source_locks_verified": len(seen),
    }


if __name__ == "__main__":
    print(json.dumps(compile_contract(), indent=2, sort_keys=True))
