#!/usr/bin/env python3
"""Compile the complete VSS capability inventory into bounded runtime lanes.

This module is deliberately static.  It reads checked-in JSON, validates exact
source locks, and emits a plan.  It never invokes Docker, accesses the network,
loads credentials, stages models, or records runtime evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
PLAN = HERE / "runtime-lane-plan.json"
SCHEMA = HERE / "runtime-lane-plan.schema.json"
SOURCE_PATHS = {
    "advertised_gap_plan": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "advertised_gap_rules": "deploy/docker/thor-local/qualification/advertised-entry-gaps/classification-rules.json",
    "manifest": "deploy/docker/thor-local/parity/manifest.json",
    "ledger": "deploy/docker/thor-local/parity/official-capabilities.json",
    "oracles": "deploy/docker/thor-local/parity/capability-oracles.json",
    "oracle_schema": "deploy/docker/thor-local/parity/capability-oracles.schema.json",
}
SOURCE_SHA256 = {
    "advertised_gap_plan": "e57f5fca4cc14b4b37a059823b23a191036ecfda1374791d6f9afde27047b4ec",
    "advertised_gap_rules": "8b32b2fcfa8e669d1b45408c7a8e04c238e54c590be2b5bc24b3506ae1449314",
    "manifest": "bd181bea21b053407da4df7767e73496c4defab100d109e4ee0a3e113e42f35a",
    "ledger": "32befd108b8e4f3eb10c066c3a28a936b277ff68d2b4940cf9e1ef40107e1873",
    "oracles": "000c2dfddd80ecaed14c416cb94827c34d68cb5b05e7111e17678b0aa94db1bb",
    "oracle_schema": "d3f86870fcca6bdb80eacb92bd402a88f34bacd68c42e52ac3408d05e0437498",
}
EXPECTED_DENOMINATORS = {
    "lanes": 8,
    "feature_families": 55,
    "advertised_entries": 500,
    "capabilities": 276,
    "oracles": 276,
    "capabilities_with_exactly_one_lane": 276,
    "feature_families_with_lane_binding": 55,
    "feature_families_without_capability_rows": 16,
    "advertised_entries_with_lane_binding": 500,
    "advertised_entries_in_families_with_capability_oracle_rows": 413,
    "advertised_entries_in_families_without_capability_oracle_rows": 87,
    "advertised_gap_entries_proposed_required_local": 56,
    "advertised_gap_entries_proposed_alternate_local_lane": 26,
    "advertised_gap_entries_proposed_external_optional": 5,
    "advertised_entries_with_entry_specific_capability_mapping": 0,
    "advertised_entries_with_entry_specific_oracle_mapping": 0,
    "advertised_entry_runtime_evidence_records": 0,
    "capabilities_with_planning_only_service_binding": 272,
    "capabilities_with_unresolved_service_binding": 4,
    "required_or_alternate_local_capabilities": 247,
    "runtime_probe_executors": 0,
    "cleanup_executors": 0,
    "runtime_evidence_records": 0,
    "warehouse_sample_bundle_capabilities": 0,
}
EXPECTED_LANE_COUNTS = {
    "base": 45,
    "search": 4,
    "lvs": 10,
    "alerts": 26,
    "standalone-services": 133,
    "custom-data-warehouse": 24,
    "official-edge-model-boundary": 5,
    "external-optional": 29,
}


class RuntimeLaneError(ValueError):
    """The static runtime-lane contract is incomplete or has drifted."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeLaneError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeLaneError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeLaneError(f"JSON root must be an object: {path}")
    return value


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


# Every advertised family has an explicitly reviewed default.  Capability-level
# overrides below handle the few cross-cutting families; unknown families fail.
FAMILY_DEFAULT_LANE = {
    "base-agent-workflow": "base",
    "video-summarization-file": "lvs",
    "video-summarization-live": "lvs",
    "semantic-search": "search",
    "search-scale": "search",
    "alert-verification": "alerts",
    "realtime-alerts": "alerts",
    "alert-notifications-slack": "external-optional",
    "rt-vlm-media": "standalone-services",
    "rt-vlm-api": "standalone-services",
    "rt-vlm-models": "standalone-services",
    "rt-vlm-performance-observability": "standalone-services",
    "rt-embed": "standalone-services",
    "rt-cv-2d": "standalone-services",
    "rt-cv-3d-sparse4d": "custom-data-warehouse",
    "rt-cv-3d-mv3dt": "custom-data-warehouse",
    "behavior-analytics": "standalone-services",
    "video-analytics-api": "standalone-services",
    "auto-calibration": "standalone-services",
    "vios-core": "standalone-services",
    "vios-codecs-audio": "standalone-services",
    "audio-understanding": "standalone-services",
    "vios-ui": "standalone-services",
    "main-ui": "base",
    "smart-city": "alerts",
    "warehouse-2d": "custom-data-warehouse",
    "warehouse-3d-and-mv3dt": "custom-data-warehouse",
    "agent-and-mcp-apis": "base",
    "infra-observability": "standalone-services",
    "spatial-ai-utils": "standalone-services",
    "synthetic-data-tools": "custom-data-warehouse",
    "docker-compose": "standalone-services",
    "helm": "external-optional",
    "nemoclaw-openclaw": "base",
    "enterprise-rag": "external-optional",
    "offline-security": "base",
    "official-agent-models": "standalone-services",
    "configuration-control-plane": "standalone-services",
    "agent-evaluation": "base",
    "model-customization": "standalone-services",
    "calibration-toolchains": "standalone-services",
    "vlm-autoscaling": "external-optional",
    "brev-launchable": "external-optional",
    "secure-deployment-boundary": "external-optional",
    "performance-envelopes": "standalone-services",
    "mv3dt-config-utils": "custom-data-warehouse",
    "extended-api-surfaces": "standalone-services",
    "non-rest-protocols": "standalone-services",
    "release-behavior-contracts": "standalone-services",
    "official-platform-prerequisites": "base",
    "official-thor-support-boundary": "official-edge-model-boundary",
    "core-api-operation-contracts": "standalone-services",
    "agent-operability-surfaces": "base",
    "official-remote-agent-models": "external-optional",
    "synthetic-data-workflows-external": "external-optional",
}


def _lane_definitions() -> list[dict[str, Any]]:
    shared_evidence = [
        "target commit and Thor host identity",
        "profile and service configuration digests",
        "exact image and model artifact identities",
        "fixture provenance and SHA-256",
        "bounded request and observation transcript",
        "every oracle assertion result",
        "cleanup transcript and postcondition results",
    ]
    lifecycle = "explicit operator approval for service lifecycle is absent"
    return [
        {
            "id": "base",
            "title": "Base agent and cross-cutting local workflow",
            "boundary": "thor-local-required",
            "profile_paths": [
                "deploy/docker/developer-profiles/dev-profile-base/compose.yml"
            ],
            "service_compose_paths": [
                "deploy/docker/services/agent/compose.yml",
                "deploy/docker/services/ui/compose.yml",
            ],
            "fixture_strategy": "bounded generated local media plus namespaced agent records",
            "cleanup_requirement": "remove only lane-owned uploads/reports and restore captured profile state",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "capability-specific runtime executors and collectors are not complete",
                "current-run fixture digests and pre-state capture are absent",
            ],
        },
        {
            "id": "search",
            "title": "Archived video semantic search",
            "boundary": "thor-local-required",
            "profile_paths": [
                "deploy/docker/developer-profiles/dev-profile-search/compose.yml"
            ],
            "service_compose_paths": [
                "deploy/docker/services/rtvi/rtvi-embed/rtvi-embed-docker-compose.yml",
                "deploy/docker/services/rtvi/rtvi-cv/compose.yaml",
                "deploy/docker/services/vios/compose.yml",
                "deploy/docker/services/agent/compose.yml",
            ],
            "fixture_strategy": "tiny codec-compatible custom clip with unique sensor and asset IDs",
            "cleanup_requirement": "delete exact ingested asset/sensor/index records and prove adjacent records unchanged",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "exact search model artifacts and current index pre-state are not admitted",
                "capability-specific search executors and collectors are not complete",
            ],
        },
        {
            "id": "lvs",
            "title": "Long video summarization",
            "boundary": "thor-local-required",
            "profile_paths": [
                "deploy/docker/developer-profiles/dev-profile-lvs/compose.yml"
            ],
            "service_compose_paths": [
                "deploy/docker/services/video-summarization/compose.yml",
                "deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml",
                "deploy/docker/services/agent/compose.yml",
            ],
            "fixture_strategy": "tiny codec-compatible local clip with deterministic visual and audio events",
            "cleanup_requirement": "delete exact LVS file/job/report IDs and restore captured service state",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "exact local VLM/LLM artifacts and current LVS executor are not admitted",
                "HITL and async completion collectors are not complete",
            ],
        },
        {
            "id": "alerts",
            "title": "Alert verification, real-time alerts, and Smart City",
            "boundary": "thor-local-required",
            "profile_paths": [
                "deploy/docker/developer-profiles/dev-profile-alerts/compose.yml",
                "deploy/docker/developer-profiles/dev-profile-thor-smartcity/compose.yml",
            ],
            "service_compose_paths": [
                "deploy/docker/services/alert/compose.yml",
                "deploy/docker/services/analytics/behavior-analytics/compose.yml",
                "deploy/docker/services/agent/compose.yml",
                "deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml",
                "deploy/docker/services/rtvi/rtvi-cv/compose.yaml",
                "deploy/docker/services/vios/compose.yml",
                "deploy/docker/services/ui/compose.yml",
            ],
            "fixture_strategy": "custom loopback video/stream with deterministic rule-triggering events",
            "cleanup_requirement": "remove exact alert/rule/incident/sensor IDs and restore captured broker/profile state",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "namespaced broker, rule, notification, and persistence collectors are not complete",
                "current exact alert-verification model artifacts are not admitted",
            ],
        },
        {
            "id": "standalone-services",
            "title": "Standalone VSS microservices and shared infrastructure",
            "boundary": "thor-local-required-or-alternate",
            "profile_paths": [
                "deploy/docker/thor-local/compose.yml",
                "deploy/docker/services/compose.yml",
            ],
            "service_compose_paths": [
                "deploy/docker/services/alert/compose.yml",
                "deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml",
                "deploy/docker/services/rtvi/rtvi-embed/rtvi-embed-docker-compose.yml",
                "deploy/docker/services/rtvi/rtvi-cv/compose.yaml",
                "deploy/docker/services/vios/compose.yml",
                "deploy/docker/services/analytics/behavior-analytics/compose.yml",
                "deploy/docker/services/analytics/video-analytics-api/compose.yml",
                "deploy/docker/services/auto-calibration/compose.yml",
                "deploy/docker/services/monitoring/compose.yml",
                "deploy/docker/services/infra/compose.yml",
                "deploy/docker/services/nim/compose.yml",
                "deploy/docker/industry-profiles/warehouse-operations/warehouse-2d-app/warehouse-2d-app.yml",
            ],
            "fixture_strategy": "capability-specific bounded generated data in an isolated namespace",
            "cleanup_requirement": "apply the exact oracle allowlist and prove captured non-owned state unchanged",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "per-service exact artifact, capacity, fixture, executor, and collector admission remains open",
                "one-service-at-a-time Thor scheduling plan has not been executed",
            ],
        },
        {
            "id": "custom-data-warehouse",
            "title": "Warehouse 2D/3D/MV3DT with custom data only",
            "boundary": "thor-local-alternate-custom-data",
            "profile_paths": [
                "deploy/docker/industry-profiles/warehouse-operations/compose.yml",
                "deploy/docker/thor-local/warehouse-2d.compose.yml",
                "deploy/docker/thor-local/warehouse-sparse4d.compose.yml",
                "deploy/docker/thor-local/warehouse-mv3dt.compose.yml",
            ],
            "service_compose_paths": [
                "deploy/docker/services/analytics/behavior-analytics/compose.yml",
                "deploy/docker/services/analytics/video-analytics-api/compose.yml",
                "deploy/docker/services/auto-calibration/compose.yml",
                "deploy/docker/thor-local/warehouse-2d.compose.yml",
                "deploy/docker/thor-local/warehouse-sparse4d.compose.yml",
                "deploy/docker/thor-local/warehouse-mv3dt.compose.yml",
            ],
            "fixture_strategy": "small user-owned custom media and calibration; official Warehouse sample bundle forbidden",
            "cleanup_requirement": "remove exact custom-data project/sensor/event/index IDs; never delete shared volumes or samples",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "official Warehouse sample bundle is excluded by user scope",
                "custom media, calibration, and exact model artifacts are not admitted",
                "AGX Thor is a custom unsupported Warehouse execution boundary in VSS 3.2.1",
            ],
        },
        {
            "id": "official-edge-model-boundary",
            "title": "Official Thor Edge model identity and support boundary",
            "boundary": "official-thor-edge-contract",
            "profile_paths": ["deploy/docker/thor-local/official-edge/compose.yml"],
            "service_compose_paths": [
                "deploy/docker/thor-local/official-edge/compose.yml"
            ],
            "fixture_strategy": "bounded generated local media after exact official model admission",
            "cleanup_requirement": "remove only namespaced Edge resources and restore every captured workload state",
            "evidence_requirements": shared_evidence,
            "blockers": [
                lifecycle,
                "exact Nemotron 3 Nano 4B FP8 and Cosmos3 Nano BF16 artifacts are not currently staged and verified",
                "prelaunch MemAvailable/Total of at least 0.80 has not been established",
                "older Edge 4B fallback is explicitly unqualified and forbidden",
            ],
        },
        {
            "id": "external-optional",
            "title": "Optional external and managed boundaries",
            "boundary": "external-not-required-for-thor-local-parity",
            "profile_paths": [],
            "service_compose_paths": [],
            "fixture_strategy": "provider-specific fixture only after separate explicit opt-in",
            "cleanup_requirement": "remove only exact externally created IDs and retain provider cleanup receipt",
            "evidence_requirements": shared_evidence,
            "blockers": [
                "external access and credentials are not authorized",
                "external inference is optional and cannot satisfy a required Thor-local capability",
                "provider-side executor, cost bound, and cleanup collector are not admitted",
            ],
        },
    ]


def _capability_lane(capability: dict[str, Any]) -> str:
    capability_id = capability["id"]
    feature_id = capability["feature_id"]
    if capability["acceptance_class"] == "external_optional":
        return "external-optional"
    if capability_id.startswith("model.edge.") or capability_id in {
        "boundary.thor.official-profiles",
        "boundary.thor.fully-local-future",
        "boundary.thor.custom-all-local-extension",
    }:
        return "official-edge-model-boundary"
    if capability_id in {
        "behavior.base.cr2-nim-recovery",
        "observability.agent.phoenix-traces",
        "protocol.agent.websocket",
        "runtime.base.report-persistence",
    }:
        return "base"
    if feature_id in {
        "warehouse-2d",
        "warehouse-3d-and-mv3dt",
        "mv3dt-config-utils",
    }:
        return "custom-data-warehouse"
    if feature_id in {"video-summarization-file", "video-summarization-live"} or (
        ".lvs." in capability_id
        or capability_id.startswith("runtime.lvs.")
        or capability_id.startswith("api.core.lvs")
        or capability_id == "performance.video-summarization"
    ):
        return "lvs"
    if feature_id in {"semantic-search", "search-scale"} or (
        ".search." in capability_id
        or capability_id.startswith("behavior.search.")
        or capability_id == "performance.search"
    ):
        return "search"
    if feature_id in {
        "alert-verification",
        "realtime-alerts",
        "smart-city",
    } or any(
        token in capability_id
        for token in (
            ".alerts.",
            ".alert.",
            "alert-verification",
            "protocol.alert.",
            "performance.alerts.",
            "performance.smart-city.",
            "api.core.alerts-",
        )
    ):
        return "alerts"
    try:
        return FAMILY_DEFAULT_LANE[feature_id]
    except KeyError as exc:
        raise RuntimeLaneError(
            f"{capability_id}: unreviewed feature family {feature_id!r}"
        ) from exc


SERVICE_COMPOSE_PATH = {
    "agent": "deploy/docker/services/agent/compose.yml",
    "alerts": "deploy/docker/services/alert/compose.yml",
    "auto-calibration": "deploy/docker/services/auto-calibration/compose.yml",
    "behavior-analytics": "deploy/docker/services/analytics/behavior-analytics/compose.yml",
    "external-provider": None,
    "host": None,
    "infrastructure": "deploy/docker/services/infra/compose.yml",
    "model-service": "deploy/docker/services/nim/compose.yml",
    "nemoclaw": None,
    "official-edge": "deploy/docker/thor-local/official-edge/compose.yml",
    "repository-tooling": None,
    "rt-cv": "deploy/docker/services/rtvi/rtvi-cv/compose.yaml",
    "rt-embed": "deploy/docker/services/rtvi/rtvi-embed/rtvi-embed-docker-compose.yml",
    "rt-vlm": "deploy/docker/services/rtvi/rtvi-vlm/rtvi-vlm-docker-compose.yml",
    "ui": "deploy/docker/services/ui/compose.yml",
    "vss-configurator": "deploy/docker/industry-profiles/warehouse-operations/warehouse-2d-app/warehouse-2d-app.yml",
    "video-analytics-api": "deploy/docker/services/analytics/video-analytics-api/compose.yml",
    "video-summarization": "deploy/docker/services/video-summarization/compose.yml",
    "vios": "deploy/docker/services/vios/compose.yml",
    "warehouse-2d": "deploy/docker/thor-local/warehouse-2d.compose.yml",
    "warehouse-mv3dt": "deploy/docker/thor-local/warehouse-mv3dt.compose.yml",
    "warehouse-sparse4d": "deploy/docker/thor-local/warehouse-sparse4d.compose.yml",
    "unresolved-service-binding": None,
}


def _planned_service_binding(
    capability: dict[str, Any], lane_id: str
) -> dict[str, Any]:
    capability_id = capability["id"]
    feature_id = capability["feature_id"]

    def binding(
        roles: list[str], basis: str, state: str = "planning_only"
    ) -> dict[str, Any]:
        return {
            "roles": sorted(set(roles)),
            "state": state,
            "basis": basis,
        }

    unresolved_ids = {
        "customization.embedding-reindex-validation",
        "protocol.nvschema.format-selection",
        "protocol.nvschema.json-frame",
        "protocol.nvschema.protobuf-messages",
    }
    if capability_id in unresolved_ids:
        return binding(
            ["unresolved-service-binding"],
            "the checked capability contract does not select one executable service boundary",
            "unresolved",
        )

    explicit_roles = {
        "api.vss-configurator.sensor": ["vss-configurator"],
        "behavior.docker.ngc-pull-29-5": ["host"],
        "config.vss-configurator.profile-manager": ["vss-configurator"],
        "config.vss-configurator.sensor-manager": ["vss-configurator"],
        "configuration.behavior.dynamic-update": [
            "behavior-analytics",
            "infrastructure",
        ],
        "customization.cosmos-embed1": ["rt-embed"],
        "customization.behavior.sink-extension": [
            "behavior-analytics",
            "repository-tooling",
        ],
        "customization.rt-detr": ["rt-cv"],
        "customization.siglip2": ["rt-cv"],
        "deployment.release.mixed-container-tags": ["repository-tooling"],
        "protocol.kafka.nvschema": ["alerts", "infrastructure"],
        "protocol.behavior.broker-sinks": [
            "behavior-analytics",
            "infrastructure",
        ],
        "protocol.redis.events": ["behavior-analytics", "infrastructure"],
        "runtime.rtvi.input-codec-boundary": ["rt-cv"],
        "tooling.agent-harnesses.validated-4": ["repository-tooling"],
        "tooling.agent-skills.catalog-16": ["repository-tooling"],
        "configuration.agent.extension-points": ["agent", "repository-tooling"],
        # These are offline repository utilities, not lifecycle-bound members
        # of the Warehouse MV3DT Compose service. Their custom-data Warehouse
        # acceptance boundary remains unchanged; only the executable role is
        # narrowed to the checked-in tool sources.
        "tool.mv3dt.cam-info-generator": ["repository-tooling"],
        "tool.mv3dt.pub-sub-generator": ["repository-tooling"],
    }
    if capability_id in explicit_roles:
        return binding(
            explicit_roles[capability_id],
            "reviewed checked-in capability contract and service definition",
        )
    if lane_id == "external-optional":
        return binding(["external-provider"], "external acceptance boundary")
    if lane_id == "official-edge-model-boundary":
        return binding(["official-edge"], "official Thor Edge boundary")
    if lane_id == "search":
        return binding(
            ["agent", "rt-cv", "rt-embed", "vios"],
            "reviewed search profile boundary",
        )
    if lane_id == "lvs":
        return binding(
            ["agent", "rt-vlm", "video-summarization"],
            "reviewed LVS profile boundary",
        )
    if lane_id == "alerts":
        roles = ["agent", "alerts", "behavior-analytics", "rt-vlm"]
        if "smart-city" in capability_id or feature_id == "smart-city":
            roles.extend(["rt-cv", "ui", "vios"])
        return binding(roles, "reviewed alerts or Smart City profile boundary")
    if lane_id == "custom-data-warehouse":
        if feature_id == "mv3dt-config-utils" or "mv3dt" in capability_id:
            return binding(["warehouse-mv3dt"], "reviewed MV3DT family rule")
        if "sparse4d" in capability_id:
            return binding(["warehouse-sparse4d"], "reviewed Sparse4D family rule")
        if feature_id == "warehouse-3d-and-mv3dt":
            return binding(
                ["warehouse-mv3dt", "warehouse-sparse4d"],
                "reviewed Warehouse 3D family boundary",
            )
        return binding(["warehouse-2d"], "reviewed Warehouse 2D family rule")
    if lane_id == "base":
        if ".ui." in capability_id or capability_id.startswith("behavior.ui."):
            return binding(["ui"], "reviewed UI capability rule")
        if "nemoclaw" in capability_id:
            return binding(["nemoclaw"], "reviewed NemoClaw capability rule")
        if capability["kind"] in {
            "deployment",
            "security",
            "tooling",
        } or capability_id.startswith("prereq."):
            return binding(["host"], "reviewed non-service host contract rule")
        return binding(["agent"], "reviewed base agent profile boundary")
    if lane_id != "standalone-services":
        raise RuntimeLaneError(f"{capability_id}: unknown lane {lane_id!r}")

    feature_roles = {
        "behavior-analytics": ["behavior-analytics"],
        "video-analytics-api": ["video-analytics-api"],
        "auto-calibration": ["auto-calibration"],
        "rt-embed": ["rt-embed"],
        "rt-cv-2d": ["rt-cv"],
        "vios-core": ["vios"],
        "vios-codecs-audio": ["vios"],
        "vios-ui": ["ui"],
    }
    if feature_id in feature_roles:
        return binding(
            feature_roles[feature_id],
            "reviewed feature-family service boundary",
        )

    tokens_to_role = (
        (("rt-vlm",), "rt-vlm"),
        (("rt-embed",), "rt-embed"),
        (("rt-cv", "deepstream", "rtdetr", "sparse4d"), "rt-cv"),
        (("vios", ".vst-", "nvstreamer"), "vios"),
        (("behavior-analytics",), "behavior-analytics"),
        (("video-analytics", "va-mcp"), "video-analytics-api"),
        (("auto-calibration", "calibration."), "auto-calibration"),
        (("observability", "elk", "message-broker", "sdrc"), "infrastructure"),
        (("model.agent",), "model-service"),
    )
    roles = {
        role
        for tokens, role in tokens_to_role
        if any(token in capability_id for token in tokens)
    }
    if capability["kind"] == "model" and not roles:
        roles.add("model-service")
    if not roles:
        return binding(
            ["unresolved-service-binding"],
            "no checked-in contract rule selects an executable service boundary",
            "unresolved",
        )
    return binding(
        sorted(roles),
        "reviewed capability identifier and feature-family planning rule",
    )


def _load_sources(repo_root: Path) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for name, relative in SOURCE_PATHS.items():
        path = repo_root / relative
        try:
            digest = _raw_sha256(path)
        except OSError as exc:
            raise RuntimeLaneError(f"missing source: {relative}") from exc
        if digest != SOURCE_SHA256[name]:
            raise RuntimeLaneError(
                f"{name} source drift: expected {SOURCE_SHA256[name]}, got {digest}"
            )
        sources[name] = _load(path)
    return sources


def build_plan(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    sources = _load_sources(repo_root)
    manifest = sources["manifest"]
    ledger = sources["ledger"]
    oracle_document = sources["oracles"]
    advertised_gap_plan = sources["advertised_gap_plan"]
    features = manifest.get("features")
    capabilities = ledger.get("capabilities")
    oracles = oracle_document.get("oracles")
    if not all(isinstance(value, list) for value in (features, capabilities, oracles)):
        raise RuntimeLaneError("source arrays are malformed")
    advertised_gap_entries = advertised_gap_plan.get("entries")
    if not isinstance(advertised_gap_entries, list):
        raise RuntimeLaneError("advertised gap-plan entries are malformed")
    advertised_gap_by_pointer = {
        item["manifest_pointer"]: item for item in advertised_gap_entries
    }
    if (
        len(advertised_gap_by_pointer) != len(advertised_gap_entries)
        or len(advertised_gap_entries) != 87
    ):
        raise RuntimeLaneError("advertised gap-plan pointer denominator drift")
    if any(
        item.get("runtime_evidence") != []
        or item.get("coverage_state") != "open_missing_entry_capability_and_oracle"
        or item.get("required_oracle", {}).get("status") != "open_unexecuted"
        for item in advertised_gap_entries
    ):
        raise RuntimeLaneError("advertised gap plan must remain open and evidence-free")

    feature_by_id = {item["id"]: item for item in features}
    capability_by_id = {item["id"]: item for item in capabilities}
    oracle_by_capability = {item["capability_id"]: item for item in oracles}
    if len(feature_by_id) != len(features):
        raise RuntimeLaneError("duplicate feature family ID")
    if len(capability_by_id) != len(capabilities):
        raise RuntimeLaneError("duplicate capability ID")
    if len(oracle_by_capability) != len(oracles):
        raise RuntimeLaneError("duplicate oracle capability binding")
    if set(capability_by_id) != set(oracle_by_capability):
        raise RuntimeLaneError("ledger/oracle capability denominator differs")
    if set(feature_by_id) != set(FAMILY_DEFAULT_LANE):
        missing = sorted(set(feature_by_id) - set(FAMILY_DEFAULT_LANE))
        stale = sorted(set(FAMILY_DEFAULT_LANE) - set(feature_by_id))
        raise RuntimeLaneError(
            f"feature-family review drift; missing={missing}, stale={stale}"
        )

    feature_capability_ids: dict[str, list[str]] = {
        feature_id: [] for feature_id in feature_by_id
    }
    for capability_id, capability in capability_by_id.items():
        feature_id = capability.get("feature_id")
        if feature_id not in feature_by_id:
            raise RuntimeLaneError(
                f"{capability_id}: capability references unknown feature family"
            )
        feature_capability_ids[feature_id].append(capability_id)
    for feature_index, feature in enumerate(features):
        advertised = feature.get("advertised")
        if not isinstance(advertised, list) or not advertised:
            raise RuntimeLaneError(
                f"/features/{feature_index}/advertised: expected non-empty array"
            )
        if any(not isinstance(item, str) or not item for item in advertised):
            raise RuntimeLaneError(
                f"/features/{feature_index}/advertised: expected non-empty strings"
            )
        reviewed_ids = sorted(feature_capability_ids[feature["id"]])
        manifest_ids = sorted(feature.get("official_capability_ids", []))
        if manifest_ids != reviewed_ids:
            raise RuntimeLaneError(
                f"{feature['id']}: manifest/ledger capability family binding drift"
            )

    lanes = _lane_definitions()
    lane_by_id = {lane["id"]: lane for lane in lanes}
    if len(lane_by_id) != len(lanes):
        raise RuntimeLaneError("duplicate runtime lane ID")

    bindings: list[dict[str, Any]] = []
    family_lanes: dict[str, set[str]] = {
        feature_id: set() for feature_id in feature_by_id
    }
    for capability_id in sorted(capability_by_id):
        capability = capability_by_id[capability_id]
        oracle = oracle_by_capability[capability_id]
        if oracle.get("oracle_id") != f"oracle.{capability_id}":
            raise RuntimeLaneError(f"{capability_id}: oracle identity drift")
        ledger_binding = oracle.get("ledger_binding")
        if not isinstance(ledger_binding, dict):
            raise RuntimeLaneError(f"{capability_id}: missing ledger binding")
        for field in (
            "feature_id",
            "kind",
            "acceptance_class",
            "runtime_state",
        ):
            if ledger_binding.get(field) != capability.get(field):
                raise RuntimeLaneError(f"{capability_id}: ledger/oracle {field} drift")
        lane_id = _capability_lane(capability)
        lane = lane_by_id[lane_id]
        service_binding = _planned_service_binding(capability, lane_id)
        planned_service_roles = service_binding["roles"]
        planned_service_paths = sorted(
            {
                path
                for role in planned_service_roles
                if (path := SERVICE_COMPOSE_PATH[role]) is not None
            }
        )
        planned_non_compose_roles = sorted(
            role for role in planned_service_roles if SERVICE_COMPOSE_PATH[role] is None
        )
        if not set(planned_service_paths) <= set(lane["service_compose_paths"]):
            raise RuntimeLaneError(
                f"{capability_id}: planned service is outside lane menu"
            )
        family_lanes[capability["feature_id"]].add(lane_id)
        fixture = copy.deepcopy(oracle.get("fixture"))
        cleanup = copy.deepcopy(oracle.get("cleanup"))
        readiness = oracle.get("acceptance_readiness")
        if not isinstance(fixture, dict) or not isinstance(cleanup, dict):
            raise RuntimeLaneError(f"{capability_id}: fixture or cleanup malformed")
        if not isinstance(readiness, dict):
            raise RuntimeLaneError(f"{capability_id}: readiness malformed")
        if oracle.get("evidence") != []:
            raise RuntimeLaneError(
                f"{capability_id}: current runtime evidence must remain absent"
            )
        if oracle.get("current_state") not in {
            "open_unexecuted",
            "external_boundary_unexecuted",
        }:
            raise RuntimeLaneError(f"{capability_id}: unexpected current state")
        if fixture.get("warehouse_sample_bundle") is not False:
            raise RuntimeLaneError(
                f"{capability_id}: Warehouse sample bundle must be false"
            )
        bindings.append(
            {
                "capability_id": capability_id,
                "oracle_id": oracle["oracle_id"],
                "feature_id": capability["feature_id"],
                "lane_id": lane_id,
                "kind": capability["kind"],
                "acceptance_class": capability["acceptance_class"],
                "runtime_state": capability["runtime_state"],
                "oracle_profile": oracle["profile"],
                "oracle_mode": oracle["mode"],
                "oracle_current_state": oracle["current_state"],
                "oracle_contract_sha256": _canonical_sha256(oracle),
                "deployment": {
                    "profile_paths": copy.deepcopy(lane["profile_paths"]),
                    "planned_service_roles": planned_service_roles,
                    "planned_service_compose_paths": planned_service_paths,
                    "planned_non_compose_roles": planned_non_compose_roles,
                    "service_binding_state": service_binding["state"],
                    "service_binding_basis": service_binding["basis"],
                    "service_binding_source_claims": copy.deepcopy(
                        capability["source_claims"]
                    ),
                    "service_binding_capability_contract_sha256": _canonical_sha256(
                        capability["contract"]
                    ),
                    "service_binding_is_runtime_evidence": False,
                    "boundary": lane["boundary"],
                },
                "probe": {
                    "fixture": fixture,
                    "expected_observation_ids": [
                        item["id"] for item in oracle["expected_observations"]
                    ],
                    "assertion_ids": [item["id"] for item in oracle["assertions"]],
                    "admission_prerequisite_ids": [
                        item["id"] for item in oracle["admission_prerequisites"]
                    ],
                    "execution_bounds": copy.deepcopy(oracle["execution_bounds"]),
                },
                "cleanup": cleanup,
                "evidence": {
                    "current_records": [],
                    "required_fields": copy.deepcopy(lane["evidence_requirements"]),
                    "may_promote_runtime_state_without_current_record": False,
                },
                "blockers": sorted(
                    set(readiness.get("blockers", []))
                    | set(lane["blockers"])
                    | (
                        {"executable service binding is unresolved for this capability"}
                        if service_binding["state"] == "unresolved"
                        else set()
                    )
                ),
            }
        )

    family_bindings: list[dict[str, Any]] = []
    for feature_id in sorted(feature_by_id):
        feature = feature_by_id[feature_id]
        bound = sorted(family_lanes[feature_id])
        default = FAMILY_DEFAULT_LANE[feature_id]
        if not bound:
            bound = [default]
        family_bindings.append(
            {
                "feature_id": feature_id,
                "category": feature["category"],
                "acceptance_class": feature["acceptance_class"],
                "default_lane_id": default,
                "lane_ids": bound,
                "capability_count": len(
                    [item for item in bindings if item["feature_id"] == feature_id]
                ),
                "advertised_entry_count": len(feature["advertised"]),
                "manifest_feature_sha256": _canonical_sha256(feature),
            }
        )

    family_binding_by_id = {item["feature_id"]: item for item in family_bindings}
    advertised_bindings: list[dict[str, Any]] = []
    for feature_index, feature in enumerate(features):
        family_binding = family_binding_by_id[feature["id"]]
        family_capability_ids = sorted(feature_capability_ids[feature["id"]])
        for advertised_index, advertised_claim in enumerate(feature["advertised"]):
            json_pointer = f"/features/{feature_index}/advertised/{advertised_index}"
            gap_entry = advertised_gap_by_pointer.get(json_pointer)
            if bool(family_capability_ids) == bool(gap_entry):
                raise RuntimeLaneError(
                    f"{json_pointer}: advertised gap-plan family binding drift"
                )
            if gap_entry is not None and (
                gap_entry.get("advertised") != advertised_claim
                or gap_entry.get("family_id") != feature["id"]
                or gap_entry.get("family_index") != feature_index
                or gap_entry.get("advertised_index") != advertised_index
            ):
                raise RuntimeLaneError(
                    f"{json_pointer}: advertised gap-plan entry identity drift"
                )
            advertised_bindings.append(
                {
                    "manifest_json_pointer": json_pointer,
                    "feature_id": feature["id"],
                    "feature_manifest_index": feature_index,
                    "advertised_index": advertised_index,
                    "advertised_claim": advertised_claim,
                    "family_acceptance_class": feature["acceptance_class"],
                    "entry_planning_acceptance_class": (
                        gap_entry["proposed_capability"]["acceptance_class"]
                        if gap_entry is not None
                        else None
                    ),
                    "entry_classification_source": (
                        "advertised-entry-gap-plan"
                        if gap_entry is not None
                        else "not-applicable-family-has-capability-rows"
                    ),
                    "default_lane_id": family_binding["default_lane_id"],
                    "lane_ids": copy.deepcopy(family_binding["lane_ids"]),
                    "lane_binding_scope": (
                        "feature_family_reviewed_not_entry_specific"
                    ),
                    "feature_capability_ids": family_capability_ids,
                    "feature_oracle_ids": [
                        oracle_by_capability[capability_id]["oracle_id"]
                        for capability_id in family_capability_ids
                    ],
                    "capability_mapping_scope": (
                        "feature_family_only"
                        if family_capability_ids
                        else "none_family_has_zero_capability_rows"
                    ),
                    "entry_specific_capability_ids": [],
                    "entry_specific_oracle_ids": [],
                    "runtime_evidence_records": [],
                    "manifest_entry_sha256": _canonical_sha256(
                        {
                            "json_pointer": json_pointer,
                            "value": advertised_claim,
                        }
                    ),
                }
            )

    lane_counts = {
        lane["id"]: sum(item["lane_id"] == lane["id"] for item in bindings)
        for lane in lanes
    }
    if lane_counts != EXPECTED_LANE_COUNTS:
        raise RuntimeLaneError(
            f"reviewed lane denominator drift: expected {EXPECTED_LANE_COUNTS}, "
            f"got {lane_counts}"
        )
    denominators = {
        "lanes": len(lanes),
        "feature_families": len(features),
        "advertised_entries": sum(len(feature["advertised"]) for feature in features),
        "capabilities": len(capabilities),
        "oracles": len(oracles),
        "capabilities_with_exactly_one_lane": len(bindings),
        "feature_families_with_lane_binding": len(family_bindings),
        "feature_families_without_capability_rows": sum(
            item["capability_count"] == 0 for item in family_bindings
        ),
        "advertised_entries_with_lane_binding": sum(
            bool(item["lane_ids"]) for item in advertised_bindings
        ),
        "advertised_entries_in_families_with_capability_oracle_rows": sum(
            bool(item["feature_capability_ids"]) for item in advertised_bindings
        ),
        "advertised_entries_in_families_without_capability_oracle_rows": sum(
            not item["feature_capability_ids"] for item in advertised_bindings
        ),
        "advertised_gap_entries_proposed_required_local": sum(
            item["entry_planning_acceptance_class"] == "required_local"
            for item in advertised_bindings
        ),
        "advertised_gap_entries_proposed_alternate_local_lane": sum(
            item["entry_planning_acceptance_class"] == "alternate_local_lane"
            for item in advertised_bindings
        ),
        "advertised_gap_entries_proposed_external_optional": sum(
            item["entry_planning_acceptance_class"] == "external_optional"
            for item in advertised_bindings
        ),
        "advertised_entries_with_entry_specific_capability_mapping": sum(
            bool(item["entry_specific_capability_ids"]) for item in advertised_bindings
        ),
        "advertised_entries_with_entry_specific_oracle_mapping": sum(
            bool(item["entry_specific_oracle_ids"]) for item in advertised_bindings
        ),
        "advertised_entry_runtime_evidence_records": sum(
            len(item["runtime_evidence_records"]) for item in advertised_bindings
        ),
        "capabilities_with_planning_only_service_binding": sum(
            item["deployment"]["service_binding_state"] == "planning_only"
            for item in bindings
        ),
        "capabilities_with_unresolved_service_binding": sum(
            item["deployment"]["service_binding_state"] == "unresolved"
            for item in bindings
        ),
        "required_or_alternate_local_capabilities": sum(
            item["acceptance_class"] != "external_optional" for item in bindings
        ),
        "runtime_probe_executors": sum(
            item["probe"]["execution_bounds"]["executor"] is not None
            for item in bindings
        ),
        "cleanup_executors": sum(
            item["cleanup"]["executor"] is not None for item in bindings
        ),
        "runtime_evidence_records": sum(
            len(item["evidence"]["current_records"]) for item in bindings
        ),
        "warehouse_sample_bundle_capabilities": sum(
            item["probe"]["fixture"]["warehouse_sample_bundle"] is not False
            for item in bindings
        ),
    }
    if denominators != EXPECTED_DENOMINATORS:
        raise RuntimeLaneError(
            f"exact denominator drift: expected {EXPECTED_DENOMINATORS}, got {denominators}"
        )

    return {
        "schema_version": 1,
        "plan_id": "thor-vss-3.2.1-complete-runtime-lanes",
        "target": {
            "platform": "NVIDIA Jetson AGX Thor",
            "release": "VSS 3.2.1",
            "evidence_state": "planning_only_no_runtime_qualification",
        },
        "source_bindings": {
            name: {"path": SOURCE_PATHS[name], "raw_sha256": SOURCE_SHA256[name]}
            for name in sorted(SOURCE_PATHS)
        },
        "policy": {
            "exactly_one_lane_per_capability": True,
            "all_feature_families_bound": True,
            "all_advertised_entries_bound": True,
            "advertised_entry_mapping_scope": "feature_family_only",
            "advertised_entry_bindings_are_runtime_evidence": False,
            "zero_capability_family_entries_block_runtime_completeness": True,
            "literal_runtime_feature_completeness_claim_allowed": False,
            "unresolved_service_bindings_block_runtime_completeness": True,
            "planned_service_bindings_are_runtime_evidence": False,
            "required_cloud_inference": False,
            "external_optional_cannot_satisfy_local": True,
            "warehouse_sample_bundle": "excluded",
            "warehouse_custom_data": "in_scope",
            "runtime_evidence_created": False,
            "live_parity_artifacts_mutated": False,
        },
        "denominators": denominators,
        "lane_capability_counts": lane_counts,
        "lanes": lanes,
        "feature_family_bindings": family_bindings,
        "advertised_entry_bindings": advertised_bindings,
        "capability_bindings": bindings,
    }


def validate_plan(plan: dict[str, Any], repo_root: Path = REPO_ROOT) -> None:
    try:
        schema = _load(
            repo_root
            / "deploy/docker/thor-local/qualification/runtime-lanes/runtime-lane-plan.schema.json"
        )
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(plan),
            key=lambda error: list(error.absolute_path),
        )
    except SchemaError as exc:
        raise RuntimeLaneError("runtime-lane schema is invalid") from exc
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise RuntimeLaneError(f"schema validation failed at {where}: {first.message}")

    expected = build_plan(repo_root)
    if plan != expected:
        raise RuntimeLaneError(
            "checked plan differs from deterministic compiler output"
        )
    lane_ids = {lane["id"] for lane in plan["lanes"]}
    if len(lane_ids) != EXPECTED_DENOMINATORS["lanes"]:
        raise RuntimeLaneError("lane ID denominator drift")
    capability_ids = [item["capability_id"] for item in plan["capability_bindings"]]
    if len(capability_ids) != len(set(capability_ids)):
        raise RuntimeLaneError("capability appears in more than one lane binding")
    if any(item["lane_id"] not in lane_ids for item in plan["capability_bindings"]):
        raise RuntimeLaneError("capability references an unknown lane")
    if any(
        item["acceptance_class"] == "external_optional"
        and item["lane_id"] != "external-optional"
        for item in plan["capability_bindings"]
    ):
        raise RuntimeLaneError("external optional capability escaped its boundary")
    if any(
        item["probe"]["fixture"]["warehouse_sample_bundle"] is not False
        for item in plan["capability_bindings"]
    ):
        raise RuntimeLaneError("Warehouse sample bundle exclusion drift")
    if any(item["evidence"]["current_records"] for item in plan["capability_bindings"]):
        raise RuntimeLaneError("runtime evidence cannot be created by this compiler")
    if any(
        item["deployment"]["service_binding_is_runtime_evidence"]
        for item in plan["capability_bindings"]
    ):
        raise RuntimeLaneError(
            "planned service bindings cannot count as runtime evidence"
        )
    unresolved_service_bindings = [
        item
        for item in plan["capability_bindings"]
        if item["deployment"]["service_binding_state"] == "unresolved"
    ]
    if (
        len(unresolved_service_bindings)
        != EXPECTED_DENOMINATORS["capabilities_with_unresolved_service_binding"]
    ):
        raise RuntimeLaneError("unresolved service-binding denominator drift")
    if not unresolved_service_bindings:
        raise RuntimeLaneError(
            "runtime completeness cannot be unblocked without reviewed service bindings"
        )
    advertised_pointers = [
        item["manifest_json_pointer"] for item in plan["advertised_entry_bindings"]
    ]
    if len(advertised_pointers) != len(set(advertised_pointers)):
        raise RuntimeLaneError("advertised manifest entry appears more than once")
    if any(not item["lane_ids"] for item in plan["advertised_entry_bindings"]):
        raise RuntimeLaneError("advertised manifest entry has no lane binding")
    if any(
        len(item["feature_capability_ids"]) != len(item["feature_oracle_ids"])
        for item in plan["advertised_entry_bindings"]
    ):
        raise RuntimeLaneError("advertised family capability/oracle binding drift")
    if any(
        item["entry_specific_capability_ids"]
        or item["entry_specific_oracle_ids"]
        or item["runtime_evidence_records"]
        for item in plan["advertised_entry_bindings"]
    ):
        raise RuntimeLaneError(
            "advertised entry binding cannot imply unreviewed semantic or runtime evidence"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        expected = build_plan()
        validate_plan(expected)
        if args.write:
            PLAN.write_bytes(_encoded(expected))
            print(f"WROTE: {PLAN.relative_to(REPO_ROOT)}")
            return 0
        actual = _load(PLAN)
        validate_plan(actual)
        if PLAN.read_bytes() != _encoded(expected):
            raise RuntimeLaneError("checked plan is not canonically encoded")
        counts = expected["lane_capability_counts"]
        print(
            "PASS: runtime lane plan; "
            f"{expected['denominators']['capabilities']} capabilities, "
            f"{expected['denominators']['feature_families']} families, "
            f"{expected['denominators']['advertised_entries']} advertised entries, "
            + ", ".join(f"{name}={count}" for name, count in counts.items())
        )
        return 0
    except (OSError, RuntimeLaneError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
