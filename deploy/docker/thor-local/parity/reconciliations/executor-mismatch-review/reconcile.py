#!/usr/bin/env python3
"""Apply or verify the two reviewed executor-mismatch ledger records."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True
LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[5]
DESCRIPTOR_PATH = LANE / "reconciliation.json"
DESCRIPTOR_CANONICAL_SHA256 = (
    "e35d56ac52de55a62612c16441141166ba27f2c5323831e4ae6e937fed2a2cd3"
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ReconciliationError(RuntimeError):
    """The descriptor, evidence, baseline, or reconciled ledger is invalid."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReconciliationError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def strict_loads(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"{label}: root must be an object")
    return value


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def canonical_sha(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def raw_sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _repo_file(relative: str, repo_root: Path = REPO_ROOT) -> Path:
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts:
        raise ReconciliationError(f"unsafe repository-relative path: {relative!r}")
    root = repo_root.resolve(strict=True)
    cursor = root
    for part in path.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ReconciliationError(f"repository path contains a symlink: {relative}")
    try:
        mode = cursor.stat(follow_symlinks=False).st_mode
        cursor.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReconciliationError(f"repository path is unavailable: {relative}") from exc
    if not stat.S_ISREG(mode):
        raise ReconciliationError(f"repository path is not a regular file: {relative}")
    return cursor


def load_descriptor(payload: bytes | None = None) -> dict[str, Any]:
    raw = DESCRIPTOR_PATH.read_bytes() if payload is None else payload
    descriptor = strict_loads(raw, "reconciliation descriptor")
    if canonical_sha(descriptor) != DESCRIPTOR_CANONICAL_SHA256:
        raise ReconciliationError("reconciliation descriptor canonical digest drift")
    if descriptor.get("schema_version") != 1:
        raise ReconciliationError("descriptor schema_version must be 1")
    ledger = descriptor.get("ledger")
    records = descriptor.get("records")
    decisions = descriptor.get("decisions")
    evidence = descriptor.get("reviewed_evidence")
    if not isinstance(ledger, dict) or set(ledger) != {
        "path",
        "baseline_raw_sha256",
        "baseline_discrepancy_count",
        "output_raw_sha256",
        "output_discrepancy_count",
    }:
        raise ReconciliationError("descriptor ledger contract is not exact")
    if not all(
        isinstance(ledger.get(key), str) and HEX64.fullmatch(ledger[key])
        for key in ("baseline_raw_sha256", "output_raw_sha256")
    ):
        raise ReconciliationError("descriptor ledger hashes are invalid")
    if (
        not isinstance(records, list)
        or len(records) != 2
        or len({record.get("id") for record in records if isinstance(record, dict)})
        != 2
        or ledger["output_discrepancy_count"]
        != ledger["baseline_discrepancy_count"] + len(records)
    ):
        raise ReconciliationError("descriptor must contain exactly two unique records")
    expected_classes = {
        "official_documentation_to_repository_name_discrepancy",
        "explicit_unqualified_thor_override",
    }
    if (
        not isinstance(decisions, list)
        or {item.get("classification") for item in decisions if isinstance(item, dict)}
        != expected_classes
    ):
        raise ReconciliationError("semantic decision classifications drifted")
    if not isinstance(evidence, list) or not evidence:
        raise ReconciliationError("reviewed evidence must be non-empty")
    for item in evidence:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str)
            or not isinstance(item["sha256"], str)
            or HEX64.fullmatch(item["sha256"]) is None
        ):
            raise ReconciliationError("reviewed evidence record is invalid")
    return descriptor


def verify_evidence(
    descriptor: dict[str, Any], repo_root: Path = REPO_ROOT
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for item in descriptor["reviewed_evidence"]:
        payload = _repo_file(item["path"], repo_root).read_bytes()
        digest = raw_sha(payload)
        if digest != item["sha256"]:
            raise ReconciliationError(f"reviewed evidence drift: {item['path']}")
        observed[item["path"]] = digest
    return observed


def build_bytes(
    baseline_payload: bytes, descriptor: dict[str, Any] | None = None
) -> bytes:
    descriptor = load_descriptor() if descriptor is None else descriptor
    ledger_contract = descriptor["ledger"]
    if raw_sha(baseline_payload) != ledger_contract["baseline_raw_sha256"]:
        raise ReconciliationError("ledger baseline raw digest drift")
    baseline = strict_loads(baseline_payload, "ledger baseline")
    discrepancies = baseline.get("source_discrepancies")
    if (
        not isinstance(discrepancies, list)
        or len(discrepancies) != ledger_contract["baseline_discrepancy_count"]
    ):
        raise ReconciliationError("ledger baseline discrepancy denominator drift")
    existing_ids = {
        item.get("id") for item in discrepancies if isinstance(item, dict)
    }
    added_ids = {item["id"] for item in descriptor["records"]}
    if existing_ids & added_ids:
        raise ReconciliationError("reconciliation record already exists in baseline")
    output = copy.deepcopy(baseline)
    output["source_discrepancies"].extend(copy.deepcopy(descriptor["records"]))
    output_payload = encoded(output)
    if raw_sha(output_payload) != ledger_contract["output_raw_sha256"]:
        raise ReconciliationError("reconciled ledger output digest drift")
    return output_payload


def derive_baseline_bytes(
    output_payload: bytes, descriptor: dict[str, Any] | None = None
) -> bytes:
    descriptor = load_descriptor() if descriptor is None else descriptor
    ledger_contract = descriptor["ledger"]
    if raw_sha(output_payload) != ledger_contract["output_raw_sha256"]:
        raise ReconciliationError("live ledger output raw digest drift")
    output = strict_loads(output_payload, "reconciled ledger")
    discrepancies = output.get("source_discrepancies")
    if (
        not isinstance(discrepancies, list)
        or len(discrepancies) != ledger_contract["output_discrepancy_count"]
        or discrepancies[-2:] != descriptor["records"]
    ):
        raise ReconciliationError("reconciliation records are absent, reordered, or changed")
    baseline = copy.deepcopy(output)
    del baseline["source_discrepancies"][-2:]
    baseline_payload = encoded(baseline)
    if raw_sha(baseline_payload) != ledger_contract["baseline_raw_sha256"]:
        raise ReconciliationError("derived ledger baseline digest drift")
    return baseline_payload


def validate_payload(
    output_payload: bytes,
    descriptor: dict[str, Any] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    descriptor = load_descriptor() if descriptor is None else descriptor
    evidence = verify_evidence(descriptor, repo_root)
    baseline_payload = derive_baseline_bytes(output_payload, descriptor)
    if build_bytes(baseline_payload, descriptor) != output_payload:
        raise ReconciliationError("reconciled ledger is not a deterministic rebuild")
    return {
        "reconciliation_id": descriptor["id"],
        "baseline_raw_sha256": raw_sha(baseline_payload),
        "output_raw_sha256": raw_sha(output_payload),
        "added_discrepancies": len(descriptor["records"]),
        "output_discrepancy_count": descriptor["ledger"][
            "output_discrepancy_count"
        ],
        "reviewed_evidence_count": len(evidence),
    }


def validate_live(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    descriptor = load_descriptor()
    ledger_path = _repo_file(descriptor["ledger"]["path"], repo_root)
    return validate_payload(ledger_path.read_bytes(), descriptor, repo_root=repo_root)


def apply_live(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    descriptor = load_descriptor()
    ledger_path = _repo_file(descriptor["ledger"]["path"], repo_root)
    current = ledger_path.read_bytes()
    current_sha = raw_sha(current)
    if current_sha == descriptor["ledger"]["output_raw_sha256"]:
        return validate_payload(current, descriptor, repo_root=repo_root)
    output = build_bytes(current, descriptor)
    descriptor_check = load_descriptor()
    if descriptor_check != descriptor:
        raise ReconciliationError("descriptor changed during apply")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{ledger_path.name}.", dir=ledger_path.parent
    )
    try:
        with os.fdopen(fd, "wb") as temporary:
            temporary.write(output)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, ledger_path)
    finally:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass
    return validate_payload(ledger_path.read_bytes(), descriptor, repo_root=repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "validate", "apply"))
    args = parser.parse_args()
    try:
        descriptor = load_descriptor()
        if args.command == "plan":
            report = {
                "reconciliation_id": descriptor["id"],
                "ledger": descriptor["ledger"],
                "decisions": descriptor["decisions"],
                "record_ids": [item["id"] for item in descriptor["records"]],
            }
        elif args.command == "validate":
            report = validate_live()
        else:
            report = apply_live()
    except ReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
