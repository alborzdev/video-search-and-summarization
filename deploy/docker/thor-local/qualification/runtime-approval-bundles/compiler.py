#!/usr/bin/env python3
"""Compile the inert Thor runtime approval-bundle plan without taking actions."""

from __future__ import annotations

import argparse
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
CONTRACT_SCHEMA_PATH = HERE / "contract.schema.json"
PLAN_SCHEMA_PATH = HERE / "plan.schema.json"
MAX_JSON_BYTES = 2_000_000
EXPECTED_PACKAGE_HASHES = {
    "contract.json": "fe6141afc526e496b43cd2b66fb1e9439161125c56f4fac0b0b6f395009b0b7d",
    "contract.schema.json": "400b3b8720cd9332c069cc2d5d14aa54722680a4493ccfabef8701db5e98d36e",
    "plan.schema.json": "ccf37af1c00cac7f677a6af1dca4c5d7f69391bbf4147561e894455fe6ecf218",
}
EXPECTED_BUNDLE_IDS = [
    "host-prerequisite-evidence-collection",
    "read-only-docker-runtime-inspection",
    "cgroupfs-remediation",
    "tiny-audio-fixture-generation",
    "model-artifact-downloads",
    "profile-lifecycle",
    "search-scale-progressive-2-4-8-16",
    "search-scale-100",
    "mv3dt-custom-data",
    "sparse4d-custom-data-models",
    "audio-native-runtime",
    "audio-asr-transcript-runtime",
    "official-edge-staging",
    "external-attestations",
]
EXPECTED_DEPENDENCIES = {
    "host-prerequisite-evidence-collection": [],
    "read-only-docker-runtime-inspection": ["host-prerequisite-evidence-collection"],
    "cgroupfs-remediation": ["read-only-docker-runtime-inspection"],
    "tiny-audio-fixture-generation": [],
    "model-artifact-downloads": ["read-only-docker-runtime-inspection"],
    "profile-lifecycle": [
        "read-only-docker-runtime-inspection",
        "cgroupfs-remediation",
        "model-artifact-downloads",
    ],
    "search-scale-progressive-2-4-8-16": ["profile-lifecycle"],
    "search-scale-100": [
        "profile-lifecycle",
        "search-scale-progressive-2-4-8-16",
    ],
    "mv3dt-custom-data": ["profile-lifecycle"],
    "sparse4d-custom-data-models": [
        "profile-lifecycle",
        "model-artifact-downloads",
    ],
    "audio-native-runtime": [
        "tiny-audio-fixture-generation",
        "model-artifact-downloads",
        "profile-lifecycle",
    ],
    "audio-asr-transcript-runtime": [
        "tiny-audio-fixture-generation",
        "model-artifact-downloads",
        "profile-lifecycle",
    ],
    "official-edge-staging": [
        "read-only-docker-runtime-inspection",
        "model-artifact-downloads",
    ],
    "external-attestations": [],
}
EXPECTED_SOURCE_PATHS = {
    "deploy/docker/thor-local/qualification/runtime.py",
    "deploy/docker/thor-local/qualification/runtime_inventory.json",
    "deploy/docker/thor-local/qualification/runtime-lanes/runtime-lane-plan.json",
    "deploy/docker/thor-local/qualification/host-prerequisite-evidence/contract.json",
    "deploy/docker/thor-local/qualification/host-prerequisite-evidence/collector.py",
    "deploy/docker/thor-local/qualification/host-preflight/contract.json",
    "deploy/docker/thor-local/qualification/host-preflight/preflight.py",
    "deploy/docker/thor-local/qualification/host-cgroupfs-remediation/remediate.py",
    "deploy/docker/thor-local/qualification/tiny-audio-fixture/fixture.py",
    "deploy/docker/thor-local/qualification/tiny-audio-fixture/receipt.schema.json",
    "deploy/docker/thor-local/qualification/official-edge-readiness/staging-plan.json",
    "deploy/docker/thor-local/qualification/official-edge-readiness/readiness.py",
    "deploy/docker/thor-local/qualification/local-alternate-models/contract.json",
    "deploy/docker/thor-local/qualification/local-alternate-models/lifecycle.py",
    "deploy/docker/thor-local/qualification/search-scale-qualification-plan/contract.json",
    "deploy/docker/thor-local/qualification/search-scale-qualification-plan/plan.py",
    "deploy/docker/thor-local/qualification/mv3dt-entry-oracles/contract.json",
    "deploy/docker/thor-local/qualification/mv3dt-entry-oracles/executor.py",
    "deploy/docker/thor-local/qualification/sparse4d-entry-oracles/contract.json",
    "deploy/docker/thor-local/qualification/sparse4d-entry-oracles/executor.py",
    "deploy/docker/thor-local/qualification/external-entry-attestations/contract.json",
    "deploy/docker/thor-local/qualification/external-entry-attestations/plan.py",
    "deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/inventory.json",
    "deploy/docker/thor-local/qualification/audio-entry-oracles/contract.json",
    "deploy/docker/thor-local/qualification/audio-entry-oracles/oracle.py",
    "deploy/docker/scripts/thor-local.sh",
    "deploy/docker/scripts/dev-profile.sh",
}
EXPECTED_FIRST_APPROVAL = {
    "id": "host-prerequisite-evidence-collection",
    "approval_placeholder": (
        "<APPROVE_ONLY_READ_ONLY_HOST_PREREQUISITE_EVIDENCE_COLLECTION>"
    ),
    "acknowledgement_token": "I_ACCEPT_READ_ONLY_HOST_PREREQUISITE_EVIDENCE",
    "authorized_command": (
        "PYTHONDONTWRITEBYTECODE=1 python3 "
        "deploy/docker/thor-local/qualification/host-prerequisite-evidence/"
        "collector.py inspect --acknowledgement "
        "I_ACCEPT_READ_ONLY_HOST_PREREQUISITE_EVIDENCE"
    ),
}


class BundleError(RuntimeError):
    """The static package, a source identity, or bundle semantics drifted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, label: str) -> dict[str, Any]:
    if len(data) > MAX_JSON_BYTES:
        raise BundleError(f"JSON exceeds bounded size: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BundleError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                BundleError(f"non-finite JSON number in {label}: {token}")
            ),
        )
    except BundleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid JSON: {label}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"JSON root must be an object: {label}")
    return value


def _package_file(name: str) -> Path:
    path = HERE / name
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise BundleError(f"missing package file: {name}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise BundleError(f"package file must be a regular non-symlink: {name}")
    return path


def _repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise BundleError(f"unsafe repository path: {relative}")
    current = REPO_ROOT
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise BundleError(f"symlinked repository path: {relative}")
    try:
        resolved = (REPO_ROOT / path).resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise BundleError(
            f"repository source escaped or is absent: {relative}"
        ) from exc
    if not resolved.is_file():
        raise BundleError(f"repository source is not a file: {relative}")
    return resolved


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json(schema_path.read_bytes(), str(schema_path))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise BundleError(f"invalid {label} schema") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(item) for item in first.absolute_path)
        raise BundleError(f"{label} schema violation at {location}: {first.message}")


def _validate_semantics(contract: dict[str, Any]) -> None:
    bundles = contract["bundles"]
    bundle_ids = [item["id"] for item in bundles]
    if bundle_ids != EXPECTED_BUNDLE_IDS:
        raise BundleError("exact ordered bundle denominator drift")
    placeholders = [item["approval_placeholder"] for item in bundles]
    if len(set(placeholders)) != len(placeholders):
        raise BundleError("approval placeholders must be unique per bundle")
    first = bundles[0]
    if any(first.get(key) != value for key, value in EXPECTED_FIRST_APPROVAL.items()):
        raise BundleError("first host-prerequisite approval gate drift")
    if any(
        "acknowledgement_token" in bundle or "authorized_command" in bundle
        for bundle in bundles[1:]
    ):
        raise BundleError("executable acknowledgement gate must remain isolated")
    positions = {bundle_id: index for index, bundle_id in enumerate(bundle_ids)}
    for bundle in bundles:
        bundle_id = bundle["id"]
        if bundle["depends_on"] != EXPECTED_DEPENDENCIES[bundle_id]:
            raise BundleError(f"dependency precedence drift: {bundle_id}")
        if any(
            positions[dependency] >= positions[bundle_id]
            for dependency in bundle["depends_on"]
        ):
            raise BundleError(f"dependency must precede dependent bundle: {bundle_id}")
        flags = bundle["flags"]
        if flags["downloads"] and not (
            flags["network"] and flags["writes"] and flags["subprocess"]
        ):
            raise BundleError(
                "download flags must disclose network, writes, and subprocess"
            )
        if flags["destructive"] and not (flags["writes"] and flags["lifecycle"]):
            raise BundleError("destructive flags must disclose writes and lifecycle")
    audio_paths = {
        item["path"]
        for item in contract["source_locks"]
        if "audio-entry-oracles" in item["path"]
    }
    if audio_paths != {
        "deploy/docker/thor-local/qualification/audio-entry-oracles/contract.json",
        "deploy/docker/thor-local/qualification/audio-entry-oracles/oracle.py",
    }:
        raise BundleError("stable audio contract/oracle lock set drifted")
    if not contract["audio_dependency_boundary"]["active_audio_package_relied_on"]:
        raise BundleError("stable audio package must be relied on")

    review = contract["download_review"]
    exact_sum = sum(
        item["exact_remote_bytes"]
        for item in review["artifacts"]
        if item["size_state"] == "exact_known"
    )
    floor_sum = sum(item["planning_floor_bytes"] or 0 for item in review["artifacts"])
    if exact_sum != review["known_exact_remote_bytes"]:
        raise BundleError("known exact download byte total drift")
    if (
        floor_sum
        != review["known_planning_floor_bytes_including_documented_cosmos_floor"]
    ):
        raise BundleError("known planning-floor byte total drift")
    if not any(item["size_state"] == "unknown" for item in review["artifacts"]):
        raise BundleError("unknown-size artifact boundary disappeared")

    locks = contract["source_locks"]
    paths = [item["path"] for item in locks]
    if len(set(paths)) != len(paths) or set(paths) != EXPECTED_SOURCE_PATHS:
        raise BundleError("exact unique source lock denominator drift")


def _load_contract() -> dict[str, Any]:
    for name, expected in EXPECTED_PACKAGE_HASHES.items():
        if _sha256(_package_file(name).read_bytes()) != expected:
            raise BundleError(f"package identity drift: {name}")
    contract = _strict_json(CONTRACT_PATH.read_bytes(), str(CONTRACT_PATH))
    _validate_schema(contract, CONTRACT_SCHEMA_PATH, "contract")
    _validate_semantics(contract)
    return contract


def _check_sources(contract: dict[str, Any]) -> list[dict[str, Any]]:
    checks = []
    for lock in contract["source_locks"]:
        match = _sha256(_repo_file(lock["path"]).read_bytes()) == lock["sha256"]
        checks.append({"path": lock["path"], "sha256_match": match})
    failed = [item["path"] for item in checks if not item["sha256_match"]]
    if failed:
        raise BundleError(f"source lock mismatch: {failed}")
    return checks


def compile_plan() -> dict[str, Any]:
    contract = _load_contract()
    result = {
        "schema_version": 1,
        "mode": "inert_nonexecuting_approval_plan",
        "contract_sha256": _sha256(CONTRACT_PATH.read_bytes()),
        "default_policy": contract["default_policy"],
        "approval_policy": contract["approval_policy"],
        "audio_dependency_boundary": contract["audio_dependency_boundary"],
        "download_review": contract["download_review"],
        "source_checks": _check_sources(contract),
        "bundle_count": len(contract["bundles"]),
        "approval_count": 0,
        "ordered_bundles": contract["bundles"],
        "boundary": "plan_only_placeholders_are_not_approval_no_action_surface",
        "next_action": "operator_reviews_and_authorizes_each_selected_bundle_separately_outside_this_compiler",
    }
    _validate_schema(result, PLAN_SCHEMA_PATH, "plan")
    if result["ordered_bundles"] != contract["bundles"]:
        raise BundleError("plan bundle copy drift")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate and compile the same inert plan"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _parser().parse_args(argv)
    try:
        result = compile_plan()
    except BundleError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
