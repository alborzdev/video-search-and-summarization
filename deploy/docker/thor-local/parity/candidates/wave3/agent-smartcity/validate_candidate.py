#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed validation for the isolated Agent and Smart City Wave3 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


SCRIPT_DIR = Path(__file__).resolve().parent
PARITY_DIR = SCRIPT_DIR.parents[2]
REPO_ROOT = SCRIPT_DIR.parents[6]
CANDIDATE = SCRIPT_DIR / "candidate.json"
SCHEMA = SCRIPT_DIR / "candidate.schema.json"
LIVE_LEDGER = PARITY_DIR / "official-capabilities.json"
LIVE_MANIFEST = PARITY_DIR / "manifest.json"
LIVE_ACCEPTANCE = REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
FIXED_POINT_GRAPH = SCRIPT_DIR.parent / "recursive-coverage" / "recursive-targets.json"
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
EXPECTED_COUNTS = {
    "reviewed_pages": 40,
    "claim_bearing_sources": 24,
    "new_capabilities": 34,
    "enrichments": 7,
    "discrepancies": 5,
    "guardrails": 4,
}
EXPECTED_SOURCE_CLASSES = {
    "claim_bearing": 24,
    "already_covered_duplicate": 8,
    "navigation_or_placeholder": 5,
    "empty_api_wrapper": 1,
    "summary_duplicate": 1,
    "legal_external": 1,
}
STALE_SOURCE_URLS = {
    "https://docs.nvidia.com/vss/3.2.1/smartcity-docs/License.html",
    "https://docs.nvidia.com/vss/3.2.1/smartcity-docs/Troubleshooting.html",
}
EXPECTED_CANDIDATE_SHA256 = "a0c366965541898d6c9f978f938a1fe8fc77fac84c1b992af09f96fc8d5ea9b7"


class CandidateContractError(ValueError):
    """The candidate package is inconsistent or no longer isolated."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CandidateContractError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
    )
    if not isinstance(value, dict):
        raise CandidateContractError(f"{path.name}: root must be an object")
    return value


def _unique_ids(values: list[Any], label: str) -> set[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or PLAIN_ID.fullmatch(value) is None:
            raise CandidateContractError(f"{label}: invalid id {value!r}")
        result.append(value)
    if len(result) != len(set(result)):
        raise CandidateContractError(f"{label}: duplicate ids")
    return set(result)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _all_source_claims(package: dict[str, Any]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    for capability in package["new_capabilities"]:
        claims.extend(capability["source_claims"])
    for enrichment in package["enrichments"]:
        claims.extend(enrichment["source_claims_add"])
    for discrepancy in package["discrepancies"]:
        claims.extend(discrepancy["source_claims"])
    for guardrail in package["guardrails"]:
        claims.extend(guardrail["source_claims"])
    return claims


def _validate_live_hashes(package: dict[str, Any], repo_root: Path) -> None:
    expected_paths = {
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "deploy/docker/thor-local/parity/manifest.json",
        "deploy/docker/thor-local/parity/capability-oracles.json",
        "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    }
    actual_paths = {item["path"] for item in package["live_inputs"]}
    if actual_paths != expected_paths:
        raise CandidateContractError("live input set drift")
    resolved_root = repo_root.resolve(strict=True)
    for item in package["live_inputs"]:
        path = repo_root / item["path"]
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise CandidateContractError(f"unsafe or missing live input {item['path']}") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise CandidateContractError(f"live input is not a regular file: {item['path']}")
        if _sha256(resolved) != item["sha256"]:
            raise CandidateContractError(f"live input hash drift: {item['path']}")


def validate(
    package: dict[str, Any] | None = None,
    *,
    live_ledger: dict[str, Any] | None = None,
    live_manifest: dict[str, Any] | None = None,
    live_acceptance: dict[str, Any] | None = None,
    check_live_hashes: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    package = load_json(CANDIDATE) if package is None else package
    live_ledger = load_json(LIVE_LEDGER) if live_ledger is None else live_ledger
    live_manifest = load_json(LIVE_MANIFEST) if live_manifest is None else live_manifest
    live_acceptance = load_json(LIVE_ACCEPTANCE) if live_acceptance is None else live_acceptance
    schema = load_json(SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CandidateContractError(f"invalid candidate schema: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(package),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise CandidateContractError(
            f"candidate schema violation at {location}: {error.message}"
        )

    if package["expected_counts"] != EXPECTED_COUNTS:
        raise CandidateContractError("expected count contract drift")
    actual_counts = {
        "reviewed_pages": len(package["sources"]),
        "claim_bearing_sources": sum(
            item["classification"] == "claim_bearing" for item in package["sources"]
        ),
        "new_capabilities": len(package["new_capabilities"]),
        "enrichments": len(package["enrichments"]),
        "discrepancies": len(package["discrepancies"]),
        "guardrails": len(package["guardrails"]),
    }
    if actual_counts != EXPECTED_COUNTS:
        raise CandidateContractError(f"exact count drift: {actual_counts}")
    if Counter(item["classification"] for item in package["sources"]) != Counter(
        EXPECTED_SOURCE_CLASSES
    ):
        raise CandidateContractError("source classification count drift")

    source_ids = _unique_ids([item["id"] for item in package["sources"]], "sources")
    source_uris = [item["uri"] for item in package["sources"]]
    if len(source_uris) != len(set(source_uris)):
        raise CandidateContractError("sources: duplicate URIs")
    stale_urls = set(source_uris) & STALE_SOURCE_URLS
    if stale_urls:
        raise CandidateContractError(f"stale non-reachable source URL: {sorted(stale_urls)[0]}")
    fixed_point_graph = load_json(FIXED_POINT_GRAPH)
    reachable_urls = set(fixed_point_graph.get("targets", []))
    outside_graph = set(source_uris) - reachable_urls
    if outside_graph:
        raise CandidateContractError(
            f"source is outside fixed-point URL graph: {sorted(outside_graph)[0]}"
        )
    source_by_id = {item["id"]: item for item in package["sources"]}
    new_ids = _unique_ids(
        [item["id"] for item in package["new_capabilities"]], "new_capabilities"
    )
    enrichment_ids = _unique_ids(
        [item["target_id"] for item in package["enrichments"]], "enrichments"
    )
    _unique_ids([item["id"] for item in package["discrepancies"]], "discrepancies")
    _unique_ids([item["id"] for item in package["guardrails"]], "guardrails")

    if package["target"] != live_ledger.get("target"):
        raise CandidateContractError("candidate and live target identities differ")
    live_capability_ids = {
        item.get("id") for item in live_ledger.get("capabilities", []) if isinstance(item, dict)
    }
    overlap = new_ids & live_capability_ids
    if overlap:
        raise CandidateContractError(
            f"isolated new capability already exists live: {sorted(overlap)[0]}"
        )
    missing_enrichments = enrichment_ids - live_capability_ids
    if missing_enrichments:
        raise CandidateContractError(
            f"enrichment target missing from live ledger: {sorted(missing_enrichments)[0]}"
        )

    feature_ids = {
        item.get("id") for item in live_manifest.get("features", []) if isinstance(item, dict)
    }
    scenario_ids = {
        item.get("id") for item in live_acceptance.get("scenarios", []) if isinstance(item, dict)
    }
    status_contract = live_manifest.get("status_contract", {})
    fixture_ids: list[str] = []
    for record in [*package["new_capabilities"], *package["enrichments"]]:
        if "feature_id" in record and record["feature_id"] not in feature_ids:
            raise CandidateContractError(
                f"{record['id']}: unknown feature family {record['feature_id']!r}"
            )
        unknown_scenarios = set(record["qualification"]["scenario_ids"]) - scenario_ids
        if unknown_scenarios:
            record_id = record.get("id", record.get("target_id"))
            raise CandidateContractError(
                f"{record_id}: unknown scenario {sorted(unknown_scenarios)[0]}"
            )
        fixture_ids.extend(item["id"] for item in record["qualification"]["fixtures"])
        if "status" in record:
            for key in ("acceptance_class", "thor_state", "runtime_state"):
                if record["status"][key] not in status_contract.get(key, []):
                    raise CandidateContractError(f"{record['id']}: invalid {key}")
            if record["status"]["runtime_state"] in {"passed_current", "passed_prior"}:
                raise CandidateContractError(
                    f"{record['id']}: extraction cannot claim runtime pass evidence"
                )
    _unique_ids(fixture_ids, "fixtures")

    referenced_source_ids = {claim["source_id"] for claim in _all_source_claims(package)}
    unknown_sources = referenced_source_ids - source_ids
    if unknown_sources:
        raise CandidateContractError(f"unknown source claim: {sorted(unknown_sources)[0]}")
    non_claim_sources = {
        source_id
        for source_id in referenced_source_ids
        if source_by_id[source_id]["classification"] != "claim_bearing"
    }
    if non_claim_sources:
        raise CandidateContractError(
            f"non-claim-bearing page used as claim source: {sorted(non_claim_sources)[0]}"
        )
    expected_claim_sources = {
        item["id"] for item in package["sources"] if item["classification"] == "claim_bearing"
    }
    if referenced_source_ids != expected_claim_sources:
        missing = expected_claim_sources - referenced_source_ids
        raise CandidateContractError(
            f"claim-bearing source has no machine-readable claim: {sorted(missing)[0]}"
        )

    if package["scope"] != {
        "warehouse_sample_bundle": "excluded",
        "smart_city_sample_bundle": "optional_demo_only",
        "operator_custom_data": "in_scope",
        "live_files_untouched": True,
    }:
        raise CandidateContractError("sample exclusion or custom-data scope drift")
    capability_by_id = {item["id"]: item for item in package["new_capabilities"]}
    prereq = capability_by_id["prereq.smart-city.reference-platform"]["contract"]
    if prereq.get("architecture") != "x86_64" or prereq.get("official_thor_support") is not False:
        raise CandidateContractError("official Smart City Thor support boundary drift")
    custom_location = capability_by_id["configuration.smart-city.custom-location"]["contract"]
    if custom_location.get("bundled_sample_required") is not False:
        raise CandidateContractError("Smart City bundled sample became required")
    synthetic_data = capability_by_id["tooling.smart-city.synthetic-data-pipeline"]["contract"]
    if synthetic_data.get("runtime_dependency") is not False:
        raise CandidateContractError("Smart City SDG became a runtime dependency")
    external_development_status = {
        "acceptance_class": "external_optional",
        "thor_state": "external_optional",
        "runtime_state": "not_applicable",
    }
    for capability_id in (
        "tooling.smart-city.synthetic-data-pipeline",
        "customization.smart-city.trafficcamnet-rtdetr",
    ):
        if capability_by_id[capability_id]["status"] != external_development_status:
            raise CandidateContractError(
                f"{capability_id}: external development boundary drift"
            )
    maps = capability_by_id["boundary.smart-city.google-maps-dependency"]["contract"]
    if maps.get("alternate_is_not_official_google_map_parity") is not True:
        raise CandidateContractError("Google Maps/local alternate boundary drift")
    model_recipe = capability_by_id["customization.smart-city.trafficcamnet-rtdetr"]["contract"]
    if model_recipe.get("vlm_fine_tuning") != "forthcoming":
        raise CandidateContractError("forthcoming VLM fine-tuning boundary drift")
    nemo_recovery = capability_by_id[
        "behavior.nemoclaw.recovery-and-destructive-boundaries"
    ]["contract"]
    if nemo_recovery.get("deep_clean_requires_explicit_authorization") is not True:
        raise CandidateContractError("NemoClaw destructive authorization boundary drift")
    limitations = capability_by_id["behavior.smart-city.known-limitations"]["contract"]
    if limitations.get("must_not_claim_remediated") is not True:
        raise CandidateContractError("Smart City limitations boundary drift")

    guardrail_ids = {item["id"] for item in package["guardrails"]}
    if guardrail_ids != {
        "guardrail.sample-bundles-optional",
        "guardrail.operator-custom-data",
        "guardrail.google-maps-external",
        "guardrail.vlm-fine-tuning-forthcoming",
    }:
        raise CandidateContractError("guardrail set drift")
    if _canonical_sha256(package) != EXPECTED_CANDIDATE_SHA256:
        raise CandidateContractError("candidate content digest drift")
    if check_live_hashes:
        _validate_live_hashes(package, repo_root)
    return actual_counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        counts = validate()
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        StopIteration,
        CandidateContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: Agent and Smart City Wave3 candidate is strict, isolated, and sample-safe")
    if args.report:
        print(", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
