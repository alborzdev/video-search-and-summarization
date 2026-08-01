#!/usr/bin/env python3
"""Compile the remaining 211 advertised strings into reviewed candidate rows.

This package is planning-only. It reads checked-in JSON and never invokes a
service, Docker, a provider, a model, or a runtime evidence collector.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4]
OUTPUT = PACKAGE / "candidate.json"
SCHEMA = PACKAGE / "candidate.schema.json"

SOURCE_PATHS = {
    "manifest": "deploy/docker/thor-local/parity/manifest.json",
    "official_capabilities": "deploy/docker/thor-local/parity/official-capabilities.json",
    "official_capabilities_schema": "deploy/docker/thor-local/parity/official-capabilities.schema.json",
    "capability_oracles": "deploy/docker/thor-local/parity/capability-oracles.json",
    "advertised_gap_plan": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "advertised_entry_coverage": "deploy/docker/thor-local/qualification/advertised-entry-coverage/coverage.json",
}
SOURCE_RAW_SHA256 = {
    "manifest": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    "official_capabilities": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    "official_capabilities_schema": "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    "capability_oracles": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
    "advertised_gap_plan": "2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c",
    "advertised_entry_coverage": "2ea517799c03bcc432856a805b8e35ae1d97c8c3dd2f7b928d99004bbb7b6af5",
}
TRANCHES = {
    "features-00-09": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/tranches/features-00-09.json",
        "feature_min": 0,
        "feature_max": 9,
        "entry_count": 66,
        "raw_sha256": "308ed1cb659eac258ff0271c4b46e1054e50b0f7e04e8c6ba6da622b63e13707",
    },
    "features-10-18": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/tranches/features-10-18.json",
        "feature_min": 10,
        "feature_max": 18,
        "entry_count": 56,
        "raw_sha256": "d11a65f518973d33796db8ad53a0324853d574d23e424692293c3b659de39097",
    },
    "features-19-35": {
        "path": "deploy/docker/thor-local/qualification/remaining-advertised-entry-candidates/tranches/features-19-35.json",
        "feature_min": 19,
        "feature_max": 35,
        "entry_count": 89,
        "raw_sha256": "1d91699fd3cfd4ac651be82c5e88fc78357c3ab683d1810de4c73c8e89623fae",
    },
}
SCHEMA_RAW_SHA256 = "e3f09d7c86c46e236b9786f5eb3aa60868e67363224922ce04cfab3d60cd12a8"
EXPECTED_OUTPUT_PAYLOAD_SHA256 = "31ab6971f9e447cc772644a21a209ceda9980c0f863b6d13b109984721754b53"
EXPECTED_OUTPUT_RAW_SHA256 = "a3c1b793f976fa384fb4ea588602f225e21c9d2d1fd563f12c0aadfa9d1a56fd"

EXPECTED_PRIOR_COUNTS = {
    "explicit_missing_entry_gap": 74,
    "family_only_unreviewed": 137,
}
EXPECTED_ACCEPTANCE_COUNTS = {
    "alternate_local_lane": 46,
    "external_optional": 6,
    "required_local": 159,
}
ALLOWED_TOP_LEVEL_TRANCHE_KEYS = {
    "schema_version",
    "tranche_id",
    "feature_index_min",
    "feature_index_max",
    "entries",
}
EXCLUDED_WAREHOUSE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)
GENERIC_MARKERS = ("<todo", "tbd", "placeholder", "generic fixture")


class CandidateError(RuntimeError):
    """A source lock, semantic candidate, or deterministic output failed."""


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CandidateError(f"{label}: duplicate JSON key {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _load_regular(path: Path, expected_sha256: str | None = None) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        raise CandidateError(f"not a regular file: {path}")
    payload = path.read_bytes()
    digest = _sha_bytes(payload)
    if expected_sha256 not in (None, "TO_BE_PINNED") and digest != expected_sha256:
        raise CandidateError(f"raw digest drift: {path}")
    return _strict_json(payload, str(path)), digest


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:56].rstrip("-") or "entry"


def _candidate_id(feature_id: str, advertised_index: int, title: str) -> str:
    return f"manifest-entry.{feature_id}.{advertised_index:02d}-{_slug(title)}"


def _unique(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = item.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise CandidateError(f"{label}: missing or duplicate {key}: {identity!r}")
        result[identity] = item
    return result


def _validate_surface(entry: dict[str, Any]) -> None:
    capability = entry["proposed_capability"]
    for surface in capability["contract"]["implementation_surfaces"]:
        path_text = surface.split("#", 1)[0]
        relative = Path(path_text)
        if (
            not path_text
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise CandidateError(
                f"{entry['manifest_pointer']}: implementation surface must be a repository-relative file: {surface}"
            )
        candidate = REPO_ROOT / relative
        current = REPO_ROOT
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise CandidateError(
                    f"{entry['manifest_pointer']}: implementation surface cannot traverse a symlink: {surface}"
                )
        try:
            candidate.resolve(strict=True).relative_to(REPO_ROOT.resolve(strict=True))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise CandidateError(
                f"{entry['manifest_pointer']}: implementation surface escapes or is missing from the repository: {surface}"
            ) from exc
        if not candidate.is_file():
            raise CandidateError(
                f"{entry['manifest_pointer']}: implementation surface must be a nonsymlink regular file: {surface}"
            )


def _atomic_write_regular(path: Path, payload: bytes) -> None:
    if path.is_symlink():
        raise CandidateError(f"refusing to replace symlink output: {path}")
    if path.exists() and not path.is_file():
        raise CandidateError(f"output is not a regular file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary.is_symlink() or not temporary.is_file():
            raise CandidateError(f"temporary output is not a regular file: {temporary}")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_entry(
    entry: dict[str, Any],
    coverage: dict[str, Any],
    feature: dict[str, Any],
    capability_by_id: dict[str, dict[str, Any]],
    source_uri_by_id: dict[str, str],
    gap_by_pointer: dict[str, dict[str, Any]],
) -> None:
    pointer = entry["manifest_pointer"]
    capability = entry["proposed_capability"]
    contract = capability["contract"]
    oracle = entry["oracle_plan"]
    advertised = coverage["advertised"]
    expected_id = _candidate_id(feature["id"], coverage["advertised_index"], advertised)
    if (
        entry["feature_index"] != coverage["feature_index"]
        or entry["feature_id"] != coverage["feature_id"]
        or coverage["feature_id"] != feature["id"]
        or entry["advertised_index"] != coverage["advertised_index"]
        or entry["advertised"] != advertised
        or entry["prior_mapping_class"] != coverage["mapping_class"]
        or pointer != coverage["manifest_pointer"]
    ):
        raise CandidateError(f"{pointer}: coverage/manifest identity drift")
    if (
        capability["id"] != expected_id
        or capability["id"] in capability_by_id
        or capability["feature_id"] != feature["id"]
        or capability["title"] != advertised
        or capability["acceptance_class"] != coverage["acceptance_class"]
        or contract["manifest_pointer"] != pointer
        or contract["advertised_literal"] != advertised
    ):
        raise CandidateError(f"{pointer}: proposed capability identity drift")
    external = capability["acceptance_class"] == "external_optional"
    if capability["runtime_state"] != (
        "not_applicable" if external else "not_qualified"
    ):
        raise CandidateError(f"{pointer}: runtime state/locality drift")
    expected_boundary = {
        "required_local": "local",
        "alternate_local_lane": "alternate_local",
        "external_optional": "external",
    }[capability["acceptance_class"]]
    if oracle["execution_boundary"] != expected_boundary:
        raise CandidateError(f"{pointer}: oracle execution boundary drift")
    existing_family_ids = set(feature.get("official_capability_ids", []))
    dependency_ids = set(contract["dependency_capability_ids"])
    if not dependency_ids <= set(capability_by_id):
        raise CandidateError(f"{pointer}: unknown dependency capability")
    if (
        entry["prior_mapping_class"] == "family_only_unreviewed"
        and not dependency_ids & existing_family_ids
    ):
        raise CandidateError(
            f"{pointer}: family-only candidate has no same-family reviewed dependency"
        )
    if entry["prior_mapping_class"] == "explicit_missing_entry_gap":
        gap = gap_by_pointer.get(pointer)
        if gap is None or capability["id"] != gap["proposed_capability"]["id"]:
            raise CandidateError(f"{pointer}: explicit gap proposal identity drift")
        if gap["proposed_capability"]["acceptance_class"] != capability["acceptance_class"]:
            raise CandidateError(f"{pointer}: explicit gap acceptance drift")
        if oracle.get("authoritative_gap_requirement") != gap["required_oracle"]:
            raise CandidateError(f"{pointer}: authoritative gap requirement drift")
    elif pointer in gap_by_pointer:
        raise CandidateError(f"{pointer}: family-only candidate overlaps gap plan")
    elif "authoritative_gap_requirement" in oracle:
        raise CandidateError(
            f"{pointer}: family-only candidate cannot carry an authoritative gap requirement"
        )
    valid_source_ids = set(source_uri_by_id)
    if any(claim["source_id"] not in valid_source_ids for claim in capability["source_claims"]):
        raise CandidateError(f"{pointer}: unknown source claim")
    if any(
        claim["locator"].lstrip().startswith("Advertised ")
        for claim in capability["source_claims"]
    ):
        raise CandidateError(f"{pointer}: synthetic advertised source locator")
    reviewed_scenarios = {
        scenario
        for reviewed_capability in capability_by_id.values()
        for scenario in reviewed_capability["scenario_ids"]
    }
    if not set(capability["scenario_ids"]) <= reviewed_scenarios:
        raise CandidateError(f"{pointer}: unknown reviewed scenario")
    _validate_surface(entry)
    serialized = json.dumps(entry, sort_keys=True).lower()
    if any(marker in serialized for marker in GENERIC_MARKERS):
        raise CandidateError(f"{pointer}: generic or placeholder candidate text")
    if "passed_current" in serialized or '"evidence"' in serialized:
        raise CandidateError(f"{pointer}: candidate cannot contain promotion/evidence")
    if any(marker in serialized for marker in EXCLUDED_WAREHOUSE_MARKERS):
        raise CandidateError(f"{pointer}: excluded Warehouse sample marker")


def compile_candidate() -> dict[str, Any]:
    documents: dict[str, Any] = {}
    source_locks: dict[str, dict[str, str]] = {}
    for source_id, relative in SOURCE_PATHS.items():
        value, digest = _load_regular(
            REPO_ROOT / relative, SOURCE_RAW_SHA256[source_id]
        )
        documents[source_id] = value
        source_locks[source_id] = {"path": relative, "raw_sha256": digest}

    manifest = documents["manifest"]
    official = documents["official_capabilities"]
    oracle_document = documents["capability_oracles"]
    coverage_document = documents["advertised_entry_coverage"]
    gap_document = documents["advertised_gap_plan"]
    official_schema = documents["official_capabilities_schema"]
    features = manifest["features"]
    capability_by_id = _unique(official["capabilities"], "id", "capability")
    source_uri_by_id = {
        item["id"]: item["uri"] for item in official["sources"]
    }
    if {
        item["capability_id"] for item in oracle_document["oracles"]
    } != set(capability_by_id):
        raise CandidateError("capability/oracle source identity drift")
    blockers = {
        item["manifest_pointer"]: item
        for item in coverage_document["entries"]
        if item["mapping_class"] in EXPECTED_PRIOR_COUNTS
    }
    if len(blockers) != 211:
        raise CandidateError("coverage blocker denominator drift")
    gap_by_pointer = {
        item["manifest_pointer"]: item for item in gap_document["entries"]
    }

    entries: list[dict[str, Any]] = []
    tranche_locks: list[dict[str, Any]] = []
    candidate_schema = _load_regular(SCHEMA, SCHEMA_RAW_SHA256)[0]
    entry_validator = Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/entry",
            "$defs": candidate_schema["$defs"],
        }
    )
    for tranche_id, specification in TRANCHES.items():
        relative = specification["path"]
        tranche, digest = _load_regular(
            REPO_ROOT / relative, specification["raw_sha256"]
        )
        if set(tranche) != ALLOWED_TOP_LEVEL_TRANCHE_KEYS:
            raise CandidateError(f"{tranche_id}: unexpected tranche keys")
        if (
            tranche["schema_version"] != 1
            or tranche["tranche_id"] != tranche_id
            or tranche["feature_index_min"] != specification["feature_min"]
            or tranche["feature_index_max"] != specification["feature_max"]
            or len(tranche["entries"]) != specification["entry_count"]
        ):
            raise CandidateError(f"{tranche_id}: tranche identity/count drift")
        for entry in tranche["entries"]:
            errors = sorted(
                entry_validator.iter_errors(entry), key=lambda error: list(error.path)
            )
            if errors:
                raise CandidateError(
                    f"{tranche_id}: entry schema error: {errors[0].message}"
                )
            if not specification["feature_min"] <= entry["feature_index"] <= specification["feature_max"]:
                raise CandidateError(f"{tranche_id}: entry outside feature range")
            compiled_entry = copy.deepcopy(entry)
            gap = gap_by_pointer.get(entry["manifest_pointer"])
            if gap is not None:
                compiled_entry["gap_plan_binding"] = copy.deepcopy(
                    gap["required_oracle"]
                )
            entries.append(compiled_entry)
        tranche_locks.append(
            {
                "tranche_id": tranche_id,
                "path": relative,
                "entry_count": len(tranche["entries"]),
                "raw_sha256": digest,
            }
        )

    pointers = [entry["manifest_pointer"] for entry in entries]
    candidate_ids = [entry["proposed_capability"]["id"] for entry in entries]
    if len(pointers) != len(set(pointers)) or set(pointers) != set(blockers):
        raise CandidateError("candidate pointer partition drift")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise CandidateError("duplicate proposed capability identity")
    for entry in entries:
        coverage = blockers[entry["manifest_pointer"]]
        feature = features[coverage["feature_index"]]
        _validate_entry(
            entry,
            coverage,
            feature,
            capability_by_id,
            source_uri_by_id,
            gap_by_pointer,
        )
    candidate_ledger = copy.deepcopy(official)
    candidate_ledger["capabilities"].extend(
        copy.deepcopy(entry["proposed_capability"]) for entry in entries
    )
    ledger_errors = sorted(
        Draft202012Validator(official_schema).iter_errors(candidate_ledger),
        key=lambda error: list(error.absolute_path),
    )
    if ledger_errors:
        error = ledger_errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise CandidateError(
            f"candidate merged ledger schema error at {location}: {error.message}"
        )
    candidate_manifest = copy.deepcopy(manifest)
    for entry in entries:
        candidate_manifest["features"][entry["feature_index"]].setdefault(
            "official_capability_ids", []
        ).append(entry["proposed_capability"]["id"])
    merged_capability_by_id = {
        item["id"]: item for item in candidate_ledger["capabilities"]
    }
    exact_mapping_count = 0
    exact_mapped_capability_ids: set[str] = set()
    for feature in candidate_manifest["features"]:
        title_to_ids: dict[str, list[str]] = {}
        for capability_id in feature.get("official_capability_ids", []):
            title_to_ids.setdefault(
                merged_capability_by_id[capability_id]["title"], []
            ).append(capability_id)
        for advertised in feature["advertised"]:
            exact_ids = title_to_ids.get(advertised, [])
            if len(exact_ids) != 1:
                raise CandidateError(
                    f"candidate manifest exact-title mapping drift: {feature['id']} / {advertised}"
                )
            exact_mapping_count += 1
            exact_mapped_capability_ids.add(exact_ids[0])
    if (
        exact_mapping_count != 500
        or exact_mapped_capability_ids != set(merged_capability_by_id)
    ):
        raise CandidateError("candidate exact-title completeness denominator drift")
    entries.sort(key=lambda item: (item["feature_index"], item["advertised_index"]))
    prior_counts = dict(sorted(Counter(item["prior_mapping_class"] for item in entries).items()))
    acceptance_counts = dict(
        sorted(
            Counter(
                item["proposed_capability"]["acceptance_class"] for item in entries
            ).items()
        )
    )
    if prior_counts != EXPECTED_PRIOR_COUNTS or acceptance_counts != EXPECTED_ACCEPTANCE_COUNTS:
        raise CandidateError("candidate class/acceptance denominator drift")

    output = {
        "schema_version": 1,
        "candidate_id": "vss-3.2.1-thor-remaining-211-advertised-entry-candidates",
        "target": {
            "product_version": "3.2.1",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "base_commit": "642b081eae180cffc6d53b30f31c6b15d514825a",
        },
        "policy": {
            "candidate_only": True,
            "can_promote_runtime_state": False,
            "runtime_evidence": [],
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
            "custom_data_warehouse_capability": "in_scope",
        },
        "source_locks": source_locks,
        "tranche_locks": tranche_locks,
        "summary": {
            "candidate_entries": len(entries),
            "candidate_merged_capabilities": len(candidate_ledger["capabilities"]),
            "candidate_exact_mappings": exact_mapping_count,
            "candidate_missing_exact_mappings": 0,
            **prior_counts,
            "gap_plan_bindings": sum(
                "gap_plan_binding" in entry for entry in entries
            ),
            "acceptance_class_counts": acceptance_counts,
            "candidate_runtime_evidence_records": 0,
            "warehouse_sample_bundle_entries": 0,
        },
        "entries": entries,
    }
    output["candidate_payload_sha256"] = _sha_json(output)
    return output


def validate_candidate(candidate: dict[str, Any]) -> None:
    schema, _ = _load_regular(SCHEMA, SCHEMA_RAW_SHA256)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(candidate),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise CandidateError(f"candidate schema error at {location}: {error.message}")
    payload = dict(candidate)
    observed_payload_sha = payload.pop("candidate_payload_sha256")
    if observed_payload_sha != _sha_json(payload):
        raise CandidateError("candidate payload digest mismatch")
    if EXPECTED_OUTPUT_PAYLOAD_SHA256 not in (
        "TO_BE_PINNED",
        observed_payload_sha,
    ):
        raise CandidateError("checked candidate payload lock drift")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        candidate = compile_candidate()
        validate_candidate(candidate)
        encoded = _encoded(candidate)
        if args.write:
            _atomic_write_regular(OUTPUT, encoded)
            print(f"WROTE: {OUTPUT.relative_to(REPO_ROOT)}")
            return 0
        checked, digest = _load_regular(OUTPUT, EXPECTED_OUTPUT_RAW_SHA256)
        if checked != candidate or OUTPUT.read_bytes() != encoded:
            raise CandidateError("checked candidate differs from deterministic compile")
        print(
            "PASS: 211 remaining advertised-entry semantic candidates; "
            "explicit_gap=74, family_only=137, runtime_evidence=0"
        )
        return 0
    except (CandidateError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
