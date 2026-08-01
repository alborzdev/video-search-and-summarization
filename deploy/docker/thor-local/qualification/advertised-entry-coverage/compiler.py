#!/usr/bin/env python3
"""Compile the fail-closed global advertised-entry semantic coverage ledger."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator


sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE.parents[4]
COVERAGE_PATH = PACKAGE / "coverage.json"
SCHEMA_PATH = PACKAGE / "coverage.schema.json"

SOURCE_PATHS = {
    "manifest": "deploy/docker/thor-local/parity/manifest.json",
    "official_capabilities": "deploy/docker/thor-local/parity/official-capabilities.json",
    "capability_oracles": "deploy/docker/thor-local/parity/capability-oracles.json",
    "advertised_gap_plan": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "runtime_lane_plan": "deploy/docker/thor-local/qualification/runtime-lanes/runtime-lane-plan.json",
}
SOURCE_RAW_SHA256 = {
    "manifest": "1f56d63437bd7742cf7488b9bd85b25fc886cdaf39a3c2b46aabecbc6b7201ce",
    "official_capabilities": "cde0dc3981aaf699a017c7108089aac72070101edc47a06489f3940e44fe52a0",
    "capability_oracles": "c4e7a5ecfedfa2ddf18e68fc2bc110bea48d9ff7ce63d0dd4fdc169711beda90",
    "advertised_gap_plan": "2fc3a8fbcbfd8afa62e657cf0d4b3f34d568294b089bd71f0f87354e9196745c",
    "runtime_lane_plan": "bf863fac268d1247eda71b9edbfd497580453c52cd3ced7fcdb333386efa25c9",
}
SOURCE_CANONICAL_SHA256 = {
    "manifest": "cbf65ddc55b3518763bf8ee57f58f24619956473035aeca98a274a7b1bc959f2",
    "official_capabilities": "30142a6716d48597f2daee6a5e776629393526bc7185ca7f70b89fefe2b13eec",
    "capability_oracles": "6d2b3991e6e31a74ba42c3271d7cc0dce8748468617d18772078db6abfd1e336",
    "advertised_gap_plan": "e3e3a81401795983a33f7f2584cc004eac3c363719cd29b83af15aaa62a4f85b",
    "runtime_lane_plan": "6645431c98b86cd615b8b06b45f72ea71b2f53b408610c5da43ede06a316da55",
}
SCHEMA_RAW_SHA256 = "dd1e29e3c6cae82a1b28af5f5630a7e88d70dedb7570084c74c3e95ef578460b"
EXPECTED_COVERAGE_PAYLOAD_SHA256 = "cc9dbbc4ccf0aec704c30ad013097eec1e2b36a506e1615a9006ca684d780a90"
EXPECTED_COVERAGE_RAW_SHA256 = "2ea517799c03bcc432856a805b8e35ae1d97c8c3dd2f7b928d99004bbb7b6af5"

EXPECTED_MAPPING_COUNTS = {
    "canonical_entry_capability": 13,
    "exact_existing_capability": 276,
    "explicit_missing_entry_gap": 74,
    "family_only_unreviewed": 137,
}
EXPECTED_ACCEPTANCE_COUNTS = {
    "alternate_local_lane": 159,
    "external_optional": 36,
    "required_local": 305,
}
EXPECTED_OBLIGATION_COUNTS = {
    "alternate": 159,
    "external_excluded": 36,
    "required": 305,
}
EXPECTED_RUNTIME_STATE_COUNTS = {
    "blocked": 9,
    "missing_entry_capability": 74,
    "not_applicable": 32,
    "not_qualified": 208,
    "passed_prior": 1,
    "static_only": 39,
    "unreviewed_entry": 137,
}
EXPECTED_TOTALS = {
    "feature_families": 55,
    "advertised_entries": 500,
    "semantic_exact_mappings": 289,
    "semantic_blockers": 211,
    "local_runtime_blockers": 464,
    "runtime_evidence_records": 0,
    "warehouse_sample_bundle_entries": 0,
}
EXCLUDED_SAMPLE_MARKERS = (
    "warehouse-4cams-20mx20m-synthetic",
    "warehouse-loading-dock-3cams-synthetic",
)


class CoverageError(RuntimeError):
    """A source, semantic mapping, schema, or checked-output invariant failed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_json(value: Any) -> str:
    return _sha_bytes(_canonical_bytes(value))


def _strict_json(payload: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CoverageError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _load_locked_json(
    path: Path,
    raw_sha256: str | None = None,
    canonical_sha256: str | None = None,
) -> Any:
    if path.is_symlink() or not path.is_file():
        raise CoverageError(f"not a regular source/package file: {path}")
    payload = path.read_bytes()
    if raw_sha256 not in (None, "TO_BE_PINNED"):
        if _sha_bytes(payload) != raw_sha256:
            raise CoverageError(f"raw digest drift: {path}")
    value = _strict_json(payload, str(path))
    if canonical_sha256 not in (None, "TO_BE_PINNED"):
        if _sha_json(value) != canonical_sha256:
            raise CoverageError(f"canonical digest drift: {path}")
    return value


def _schema_errors(instance: Any, schema: Any) -> list[str]:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    return [
        f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
        for error in errors
    ]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:56].rstrip("-") or "entry"


def _canonical_entry_id(feature_id: str, advertised_index: int, claim: str) -> str:
    return f"manifest-entry.{feature_id}.{advertised_index:02d}-{_slug(claim)}"


def _obligation(acceptance_class: str) -> str:
    try:
        return {
            "required_local": "required",
            "alternate_local_lane": "alternate",
            "external_optional": "external_excluded",
        }[acceptance_class]
    except KeyError as exc:
        raise CoverageError(f"unknown acceptance class: {acceptance_class!r}") from exc


def _unique_by(items: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or not value or value in result:
            raise CoverageError(f"{label}: missing or duplicate {key}: {value!r}")
        result[value] = item
    return result


def _validate_capability_source_claims(
    capability: dict[str, Any], source_ids: set[str]
) -> None:
    capability_id = capability["id"]
    source_claims = capability.get("source_claims")
    if not isinstance(source_claims, list) or not source_claims:
        raise CoverageError(f"{capability_id}: exact mapping has no source claims")
    for source_claim in source_claims:
        if (
            not isinstance(source_claim, dict)
            or source_claim.get("source_id") not in source_ids
            or not isinstance(source_claim.get("locator"), str)
            or not source_claim["locator"].strip()
        ):
            raise CoverageError(f"{capability_id}: invalid exact source claim")


def _validate_oracle_binding(
    capability: dict[str, Any], oracle: dict[str, Any]
) -> None:
    capability_id = capability["id"]
    if oracle.get("oracle_id") != f"oracle.{capability_id}":
        raise CoverageError(f"{capability_id}: oracle identity drift")
    expected_binding = {
        key: capability[key]
        for key in (
            "feature_id",
            "kind",
            "title",
            "source_claims",
            "acceptance_class",
            "thor_state",
            "runtime_state",
            "contract",
            "gap",
        )
    }
    if oracle.get("ledger_binding") != expected_binding:
        raise CoverageError(f"{capability_id}: oracle ledger binding drift")
    if oracle.get("acceptance_readiness", {}).get("classification") != "planning_index_only":
        raise CoverageError(f"{capability_id}: oracle is not planning-index-only")
    if oracle.get("evidence") != []:
        raise CoverageError(f"{capability_id}: oracle runtime evidence is forbidden")
    fixture = oracle.get("fixture", {})
    bounds = oracle.get("execution_bounds", {})
    if fixture.get("warehouse_sample_bundle") is not False:
        raise CoverageError(f"{capability_id}: Warehouse sample fixture escaped exclusion")
    if bounds.get("warehouse_sample_bundle") != "excluded":
        raise CoverageError(f"{capability_id}: Warehouse sample execution escaped exclusion")
    external = capability["acceptance_class"] == "external_optional"
    expected_state = "external_boundary_unexecuted" if external else "open_unexecuted"
    if oracle.get("current_state") != expected_state:
        raise CoverageError(f"{capability_id}: oracle boundary/current state drift")
    if external and capability.get("runtime_state") != "not_applicable":
        raise CoverageError(f"{capability_id}: external capability must be not_applicable")
    if capability.get("runtime_state") == "passed_current":
        raise CoverageError(f"{capability_id}: mapping ledger cannot ingest passed_current")


def compile_documents(
    manifest: dict[str, Any],
    official: dict[str, Any],
    oracle_document: dict[str, Any],
    gap_plan: dict[str, Any],
    runtime_plan: dict[str, Any],
    source_locks: dict[str, dict[str, str]],
) -> dict[str, Any]:
    features = manifest.get("features")
    capabilities = official.get("capabilities")
    oracles = oracle_document.get("oracles")
    gap_entries = gap_plan.get("entries")
    runtime_entries = runtime_plan.get("advertised_entry_bindings")
    if not all(isinstance(value, list) for value in (features, capabilities, oracles, gap_entries, runtime_entries)):
        raise CoverageError("one or more source collections are malformed")
    if len(features) != 55 or sum(len(item.get("advertised", [])) for item in features) != 500:
        raise CoverageError("manifest denominator drift")
    if len(capabilities) != 289 or len(oracles) != 289:
        raise CoverageError("capability/oracle denominator drift")
    if len(gap_entries) != 74 or len(runtime_entries) != 500:
        raise CoverageError("gap/runtime advertised denominator drift")

    capability_by_id = _unique_by(capabilities, "id", "official capabilities")
    oracle_by_capability = _unique_by(oracles, "capability_id", "capability oracles")
    gap_by_pointer = _unique_by(gap_entries, "manifest_pointer", "advertised gap plan")
    runtime_by_pointer = _unique_by(
        runtime_entries, "manifest_json_pointer", "runtime advertised bindings"
    )
    source_ids = {
        item.get("id")
        for item in official.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(source_ids) != len(official.get("sources", [])):
        raise CoverageError("official source identity drift")

    feature_ids: set[str] = set()
    all_manifest_capability_ids: list[str] = []
    rows: list[dict[str, Any]] = []
    for feature_index, feature in enumerate(features):
        feature_id = feature.get("id")
        if not isinstance(feature_id, str) or feature_id in feature_ids:
            raise CoverageError(f"manifest feature identity drift: {feature_id!r}")
        feature_ids.add(feature_id)
        family_capability_ids = feature.get("official_capability_ids", [])
        if not isinstance(family_capability_ids, list) or len(family_capability_ids) != len(set(family_capability_ids)):
            raise CoverageError(f"{feature_id}: invalid family capability IDs")
        all_manifest_capability_ids.extend(family_capability_ids)
        for capability_id in family_capability_ids:
            capability = capability_by_id.get(capability_id)
            if capability is None or capability.get("feature_id") != feature_id:
                raise CoverageError(f"{feature_id}: capability feature binding drift: {capability_id}")

        family_hash = _sha_json(feature)
        family_ids_hash = _sha_json(family_capability_ids)
        for advertised_index, claim in enumerate(feature.get("advertised", [])):
            if not isinstance(claim, str) or not claim:
                raise CoverageError(f"{feature_id}: invalid advertised claim")
            pointer = f"/features/{feature_index}/advertised/{advertised_index}"
            runtime = runtime_by_pointer.get(pointer)
            if runtime is None:
                raise CoverageError(f"{pointer}: runtime-lane binding missing")
            if (
                runtime.get("feature_id") != feature_id
                or runtime.get("feature_manifest_index") != feature_index
                or runtime.get("advertised_index") != advertised_index
                or runtime.get("advertised_claim") != claim
            ):
                raise CoverageError(f"{pointer}: runtime-lane source identity drift")
            expected_manifest_entry_sha = _sha_json(
                {"json_pointer": pointer, "value": claim}
            )
            if runtime.get("manifest_entry_sha256") != expected_manifest_entry_sha:
                raise CoverageError(f"{pointer}: runtime-lane entry digest drift")

            exact_ids = [
                capability_id
                for capability_id in family_capability_ids
                if capability_by_id[capability_id].get("title") == claim
            ]
            if len(exact_ids) > 1:
                raise CoverageError(f"{pointer}: ambiguous exact capability title mapping")
            gap = gap_by_pointer.get(pointer)
            if exact_ids and gap is not None:
                raise CoverageError(f"{pointer}: exact capability overlaps explicit gap")

            capability_ids: list[str] = []
            oracle_ids: list[str] = []
            oracle_states: list[str] = []
            gap_reference: dict[str, Any] | None = None
            source_claim_count = 0
            source_claims_sha256: str | None = None
            capability_contract_sha256: str | None = None
            oracle_contract_sha256: str | None = None

            if exact_ids:
                capability_id = exact_ids[0]
                capability = capability_by_id[capability_id]
                oracle = oracle_by_capability.get(capability_id)
                if oracle is None:
                    raise CoverageError(f"{pointer}: exact capability lacks oracle")
                _validate_capability_source_claims(capability, source_ids)
                _validate_oracle_binding(capability, oracle)
                canonical = capability_id.startswith("manifest-entry.")
                mapping_class = (
                    "canonical_entry_capability"
                    if canonical
                    else "exact_existing_capability"
                )
                review_state = "canonical_exact" if canonical else "reviewed_exact"
                if canonical and capability_id != _canonical_entry_id(
                    feature_id, advertised_index, claim
                ):
                    raise CoverageError(f"{pointer}: canonical entry identity drift")
                capability_ids = [capability_id]
                oracle_ids = [oracle["oracle_id"]]
                oracle_states = [oracle["current_state"]]
                acceptance_class = capability["acceptance_class"]
                runtime_state = capability["runtime_state"]
                source_claim_count = len(capability["source_claims"])
                source_claims_sha256 = _sha_json(capability["source_claims"])
                capability_contract_sha256 = _sha_json(capability["contract"])
                oracle_contract_sha256 = _sha_json(oracle)
                semantic_blocker = False
                expected_runtime_scope = mapping_class
            elif gap is not None:
                if (
                    gap.get("family_id") != feature_id
                    or gap.get("family_index") != feature_index
                    or gap.get("advertised_index") != advertised_index
                    or gap.get("advertised") != claim
                    or gap.get("runtime_evidence") != []
                    or gap.get("required_oracle", {}).get("runtime_evidence") != []
                    or gap.get("warehouse_scope", {}).get("sample_bundle_required") is not False
                ):
                    raise CoverageError(f"{pointer}: gap identity/evidence/Warehouse drift")
                proposed_id = gap.get("proposed_capability", {}).get("id")
                proposed_oracle_id = gap.get("required_oracle", {}).get("id")
                if proposed_id in capability_by_id or proposed_oracle_id in {
                    item.get("oracle_id") for item in oracles
                }:
                    raise CoverageError(f"{pointer}: open gap overlaps canonical ledger")
                mapping_class = "explicit_missing_entry_gap"
                review_state = "open_gap"
                acceptance_class = gap["proposed_capability"]["acceptance_class"]
                runtime_state = "missing_entry_capability"
                semantic_blocker = True
                expected_runtime_scope = (
                    "feature_family_only_with_open_entry_gap"
                    if family_capability_ids
                    else "none_family_has_zero_capability_rows"
                )
                gap_reference = {
                    "gap_entry_id": gap["entry_id"],
                    "coverage_state": gap["coverage_state"],
                    "proposed_capability_id": proposed_id,
                    "required_oracle_id": proposed_oracle_id,
                }
            else:
                if not family_capability_ids:
                    raise CoverageError(f"{pointer}: zero-capability entry escaped gap plan")
                mapping_class = "family_only_unreviewed"
                review_state = "unreviewed_family_only"
                acceptance_class = feature["acceptance_class"]
                runtime_state = "unreviewed_entry"
                semantic_blocker = True
                expected_runtime_scope = "feature_family_only"

            if (
                runtime.get("entry_specific_capability_ids") != capability_ids
                or runtime.get("entry_specific_oracle_ids") != oracle_ids
                or runtime.get("capability_mapping_scope") != expected_runtime_scope
                or runtime.get("runtime_evidence_records") != []
            ):
                raise CoverageError(f"{pointer}: runtime-lane semantic mapping drift")
            lane_ids = runtime.get("lane_ids")
            if not isinstance(lane_ids, list) or not lane_ids or len(lane_ids) != len(set(lane_ids)):
                raise CoverageError(f"{pointer}: invalid runtime lane set")
            obligation = _obligation(acceptance_class)
            runtime_default_lane_id = runtime.get("default_lane_id")
            if acceptance_class == "external_optional":
                if (
                    runtime_default_lane_id != "external-optional"
                    or lane_ids != ["external-optional"]
                ):
                    raise CoverageError(
                        f"{pointer}: external optional entry escaped its exact runtime lane"
                    )
            elif runtime_default_lane_id == "external-optional":
                raise CoverageError(
                    f"{pointer}: required/alternate entry defaults to external-optional"
                )
            rows.append(
                {
                    "manifest_pointer": pointer,
                    "feature_pointer": f"/features/{feature_index}",
                    "feature_index": feature_index,
                    "feature_id": feature_id,
                    "feature_category": feature["category"],
                    "advertised_index": advertised_index,
                    "advertised": claim,
                    "advertised_utf8_sha256": _sha_bytes(claim.encode("utf-8")),
                    "advertised_canonical_sha256": _sha_json(claim),
                    "manifest_entry_sha256": expected_manifest_entry_sha,
                    "family_canonical_sha256": family_hash,
                    "family_capability_ids": family_capability_ids,
                    "family_capability_ids_sha256": family_ids_hash,
                    "mapping_class": mapping_class,
                    "mapping_review_state": review_state,
                    "capability_ids": capability_ids,
                    "oracle_ids": oracle_ids,
                    "gap_reference": gap_reference,
                    "semantic_match_basis": {
                        "exact_title_match": bool(capability_ids),
                        "exact_feature_match": bool(capability_ids),
                        "source_claim_count": source_claim_count,
                        "source_claims_sha256": source_claims_sha256,
                        "capability_contract_sha256": capability_contract_sha256,
                        "oracle_contract_sha256": oracle_contract_sha256,
                    },
                    "acceptance_class": acceptance_class,
                    "local_parity_obligation": obligation,
                    "runtime_qualification_state": runtime_state,
                    "oracle_current_states": oracle_states,
                    "runtime_default_lane_id": runtime_default_lane_id,
                    "runtime_lane_ids": lane_ids,
                    "runtime_evidence_ids": [],
                    "mapping_is_runtime_evidence": False,
                    "blocks_literal_semantic_completeness": semantic_blocker,
                    "blocks_local_runtime_completeness": obligation
                    != "external_excluded",
                    "warehouse_sample_bundle_required": False,
                }
            )

    if len(all_manifest_capability_ids) != len(set(all_manifest_capability_ids)):
        raise CoverageError("capability is listed by more than one manifest family")
    if set(all_manifest_capability_ids) != set(capability_by_id):
        raise CoverageError("manifest and official capability identities differ")
    if set(oracle_by_capability) != set(capability_by_id):
        raise CoverageError("capability and oracle identities differ")
    expected_pointers = {item["manifest_pointer"] for item in rows}
    if set(gap_by_pointer) - expected_pointers or set(runtime_by_pointer) != expected_pointers:
        raise CoverageError("gap/runtime pointer coverage drift")

    mapping_counts = dict(sorted(Counter(item["mapping_class"] for item in rows).items()))
    acceptance_counts = dict(sorted(Counter(item["acceptance_class"] for item in rows).items()))
    obligation_counts = dict(sorted(Counter(item["local_parity_obligation"] for item in rows).items()))
    runtime_state_counts = dict(sorted(Counter(item["runtime_qualification_state"] for item in rows).items()))
    totals = {
        "feature_families": len(features),
        "advertised_entries": len(rows),
        "semantic_exact_mappings": sum(
            not item["blocks_literal_semantic_completeness"] for item in rows
        ),
        "semantic_blockers": sum(
            item["blocks_literal_semantic_completeness"] for item in rows
        ),
        "local_runtime_blockers": sum(
            item["blocks_local_runtime_completeness"] for item in rows
        ),
        "runtime_evidence_records": sum(
            len(item["runtime_evidence_ids"]) for item in rows
        ),
        "warehouse_sample_bundle_entries": sum(
            item["warehouse_sample_bundle_required"] for item in rows
        ),
    }
    if mapping_counts != EXPECTED_MAPPING_COUNTS:
        raise CoverageError(f"mapping denominator drift: {mapping_counts}")
    if acceptance_counts != EXPECTED_ACCEPTANCE_COUNTS:
        raise CoverageError(f"acceptance denominator drift: {acceptance_counts}")
    if obligation_counts != EXPECTED_OBLIGATION_COUNTS:
        raise CoverageError(f"obligation denominator drift: {obligation_counts}")
    if runtime_state_counts != EXPECTED_RUNTIME_STATE_COUNTS:
        raise CoverageError(f"runtime-state denominator drift: {runtime_state_counts}")
    if totals != EXPECTED_TOTALS:
        raise CoverageError(f"global denominator drift: {totals}")
    if any(marker in json.dumps(rows) for marker in EXCLUDED_SAMPLE_MARKERS):
        raise CoverageError("excluded Warehouse sample marker entered coverage ledger")
    if runtime_plan.get("policy", {}).get("warehouse_sample_bundle") != "excluded":
        raise CoverageError("runtime plan does not exclude the Warehouse sample bundle")
    if runtime_plan.get("policy", {}).get("required_cloud_inference") is not False:
        raise CoverageError("runtime plan requires cloud inference")
    if runtime_plan.get("policy", {}).get("literal_runtime_feature_completeness_claim_allowed") is not False:
        raise CoverageError("runtime plan permits a false completeness claim")
    if gap_plan.get("policy", {}).get("warehouse_sample_bundle") != "excluded":
        raise CoverageError("gap plan does not exclude the Warehouse sample bundle")

    coverage: dict[str, Any] = {
        "schema_version": 1,
        "ledger_id": "thor-vss-3.2.1-global-advertised-entry-coverage",
        "target": {
            "platform": "NVIDIA Jetson AGX Thor",
            "release": "VSS 3.2.1",
            "evidence_state": "static_semantic_mapping_only_no_runtime_qualification",
        },
        "source_locks": source_locks,
        "policy": {
            "static_read_only": True,
            "mapping_is_runtime_evidence": False,
            "can_promote_runtime_state": False,
            "family_binding_is_semantic_coverage": False,
            "exact_title_match_requires_feature_oracle_source_alignment": True,
            "external_optional_cannot_satisfy_local": True,
            "warehouse_sample_bundle": "excluded",
            "required_cloud_inference": False,
            "runtime_evidence": [],
            "literal_semantic_completeness_claim_allowed": False,
            "literal_runtime_completeness_claim_allowed": False,
        },
        "summary": {
            **totals,
            "mapping_class_counts": mapping_counts,
            "acceptance_class_counts": acceptance_counts,
            "local_parity_obligation_counts": obligation_counts,
            "runtime_qualification_state_counts": runtime_state_counts,
        },
        "entries": rows,
    }
    coverage["coverage_payload_sha256"] = _sha_json(coverage)
    return coverage


def build_coverage(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    locks: dict[str, dict[str, str]] = {}
    for name, relative_path in SOURCE_PATHS.items():
        path = repo_root / relative_path
        raw_sha = SOURCE_RAW_SHA256[name]
        canonical_sha = SOURCE_CANONICAL_SHA256[name]
        documents[name] = _load_locked_json(path, raw_sha, canonical_sha)
        locks[name] = {
            "path": relative_path,
            "raw_sha256": raw_sha,
            "canonical_sha256": canonical_sha,
        }
    return compile_documents(
        documents["manifest"],
        documents["official_capabilities"],
        documents["capability_oracles"],
        documents["advertised_gap_plan"],
        documents["runtime_lane_plan"],
        locks,
    )


def validate_coverage(
    coverage: dict[str, Any], *, compare_fresh: bool = True, enforce_pins: bool = True
) -> None:
    schema = _load_locked_json(SCHEMA_PATH, SCHEMA_RAW_SHA256)
    errors = _schema_errors(coverage, schema)
    if errors:
        raise CoverageError(f"coverage schema failed: {'; '.join(errors[:8])}")
    payload = dict(coverage)
    observed_payload_sha = payload.pop("coverage_payload_sha256")
    if _sha_json(payload) != observed_payload_sha:
        raise CoverageError("coverage payload digest mismatch")
    if enforce_pins and EXPECTED_COVERAGE_PAYLOAD_SHA256 != "TO_BE_PINNED":
        if observed_payload_sha != EXPECTED_COVERAGE_PAYLOAD_SHA256:
            raise CoverageError("checked coverage payload digest drift")
    if coverage["summary"]["mapping_class_counts"] != EXPECTED_MAPPING_COUNTS:
        raise CoverageError("checked mapping denominators drifted")
    if coverage["summary"]["semantic_blockers"] != 211:
        raise CoverageError("semantic blocker denominator drifted")
    if any(item["runtime_evidence_ids"] for item in coverage["entries"]):
        raise CoverageError("coverage ledger cannot contain runtime evidence")
    if any(item["warehouse_sample_bundle_required"] for item in coverage["entries"]):
        raise CoverageError("coverage ledger cannot require the Warehouse sample bundle")
    if compare_fresh and coverage != build_coverage():
        raise CoverageError("checked coverage differs from deterministic compilation")


def check_checked_coverage() -> dict[str, Any]:
    if COVERAGE_PATH.is_symlink() or not COVERAGE_PATH.is_file():
        raise CoverageError("checked coverage.json is missing or unsafe")
    payload = COVERAGE_PATH.read_bytes()
    if EXPECTED_COVERAGE_RAW_SHA256 != "TO_BE_PINNED":
        if _sha_bytes(payload) != EXPECTED_COVERAGE_RAW_SHA256:
            raise CoverageError("checked coverage raw digest drift")
    coverage = _strict_json(payload, str(COVERAGE_PATH))
    validate_coverage(coverage)
    if payload != _encoded(coverage):
        raise CoverageError("checked coverage is not canonically rendered")
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        coverage = build_coverage()
        validate_coverage(coverage, compare_fresh=False, enforce_pins=False)
        if args.write:
            COVERAGE_PATH.write_bytes(_encoded(coverage))
            print(f"WROTE: {COVERAGE_PATH.relative_to(REPO_ROOT)}")
            return 0
        checked = check_checked_coverage()
        counts = checked["summary"]["mapping_class_counts"]
        print(
            "PASS: global advertised-entry coverage; "
            f"{checked['summary']['advertised_entries']} entries, "
            + ", ".join(f"{key}={value}" for key, value in counts.items())
            + f", semantic_blockers={checked['summary']['semantic_blockers']}"
        )
        return 0
    except (CoverageError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
