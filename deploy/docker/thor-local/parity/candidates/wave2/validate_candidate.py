#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed validation for the VSS wave-2 extraction and merge lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


SCRIPT_DIR = Path(__file__).resolve().parent
PARITY_DIR = SCRIPT_DIR.parents[1]
REPO_ROOT = SCRIPT_DIR.parents[5]
CANDIDATE = SCRIPT_DIR / "candidate.json"
SCHEMA = SCRIPT_DIR / "candidate.schema.json"
LIVE_LEDGER = PARITY_DIR / "official-capabilities.json"
LIVE_MANIFEST = PARITY_DIR / "manifest.json"
LIVE_ACCEPTANCE = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
EXPECTED_COUNTS = {
    "new_capabilities": 30,
    "enrichments": 9,
    "discrepancies_and_boundaries": 14,
}

ALLOWED_LIVE_THOR_TRANSITIONS = {
    "source_only": {"source_only", "partial", "wired"},
    "partial": {"partial", "wired"},
    "wired": {"wired"},
    "external_optional": {"external_optional"},
    "blocked_upstream": {"blocked_upstream"},
}
ALLOWED_LIVE_RUNTIME_TRANSITIONS = {
    "blocked": {
        "blocked",
        "not_qualified",
        "static_only",
        "passed_prior",
        "passed_current",
    },
    "not_qualified": {
        "not_qualified",
        "static_only",
        "passed_prior",
        "passed_current",
    },
    "static_only": {"static_only", "passed_prior", "passed_current"},
    "passed_prior": {"passed_prior", "passed_current"},
    "passed_current": {"passed_current"},
    "not_applicable": {"not_applicable"},
}


class CandidateContractError(ValueError):
    """The candidate package or its live merge is inconsistent."""


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


def _ids(values: list[Any], label: str) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or PLAIN_ID.fullmatch(value) is None:
            raise CandidateContractError(f"{label}: invalid id {value!r}")
        result.append(value)
    if len(result) != len(set(result)):
        raise CandidateContractError(f"{label}: duplicate ids")
    return result


def _claim_items(package: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for capability in package["new_capabilities"]:
        for claim in capability["source_claims"]:
            if claim["source_id"] == source_id:
                claims.append(
                    {
                        "record_type": "new_capability",
                        "record_id": capability["id"],
                        "locator": claim["locator"],
                        "contract": capability["contract"],
                    }
                )
    for enrichment in package["enrichments"]:
        for claim in enrichment["source_claims_add"]:
            if claim["source_id"] == source_id:
                claims.append(
                    {
                        "record_type": "enrichment",
                        "record_id": enrichment["target_id"],
                        "locator": claim["locator"],
                        "contract": enrichment["contract_merge"],
                    }
                )
    for discrepancy in package["discrepancies_and_boundaries"]:
        for claim in discrepancy["source_claims"]:
            if claim["source_id"] == source_id:
                claims.append(
                    {
                        "record_type": "discrepancy_or_boundary",
                        "record_id": discrepancy["id"],
                        "locator": claim["locator"],
                        "contract": {
                            "category": discrepancy["category"],
                            "resolution": discrepancy["resolution"],
                            "must_not_claim": discrepancy["must_not_claim"],
                        },
                    }
                )
    return claims


def source_claim_hashes(package: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in package["sources"]:
        source_id = source["id"]
        claims = _claim_items(package, source_id)
        canonical = sorted(
            json.dumps(item, sort_keys=True, separators=(",", ":")) for item in claims
        )
        result[source_id] = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":")).encode()
        ).hexdigest()
    return result


def _validate_expected_manifest(
    path_value: str, repo_root: Path, capability_id: str
) -> None:
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise CandidateContractError(f"{capability_id}: unsafe expected manifest path")
    candidate = repo_root / relative
    try:
        resolved_root = repo_root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise CandidateContractError(
            f"{capability_id}: expected manifest path is missing or unsafe"
        ) from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise CandidateContractError(
            f"{capability_id}: expected manifest must be a regular non-symlink file"
        )


def _is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _is_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(value in actual for value in expected)
    return expected == actual


def validate(
    package: dict[str, Any] | None = None,
    *,
    live_ledger: dict[str, Any] | None = None,
    live_manifest: dict[str, Any] | None = None,
    live_acceptance: dict[str, Any] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    package = load_json(CANDIDATE) if package is None else package
    live_ledger = load_json(LIVE_LEDGER) if live_ledger is None else live_ledger
    live_manifest = load_json(LIVE_MANIFEST) if live_manifest is None else live_manifest
    live_acceptance = (
        load_json(LIVE_ACCEPTANCE) if live_acceptance is None else live_acceptance
    )
    schema = load_json(SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CandidateContractError(
            f"invalid candidate schema: {exc.message}"
        ) from exc
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(package),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise CandidateContractError(
            f"candidate schema violation at {location}: {error.message}"
        )

    for key, expected in EXPECTED_COUNTS.items():
        if package["expected_counts"][key] != expected or len(package[key]) != expected:
            raise CandidateContractError(f"{key}: exact count must remain {expected}")

    source_ids = _ids([item["id"] for item in package["sources"]], "sources")
    new_ids = _ids(
        [item["id"] for item in package["new_capabilities"]],
        "new_capabilities",
    )
    enrichment_ids = _ids(
        [item["target_id"] for item in package["enrichments"]],
        "enrichments",
    )
    _ids(
        [item["id"] for item in package["discrepancies_and_boundaries"]],
        "discrepancies_and_boundaries",
    )

    live_capability_ids = {
        item.get("id")
        for item in live_ledger.get("capabilities", [])
        if isinstance(item, dict)
    }
    overlap = set(new_ids) & live_capability_ids
    if overlap and overlap != set(new_ids):
        raise CandidateContractError(
            f"partial live merge detected at capability: {sorted(overlap)[0]}"
        )
    merged = overlap == set(new_ids)
    if package["target"] != live_ledger.get("target"):
        raise CandidateContractError("candidate and live target identities differ")
    missing_enrichments = set(enrichment_ids) - live_capability_ids
    if missing_enrichments:
        raise CandidateContractError(
            f"enrichment target missing from live ledger: {sorted(missing_enrichments)[0]}"
        )

    feature_by_id = {
        item.get("id"): item
        for item in live_manifest.get("features", [])
        if isinstance(item, dict)
    }
    scenario_ids = {
        item.get("id")
        for item in live_acceptance.get("scenarios", [])
        if isinstance(item, dict)
    }
    status_contract = live_manifest.get("status_contract", {})
    for capability in package["new_capabilities"]:
        capability_id = capability["id"]
        if capability["feature_id"] not in feature_by_id:
            raise CandidateContractError(
                f"{capability_id}: unknown live feature family {capability['feature_id']!r}"
            )
        if not set(capability["scenario_ids"]) <= scenario_ids:
            raise CandidateContractError(
                f"{capability_id}: unknown acceptance scenario"
            )
        status = capability["status"]
        for key in ("acceptance_class", "thor_state", "runtime_state"):
            if status[key] not in status_contract.get(key, []):
                raise CandidateContractError(f"{capability_id}: invalid {key}")
        if status["runtime_state"] == "passed_current":
            raise CandidateContractError(
                f"{capability_id}: isolated extraction cannot claim passed_current"
            )
        binding = capability["expected_manifest_binding"]
        if binding["semantic_coverage"] is not False:
            raise CandidateContractError(
                f"{capability_id}: API manifest cannot provide semantic coverage"
            )
        if binding["path"] is not None:
            _validate_expected_manifest(binding["path"], repo_root, capability_id)
        for claim in capability["source_claims"]:
            if claim["source_id"] not in source_ids:
                raise CandidateContractError(f"{capability_id}: unknown source")

    for enrichment in package["enrichments"]:
        for claim in enrichment["source_claims_add"]:
            if claim["source_id"] not in source_ids:
                raise CandidateContractError(
                    f"{enrichment['target_id']}: unknown enrichment source"
                )
    for discrepancy in package["discrepancies_and_boundaries"]:
        for claim in discrepancy["source_claims"]:
            if claim["source_id"] not in source_ids:
                raise CandidateContractError(
                    f"{discrepancy['id']}: unknown discrepancy source"
                )

    auto_boundary = next(
        item
        for item in package["new_capabilities"]
        if item["id"] == "boundary.auto-calibration.thor-extension"
    )
    if (
        auto_boundary["contract"].get("official_architecture") != "x86_64"
        or auto_boundary["contract"].get("must_not_claim_official_thor_support")
        is not True
    ):
        raise CandidateContractError("Auto Calibration Thor support boundary drift")
    security = next(
        item
        for item in package["new_capabilities"]
        if item["id"] == "security.known-unmitigated-limitations"
    )
    if security["contract"].get("must_not_claim_remediated") is not True:
        raise CandidateContractError("security limitation boundary drift")
    if package["scope"] != {
        "warehouse_sample_bundle": "excluded",
        "warehouse_custom_data": "in_scope",
        "live_files_untouched": True,
    }:
        raise CandidateContractError("candidate scope boundary drift")

    computed_hashes = source_claim_hashes(package)
    for source in package["sources"]:
        claims = _claim_items(package, source["id"])
        if not claims:
            raise CandidateContractError(f"{source['id']}: source has no claim")
        if source["claim_set_sha256"] != computed_hashes[source["id"]]:
            raise CandidateContractError(f"{source['id']}: source claim hash drift")

    if merged:
        live_source_by_uri = {
            item.get("uri"): item
            for item in live_ledger.get("sources", [])
            if isinstance(item, dict)
        }
        source_uri_by_id = {item["id"]: item["uri"] for item in package["sources"]}
        if not set(source_uri_by_id.values()) <= set(live_source_by_uri):
            raise CandidateContractError("merged live ledger is missing a wave-2 source")
        live_capability_by_id = {
            item["id"]: item for item in live_ledger["capabilities"]
        }
        feature_by_id = {item["id"]: item for item in live_manifest["features"]}
        coverage_by_id = {
            item["feature_id"]: item
            for item in live_acceptance["coverage"]["features"]
        }
        for proposed in package["new_capabilities"]:
            live = live_capability_by_id[proposed["id"]]
            if live.get("acceptance_class") != proposed["status"]["acceptance_class"]:
                raise CandidateContractError(
                    f"{proposed['id']}: merged live acceptance_class drift"
                )
            candidate_thor = proposed["status"]["thor_state"]
            if live.get("thor_state") not in ALLOWED_LIVE_THOR_TRANSITIONS[
                candidate_thor
            ]:
                raise CandidateContractError(
                    f"{proposed['id']}: merged live thor_state regression"
                )
            candidate_runtime = proposed["status"]["runtime_state"]
            if live.get("runtime_state") not in ALLOWED_LIVE_RUNTIME_TRANSITIONS[
                candidate_runtime
            ]:
                raise CandidateContractError(
                    f"{proposed['id']}: merged live runtime_state regression"
                )
            if not _is_subset(proposed["contract"], live.get("contract")):
                raise CandidateContractError(
                    f"{proposed['id']}: merged live contract drift"
                )
            if (
                live["contract"].get("related_expected_manifest_semantic_coverage")
                is not False
            ):
                raise CandidateContractError(
                    f"{proposed['id']}: live API manifest implies semantic coverage"
                )
            live_claim_uris = {
                next(
                    item["uri"]
                    for item in live_ledger["sources"]
                    if item["id"] == claim["source_id"]
                )
                for claim in live["source_claims"]
            }
            expected_claim_uris = {
                source_uri_by_id[claim["source_id"]]
                for claim in proposed["source_claims"]
            }
            if not expected_claim_uris <= live_claim_uris:
                raise CandidateContractError(
                    f"{proposed['id']}: merged live source-claim drift"
                )
            feature = feature_by_id[proposed["feature_id"]]
            if (
                proposed["id"] not in feature.get("official_capability_ids", [])
                or proposed["title"] not in feature.get("advertised", [])
                or not set(proposed["scenario_ids"])
                <= set(coverage_by_id[proposed["feature_id"]]["scenario_ids"])
            ):
                raise CandidateContractError(
                    f"{proposed['id']}: merged manifest/acceptance cross-link drift"
                )
        live_discrepancies = {
            item.get("id")
            for item in live_ledger.get("source_discrepancies", [])
            if isinstance(item, dict)
        }
        proposed_discrepancies = {
            item["id"] for item in package["discrepancies_and_boundaries"]
        }
        if not proposed_discrepancies <= live_discrepancies:
            raise CandidateContractError("merged live discrepancy coverage drift")

    return {
        "sources": len(package["sources"]),
        "new_capabilities": len(package["new_capabilities"]),
        "enrichments": len(package["enrichments"]),
        "discrepancies_and_boundaries": len(package["discrepancies_and_boundaries"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--print-source-hashes", action="store_true")
    args = parser.parse_args()
    try:
        package = load_json(CANDIDATE)
        if args.print_source_hashes:
            print(json.dumps(source_claim_hashes(package), indent=2, sort_keys=True))
            return 0
        counts = validate(package)
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        StopIteration,
        CandidateContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: wave-2 extraction is strict, counted, and lifecycle-safe")
    if args.report:
        print(", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
