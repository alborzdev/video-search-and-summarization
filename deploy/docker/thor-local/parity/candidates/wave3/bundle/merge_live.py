#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Deterministically merge the reviewed Wave 3 bundle into live static contracts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PARITY_DIR = SCRIPT_DIR.parents[2]
REPO_ROOT = SCRIPT_DIR.parents[6]
QUALIFICATION_DIR = REPO_ROOT / "deploy/docker/thor-local/qualification"
LEDGER = PARITY_DIR / "official-capabilities.json"
MANIFEST = PARITY_DIR / "manifest.json"
ORACLES = PARITY_DIR / "capability-oracles.json"
ACCEPTANCE = QUALIFICATION_DIR / "acceptance_inventory.json"
RECEIPT = SCRIPT_DIR / "merge-receipt.json"
EXECUTOR_SUCCESSOR = (
    QUALIFICATION_DIR / "lvs-mcp-static-adapter-integration/integrate_live.py"
)
BASELINE_DIR = SCRIPT_DIR / "baseline"
PLAN = SCRIPT_DIR / "merge-plan.json"
FEATURE_MAP = SCRIPT_DIR / "systems-feature-map.json"
AGENT = SCRIPT_DIR.parent / "agent-smartcity" / "candidate.json"
SYSTEMS = SCRIPT_DIR.parent / "systems" / "candidate.json"
CALIBRATION = SCRIPT_DIR.parent / "calibration-warehouse" / "candidate.json"

sys.path.insert(0, str(PARITY_DIR))
import capability_oracles  # noqa: E402


PRE_HASHES = {
    "official-capabilities.json": "e33eff2cc03f7770e0513a061732ec860ccb241721e40b9d60d6dbb2b0dafee8",
    "manifest.json": "4c2712271a0157522d2ad5b8335a0853309796d33f72ef1396605a3f3baecdc4",
    "capability-oracles.json": "5462c555436b96ec3c2fab9f3af3223fce26b064d85ee4cfd1c38128bceff56b",
    "acceptance_inventory.json": "24f2ee284abc795cdc14537319f99c2b0655718ab541f1381132085cf20cff26",
}
PUBLISHED_BASELINE_COMMIT = "45dd109d767f11f0bdef0ea25a31ef4693eccae6"
CANDIDATE_CANONICAL = {
    "agent-smartcity": "a0c366965541898d6c9f978f938a1fe8fc77fac84c1b992af09f96fc8d5ea9b7",
    "systems": "b4417c11a667bf4a6b2fa8c780f90e5504107c25821e117f6a5adc83af19af93",
    "calibration-warehouse": "e8aa7045c93cf0ef73e70034dd7d8efedb4f2c5e54153f10008c83eb70911783",
}
PLAN_RAW_SHA256 = "bcb98e16ed991eb1e92504c1d2031c8d5a1f690cde73509a8b40848eca990a3d"
PLAN_CANONICAL_SHA256 = "7c61cb7569f095c66a8590ef56b323364643899271a460b7c375abbc6adb0fea"
FEATURE_MAP_RAW_SHA256 = "ad4a1f56c528e404c3b9bb2eb2c86539801c1fc2ff7c21c546c48c78ff3d9091"
FEATURE_MAP_CANONICAL_SHA256 = "98a3fae17478bde0fe044ec6e30e57748427dce5a07766dc359c237ded13073f"
BOUND_INPUT_PATHS = {
    "source-lock": "deploy/docker/thor-local/parity/source-lock/source-lock.json",
    "recursive-targets": "deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/recursive-targets.json",
    "agent-smartcity": "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
    "systems": "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json",
    "calibration-warehouse": "deploy/docker/thor-local/parity/candidates/wave3/calibration-warehouse/candidate.json",
    "systems-broker-evidence": "deploy/docker/thor-local/parity/candidates/wave3/systems/evidence/broker-topic-contracts.json",
    "systems-nvstreamer-evidence": "deploy/docker/thor-local/parity/candidates/wave3/systems/evidence/nvstreamer-config-contract.json",
    "systems-performance-evidence": "deploy/docker/thor-local/parity/candidates/wave3/systems/evidence/performance-reference-contracts.json",
}
EXCLUDED_SOURCE_IDS = {
    "agent-smartcity": {
        "agent-workflows-doc-3.2.1",
        "agent-api-wrapper-doc-3.2.1",
        "smartcity-introduction-doc-3.2.1",
        "smartcity-development-doc-3.2.1",
        "smartcity-operations-doc-3.2.1",
        "smartcity-troubleshooting-doc-3.2.1",
        "smartcity-faq-doc-3.2.1",
        "smartcity-license-doc-3.2.1",
    },
    "calibration-warehouse": {
        "warehouse-accuracy-doc-3.2.1",
        "warehouse-system-sizing-doc-3.2.1",
        "warehouse-blueprint-profiles-doc-3.2.1",
        "warehouse-toc-doc-3.2.1",
        "warehouse-sdg-scene-customization-doc-3.2.1",
        "warehouse-sdg-index-doc-3.2.1",
    },
    "systems": set(),
}
EXPECTED_POST_COUNTS = {
    "candidate_registry_sources": 140,
    "excluded_non_claim_sources": 14,
    "live_claim_sources": 126,
    "capabilities": 276,
    "discrepancies": 45,
    "guardrails": 10,
    "planning_requirements": 110,
    "oracles": 276,
    "executor_ready": 0,
}
EXPECTED_STATUS_COUNTS = {
    "acceptance_class": {"required_local": 145, "alternate_local_lane": 102, "external_optional": 29},
    "thor_state": {"wired": 30, "partial": 151, "source_only": 66, "external_optional": 27, "blocked_upstream": 2},
    "runtime_state": {"passed_prior": 1, "static_only": 38, "not_qualified": 196, "blocked": 10, "not_applicable": 31},
}
EXPECTED_DISCREPANCY_SEMANTICS = {
    "legacy_cross_source": 18,
    "single_source_record": 19,
    "cross_source_discrepancy": 8,
}
EXPECTED_DISCREPANCY_CATEGORIES = {
    "legacy_unspecified": 18,
    "boundary": 15,
    "discrepancy": 10,
    "scoped_default": 2,
}
EXPECTED_SCHEMA_RAW_SHA256 = "6bbd5354db37f871a2a912a79a1bb45c477617ef65e54e1fb1a13f0269efad39"
RELATED_FEATURES = {
    "runtime.rt-cv.model-pipelines": ["rt-cv-3d-sparse4d"],
}
EXTERNAL_SYNTHETIC_IDS = {
    "tooling.smart-city.synthetic-data-pipeline",
    "boundary.warehouse.sdg-toolchain",
    "boundary.warehouse.sdg-scene-calibration",
    "boundary.warehouse.sdg-postprocess",
    "boundary.warehouse.sim2real",
}
GUARDRAIL_RECORD_MAP = {
    "guardrail.sample-bundles-optional": [
        "configuration.smart-city.custom-location",
        "deployment.smart-city.bp-smc-surface",
        "runtime.smart-city.traffic-analytics",
    ],
    "guardrail.operator-custom-data": [
        "configuration.smart-city.custom-location",
        "calibration.legacy.core",
        "calibration.legacy.gis",
        "runtime.smart-city.traffic-analytics",
    ],
    "guardrail.google-maps-external": [
        "boundary.smart-city.google-maps-dependency",
        "runtime.smart-city.map-ui",
    ],
    "guardrail.vlm-fine-tuning-forthcoming": [
        "customization.smart-city.trafficcamnet-rtdetr"
    ],
    "guardrail.warehouse-sample-excluded": [
        "configuration.warehouse.custom-inputs",
        "runtime.warehouse.profile-2d-pipeline",
        "runtime.warehouse.profile-2d-agent-pipeline",
        "runtime.warehouse.profile-3d-sparse4d-pipeline",
        "runtime.warehouse.profile-mv3dt-pipeline",
        "performance.warehouse.profile-latency",
    ],
    "guardrail.warehouse-operator-data-in-scope": [
        "configuration.warehouse.custom-inputs",
        "calibration.auto.input-contract",
        "runtime.warehouse.profile-2d-pipeline",
        "runtime.warehouse.profile-2d-agent-pipeline",
        "runtime.warehouse.profile-3d-sparse4d-pipeline",
        "runtime.warehouse.profile-mv3dt-pipeline",
    ],
    "guardrail.warehouse-platform-scope": [
        "prereq.warehouse.thor-platform",
        "configuration.warehouse.profile-hardware-matrix",
    ],
    "guardrail.warehouse-agent-vlm-topology": [
        "runtime.warehouse.profile-2d-agent-pipeline",
        "runtime.warehouse.agent-hierarchy",
        "model.agent-vlm.cosmos3-nano",
    ],
    "guardrail.warehouse-external-development": [
        "boundary.warehouse.sdg-toolchain",
        "boundary.warehouse.sdg-scene-calibration",
        "boundary.warehouse.sdg-postprocess",
        "boundary.warehouse.sim2real",
        "calibration.sdg.workflow",
    ],
    "guardrail.warehouse-destructive-and-benchmark": [
        "behavior.warehouse.destructive-troubleshooting-boundaries",
        "performance.warehouse.profile-latency",
    ],
}
PACKAGE_PATHS = {
    "agent-smartcity": (
        "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json"
    ),
    "systems": (
        "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json"
    ),
    "calibration-warehouse": (
        "deploy/docker/thor-local/parity/candidates/wave3/calibration-warehouse/candidate.json"
    ),
}


class MergeError(ValueError):
    """The live state or reviewed merge input is not exact."""


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MergeError(f"{path}: JSON root must be an object")
    return value


def encoded(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_sha(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha_bytes(raw)


def fingerprint(items: list[Any]) -> str:
    canonical = sorted(
        json.dumps(item, sort_keys=True, separators=(",", ":")) for item in items
    )
    return sha_bytes(json.dumps(canonical, separators=(",", ":")).encode("utf-8"))


def validate_bound_inputs(plan: dict[str, Any], feature_map: dict[str, Any]) -> None:
    if sha_file(PLAN) != PLAN_RAW_SHA256 or canonical_sha(plan) != PLAN_CANONICAL_SHA256:
        raise MergeError("merge plan digest drift")
    if (
        sha_file(FEATURE_MAP) != FEATURE_MAP_RAW_SHA256
        or canonical_sha(feature_map) != FEATURE_MAP_CANONICAL_SHA256
    ):
        raise MergeError("Systems feature map digest drift")
    if sha_file(PARITY_DIR / "official-capabilities.schema.json") != EXPECTED_SCHEMA_RAW_SHA256:
        raise MergeError("official capability schema digest drift")
    bindings = {item["id"]: item for item in plan["inputs"]}
    for input_id, relative in BOUND_INPUT_PATHS.items():
        binding = bindings.get(input_id)
        path = REPO_ROOT / relative
        if binding is None or binding.get("path") != relative:
            raise MergeError(f"bound input path drift: {input_id}")
        document = load(path)
        if sha_file(path) != binding.get("sha256"):
            raise MergeError(f"bound input raw digest drift: {input_id}")
        if canonical_sha(document) != binding.get("canonical_sha256"):
            raise MergeError(f"bound input canonical digest drift: {input_id}")


def merge_value(current: Any, addition: Any) -> Any:
    if isinstance(current, dict) and isinstance(addition, dict):
        result = copy.deepcopy(current)
        for key, value in addition.items():
            result[key] = (
                merge_value(result[key], value)
                if key in result
                else copy.deepcopy(value)
            )
        return result
    if isinstance(current, list) and isinstance(addition, list):
        result = copy.deepcopy(current)
        for value in addition:
            if value not in result:
                result.append(copy.deepcopy(value))
        return result
    if current != addition:
        raise MergeError(f"unsafe scalar merge conflict: {current!r} != {addition!r}")
    return copy.deepcopy(current)


def aggregate_family(feature: dict[str, Any], records: list[dict[str, Any]]) -> None:
    classes = {item["acceptance_class"] for item in records}
    feature["acceptance_class"] = (
        "required_local"
        if "required_local" in classes
        else "external_optional"
        if classes == {"external_optional"}
        else "alternate_local_lane"
    )
    thor = {item["thor_state"] for item in records}
    feature["thor_state"] = next(iter(thor)) if len(thor) == 1 else "partial"
    runtime = {item["runtime_state"] for item in records}
    feature["runtime_state"] = (
        next(iter(runtime)) if len(runtime) == 1 else "not_qualified"
    )


def candidate_sources(package_id: str, package: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for source in package["sources"]:
        result.append(
            {
                "package": package_id,
                "id": source["id"],
                "uri": source.get("uri", source.get("url")),
                "classification": source.get("classification", source.get("category")),
                "locator_policy": source.get(
                    "locator_policy",
                    f"Wave 3 Systems {source.get('category')} extraction captured 2026-07-31.",
                ),
            }
        )
    return result


def claims_for_record(package_id: str, record: dict[str, Any]) -> list[dict[str, str]]:
    if package_id == "systems":
        source = record["source"]
        return [
            {
                "source_id": source["source_id"],
                "locator": f"{source['heading']} — {source['locator']}",
            }
        ]
    return copy.deepcopy(record["source_claims"])


def qualification_for_record(
    package_id: str, record: dict[str, Any]
) -> tuple[list[str], list[str]]:
    if package_id == "systems":
        return [record["acceptance"]["scenario_id"]], [
            record["acceptance"]["fixture_id"]
        ]
    qualification = record["qualification"]
    fixture_key = "fixtures" if package_id == "agent-smartcity" else "acceptance_vector_ids"
    fixtures = qualification[fixture_key]
    if package_id == "agent-smartcity":
        fixtures = [item["id"] for item in fixtures]
    return copy.deepcopy(qualification["scenario_ids"]), list(fixtures)


def receipt_core(
    plan: dict[str, Any], packages: dict[str, dict[str, Any]], feature_map: dict[str, Any]
) -> dict[str, Any]:
    excluded = []
    sources_by_package = {
        package_id: {item["id"]: item for item in candidate_sources(package_id, package)}
        for package_id, package in packages.items()
    }
    for package_id, ids in EXCLUDED_SOURCE_IDS.items():
        for source_id in sorted(ids):
            source = sources_by_package[package_id][source_id]
            excluded.append(
                {
                    "package": package_id,
                    "source_id": source_id,
                    "uri": source["uri"],
                    "classification": source["classification"],
                    "reason": "navigation_summary_legal_or_no_independent_capability_claim",
                }
            )
    return {
        "schema_version": 1,
        "merge_id": "wave3-vss-3.2.1-thor-static",
        "target": copy.deepcopy(packages["agent-smartcity"]["target"]),
        "bundle": {
            "path": "deploy/docker/thor-local/parity/candidates/wave3/bundle/merge-plan.json",
            "raw_sha256": sha_file(PLAN),
            "canonical_sha256": canonical_sha(plan),
        },
        "published_baseline": {
            "commit": PUBLISHED_BASELINE_COMMIT,
            "files": copy.deepcopy(PRE_HASHES),
        },
        "candidates": [
            {
                "id": package_id,
                "path": PACKAGE_PATHS[package_id],
                "raw_sha256": sha_file(REPO_ROOT / PACKAGE_PATHS[package_id]),
                "canonical_sha256": CANDIDATE_CANONICAL[package_id],
            }
            for package_id in ("agent-smartcity", "systems", "calibration-warehouse")
        ],
        "systems_feature_map": {
            "path": "deploy/docker/thor-local/parity/candidates/wave3/bundle/systems-feature-map.json",
            "raw_sha256": sha_file(FEATURE_MAP),
            "canonical_sha256": canonical_sha(feature_map),
            "entry_count": 55,
        },
        "source_resolutions": copy.deepcopy(plan["source_merge"]),
        "excluded_from_live_claim_registry": excluded,
        "expected_post_counts": copy.deepcopy(EXPECTED_POST_COUNTS),
        "expected_discrepancy_distributions": {
            "record_semantics": copy.deepcopy(EXPECTED_DISCREPANCY_SEMANTICS),
            "category": copy.deepcopy(EXPECTED_DISCREPANCY_CATEGORIES),
        },
        "boundaries": {
            "warehouse_sample_bundle": "excluded_optional",
            "warehouse_official_platform": "IGX-THOR Jetson Linux 38.5",
            "current_host": "AGX Thor Jetson Linux 38.4",
            "warehouse_single_gpu_agent_vlm_official": False,
            "auto_calibration_official_architecture": "x86_64",
            "docker_cgroup_driver_required": "cgroupfs",
            "runtime_pass_evidence_added": False,
        },
    }


def build_unmerged(
    *, from_baseline: bool = False
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = {
        "official-capabilities.json": LEDGER,
        "manifest.json": MANIFEST,
        "capability-oracles.json": ORACLES,
        "acceptance_inventory.json": ACCEPTANCE,
    }
    input_paths = (
        {
            "official-capabilities.json": BASELINE_DIR / "official-capabilities.json",
            "manifest.json": BASELINE_DIR / "manifest.json",
            "capability-oracles.json": BASELINE_DIR / "capability-oracles.json",
            "acceptance_inventory.json": BASELINE_DIR / "acceptance_inventory.json",
        }
        if from_baseline
        else paths
    )
    for name, path in input_paths.items():
        if sha_file(path) != PRE_HASHES[name]:
            raise MergeError(f"pre-merge input hash drift: {name}")

    ledger = load(input_paths["official-capabilities.json"])
    manifest = load(input_paths["manifest.json"])
    acceptance = load(input_paths["acceptance_inventory.json"])
    plan, feature_map = load(PLAN), load(FEATURE_MAP)
    validate_bound_inputs(plan, feature_map)
    packages = {
        "agent-smartcity": load(AGENT),
        "systems": load(SYSTEMS),
        "calibration-warehouse": load(CALIBRATION),
    }
    for package_id, package in packages.items():
        if canonical_sha(package) != CANDIDATE_CANONICAL[package_id]:
            raise MergeError(f"candidate digest drift: {package_id}")
        if package["target"] != ledger["target"]:
            raise MergeError(f"candidate target drift: {package_id}")
    systems_ids = {item["id"] for item in packages["systems"]["proposed_capabilities"]}
    if set(feature_map) != systems_ids or len(feature_map) != 55:
        raise MergeError("Systems feature map must cover the exact 55-ID set")
    manifest_features = {item["id"] for item in manifest["features"]}
    if not set(feature_map.values()) <= manifest_features:
        raise MergeError("Systems feature map contains a non-manifest family")
    if feature_map["runtime.rtvi.input-codec-boundary"] != "rt-cv-2d":
        raise MergeError("RTVI input-codec claim must remain attributed to RT-CV")

    all_sources = [
        source
        for package_id, package in packages.items()
        for source in candidate_sources(package_id, package)
    ]
    live_by_uri = {item["uri"]: item for item in ledger["sources"]}
    live_ids = {item["id"] for item in ledger["sources"]}
    source_maps: dict[str, dict[str, str]] = defaultdict(dict)
    source_records: dict[tuple[str, str], dict[str, Any]] = {}
    for source in all_sources:
        package_id, source_id, uri = source["package"], source["id"], source["uri"]
        source_records[(package_id, source_id)] = source
        existing = live_by_uri.get(uri)
        if existing is not None:
            source_maps[package_id][source_id] = existing["id"]
            continue
        target_id = (
            "agent-video-analytics-mcp-doc-3.2.1"
            if package_id == "agent-smartcity"
            and source_id == "video-analytics-mcp-doc-3.2.1"
            else source_id
        )
        if target_id in live_ids:
            raise MergeError(f"same source ID maps to a different URI: {target_id}")
        source_maps[package_id][source_id] = target_id

    def remap(package_id: str, claims: list[dict[str, str]]) -> list[dict[str, str]]:
        result = []
        for claim in claims:
            item = copy.deepcopy(claim)
            item["source_id"] = source_maps[package_id][item["source_id"]]
            if item not in result:
                result.append(item)
        return result

    capabilities = {item["id"]: item for item in ledger["capabilities"]}
    new_records: list[tuple[str, dict[str, Any]]] = []
    new_records.extend(("agent-smartcity", item) for item in packages["agent-smartcity"]["new_capabilities"])
    new_records.extend(("systems", item) for item in packages["systems"]["proposed_capabilities"])
    new_records.extend(("calibration-warehouse", item) for item in packages["calibration-warehouse"]["new_capabilities"])
    if len(new_records) != 115 or {item["id"] for _, item in new_records} & set(capabilities):
        raise MergeError("Wave 3 new capability set is not wholly unmerged")

    record_source_ids: dict[tuple[str, str], list[str]] = {}
    for package_id, proposed in new_records:
        scenarios, planning_ids = qualification_for_record(package_id, proposed)
        claims = remap(package_id, claims_for_record(package_id, proposed))
        record_source_ids[(package_id, proposed["id"])] = [item["source_id"] for item in claims]
        if package_id == "systems":
            state = proposed["acceptance"]
            feature_id = feature_map[proposed["id"]]
            contract = copy.deepcopy(proposed["contract"])
            contract["wave3_acceptance"] = {
                "package": package_id,
                "candidate_family": proposed["family"],
                "planning_requirement_ids": planning_ids,
                "materialized": False,
                "executor_ready": False,
            }
        else:
            state = proposed["status"]
            feature_id = proposed["feature_id"]
            contract = copy.deepcopy(proposed["contract"])
            contract["wave3_acceptance"] = {
                "package": package_id,
                "planning_requirement_ids": planning_ids,
                "materialized": False,
                "executor_ready": False,
            }
            if proposed["id"] in EXTERNAL_SYNTHETIC_IDS:
                if feature_id != "synthetic-data-tools" or state["acceptance_class"] != "external_optional":
                    raise MergeError("external synthetic family split contract drift")
                contract["wave3_acceptance"]["candidate_feature_id"] = feature_id
                feature_id = "synthetic-data-workflows-external"
        if proposed["id"] in RELATED_FEATURES:
            contract["related_feature_ids"] = RELATED_FEATURES[proposed["id"]]
        kind = "model_customization" if proposed["kind"] == "customization" else proposed["kind"]
        live = {
            "id": proposed["id"],
            "feature_id": feature_id,
            "kind": kind,
            "title": proposed["title"],
            "source_claims": claims,
            "acceptance_class": state["acceptance_class"],
            "thor_state": state["thor_state"],
            "runtime_state": state["runtime_state"],
            "contract": contract,
            "scenario_ids": scenarios,
            "gap": proposed["gap"],
        }
        if live["runtime_state"] == "passed_current":
            raise MergeError(f"Wave 3 cannot add runtime pass evidence: {live['id']}")
        ledger["capabilities"].append(live)
        capabilities[live["id"]] = live

    enrichments: list[tuple[str, dict[str, Any]]] = []
    enrichments.extend(("agent-smartcity", item) for item in packages["agent-smartcity"]["enrichments"])
    enrichments.extend(("systems", item) for item in packages["systems"]["enrichments"])
    enrichments.extend(("calibration-warehouse", item) for item in packages["calibration-warehouse"]["enrichments"])
    if len(enrichments) != 46:
        raise MergeError("Wave 3 enrichment count drift")
    for package_id, enrichment in enrichments:
        target = capabilities[enrichment["target_id"]]
        source_claims = enrichment.get("source_claims_add", enrichment.get("sources"))
        if package_id == "systems":
            source_claims = [
                {
                    "source_id": item["source_id"],
                    "locator": f"{item['heading']} — {item['locator']}",
                }
                for item in source_claims
            ]
            planning_ids = (
                [enrichment["contract_merge"]["fixture_id"]]
                if "fixture_id" in enrichment["contract_merge"]
                else []
            )
            scenarios: list[str] = []
        else:
            qualification = enrichment["qualification"]
            scenarios = qualification["scenario_ids"]
            if package_id == "agent-smartcity":
                planning_ids = [item["id"] for item in qualification["fixtures"]]
            else:
                planning_ids = qualification["acceptance_vector_ids"]
        claims = remap(package_id, source_claims)
        record_source_ids[(package_id, enrichment["target_id"])] = [item["source_id"] for item in claims]
        addition = copy.deepcopy(enrichment["contract_merge"])
        correction = addition.pop("acceptance_class_correction", None)
        target["contract"] = merge_value(target["contract"], addition)
        target["source_claims"] = merge_value(target["source_claims"], claims)
        target["scenario_ids"] = merge_value(target["scenario_ids"], scenarios)
        acceptance_meta = target["contract"].setdefault(
            "wave3_acceptance", {"contributions": [], "materialized": False, "executor_ready": False}
        )
        if "contributions" not in acceptance_meta:
            acceptance_meta = {
                "base": acceptance_meta,
                "contributions": [],
                "materialized": False,
                "executor_ready": False,
            }
            target["contract"]["wave3_acceptance"] = acceptance_meta
        acceptance_meta["contributions"].append(
            {"package": package_id, "planning_requirement_ids": planning_ids}
        )
        if correction is not None:
            if enrichment["target_id"] != "calibration.sdg.workflow" or correction != "external_optional":
                raise MergeError("unreviewed status correction")
            target["acceptance_class"] = "external_optional"
            target["thor_state"] = "source_only"
            target["runtime_state"] = "not_applicable"

    used_source_ids = {
        claim["source_id"]
        for capability in ledger["capabilities"]
        for claim in capability["source_claims"]
    }
    excluded = {
        (package_id, source_id)
        for package_id, ids in EXCLUDED_SOURCE_IDS.items()
        for source_id in ids
    }
    observed_excluded: set[tuple[str, str]] = set()
    for source in all_sources:
        key = (source["package"], source["id"])
        mapped_id = source_maps[source["package"]][source["id"]]
        if source["uri"] in live_by_uri:
            continue
        if mapped_id not in used_source_ids:
            observed_excluded.add(key)
            continue
        record = {
            "id": mapped_id,
            "kind": "release_notes" if source["uri"].endswith("release-notes.html") else "versioned_official_docs",
            "uri": source["uri"],
            "version": "3.2.1",
            "locator_policy": source["locator_policy"],
            "claim_set_sha256": "0" * 64,
        }
        ledger["sources"].append(record)
        live_by_uri[source["uri"]] = record
        live_ids.add(mapped_id)
    if observed_excluded != excluded:
        raise MergeError(
            f"exact no-independent-claim source set drift: {sorted(observed_excluded ^ excluded)}"
        )
    if len(ledger["sources"]) != 126 or len({item["uri"] for item in ledger["sources"]}) != 126:
        raise MergeError("post-merge live claim source count must be exactly 126")

    discrepancies: list[tuple[str, dict[str, Any]]] = []
    discrepancies.extend(("agent-smartcity", item) for item in packages["agent-smartcity"]["discrepancies"])
    discrepancies.extend(("systems", item) for item in packages["systems"]["discrepancies_and_boundaries"])
    discrepancies.extend(("calibration-warehouse", item) for item in packages["calibration-warehouse"]["discrepancies"])
    discrepancy_ids = {item["id"] for item in ledger["source_discrepancies"]}
    for package_id, proposed in discrepancies:
        claims = proposed.get("source_claims", proposed.get("sources"))
        if package_id == "systems":
            claims = [
                {
                    "source_id": item["source_id"],
                    "locator": f"{item['heading']} — {item['locator']}",
                }
                for item in claims
            ]
        claims = remap(package_id, claims)
        observations = [
            {
                "source_id": claim["source_id"],
                "locator": claim["locator"],
                "claim": claim["locator"],
            }
            for claim in claims
        ]
        semantics = (
            "single_source_record"
            if len(observations) == 1
            else "cross_source_discrepancy"
        )
        item = {
            "id": proposed["id"],
            "category": proposed.get(
                "category",
                "boundary" if semantics == "single_source_record" else "discrepancy",
            ),
            "record_semantics": semantics,
            "source_ids": list(dict.fromkeys(value["source_id"] for value in observations)),
            "observations": observations,
            "resolution": proposed["resolution"],
            "must_not_claim": proposed["must_not_claim"],
        }
        if proposed.get("observations"):
            item["candidate_observations"] = copy.deepcopy(proposed["observations"])
        if item["id"] in discrepancy_ids:
            raise MergeError(f"discrepancy already exists before merge: {item['id']}")
        ledger["source_discrepancies"].append(item)
        discrepancy_ids.add(item["id"])

    receipt = receipt_core(plan, packages, feature_map)
    receipt_contract_sha = canonical_sha(receipt)
    acceptance["wave3_contracts"] = build_acceptance_contracts(
        packages,
        source_maps,
        record_source_ids,
        receipt_contract_sha,
        receipt,
    )
    for requirement in acceptance["wave3_contracts"]["planning_requirements"]:
        owner_ids = {requirement["owner_id"], *requirement.get("applicable_record_ids", [])}
        for capability_id in owner_ids & capabilities.keys():
            metadata = capabilities[capability_id]["contract"].setdefault(
                "wave3_acceptance",
                {"contributions": [], "materialized": False, "executor_ready": False},
            )
            metadata.setdefault("planning_requirement_ids", [])
            if requirement["id"] not in metadata["planning_requirement_ids"]:
                metadata["planning_requirement_ids"].append(requirement["id"])
    simulation_blocker = {
        "id": "external-simulation-toolchain-required",
        "reason": "CARLA, RoadRunner, Isaac Sim, Cosmos Transfer, and associated training/simulation environments are operator-managed external dependencies.",
        "scope": "external",
    }
    acceptance["blockers"].append(simulation_blocker)
    external_scenario = next(
        item for item in acceptance["scenarios"]
        if item["id"] == "external-integration-boundaries"
    )
    external_scenario["blocker_ids"].append(simulation_blocker["id"])
    for requirement in acceptance["wave3_contracts"]["planning_requirements"]:
        owners = {requirement["owner_id"], *requirement.get("applicable_record_ids", [])}
        if owners & EXTERNAL_SYNTHETIC_IDS:
            requirement["blocker_ids"] = [simulation_blocker["id"]]
    for guardrail in acceptance["wave3_contracts"]["guardrails"]:
        for capability_id in guardrail["applicable_record_ids"]:
            metadata = capabilities[capability_id]["contract"].setdefault(
                "wave3_acceptance",
                {"contributions": [], "materialized": False, "executor_ready": False},
            )
            metadata.setdefault("guardrail_ids", [])
            if guardrail["id"] not in metadata["guardrail_ids"]:
                metadata["guardrail_ids"].append(guardrail["id"])

    # Source digests bind the final contracts, including planning and guardrail
    # cross-references injected above.
    for source in ledger["sources"]:
        claim_items = []
        for capability in ledger["capabilities"]:
            for claim in capability["source_claims"]:
                if claim["source_id"] == source["id"]:
                    claim_items.append(
                        {
                            "capability_id": capability["id"],
                            "locator": claim["locator"],
                            "contract": capability["contract"],
                        }
                    )
        if not claim_items:
            raise MergeError(f"live source has no capability claim: {source['id']}")
        source["claim_set_sha256"] = fingerprint(claim_items)

    manifest["features"].append(
        {
            "id": "synthetic-data-workflows-external",
            "acceptance_class": "external_optional",
            "category": "tooling",
            "advertised": [],
            "source_evidence": [
                "deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/candidate.json",
                "deploy/docker/thor-local/parity/candidates/wave3/calibration-warehouse/candidate.json",
            ],
            "thor_evidence": [
                "deploy/docker/thor-local/parity/candidates/wave3/bundle/merge-receipt.json"
            ],
            "thor_state": "external_optional",
            "runtime_state": "not_applicable",
            "boundary_reason": "CARLA, RoadRunner, Isaac Sim, Cosmos Transfer, and training/simulation workflows are external development boundaries rather than Thor-local VSS runtime services.",
            "external_dependency": "Operator-managed CARLA, RoadRunner, Isaac Sim, Cosmos Transfer, and associated training/simulation environments outside the Thor-local VSS runtime.",
            "gap": "These workflows remain planning-only external integrations; no Thor-local runtime pass evidence is claimed.",
            "official_capability_ids": [],
        }
    )
    acceptance["coverage"]["features"].append(
        {
            "blocker_ids": [
                "phase1-execution-disabled",
                "current-runtime-evidence-required",
                "external-simulation-toolchain-required",
            ],
            "capabilities_sha256": "0" * 64,
            "disposition": "external-optional",
            "expected_capability_count": 0,
            "feature_id": "synthetic-data-workflows-external",
            "scenario_ids": ["external-integration-boundaries"],
            "selector": "all-current-capabilities",
        }
    )

    by_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for capability in ledger["capabilities"]:
        by_feature[capability["feature_id"]].append(capability)
    manifest_by_id = {item["id"]: item for item in manifest["features"]}
    for feature_id, records in by_feature.items():
        feature = manifest_by_id[feature_id]
        feature["official_capability_ids"] = [item["id"] for item in records]
        for capability in records:
            if capability["title"] not in feature["advertised"]:
                feature["advertised"].append(capability["title"])
        aggregate_family(feature, records)
        if feature["acceptance_class"] == "external_optional":
            feature.setdefault(
                "boundary_reason",
                "The reviewed family consists only of external development or provider-managed contracts and is not a Thor-local runtime prerequisite.",
            )
            feature.setdefault(
                "external_dependency",
                "Operator-provided external development environment, assets, services, and credentials.",
            )
        if any(item["id"] in {record["id"] for _, record in new_records} for item in records):
            suffix = (
                " Wave 3 adds reviewed planning-only contracts from the complete candidate "
                "registry; no new runtime pass evidence is implied."
            )
            if suffix.strip() not in feature["gap"]:
                feature["gap"] += suffix
            evidence_path = "deploy/docker/thor-local/parity/candidates/wave3/bundle/merge-receipt.json"
            if evidence_path not in feature["thor_evidence"]:
                feature["thor_evidence"].append(evidence_path)
    external_synthetic = manifest_by_id["synthetic-data-workflows-external"]
    if set(external_synthetic["official_capability_ids"]) != EXTERNAL_SYNTHETIC_IDS:
        raise MergeError("external synthetic family exact five-ID closure drift")

    coverage_by_id = {
        item["feature_id"]: item for item in acceptance["coverage"]["features"]
    }
    for feature in manifest["features"]:
        record = coverage_by_id[feature["id"]]
        record["expected_capability_count"] = len(feature["advertised"])
        record["capabilities_sha256"] = fingerprint(feature["advertised"])
        scenarios = {
            scenario
            for capability in by_feature[feature["id"]]
            for scenario in capability["scenario_ids"]
        }
        record["scenario_ids"] = sorted(set(record["scenario_ids"]) | scenarios)

    oracle_plan = capability_oracles.compile_plan(
        ledger, include_local_runtime_bounds=False
    )
    if len(oracle_plan["oracles"]) != 276 or any(
        item["acceptance_readiness"]["classification"] != "planning_index_only"
        or item["evidence"]
        for item in oracle_plan["oracles"]
    ):
        raise MergeError("Wave 3 oracle compilation implied execution or pass evidence")

    if (
        len(ledger["capabilities"]) != 276
        or len(ledger["source_discrepancies"]) != 45
        or len(acceptance["wave3_contracts"]["guardrails"]) != 10
        or len(acceptance["wave3_contracts"]["planning_requirements"]) != 110
    ):
        raise MergeError("post-merge exact count drift")
    observed_semantics: dict[str, int] = defaultdict(int)
    observed_categories: dict[str, int] = defaultdict(int)
    for discrepancy in ledger["source_discrepancies"]:
        observed_semantics[discrepancy.get("record_semantics", "legacy_cross_source")] += 1
        observed_categories[discrepancy.get("category", "legacy_unspecified")] += 1
    if dict(observed_semantics) != EXPECTED_DISCREPANCY_SEMANTICS:
        raise MergeError("post-merge discrepancy semantics distribution drift")
    if dict(observed_categories) != EXPECTED_DISCREPANCY_CATEGORIES:
        raise MergeError("post-merge discrepancy category distribution drift")
    for field, expected in EXPECTED_STATUS_COUNTS.items():
        observed: dict[str, int] = defaultdict(int)
        for capability in ledger["capabilities"]:
            observed[capability[field]] += 1
        if dict(observed) != expected:
            raise MergeError(f"post-merge {field} distribution drift: {dict(observed)}")
    oracle_states: dict[str, int] = defaultdict(int)
    readiness: dict[str, int] = defaultdict(int)
    for oracle in oracle_plan["oracles"]:
        oracle_states[oracle["current_state"]] += 1
        readiness[oracle["acceptance_readiness"]["classification"]] += 1
    if dict(oracle_states) != {"open_unexecuted": 247, "external_boundary_unexecuted": 29}:
        raise MergeError("post-merge oracle-state distribution drift")
    if dict(readiness) != {"planning_index_only": 276}:
        raise MergeError("post-merge oracle-readiness distribution drift")

    receipt["contract_sha256"] = receipt_contract_sha
    receipt["outputs"] = {
        "official-capabilities.json": sha_bytes(encoded(ledger)),
        "manifest.json": sha_bytes(encoded(manifest)),
        "acceptance_inventory.json": sha_bytes(encoded(acceptance)),
        "capability-oracles.json": sha_bytes(encoded(oracle_plan)),
        "official-capabilities.schema.json": sha_file(PARITY_DIR / "official-capabilities.schema.json"),
    }
    receipt["lifecycle"] = "wholly_merged"
    return ledger, manifest, acceptance, oracle_plan, receipt


def build_acceptance_contracts(
    packages: dict[str, dict[str, Any]],
    source_maps: dict[str, dict[str, str]],
    record_source_ids: dict[tuple[str, str], list[str]],
    receipt_contract_sha: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    requirements = []

    def provenance(package_id: str, owner_id: str) -> dict[str, Any]:
        return {
            "candidate_path": PACKAGE_PATHS[package_id],
            "candidate_canonical_sha256": CANDIDATE_CANONICAL[package_id],
            "source_ids": record_source_ids.get((package_id, owner_id), []),
        }

    agent = packages["agent-smartcity"]
    for record_group, records in (
        ("new_capabilities", agent["new_capabilities"]),
        ("enrichments", agent["enrichments"]),
    ):
        for record_index, record in enumerate(records):
            owner_id = record.get("id", record.get("target_id"))
            for fixture_index, fixture in enumerate(record["qualification"]["fixtures"]):
                requirements.append(
                    {
                        "id": fixture["id"],
                        "owner_type": "capability_or_enrichment_target",
                        "owner_id": owner_id,
                        "package": "agent-smartcity",
                        "json_pointer": f"/{record_group}/{record_index}/qualification/fixtures/{fixture_index}",
                        "payload": copy.deepcopy(fixture),
                        "payload_canonical_sha256": canonical_sha(fixture),
                        "provenance": provenance("agent-smartcity", owner_id),
                        "materialized": False,
                        "executor_ready": False,
                        "runtime_evidence": [],
                    }
                )
    systems = packages["systems"]
    for record_index, record in enumerate(systems["proposed_capabilities"]):
        requirements.append(
            {
                "id": record["acceptance"]["fixture_id"],
                "owner_type": "capability",
                "owner_id": record["id"],
                "package": "systems",
                "json_pointer": f"/proposed_capabilities/{record_index}/acceptance",
                "payload": copy.deepcopy(record["acceptance"]),
                "payload_canonical_sha256": canonical_sha(record["acceptance"]),
                "provenance": provenance("systems", record["id"]),
                "materialized": False,
                "executor_ready": False,
                "runtime_evidence": [],
            }
        )
    for requirement_index, requirement in enumerate(systems["performance_fixture_requirements"]):
        owner = next(
            item["target_id"]
            for item in systems["enrichments"]
            if item["contract_merge"].get("fixture_id") == requirement["id"]
        )
        requirements.append(
            {
                "id": requirement["id"],
                "owner_type": "performance_enrichment_target",
                "owner_id": owner,
                "package": "systems",
                "json_pointer": f"/performance_fixture_requirements/{requirement_index}",
                "payload": copy.deepcopy(requirement),
                "payload_canonical_sha256": canonical_sha(requirement),
                "provenance": {
                    **provenance("systems", owner),
                    "reference_only": True,
                    "thor_remeasurement_required": True,
                },
                "materialized": False,
                "executor_ready": False,
                "runtime_evidence": [],
            }
        )
    calibration = packages["calibration-warehouse"]
    cal_records = [*calibration["new_capabilities"], *calibration["enrichments"]]
    for vector_index, vector in enumerate(calibration["acceptance_vectors"]):
        owners = [
            record.get("id", record.get("target_id"))
            for record in cal_records
            if vector["id"] in record["qualification"]["acceptance_vector_ids"]
        ]
        requirements.append(
            {
                "id": vector["id"],
                "owner_type": "global_acceptance_vector",
                "owner_id": vector["id"],
                "package": "calibration-warehouse",
                "json_pointer": f"/acceptance_vectors/{vector_index}",
                "payload": copy.deepcopy(vector),
                "payload_canonical_sha256": canonical_sha(vector),
                "applicable_record_ids": owners,
                "provenance": {
                    "candidate_path": PACKAGE_PATHS["calibration-warehouse"],
                    "candidate_canonical_sha256": CANDIDATE_CANONICAL["calibration-warehouse"],
                    "source_ids": sorted(
                        {
                            source_id
                            for owner in owners
                            for source_id in record_source_ids.get(("calibration-warehouse", owner), [])
                        }
                    ),
                },
                "materialized": False,
                "executor_ready": False,
                "runtime_evidence": [],
            }
        )
    if len(requirements) != 110 or len({item["id"] for item in requirements}) != 110:
        raise MergeError("planning requirement ownership is not exact")

    guardrails = []
    for package_id, values in (
        ("agent-smartcity", packages["agent-smartcity"]["guardrails"]),
        ("calibration-warehouse", packages["calibration-warehouse"]["guardrails"]),
    ):
        for guardrail in values:
            claims = [
                {
                    "source_id": source_maps[package_id][claim["source_id"]],
                    "locator": claim["locator"],
                }
                for claim in guardrail["source_claims"]
            ]
            applicable = GUARDRAIL_RECORD_MAP.get(guardrail["id"])
            if not applicable:
                raise MergeError(f"guardrail has no reviewed record map: {guardrail['id']}")
            guardrails.append(
                {
                    "id": guardrail["id"],
                    "package": package_id,
                    "source_claims": claims,
                    "rule": guardrail["rule"],
                    "applicable_record_ids": copy.deepcopy(applicable),
                    "payload": copy.deepcopy(guardrail),
                    "payload_canonical_sha256": canonical_sha(guardrail),
                }
            )
    if len(guardrails) != 10 or len({item["id"] for item in guardrails}) != 10:
        raise MergeError("guardrail mapping is not exact")
    return {
        "schema_version": 1,
        "merge_receipt": {
            "path": "deploy/docker/thor-local/parity/candidates/wave3/bundle/merge-receipt.json",
            "contract_sha256": receipt_contract_sha,
        },
        "bundle": copy.deepcopy(receipt["bundle"]),
        "candidates": copy.deepcopy(receipt["candidates"]),
        "policies": {
            "planning_only": True,
            "materialized_fixtures_added": False,
            "executor_ready_added": False,
            "runtime_pass_evidence_added": False,
            "warehouse_sample_bundle": "excluded_optional",
        },
        "planning_requirements": requirements,
        "guardrails": guardrails,
    }


def validate_merged_state() -> dict[str, Any]:
    if not RECEIPT.exists():
        raise MergeError("merged capability IDs exist without a merge receipt")
    receipt = load(RECEIPT)
    expected_ledger, expected_manifest, expected_acceptance, expected_oracles, expected_receipt = (
        build_unmerged(from_baseline=True)
    )
    if RECEIPT.read_bytes() != encoded(expected_receipt):
        raise MergeError("merge receipt differs from deterministic baseline rebuild")
    output_paths = {
        "official-capabilities.json": LEDGER,
        "manifest.json": MANIFEST,
        "acceptance_inventory.json": ACCEPTANCE,
        "capability-oracles.json": ORACLES,
    }
    expected_values = {
        "official-capabilities.json": expected_ledger,
        "manifest.json": expected_manifest,
        "acceptance_inventory.json": expected_acceptance,
        "capability-oracles.json": expected_oracles,
    }
    drifted = [
        name
        for name, path in output_paths.items()
        if path.read_bytes() != encoded(expected_values[name])
    ]
    if drifted:
        spec = importlib.util.spec_from_file_location(
            "wave3_executor_successor", EXECUTOR_SUCCESSOR
        )
        if spec is None or spec.loader is None:
            raise MergeError(f"partial or drifted merged output: {drifted[0]}")
        successor = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = successor
        try:
            spec.loader.exec_module(successor)
            # Validate the same output paths owned by this lifecycle adapter.
            # This matters both for successor overlays and for tamper tests that
            # deliberately redirect the Wave 3 live files to an isolated tree.
            successor.LEDGER = LEDGER
            successor.MANIFEST = MANIFEST
            successor.ACCEPTANCE = ACCEPTANCE
            successor.ORACLES = ORACLES
            successor.validate_live()
        except Exception as exc:
            raise MergeError(
                f"invalid reviewed successor after Wave 3: {exc}"
            ) from exc
        return receipt
    for name, path in output_paths.items():
        if receipt["outputs"].get(name) != sha_file(path):
            raise MergeError(f"receipt output digest drift: {name}")
    schema_name = "official-capabilities.schema.json"
    if receipt["outputs"].get(schema_name) != EXPECTED_SCHEMA_RAW_SHA256:
        raise MergeError("receipt schema digest drift")
    return receipt


def lifecycle() -> str:
    ledger = load(LEDGER)
    packages = [load(AGENT), load(SYSTEMS), load(CALIBRATION)]
    candidate_ids = {
        item["id"]
        for package in packages
        for key in ("new_capabilities", "proposed_capabilities")
        for item in package.get(key, [])
    }
    overlap = candidate_ids & {item["id"] for item in ledger["capabilities"]}
    if not overlap:
        for name, path in {
            "official-capabilities.json": LEDGER,
            "manifest.json": MANIFEST,
            "capability-oracles.json": ORACLES,
            "acceptance_inventory.json": ACCEPTANCE,
        }.items():
            if sha_file(path) != PRE_HASHES[name]:
                raise MergeError(f"partial unmerged state: {name}")
        return "wholly_unmerged"
    if overlap != candidate_ids:
        raise MergeError(f"partial capability merge: {len(overlap)}/115")
    validate_merged_state()
    return "wholly_merged"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write all live Wave 3 contracts")
    parser.add_argument(
        "--rebuild-from-baseline",
        action="store_true",
        help="rewrite an all-or-none state from the pinned published baseline",
    )
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        if args.rebuild_from_baseline:
            ledger_now = load(LEDGER)
            packages_now = [load(AGENT), load(SYSTEMS), load(CALIBRATION)]
            candidate_ids = {
                item["id"]
                for package in packages_now
                for key in ("new_capabilities", "proposed_capabilities")
                for item in package.get(key, [])
            }
            overlap = candidate_ids & {item["id"] for item in ledger_now["capabilities"]}
            if overlap and overlap != candidate_ids:
                raise MergeError(f"partial capability merge: {len(overlap)}/115")
            values = build_unmerged(from_baseline=True)
            for path, value in zip(
                (LEDGER, MANIFEST, ACCEPTANCE, ORACLES, RECEIPT), values, strict=True
            ):
                path.write_bytes(encoded(value))
            receipt = validate_merged_state()
            print(json.dumps({"lifecycle": "wholly_merged", **receipt["expected_post_counts"]}, sort_keys=True))
            return 0
        state = lifecycle()
        if state == "wholly_merged":
            receipt = validate_merged_state()
            print(json.dumps({"lifecycle": state, **receipt["expected_post_counts"]}, sort_keys=True))
            return 0
        ledger, manifest, acceptance, oracles, receipt = build_unmerged()
        report = {"lifecycle": "prospective_wholly_merged", **receipt["expected_post_counts"]}
        if args.apply:
            for path, value in (
                (LEDGER, ledger),
                (MANIFEST, manifest),
                (ACCEPTANCE, acceptance),
                (ORACLES, oracles),
                (RECEIPT, receipt),
            ):
                path.write_bytes(encoded(value))
            validate_merged_state()
            report["lifecycle"] = "wholly_merged"
        print(json.dumps(report, sort_keys=True))
        return 0
    except (KeyError, StopIteration, MergeError, capability_oracles.OracleContractError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
