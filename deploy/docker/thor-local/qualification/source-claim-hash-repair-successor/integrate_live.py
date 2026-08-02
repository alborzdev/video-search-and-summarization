#!/usr/bin/env python3
"""Repair six stale official source claim-set hashes without changing claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
PARITY = REPO_ROOT / "deploy/docker/thor-local/parity"
QUALIFICATION = REPO_ROOT / "deploy/docker/thor-local/qualification"
LEDGER = PARITY / "official-capabilities.json"
ORACLES = PARITY / "capability-oracles.json"
MANIFEST = PARITY / "manifest.json"
ACCEPTANCE = QUALIFICATION / "acceptance_inventory.json"
RECEIPT = LANE / "live-integration-receipt.json"
RECEIPT_SCHEMA = LANE / "live-integration-receipt.schema.json"

PREDECESSOR_OFFICIAL_SHA256 = (
    "fb1638a82e8bf04b0b07482fc016184c3abc6bc692ca8a11fa94681837953055"
)
FINAL_OFFICIAL_SHA256 = (
    "61c2a4c0bc9d23940d954311f93824dc55c18cfc58caca002162cc1ef6808098"
)
PRESERVED_RAW_SHA256 = {
    "deploy/docker/thor-local/parity/capability-oracles.json": "24214553cbd669eb80efa7b4a602ac52328e00bd43241c839b43b10d05e22e8e",
    "deploy/docker/thor-local/parity/manifest.json": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    "deploy/docker/thor-local/qualification/acceptance_inventory.json": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
}

SOURCE_HASH_TRANSITIONS = (
    {
        "index": 0,
        "source_id": "release-notes-3.2.1",
        "old": "19081de42ba87a582281ea68046a08e98602a14b33579da5d970b9fd2e59bd22",
        "new": "4dd56cbf6453067e5d6515977fd681fdd51a1067823fd91710e777f778ec9de5",
    },
    {
        "index": 17,
        "source_id": "lvs-api-doc-3.2.1",
        "old": "eef97a91cba69f24c4d9f04457dbc7652df07247bc0cdcbd9d7159b2d9a97c8f",
        "new": "03c398b054ce2acf6fcf74fb0f93cb2b61a5d7a946137743696b58943606e065",
    },
    {
        "index": 18,
        "source_id": "lvs-doc-3.2.1",
        "old": "17a2fe3fd627f9d06edc0585e02df7f8244694dab3b5d209c9bc701a3deec99a",
        "new": "dd5748aa7a58bc774ed46f8553709dcfbffddcff8907d265898bf63060b36145",
    },
    {
        "index": 19,
        "source_id": "alerts-api-doc-3.2.1",
        "old": "4a22b631724480354490fbca61aa8e6de63eaeb0cb96cbb59ab689e033c114ec",
        "new": "ab5df280aec7dc38ae64c6873a5378e2104888f1fdbcc0f57bb7649dfeb8c83e",
    },
    {
        "index": 32,
        "source_id": "main-repository-7732edf8",
        "old": "fc36e720d9ab4a684b328a2b234456959932163de93e5d8dd54d162b2fe97089",
        "new": "d0b3c9f0811df7a07f1bf5255d0c86b9ff3e4b530b45424009628ebcc821d65c",
    },
    {
        "index": 77,
        "source_id": "doc.alerts",
        "old": "26c179a55ce9f6e372ea3299ad422b11bdaf94cf87d453014d9cbe634662958e",
        "new": "ffdabea5ad022b1ef87301860138ffe0c3e9532ef1304dfb9ab1bdca4ced4754",
    },
)


class IntegrationError(ValueError):
    """The predecessor, allowlist, derived hashes, or receipt drifted."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    )


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                IntegrationError(f"non-finite JSON value in {label}: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise IntegrationError(f"JSON root is not an object: {label}")
    return value


def _regular_bytes(path: Path) -> bytes:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise IntegrationError(f"not a regular non-symlink file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        return os.read(descriptor, metadata.st_size + 1)
    finally:
        os.close(descriptor)


def _leaf_diffs(before: Any, after: Any, pointer: str = "") -> list[str]:
    if type(before) is not type(after):
        return [pointer]
    if isinstance(before, dict):
        if list(before) != list(after):
            return [pointer]
        result: list[str] = []
        for key in before:
            escaped = key.replace("~", "~0").replace("/", "~1")
            result.extend(_leaf_diffs(before[key], after[key], f"{pointer}/{escaped}"))
        return result
    if isinstance(before, list):
        if len(before) != len(after):
            return [pointer]
        result = []
        for index, (old, new) in enumerate(zip(before, after, strict=True)):
            result.extend(_leaf_diffs(old, new, f"{pointer}/{index}"))
        return result
    return [] if before == after else [pointer]


def _normalize_predecessor(live: bytes) -> bytes:
    if _sha256(live) == PREDECESSOR_OFFICIAL_SHA256:
        return live
    result = live
    for row in SOURCE_HASH_TRANSITIONS:
        old = row["old"].encode()
        new = row["new"].encode()
        old_count = result.count(old)
        new_count = result.count(new)
        if old_count == 1 and new_count == 0:
            continue
        if new_count == 1 and old_count == 0:
            result = result.replace(new, old)
            continue
        raise IntegrationError(f"mixed source-hash state: {row['source_id']}")
    return result


def _transition() -> tuple[bytes, bytes, dict[str, Any], dict[str, Any]]:
    live = _regular_bytes(LEDGER)
    predecessor = _normalize_predecessor(live)
    if _sha256(predecessor) != PREDECESSOR_OFFICIAL_SHA256:
        raise IntegrationError("official ledger does not reverse to locked predecessor")
    successor = predecessor
    for row in SOURCE_HASH_TRANSITIONS:
        old = row["old"].encode()
        new = row["new"].encode()
        if successor.count(old) != 1 or successor.count(new) != 0:
            raise IntegrationError(f"replacement denominator drift: {row['source_id']}")
        successor = successor.replace(old, new)
    if _sha256(successor) != FINAL_OFFICIAL_SHA256:
        raise IntegrationError("official successor digest drift")
    before = _strict_json_bytes(predecessor, "official predecessor")
    after = _strict_json_bytes(successor, "official successor")
    observed = sorted(_leaf_diffs(before, after))
    expected = sorted(
        f"/sources/{row['index']}/claim_set_sha256" for row in SOURCE_HASH_TRANSITIONS
    )
    if observed != expected:
        raise IntegrationError("six-leaf semantic allowlist drift")
    return predecessor, successor, before, after


def _derived_claim_hashes(ledger: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in ledger.get("sources", []):
        source_id = source.get("id")
        claims = []
        for capability in ledger.get("capabilities", []):
            for claim in capability.get("source_claims", []):
                if claim.get("source_id") == source_id:
                    claims.append(
                        {
                            "capability_id": capability["id"],
                            "locator": claim["locator"],
                            "contract": capability["contract"],
                        }
                    )
        canonical = sorted(
            json.dumps(item, sort_keys=True, separators=(",", ":"))
            for item in claims
        )
        result[source_id] = _sha256(
            json.dumps(canonical, separators=(",", ":")).encode()
        )
    return result


def _validate_boundaries(before: dict[str, Any], after: dict[str, Any]) -> None:
    if before.get("capabilities") != after.get("capabilities"):
        raise IntegrationError("capability content change is forbidden")
    if len(after.get("sources", [])) != len(before.get("sources", [])):
        raise IntegrationError("source denominator drift")
    derived = _derived_claim_hashes(after)
    if any(
        derived.get(source.get("id")) != source.get("claim_set_sha256")
        for source in after["sources"]
    ):
        raise IntegrationError("source claim-set hashes are not verifier-derived")
    for row in SOURCE_HASH_TRANSITIONS:
        old_source = before["sources"][row["index"]]
        new_source = after["sources"][row["index"]]
        if old_source.get("id") != row["source_id"] or new_source.get("id") != row["source_id"]:
            raise IntegrationError(f"source index drift: {row['source_id']}")
        stripped_old = dict(old_source)
        stripped_new = dict(new_source)
        stripped_old.pop("claim_set_sha256")
        stripped_new.pop("claim_set_sha256")
        if stripped_old != stripped_new:
            raise IntegrationError(f"source record drift: {row['source_id']}")
    for relative, digest in PRESERVED_RAW_SHA256.items():
        payload = _regular_bytes(REPO_ROOT / relative)
        if _sha256(payload) != digest:
            raise IntegrationError(f"preserved aggregate drift: {relative}")
    oracles = _strict_json_bytes(_regular_bytes(ORACLES), "preserved oracles")
    if any(row.get("evidence") for row in oracles.get("oracles", [])):
        raise IntegrationError("runtime evidence addition is forbidden")
    if any(row.get("current_state") == "passed_current" for row in oracles.get("oracles", [])):
        raise IntegrationError("passed_current promotion is forbidden")
    if oracles.get("policy", {}).get("warehouse_sample_bundle") != (
        "excluded; custom-data fixtures remain in scope"
    ):
        raise IntegrationError("warehouse exclusion drift")


def build_expected() -> tuple[bytes, dict[str, Any]]:
    predecessor, successor, before, after = _transition()
    _validate_boundaries(before, after)
    receipt_core = {
        "schema_version": 1,
        "integration_id": "source-claim-hash-repair-successor-2026-08-02",
        "target": {
            "path": "deploy/docker/thor-local/parity/official-capabilities.json",
            "predecessor_raw_sha256": _sha256(predecessor),
            "successor_raw_sha256": _sha256(successor),
        },
        "changes": [
            {
                "source_index": row["index"],
                "source_id": row["source_id"],
                "old_claim_set_sha256": row["old"],
                "new_claim_set_sha256": row["new"],
                "semantic_pointer": f"/sources/{row['index']}/claim_set_sha256",
            }
            for row in SOURCE_HASH_TRANSITIONS
        ],
        "preserved_aggregates": [
            {"path": relative, "raw_sha256": digest}
            for relative, digest in sorted(PRESERVED_RAW_SHA256.items())
        ],
        "boundaries": {
            "semantic_leaf_change_count": 6,
            "capabilities_changed": False,
            "oracles_written": False,
            "manifest_written": False,
            "acceptance_written": False,
            "runtime_evidence_added": False,
            "passed_current_allowed": False,
            "warehouse_sample_bundle": "excluded",
            "network": "forbidden",
            "docker": "forbidden",
            "services": "forbidden",
        },
        "rollback": {
            "command": "integrate_live.py rollback",
            "restores_exact_predecessor_digest": True,
            "semantic_leaf_change_count": 6,
        },
    }
    receipt = dict(receipt_core)
    receipt["contract_sha256"] = _canonical_sha256(receipt_core)
    receipt["lifecycle"] = "source_claim_hash_repair_successor_integrated"
    return successor, receipt


def review() -> dict[str, Any]:
    successor, receipt = build_expected()
    receipt_bytes = _encoded(receipt)
    current_receipt = _regular_bytes(RECEIPT) if RECEIPT.exists() else None
    return {
        "lifecycle": "prospective_source_claim_hash_repair_successor_reviewed",
        "writes_performed": False,
        "semantic_leaf_change_count": 6,
        "write_targets": [
            {
                "path": str(LEDGER.relative_to(REPO_ROOT)),
                "current_raw_sha256": _sha256(_regular_bytes(LEDGER)),
                "prospective_raw_sha256": _sha256(successor),
                "byte_identical": _regular_bytes(LEDGER) == successor,
            },
            {
                "path": str(RECEIPT.relative_to(REPO_ROOT)),
                "current_raw_sha256": _sha256(current_receipt) if current_receipt else None,
                "prospective_raw_sha256": _sha256(receipt_bytes),
                "byte_identical": current_receipt == receipt_bytes,
            },
        ],
    }


def validate() -> dict[str, Any]:
    successor, receipt = build_expected()
    if _regular_bytes(LEDGER) != successor:
        raise IntegrationError("live official successor output drift")
    if _regular_bytes(RECEIPT) != _encoded(receipt):
        raise IntegrationError("successor receipt differs from read-only replay")
    return {
        "lifecycle": receipt["lifecycle"],
        "semantic_leaf_change_count": 6,
        "capabilities_changed": False,
        "oracles_written": False,
        "runtime_evidence_records": 0,
        "passed_current_promotions": 0,
    }


def rollback_plan() -> dict[str, Any]:
    predecessor, _successor, _before, _after = _transition()
    return {
        "lifecycle": "prospective_source_claim_hash_repair_rollback_reviewed",
        "writes_performed": False,
        "semantic_leaf_change_count": 6,
        "path": str(LEDGER.relative_to(REPO_ROOT)),
        "rollback_raw_sha256": _sha256(predecessor),
        "matches_locked_predecessor": _sha256(predecessor) == PREDECESSOR_OFFICIAL_SHA256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "review",
            "write",
            "apply",
            "validate",
            "rollback-plan",
            "rollback",
            "validate-rollback",
        ),
    )
    args = parser.parse_args()
    try:
        if args.command == "plan":
            successor, _receipt = build_expected()
            print(
                json.dumps(
                    {
                        "lifecycle": "prospective_source_claim_hash_repair_successor",
                        "semantic_leaf_change_count": 6,
                        "predecessor_raw_sha256": PREDECESSOR_OFFICIAL_SHA256,
                        "successor_raw_sha256": _sha256(successor),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "review":
            print(json.dumps(review(), sort_keys=True))
            return 0
        if args.command == "validate":
            print(json.dumps(validate(), sort_keys=True))
            return 0
        if args.command == "rollback-plan":
            print(json.dumps(rollback_plan(), sort_keys=True))
            return 0
        if args.command == "validate-rollback":
            if _sha256(_regular_bytes(LEDGER)) != PREDECESSOR_OFFICIAL_SHA256:
                raise IntegrationError("live file does not match rollback state")
            print(json.dumps({"lifecycle": "source_claim_hash_repair_rolled_back"}, sort_keys=True))
            return 0
        successor, receipt = build_expected()
        if args.command == "rollback":
            predecessor, _successor, _before, _after = _transition()
            LEDGER.write_bytes(predecessor)
            print(json.dumps({"lifecycle": "source_claim_hash_repair_rolled_back"}, sort_keys=True))
            return 0
        LEDGER.write_bytes(successor)
        RECEIPT.write_bytes(_encoded(receipt))
        print(json.dumps({"lifecycle": receipt["lifecycle"]}, sort_keys=True))
        return 0
    except (IntegrationError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
