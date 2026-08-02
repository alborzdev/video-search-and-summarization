#!/usr/bin/env python3
"""Surgically bind the current Alerts manifest into live parity records."""

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

OLD_ALERTS_SHA256 = "0137b325a56258df582529ae8391db4f631a2f9ef7639f698134d31a66b4621b"
NEW_ALERTS_SHA256 = "b4604b621376c6e356003027678f962e7dc39193f75347abaeab0eaa153388f1"

PREDECESSOR_RAW_SHA256 = {
    "deploy/docker/thor-local/parity/official-capabilities.json": "d1a047345a309d675f692756fc2d9b56159c53840b6328264bb3cefb07f0cce6",
    "deploy/docker/thor-local/parity/capability-oracles.json": "4625c8efb38df757ed90483826df9064717cf131f52d7500ef8eec39510e0804",
    "deploy/docker/thor-local/parity/manifest.json": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    "deploy/docker/thor-local/qualification/acceptance_inventory.json": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
}
STATIC_INPUTS = {
    "deploy/docker/thor-local/qualification/api_inventory.json": "17d3f26a950b142c72e5d5003ac0429ac56f552247ca24458b05c964bf0edb6d",
    "deploy/docker/thor-local/qualification/expected/alerts.json": NEW_ALERTS_SHA256,
    "services/alert/openapi.json": "d7336051ddbbb368d6376bbe0a0d71414b2738a7e1899321eddb4d24dcd95881",
}
TARGETS = {
    "deploy/docker/thor-local/parity/official-capabilities.json": {
        "path": LEDGER,
        "region_start": b'      "id": "api.core.alerts-19",',
        "region_end": b'      "id": "api.core.vst-sensor-28",',
        "replacements": [
            (OLD_ALERTS_SHA256.encode(), NEW_ALERTS_SHA256.encode(), 1),
            (b'"operation_count": 19', b'"operation_count": 21', 1),
        ],
        "replacement_count": 2,
        "semantic_pointers": [
            "/capabilities/118/contract/expected_manifest_sha256",
            "/capabilities/118/contract/operation_count",
        ],
    },
    "deploy/docker/thor-local/parity/capability-oracles.json": {
        "path": ORACLES,
        "region_start": (
            b'    {\n      "capability_id": "api.core.alerts-19",\n'
            b'      "oracle_id": "oracle.api.core.alerts-19",'
        ),
        "region_end": (
            b'    {\n      "capability_id": "api.core.vst-sensor-28",\n'
            b'      "oracle_id": "oracle.api.core.vst-sensor-28",'
        ),
        "replacements": [
            (OLD_ALERTS_SHA256.encode(), NEW_ALERTS_SHA256.encode(), 3),
            (b'"operation_count": 19', b'"operation_count": 21', 2),
            (b'"expected": 19', b'"expected": 21', 1),
            (b'"max_requests": 77', b'"max_requests": 85', 1),
            (b'"units": 19', b'"units": 21', 1),
            (
                b'"calculated_max_requests": 77',
                b'"calculated_max_requests": 85',
                1,
            ),
            (b'"max_actions": 77', b'"max_actions": 85', 1),
        ],
        "replacement_count": 10,
        "semantic_pointers": [
            "/oracles/118/assertions/2/expected",
            "/oracles/118/assertions/4/expected",
            "/oracles/118/execution_bounds/max_actions",
            "/oracles/118/execution_bounds/max_requests",
            "/oracles/118/execution_bounds/workload/calculated_max_requests",
            "/oracles/118/execution_bounds/workload/units",
            "/oracles/118/fixture/input/contract/expected_manifest_sha256",
            "/oracles/118/fixture/input/contract/operation_count",
            "/oracles/118/ledger_binding/contract/expected_manifest_sha256",
            "/oracles/118/ledger_binding/contract/operation_count",
        ],
    },
}


class IntegrationError(ValueError):
    """The predecessor, allowlisted delta, receipt, or live result drifted."""


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
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise IntegrationError(f"duplicate JSON key: {key}")
        value[key] = item
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


def _locked(relative: str, expected: str) -> bytes:
    payload = _regular_bytes(REPO_ROOT / relative)
    if _sha256(payload) != expected:
        raise IntegrationError(f"reviewed input digest drift: {relative}")
    return payload


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


def _replace_in_region(
    payload: bytes, descriptor: dict[str, Any], *, reverse: bool
) -> bytes:
    start_marker = descriptor["region_start"]
    end_marker = descriptor["region_end"]
    if payload.count(start_marker) != 1 or payload.count(end_marker) != 1:
        raise IntegrationError("Alerts record boundary drift")
    start = payload.index(start_marker)
    end = payload.index(end_marker, start + len(start_marker))
    region = payload[start:end]
    for old, new, expected_count in descriptor["replacements"]:
        source, target = (new, old) if reverse else (old, new)
        if region.count(source) != expected_count or region.count(target) != 0:
            raise IntegrationError("Alerts replacement denominator drift")
        region = region.replace(source, target)
    return payload[:start] + region + payload[end:]


def _normalize_predecessor(
    live: bytes, relative: str, descriptor: dict[str, Any]
) -> bytes:
    if _sha256(live) == PREDECESSOR_RAW_SHA256[relative]:
        return live
    start_marker = descriptor["region_start"]
    end_marker = descriptor["region_end"]
    if live.count(start_marker) != 1 or live.count(end_marker) != 1:
        raise IntegrationError("Alerts record boundary drift")
    start = live.index(start_marker)
    end = live.index(end_marker, start + len(start_marker))
    region = live[start:end]
    for old, new, expected_count in descriptor["replacements"]:
        old_count = region.count(old)
        new_count = region.count(new)
        if old_count == expected_count and new_count == 0:
            continue
        if new_count == expected_count and old_count == 0:
            region = region.replace(new, old)
            continue
        raise IntegrationError("Alerts mixed replacement state drift")
    return live[:start] + region + live[end:]


def _transition(relative: str) -> tuple[bytes, bytes, dict[str, Any], dict[str, Any]]:
    descriptor = TARGETS[relative]
    live = _regular_bytes(descriptor["path"])
    predecessor = _normalize_predecessor(live, relative, descriptor)
    if _sha256(predecessor) != PREDECESSOR_RAW_SHA256[relative]:
        raise IntegrationError(f"live output does not reverse to predecessor: {relative}")
    successor = _replace_in_region(predecessor, descriptor, reverse=False)
    before = _strict_json_bytes(predecessor, f"{relative} predecessor")
    after = _strict_json_bytes(successor, f"{relative} successor")
    observed = sorted(_leaf_diffs(before, after))
    expected = sorted(descriptor["semantic_pointers"])
    expected_count = descriptor["replacement_count"]
    if observed != expected or len(observed) != expected_count:
        raise IntegrationError(f"semantic diff allowlist drift: {relative}")
    return predecessor, successor, before, after


def _validate_boundaries(documents: dict[str, dict[str, Any]]) -> None:
    ledger = documents["deploy/docker/thor-local/parity/official-capabilities.json"]
    oracles = documents["deploy/docker/thor-local/parity/capability-oracles.json"]
    capability = ledger["capabilities"][118]
    oracle = oracles["oracles"][118]
    if capability.get("id") != "api.core.alerts-19":
        raise IntegrationError("Alerts capability identity drift")
    if oracle.get("capability_id") != "api.core.alerts-19":
        raise IntegrationError("Alerts oracle identity drift")
    if capability.get("contract", {}).get("expected_manifest_sha256") != NEW_ALERTS_SHA256:
        raise IntegrationError("Alerts capability did not receive current manifest digest")
    if capability.get("contract", {}).get("operation_count") != 21:
        raise IntegrationError("Alerts capability operation count is not current")
    oracle_contracts = (
        oracle.get("ledger_binding", {}).get("contract", {}),
        oracle.get("fixture", {}).get("input", {}).get("contract", {}),
    )
    if any(contract.get("operation_count") != 21 for contract in oracle_contracts):
        raise IntegrationError("Alerts oracle contract copy is not current")
    bounds = oracle.get("execution_bounds", {})
    workload = bounds.get("workload", {})
    if (
        bounds.get("max_actions") != 85
        or bounds.get("max_requests") != 85
        or workload.get("units") != 21
        or workload.get("calculated_max_requests") != 85
    ):
        raise IntegrationError("Alerts oracle workload bounds are not current")
    if any(row.get("runtime_evidence") for row in oracles.get("oracles", [])):
        raise IntegrationError("runtime evidence addition is forbidden")
    if any(row.get("current_state") == "passed_current" for row in oracles.get("oracles", [])):
        raise IntegrationError("passed_current promotion is forbidden")


def build_expected() -> tuple[dict[str, bytes], dict[str, Any]]:
    for relative, digest in STATIC_INPUTS.items():
        _locked(relative, digest)
    _locked(
        "deploy/docker/thor-local/parity/manifest.json",
        PREDECESSOR_RAW_SHA256["deploy/docker/thor-local/parity/manifest.json"],
    )
    _locked(
        "deploy/docker/thor-local/qualification/acceptance_inventory.json",
        PREDECESSOR_RAW_SHA256[
            "deploy/docker/thor-local/qualification/acceptance_inventory.json"
        ],
    )
    outputs: dict[str, bytes] = {}
    successor_documents: dict[str, dict[str, Any]] = {}
    target_receipts = []
    for relative, descriptor in TARGETS.items():
        predecessor, successor, _before, after = _transition(relative)
        outputs[relative] = successor
        successor_documents[relative] = after
        target_receipts.append(
            {
                "path": relative,
                "predecessor_raw_sha256": _sha256(predecessor),
                "successor_raw_sha256": _sha256(successor),
                "replacement_count": descriptor["replacement_count"],
                "semantic_pointers": descriptor["semantic_pointers"],
            }
        )
    _validate_boundaries(successor_documents)
    receipt_core = {
        "schema_version": 1,
        "integration_id": "alerts-current-contract-successor-2026-08-02",
        "static_inputs": [
            {"path": path, "raw_sha256": digest}
            for path, digest in sorted(STATIC_INPUTS.items())
        ],
        "unchanged_live_aggregates": [
            {
                "path": "deploy/docker/thor-local/parity/manifest.json",
                "raw_sha256": PREDECESSOR_RAW_SHA256[
                    "deploy/docker/thor-local/parity/manifest.json"
                ],
            },
            {
                "path": "deploy/docker/thor-local/qualification/acceptance_inventory.json",
                "raw_sha256": PREDECESSOR_RAW_SHA256[
                    "deploy/docker/thor-local/qualification/acceptance_inventory.json"
                ],
            },
        ],
        "delta": {
            "capability_id": "api.core.alerts-19",
            "old_expected_manifest_sha256": OLD_ALERTS_SHA256,
            "new_expected_manifest_sha256": NEW_ALERTS_SHA256,
            "targets": target_receipts,
            "semantic_leaf_change_count": 12,
        },
        "boundaries": {
            "runtime_evidence_added": False,
            "passed_current_allowed": False,
            "manifest_written": False,
            "acceptance_written": False,
            "network": "forbidden",
            "docker": "forbidden",
            "services": "forbidden",
        },
        "rollback": {
            "command": "integrate_live.py rollback",
            "restores_exact_predecessor_digests": True,
            "target_count": 2,
            "semantic_leaf_change_count": 12,
        },
    }
    receipt = dict(receipt_core)
    receipt["contract_sha256"] = _canonical_sha256(receipt_core)
    receipt["outputs"] = {
        relative: _sha256(payload) for relative, payload in outputs.items()
    }
    receipt["lifecycle"] = "alerts_current_contract_successor_integrated"
    return outputs, receipt


def review() -> dict[str, Any]:
    outputs, receipt = build_expected()
    rows = []
    for relative, payload in outputs.items():
        current = _regular_bytes(REPO_ROOT / relative)
        rows.append(
            {
                "path": relative,
                "current_raw_sha256": _sha256(current),
                "prospective_raw_sha256": _sha256(payload),
                "byte_identical": current == payload,
            }
        )
    current_receipt = _regular_bytes(RECEIPT) if RECEIPT.exists() else None
    expected_receipt = _encoded(receipt)
    rows.append(
        {
            "path": str(RECEIPT.relative_to(REPO_ROOT)),
            "current_raw_sha256": _sha256(current_receipt) if current_receipt else None,
            "prospective_raw_sha256": _sha256(expected_receipt),
            "byte_identical": current_receipt == expected_receipt,
        }
    )
    return {
        "lifecycle": "prospective_alerts_current_contract_successor_reviewed",
        "writes_performed": False,
        "semantic_leaf_change_count": 12,
        "write_targets": rows,
    }


def validate() -> dict[str, Any]:
    outputs, receipt = build_expected()
    for relative, payload in outputs.items():
        if _regular_bytes(REPO_ROOT / relative) != payload:
            raise IntegrationError(f"live successor output drift: {relative}")
    if _regular_bytes(RECEIPT) != _encoded(receipt):
        raise IntegrationError("successor receipt differs from read-only replay")
    return {
        "lifecycle": receipt["lifecycle"],
        "semantic_leaf_change_count": 12,
        "runtime_evidence_records": 0,
        "passed_current_promotions": 0,
    }


def rollback_plan() -> dict[str, Any]:
    outputs, _receipt = build_expected()
    rows = []
    for relative in outputs:
        predecessor, _successor, _before, _after = _transition(relative)
        rows.append(
            {
                "path": relative,
                "rollback_raw_sha256": _sha256(predecessor),
                "matches_locked_predecessor": (
                    _sha256(predecessor) == PREDECESSOR_RAW_SHA256[relative]
                ),
            }
        )
    return {
        "lifecycle": "prospective_alerts_successor_rollback_reviewed",
        "writes_performed": False,
        "semantic_leaf_change_count": 12,
        "targets": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "review",
            "apply",
            "write",
            "validate",
            "rollback-plan",
            "rollback",
            "validate-rollback",
        ),
    )
    args = parser.parse_args()
    try:
        if args.command == "plan":
            outputs, receipt = build_expected()
            print(
                json.dumps(
                    {
                        "lifecycle": "prospective_alerts_current_contract_successor",
                        "semantic_leaf_change_count": 12,
                        "output_raw_sha256": receipt["outputs"],
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
            rows = rollback_plan()["targets"]
            if any(
                _sha256(_regular_bytes(REPO_ROOT / row["path"]))
                != row["rollback_raw_sha256"]
                for row in rows
            ):
                raise IntegrationError("live files do not match rollback state")
            print(json.dumps({"lifecycle": "alerts_successor_rolled_back"}, sort_keys=True))
            return 0
        outputs, receipt = build_expected()
        if args.command == "rollback":
            for relative in outputs:
                predecessor, _successor, _before, _after = _transition(relative)
                (REPO_ROOT / relative).write_bytes(predecessor)
            print(json.dumps({"lifecycle": "alerts_successor_rolled_back"}, sort_keys=True))
            return 0
        for relative, payload in outputs.items():
            (REPO_ROOT / relative).write_bytes(payload)
        RECEIPT.write_bytes(_encoded(receipt))
        print(json.dumps({"lifecycle": receipt["lifecycle"]}, sort_keys=True))
        return 0
    except (IntegrationError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
