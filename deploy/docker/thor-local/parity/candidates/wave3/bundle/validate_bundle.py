#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed validation for the Wave 3 candidate merge plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[6]
PLAN = SCRIPT_DIR / "merge-plan.json"
SCHEMA = SCRIPT_DIR / "merge-plan.schema.json"
EXPECTED_PLAN_CANONICAL_SHA256 = "7c61cb7569f095c66a8590ef56b323364643899271a460b7c375abbc6adb0fea"
EXPECTED_INPUT_PATHS = {
    "live-ledger": "deploy/docker/thor-local/parity/official-capabilities.json",
    "source-lock": "deploy/docker/thor-local/parity/source-lock/source-lock.json",
    "recursive-targets": (
        "deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/"
        "recursive-targets.json"
    ),
    "agent-smartcity": (
        "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json"
    ),
    "systems": "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json",
    "calibration-warehouse": (
        "deploy/docker/thor-local/parity/candidates/wave3/"
        "calibration-warehouse/candidate.json"
    ),
    "systems-broker-evidence": (
        "deploy/docker/thor-local/parity/candidates/wave3/systems/"
        "evidence/broker-topic-contracts.json"
    ),
    "systems-nvstreamer-evidence": (
        "deploy/docker/thor-local/parity/candidates/wave3/systems/"
        "evidence/nvstreamer-config-contract.json"
    ),
    "systems-performance-evidence": (
        "deploy/docker/thor-local/parity/candidates/wave3/systems/"
        "evidence/performance-reference-contracts.json"
    ),
}
PACKAGE_ORDER = ("live-ledger", "agent-smartcity", "systems", "calibration-warehouse")
EXPECTED_COUNTS = {
    "source_lock_urls": 172,
    "live_source_records": 55,
    "candidate_source_records": 96,
    "all_source_records": 151,
    "duplicate_source_records": 11,
    "proposed_unique_sources": 140,
    "live_capabilities": 161,
    "new_capability_records": 115,
    "proposed_capabilities": 276,
    "enrichment_records": 46,
    "unique_enrichment_targets": 44,
    "approved_enrichment_collisions": 2,
    "live_discrepancies": 18,
    "new_discrepancy_records": 27,
    "proposed_discrepancies": 45,
    "unique_proposed_discrepancies": 45,
    "guardrail_records": 10,
    "unique_guardrails": 10,
    "agent_fixture_records": 41,
    "systems_acceptance_fixture_records": 55,
    "systems_performance_fixture_records": 7,
    "calibration_acceptance_vectors": 7,
    "candidate_fixture_records": 110,
    "unique_candidate_fixtures": 110,
}
EXPECTED_NORMALIZATIONS = {
    "calibration.sdg.workflow": {
        "acceptance_class": "external_optional",
        "thor_state": "source_only",
        "runtime_state": "not_applicable",
    },
    "customization.smart-city.trafficcamnet-rtdetr": {
        "acceptance_class": "external_optional",
        "thor_state": "external_optional",
        "runtime_state": "not_applicable",
    },
    "tooling.smart-city.synthetic-data-pipeline": {
        "acceptance_class": "external_optional",
        "thor_state": "external_optional",
        "runtime_state": "not_applicable",
    },
}
EXPECTED_SOURCE_ID_RENAMES = [
    {
        "input_id": "agent-smartcity",
        "from_source_id": "video-analytics-mcp-doc-3.2.1",
        "to_source_id": "agent-video-analytics-mcp-doc-3.2.1",
        "uri": (
            "https://docs.nvidia.com/vss/3.2.1/"
            "vss-agent/Video-Analytics-MCP-Server.html"
        ),
        "claim_reference_count": 1,
        "reason": "same_source_id_distinct_uri",
    }
]


class BundleContractError(ValueError):
    """A bound input or merge decision is malformed, ambiguous, or stale."""


def _reject_constant(value: str) -> None:
    raise BundleContractError(f"non-finite JSON number is forbidden: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleContractError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleContractError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BundleContractError(f"{path}: root must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_schema(plan: dict[str, Any]) -> None:
    schema = load_json(SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise BundleContractError(f"invalid merge-plan schema: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(plan),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise BundleContractError(
            f"merge-plan schema violation at {location}: {error.message}"
        )


def _load_bound_inputs(
    plan: dict[str, Any], repo_root: Path, check_input_hashes: bool
) -> dict[str, dict[str, Any]]:
    input_by_id = {item["id"]: item for item in plan["inputs"]}
    if len(input_by_id) != len(plan["inputs"]):
        raise BundleContractError("duplicate input IDs")
    if {key: value["path"] for key, value in input_by_id.items()} != EXPECTED_INPUT_PATHS:
        raise BundleContractError("input path set drift")

    root = repo_root.resolve(strict=True)
    documents: dict[str, dict[str, Any]] = {}
    for input_id, expected_path in EXPECTED_INPUT_PATHS.items():
        path = (repo_root / expected_path).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise BundleContractError(f"unsafe input path: {expected_path}") from exc
        if not path.is_file() or path.is_symlink():
            raise BundleContractError(f"input is not a regular file: {expected_path}")
        document = load_json(path)
        binding = input_by_id[input_id]
        if check_input_hashes and _sha256(path) != binding["sha256"]:
            raise BundleContractError(f"raw input hash drift: {input_id}")
        if _canonical_sha256(document) != binding["canonical_sha256"]:
            raise BundleContractError(f"canonical input hash drift: {input_id}")
        documents[input_id] = document
    return documents


def _candidate_sources(
    input_id: str, document: dict[str, Any]
) -> list[dict[str, str]]:
    url_key = "url" if input_id == "systems" else "uri"
    return [
        {"input_id": input_id, "source_id": item["id"], "uri": item[url_key]}
        for item in document["sources"]
    ]


def _new_capabilities(input_id: str, document: dict[str, Any]) -> list[dict[str, Any]]:
    key = "proposed_capabilities" if input_id == "systems" else "new_capabilities"
    return document[key]


def _discrepancies(input_id: str, document: dict[str, Any]) -> list[dict[str, Any]]:
    key = "discrepancies_and_boundaries" if input_id == "systems" else "discrepancies"
    return document[key]


def _fixture_ids(documents: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    agent = documents["agent-smartcity"]
    agent_ids = [
        fixture["id"]
        for record in [*agent["new_capabilities"], *agent["enrichments"]]
        for fixture in record["qualification"]["fixtures"]
    ]
    systems_ids = [
        item["id"] for item in documents["systems"]["performance_fixture_requirements"]
    ]
    systems_acceptance_ids = [
        item["acceptance"]["fixture_id"]
        for item in documents["systems"]["proposed_capabilities"]
    ]
    calibration_ids = [
        item["id"] for item in documents["calibration-warehouse"]["acceptance_vectors"]
    ]
    return {
        "agent-smartcity": agent_ids,
        "systems-acceptance": systems_acceptance_ids,
        "systems-performance": systems_ids,
        "calibration-warehouse": calibration_ids,
    }


def _source_claim_reference_count(document: Any, source_id: str) -> int:
    if isinstance(document, dict):
        own = int(document.get("source_id") == source_id)
        return own + sum(
            _source_claim_reference_count(value, source_id) for value in document.values()
        )
    if isinstance(document, list):
        return sum(_source_claim_reference_count(value, source_id) for value in document)
    return 0


def _source_claim_ids(document: Any) -> list[str]:
    if isinstance(document, dict):
        result = [document["source_id"]] if "source_id" in document else []
        for value in document.values():
            result.extend(_source_claim_ids(value))
        return result
    if isinstance(document, list):
        return [item for value in document for item in _source_claim_ids(value)]
    return []


def _validate_candidate_source_references(
    documents: dict[str, dict[str, Any]],
) -> None:
    for input_id in PACKAGE_ORDER[1:]:
        source_ids = {
            item["source_id"]
            for item in _candidate_sources(input_id, documents[input_id])
        }
        unknown = set(_source_claim_ids(documents[input_id])) - source_ids
        if unknown:
            raise BundleContractError(
                f"{input_id} has an unknown source claim: {sorted(unknown)[0]}"
            )


def _computed_source_merge(
    plan: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    reachable: set[str],
    locked: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    renames = plan["source_merge"]["source_id_renames"]
    if renames != EXPECTED_SOURCE_ID_RENAMES:
        raise BundleContractError("same-ID/different-URI source rename drift")
    rename_by_input_id = {
        (item["input_id"], item["from_source_id"]): item for item in renames
    }
    for rename in renames:
        existing_ids = {
            source["source_id"]
            for input_id in PACKAGE_ORDER
            for source in _candidate_sources(input_id, documents[input_id])
        }
        if rename["to_source_id"] in existing_ids:
            raise BundleContractError("source rename destination already exists")
        source_matches = [
            item
            for item in _candidate_sources(
                rename["input_id"], documents[rename["input_id"]]
            )
            if item["source_id"] == rename["from_source_id"]
            and item["uri"] == rename["uri"]
        ]
        if len(source_matches) != 1:
            raise BundleContractError("source rename does not resolve exactly one source")
        actual_refs = _source_claim_reference_count(
            documents[rename["input_id"]], rename["from_source_id"]
        )
        if actual_refs != rename["claim_reference_count"]:
            raise BundleContractError(
                "source rename does not remap every candidate claim reference"
            )

    by_uri: dict[str, list[dict[str, str]]] = defaultdict(list)
    id_to_uri: dict[str, str] = {}
    for input_id in PACKAGE_ORDER:
        for source in _candidate_sources(input_id, documents[input_id]):
            # The 172-page byte lock covers the official versioned documentation
            # site. Pre-existing live sources may intentionally be upstream GitHub,
            # NGC, or repository evidence; every Wave 3 candidate source must be in
            # both exact sets.
            if input_id != "live-ledger" and (
                source["uri"] not in reachable or source["uri"] not in locked
            ):
                raise BundleContractError(
                    f"source outside recursive/source lock: {source['uri']}"
                )
            rename = rename_by_input_id.get((input_id, source["source_id"]))
            effective_source_id = rename["to_source_id"] if rename else source["source_id"]
            previous_uri = id_to_uri.setdefault(effective_source_id, source["uri"])
            if previous_uri != source["uri"]:
                raise BundleContractError(
                    f"source ID maps to multiple URIs: {effective_source_id}"
                )
            by_uri[source["uri"]].append(source)

    resolutions: list[dict[str, Any]] = []
    remaps: list[dict[str, str]] = []
    for uri, contributors in sorted(by_uri.items()):
        if len(contributors) < 2:
            continue
        live = [item for item in contributors if item["input_id"] == "live-ledger"]
        canonical = live[0] if live else contributors[0]
        resolution = {
            "uri": uri,
            "canonical_source_id": canonical["source_id"],
            "contributors": [
                {"input_id": item["input_id"], "source_id": item["source_id"]}
                for item in contributors
            ],
        }
        resolutions.append(resolution)
        for item in contributors:
            if item["source_id"] != canonical["source_id"]:
                remaps.append(
                    {
                        "input_id": item["input_id"],
                        "from_source_id": item["source_id"],
                        "to_source_id": canonical["source_id"],
                        "uri": uri,
                        "claim_reference_count": _source_claim_reference_count(
                            documents[item["input_id"]], item["source_id"]
                        ),
                    }
                )
    return resolutions, remaps, len(by_uri)


def _validate_capability_merge(
    plan: dict[str, Any], documents: dict[str, dict[str, Any]]
) -> tuple[int, int]:
    live_ids = [item["id"] for item in documents["live-ledger"]["capabilities"]]
    if len(live_ids) != len(set(live_ids)):
        raise BundleContractError("live capability IDs are not unique")

    new_owners: dict[str, list[str]] = defaultdict(list)
    for input_id in PACKAGE_ORDER[1:]:
        records = _new_capabilities(input_id, documents[input_id])
        record_ids = [item["id"] for item in records]
        if len(record_ids) != len(set(record_ids)):
            raise BundleContractError(f"duplicate new capability ID inside {input_id}")
        for capability_id in record_ids:
            new_owners[capability_id].append(input_id)
    collisions = {
        capability_id: owners
        for capability_id, owners in new_owners.items()
        if len(owners) > 1 or capability_id in live_ids
    }
    if collisions:
        capability_id = sorted(collisions)[0]
        raise BundleContractError(f"unapproved capability collision: {capability_id}")

    enrichment_by_target: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for input_id in PACKAGE_ORDER[1:]:
        records = documents[input_id]["enrichments"]
        target_ids = [item["target_id"] for item in records]
        if len(target_ids) != len(set(target_ids)):
            raise BundleContractError(f"duplicate enrichment target inside {input_id}")
        for record in records:
            if record["target_id"] not in live_ids:
                raise BundleContractError(
                    f"enrichment target is absent live: {record['target_id']}"
                )
            enrichment_by_target[record["target_id"]].append((input_id, record))

    actual_collision_targets = {
        target for target, records in enrichment_by_target.items() if len(records) > 1
    }
    planned_collision_targets = {
        item["target_id"] for item in plan["capability_merge"]["approved_enrichment_collisions"]
    }
    if actual_collision_targets != planned_collision_targets:
        raise BundleContractError("approved enrichment collision set drift")

    collision_by_target = {
        item["target_id"]: item
        for item in plan["capability_merge"]["approved_enrichment_collisions"]
    }
    api_records = dict(enrichment_by_target["api.core.video-analytics-56"])
    api_plan = collision_by_target["api.core.video-analytics-56"]
    if set(api_records) != {"agent-smartcity", "systems"}:
        raise BundleContractError("Video Analytics enrichment contributors drift")
    if set(api_records["agent-smartcity"]["contract_merge"]) != {"smart_city_uploads"}:
        raise BundleContractError("Smart City upload contract was not preserved exactly")
    if set(api_records["systems"]["contract_merge"]) != {"query_families"}:
        raise BundleContractError("Systems query-family contract was not preserved exactly")
    if api_plan["merge_policy"] != "deep_merge_disjoint" or api_plan[
        "required_contract_keys"
    ] != {
        "agent-smartcity": ["smart_city_uploads"],
        "systems": ["query_families"],
    } or api_plan["contributors"] != ["agent-smartcity", "systems"]:
        raise BundleContractError("Video Analytics merge decision drift")

    calibration_records = dict(enrichment_by_target["calibration.sdg.workflow"])
    calibration_plan = collision_by_target["calibration.sdg.workflow"]
    if set(calibration_records) != {"agent-smartcity", "calibration-warehouse"}:
        raise BundleContractError("SDG calibration enrichment contributors drift")
    agent_contract = calibration_records["agent-smartcity"]["contract_merge"]
    warehouse_contract = calibration_records["calibration-warehouse"]["contract_merge"]
    expected_union = list(
        dict.fromkeys([*agent_contract["outputs"], *warehouse_contract["outputs"]])
    )
    if calibration_plan["merge_policy"] != "deep_merge_with_explicit_output_union":
        raise BundleContractError("SDG calibration merge policy drift")
    if calibration_plan["contributors"] != [
        "agent-smartcity",
        "calibration-warehouse",
    ] or calibration_plan["required_contract_keys"] != {
        "agent-smartcity": sorted(agent_contract),
        "calibration-warehouse": sorted(warehouse_contract),
    }:
        raise BundleContractError("SDG calibration contributor/key decision drift")
    if calibration_plan["output_union"] != expected_union:
        raise BundleContractError("SDG calibration outputs were not preserved as a union")
    if warehouse_contract.get("acceptance_class_correction") != "external_optional":
        raise BundleContractError("SDG calibration external boundary was lost")
    if calibration_plan["resolved_status"] != EXPECTED_NORMALIZATIONS[
        "calibration.sdg.workflow"
    ]:
        raise BundleContractError("SDG calibration status resolution drift")

    return len(new_owners), len(enrichment_by_target)


def _validate_normalizations(
    plan: dict[str, Any], documents: dict[str, dict[str, Any]]
) -> None:
    records = {
        item["id"]: item
        for item in documents["agent-smartcity"]["new_capabilities"]
    }
    for capability_id in (
        "tooling.smart-city.synthetic-data-pipeline",
        "customization.smart-city.trafficcamnet-rtdetr",
    ):
        if records[capability_id]["status"] != EXPECTED_NORMALIZATIONS[capability_id]:
            raise BundleContractError(
                f"Smart City external-optional normalization drift: {capability_id}"
            )
    actual = {
        item["target_id"]: item["resolved_status"]
        for item in plan["status_normalizations"]
    }
    if actual != EXPECTED_NORMALIZATIONS:
        raise BundleContractError("status normalization decision set drift")


def _validate_fixtures(
    plan: dict[str, Any], documents: dict[str, dict[str, Any]]
) -> int:
    fixture_ids = _fixture_ids(documents)
    owners: dict[str, list[str]] = defaultdict(list)
    for input_id, values in fixture_ids.items():
        if len(values) != len(set(values)):
            raise BundleContractError(f"fixture collision inside {input_id}")
        for fixture_id in values:
            owners[fixture_id].append(input_id)
    collisions = {key: value for key, value in owners.items() if len(value) > 1}
    if collisions:
        fixture_id = sorted(collisions)[0]
        raise BundleContractError(f"unapproved fixture collision: {fixture_id}")
    if plan["fixture_merge"]["approved_collisions"] != []:
        raise BundleContractError("fixture collisions are not approved in Wave 3")
    if plan["fixture_merge"]["input_counts"] != {
        key: len(value) for key, value in fixture_ids.items()
    }:
        raise BundleContractError("fixture input counts drift")
    return len(owners)


def _validate_record_id_collisions(documents: dict[str, dict[str, Any]]) -> tuple[int, int]:
    discrepancy_groups = {
        "live-ledger": documents["live-ledger"]["source_discrepancies"],
        "agent-smartcity": documents["agent-smartcity"]["discrepancies"],
        "systems": documents["systems"]["discrepancies_and_boundaries"],
        "calibration-warehouse": documents["calibration-warehouse"]["discrepancies"],
    }
    discrepancy_owners: dict[str, list[str]] = defaultdict(list)
    for input_id, records in discrepancy_groups.items():
        for record in records:
            discrepancy_owners[record["id"]].append(input_id)
    discrepancy_collisions = {
        key: value for key, value in discrepancy_owners.items() if len(value) > 1
    }
    if discrepancy_collisions:
        record_id = sorted(discrepancy_collisions)[0]
        raise BundleContractError(f"unapproved discrepancy collision: {record_id}")

    guardrail_groups = {
        "agent-smartcity": documents["agent-smartcity"]["guardrails"],
        "calibration-warehouse": documents["calibration-warehouse"]["guardrails"],
    }
    guardrail_owners: dict[str, list[str]] = defaultdict(list)
    for input_id, records in guardrail_groups.items():
        for record in records:
            guardrail_owners[record["id"]].append(input_id)
    guardrail_collisions = {
        key: value for key, value in guardrail_owners.items() if len(value) > 1
    }
    if guardrail_collisions:
        record_id = sorted(guardrail_collisions)[0]
        raise BundleContractError(f"unapproved guardrail collision: {record_id}")
    return len(discrepancy_owners), len(guardrail_owners)


def validate(
    plan: dict[str, Any] | None = None,
    *,
    documents: dict[str, dict[str, Any]] | None = None,
    check_input_hashes: bool = True,
    check_plan_digest: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    plan = load_json(PLAN) if plan is None else plan
    _validate_schema(plan)
    if check_plan_digest and _canonical_sha256(plan) != EXPECTED_PLAN_CANONICAL_SHA256:
        raise BundleContractError("merge-plan canonical digest drift")
    if plan["counts"] != EXPECTED_COUNTS:
        raise BundleContractError("published exact-count contract drift")
    if documents is None:
        documents = _load_bound_inputs(plan, repo_root, check_input_hashes)
    elif set(documents) != set(EXPECTED_INPUT_PATHS):
        raise BundleContractError("injected input set drift")

    live = documents["live-ledger"]
    for input_id in ("agent-smartcity", "systems", "calibration-warehouse"):
        if documents[input_id]["target"] != live["target"]:
            raise BundleContractError(f"target identity drift: {input_id}")
    if plan["target"] != live["target"]:
        raise BundleContractError("merge-plan target identity drift")

    recursive = documents["recursive-targets"]
    source_lock = documents["source-lock"]
    reachable_values = recursive["targets"]
    if len(reachable_values) != len(set(reachable_values)) or len(reachable_values) != 172:
        raise BundleContractError("recursive target set is not the exact 172-page fixed point")
    locked_records = source_lock["records"]
    locked_values = [item["url"] for item in locked_records]
    if len(locked_values) != len(set(locked_values)) or len(locked_values) != 172:
        raise BundleContractError("source lock is not an exact 172-URL set")
    for item in locked_records:
        if (
            item["outcome"] != "success"
            or item["http_status"] != 200
            or item["final_url"] != item["url"]
        ):
            raise BundleContractError(f"source-lock record is not byte-locked: {item['url']}")
    reachable = set(reachable_values)
    locked = set(locked_values)
    if reachable != locked:
        raise BundleContractError("recursive target and source-lock URL sets differ")

    _validate_candidate_source_references(documents)
    resolutions, remaps, unique_sources = _computed_source_merge(
        plan, documents, reachable, locked
    )
    if plan["source_merge"]["duplicate_uri_resolutions"] != resolutions:
        raise BundleContractError("same-URI source resolution drift")
    if plan["source_merge"]["source_id_remaps"] != remaps:
        raise BundleContractError("source-ID remap drift")

    new_count, enrichment_count = _validate_capability_merge(plan, documents)
    _validate_normalizations(plan, documents)
    fixture_count = _validate_fixtures(plan, documents)
    discrepancy_count, guardrail_count = _validate_record_id_collisions(documents)

    computed_counts = {
        "source_lock_urls": len(locked),
        "live_source_records": len(live["sources"]),
        "candidate_source_records": sum(
            len(documents[key]["sources"]) for key in PACKAGE_ORDER[1:]
        ),
        "all_source_records": sum(
            len(documents[key]["sources"]) for key in PACKAGE_ORDER
        ),
        "duplicate_source_records": sum(
            len(item["contributors"]) - 1 for item in resolutions
        ),
        "proposed_unique_sources": unique_sources,
        "live_capabilities": len(live["capabilities"]),
        "new_capability_records": new_count,
        "proposed_capabilities": len(live["capabilities"]) + new_count,
        "enrichment_records": sum(
            len(documents[key]["enrichments"]) for key in PACKAGE_ORDER[1:]
        ),
        "unique_enrichment_targets": enrichment_count,
        "approved_enrichment_collisions": len(
            plan["capability_merge"]["approved_enrichment_collisions"]
        ),
        "live_discrepancies": len(live["source_discrepancies"]),
        "new_discrepancy_records": sum(
            len(_discrepancies(key, documents[key])) for key in PACKAGE_ORDER[1:]
        ),
        "proposed_discrepancies": len(live["source_discrepancies"])
        + sum(len(_discrepancies(key, documents[key])) for key in PACKAGE_ORDER[1:]),
        "unique_proposed_discrepancies": discrepancy_count,
        "guardrail_records": len(documents["agent-smartcity"]["guardrails"])
        + len(documents["calibration-warehouse"]["guardrails"]),
        "unique_guardrails": guardrail_count,
        "agent_fixture_records": len(_fixture_ids(documents)["agent-smartcity"]),
        "systems_acceptance_fixture_records": len(
            _fixture_ids(documents)["systems-acceptance"]
        ),
        "systems_performance_fixture_records": len(
            _fixture_ids(documents)["systems-performance"]
        ),
        "calibration_acceptance_vectors": len(
            _fixture_ids(documents)["calibration-warehouse"]
        ),
        "candidate_fixture_records": sum(
            len(value) for value in _fixture_ids(documents).values()
        ),
        "unique_candidate_fixtures": fixture_count,
    }
    if computed_counts != EXPECTED_COUNTS:
        raise BundleContractError(f"computed exact-count drift: {computed_counts}")
    return computed_counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print validated counts as JSON")
    args = parser.parse_args()
    try:
        counts = validate()
    except BundleContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(counts, indent=2, sort_keys=True))
    else:
        print(
            "PASS: Wave 3 merge plan is byte-bound, collision-safe, and planning-only "
            f"({counts['proposed_capabilities']} proposed capabilities; "
            f"{counts['proposed_unique_sources']} unique sources)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
