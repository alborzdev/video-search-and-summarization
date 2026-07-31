#!/usr/bin/env python3

"""Idempotently merge the reviewed wave-2 extraction into the live contracts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PARITY_DIR = SCRIPT_DIR.parents[1]
REPO_ROOT = SCRIPT_DIR.parents[5]
CANDIDATE = SCRIPT_DIR / "candidate.json"
LEDGER = PARITY_DIR / "official-capabilities.json"
MANIFEST = PARITY_DIR / "manifest.json"
ACCEPTANCE = REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"

CANDIDATE_EVIDENCE = "deploy/docker/thor-local/parity/candidates/wave2/candidate.json"

GAP_SUFFIXES = {
    "base-agent-workflow": (
        " Wave 2 also requires field-level Agent configuration, MCP resolution, "
        "profile-specific report persistence, hierarchy, known-issue, and semantic "
        "report oracles before current-runtime qualification."
    ),
    "agent-evaluation": (
        " A qualifying run must execute nat eval and retain all five documented "
        "evaluation artifacts; static evaluator source is not runtime proof."
    ),
    "rt-embed": (
        " Model-default claims remain scoped: 448p is the base-service default and "
        "448p-anomaly is the search-workflow default. Exact identity, dimensions, "
        "custom model-source integration, and reindex semantics remain unqualified."
    ),
    "auto-calibration": (
        " Official Auto Calibration remains x86_64/Ubuntu 24.04/driver 590 only; "
        "the Thor lane is a custom unsupported extension and must not claim official "
        "Thor support. The Warehouse sample is not required; qualify custom data."
    ),
    "warehouse-2d": (
        " Wave 2 retains the custom-data-only scope for behavior configuration, "
        "alerts, agent hierarchy, UI surfaces, and known limitations; the excluded "
        "roughly 100 GB Warehouse sample is not a parity prerequisite."
    ),
    "infra-observability": (
        " Agent Phoenix qualification must prove the documented root agent span, "
        "child LLM/tool spans, report sub-agent spans, and error/status propagation."
    ),
    "helm": (
        " The four developer-profile charts remain an external Kubernetes surface, "
        "not a Thor-local Compose runtime requirement."
    ),
    "offline-security": (
        " Network isolation and external edge controls are mitigations only: they "
        "must not be represented as remediation of missing internal TLS, message "
        "integrity, consistent authentication, or complete limits/timeouts."
    ),
}


# Each discrepancy must retain two independently reviewable sides even when both
# sides live in one official document.
OBSERVATION_CLAIMS: dict[str, list[tuple[str, str, str]]] = {
    "agent-video-understanding-defaults-three-way": [
        ("agent-config-doc-3.2.1", "video_understanding snippet/table lines 230-260", "Documentation lists 60 seconds, 1568 tokens, and 208544 bytes."),
        ("agent-report-doc-3.2.1", "Base Profile lines 164-220", "The base-profile report example does not establish the deployed video_understanding defaults."),
        ("tagged-repository-wave2-3.2.1", "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml", "The checked-in base profile selects 30 seconds, 3136 tokens, and 8388608 bytes."),
        ("tagged-repository-wave2-3.2.1", "services/agent/src/vss_agents/tools/video_understanding.py", "Pydantic source defaults are 24 seconds, 1568 tokens, and 345600 bytes."),
    ],
    "agent-video-report-prompt-singular-vs-plural": [
        ("agent-report-doc-3.2.1", "Customizing vlm_prompt lines 247-257", "Prose uses the plural vlm_prompts key for video_report_gen."),
        ("tagged-repository-wave2-3.2.1", "services/agent/src/vss_agents/tools/video_report_gen.py", "video_report_gen consumes the singular vlm_prompt key."),
        ("tagged-repository-wave2-3.2.1", "services/agent/src/vss_agents/tools/template_report_gen.py", "The plural vlm_prompts key belongs to template_report_gen."),
    ],
    "agent-evaluation-max-concurrency-example": [
        ("agent-eval-detail-doc-3.2.1", "Running Evaluation example lines 581-665", "The documentation example sets max_concurrency to 10."),
        ("tagged-repository-wave2-3.2.1", "deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml eval.general.max_concurrency", "The checked-in base profile selects max_concurrency 5."),
    ],
    "agent-mcp-tool-name-normalization": [
        ("agent-config-doc-3.2.1", "MCP include examples lines 197-228", "Configuration examples use one MCP include-name representation."),
        ("warehouse-agents-doc-3.2.1", "Video Analytics Tools lines 188-215", "Warehouse documentation presents human-facing video analytics tool names."),
        ("tagged-repository-wave2-3.2.1", "Thor-full Agent config and services/agent video_analytics tests", "Thor/NAT uses normalized double-underscore names such as video_analytics__get_incidents."),
    ],
    "rt-embed-scoped-model-defaults": [
        ("rt-embed-doc-3.2.1", "Supported Models lines 197-202", "Cosmos-Embed1-448p is the RT-Embed service default."),
        ("rt-embed-doc-3.2.1", "Supported Models lines 203-207", "Cosmos-Embed1-448p-anomaly-detection is the search-workflow default."),
    ],
    "rt-embed-repository-script-env-table-omission": [
        ("rt-embed-doc-3.2.1", "Model Configuration lines 523-537", "The documented environment-variable table omits MODEL_REPOSITORY_SCRIPT_PATH."),
        ("tagged-repository-wave2-3.2.1", "services/rtvi/rt-embed/docker/compose.yaml", "Compose supplies a MODEL_REPOSITORY_SCRIPT_PATH default."),
        ("tagged-repository-wave2-3.2.1", "services/rtvi/rt-embed/src/scripts/start_rtvi_embed.sh", "The startup script consumes MODEL_REPOSITORY_SCRIPT_PATH."),
    ],
    "sparse4d-v2.2-class-list-pallet-truck": [
        ("sparse4d-doc-3.2.1", "Model Card class list lines 160-167", "The opening model-card prose lists six classes without pallet_truck."),
        ("sparse4d-doc-3.2.1", "Model Versions v2.2 entry lines 168-178", "The v2.2 release entry says pallet_truck was added."),
    ],
    "model-pages-retain-vss-3.2.0-labels": [
        ("siglip2-doc-3.2.1", "SigLIP 2 at a glance lines 167-192", "The v3.2.1 URL retains VSS 3.2.0 labeling."),
        ("sparse4d-doc-3.2.1", "Model Versions lines 168-178", "The v3.2.1 URL retains VSS 3.2.0 labeling."),
        ("rt-detr-doc-3.2.1", "Model versions lines 239-248", "The v3.2.1 URL retains VSS 3.2.0 labeling."),
        ("main-repository-wave2-7732edf8", "Pinned main commit 7732edf8 documentation comparison", "Pinned main does not replace the versioned v3.2.1 model-page target."),
    ],
    "autocalibration-official-x86-only-thor-custom": [
        ("autocalib-getting-started-doc-3.2.1", "Prerequisites and System Requirements lines 202-218", "Official Auto Calibration requires x86_64, Ubuntu 24.04, and driver 590."),
        ("tagged-repository-wave2-3.2.1", "deploy/docker/services/auto-calibration", "The repository service is the basis for a custom Thor extension, not documented official Thor support."),
    ],
    "autocalibration-host-port-effective-config": [
        ("autocalib-getting-started-doc-3.2.1", "Deployment environment lines 272-280", "The deployment guide configures host port 8000."),
        ("autocalib-getting-started-doc-3.2.1", "Compose port note lines 281-285", "The guide notes Compose may default to host port 8010."),
        ("tagged-repository-wave2-3.2.1", "deploy/docker/services/auto-calibration Compose defaults", "Repository Compose defaults determine the effective selected port."),
    ],
    "warehouse-real-camera-no-tooling-stale": [
        ("warehouse-limitations-doc-3.2.1", "Using Real Cameras in 3D Blueprint lines 195-197", "Real-camera 3D is not thoroughly tested and the page says tooling is unavailable."),
        ("autocalib-overview-doc-3.2.1", "Auto Calibration capabilities lines 160-225", "The same release documents AutoMagicCalib calibration tooling."),
    ],
    "warehouse-thor-local-nim-vs-local-inference": [
        ("warehouse-limitations-doc-3.2.1", "Agents local NIM limitation lines 178-187", "Warehouse Agents do not support local NIM containers on Thor."),
        ("edge-doc-wave2-3.2.1", "AGX/IGX Thor local model deployment recipe", "Edge deployment documents local vLLM/RT-VLM paths, not local NIM support."),
    ],
    "warehouse-alert-vlm-model-prose-conflict": [
        ("warehouse-alerting-doc-3.2.1", "General model note line 185", "The page says all alert rules use Cosmos3 Nano."),
        ("warehouse-alerting-doc-3.2.1", "Near Miss prose line 200", "The Near Miss rule prose names Cosmos Reason 2."),
    ],
    "security-isolation-is-mitigation-not-remediation": [
        ("known-limitations-doc-3.2.1", "Security Considerations lines 163-172", "VSS documents missing internal TLS, integrity protection, consistent authentication, and complete limits/timeouts."),
        ("secure-deployment-doc-3.2.1", "Secure Deployment Recipe lines 160-195", "Loopback, firewall, VPN, and proxy controls mitigate external exposure."),
    ],
}


EXISTING_OBSERVATIONS: dict[str, list[dict[str, str]]] = {
    "lvs-mcp-doc-13-vs-repository-9": [
        {"source_id": "lvs-doc-3.2.1", "locator": "Video Summarization MCP Tools table", "claim": "Versioned VSS 3.2.1 documentation lists 13 MCP tools."},
        {"source_id": "tagged-repository-3.2.1", "locator": "services/vss-agent tool registration at tag v3.2.1", "claim": "The tagged implementation registers nine MCP tools."},
        {"source_id": "main-repository-7732edf8", "locator": "services/vss-agent tool registration at commit 7732edf8", "claim": "Pinned main also registers nine MCP tools."},
    ],
    "rt-vlm-model-table-doc-vs-repository": [
        {"source_id": "rt-vlm-doc-3.2.1", "locator": "Supported Models table", "claim": "Versioned VSS 3.2.1 documentation advertises 18 RT-VLM models."},
        {"source_id": "tagged-repository-3.2.1", "locator": "services/rtvi/rt-vlm README Supported Models", "claim": "The tagged repository README advertises 11 RT-VLM models."},
        {"source_id": "main-repository-7732edf8", "locator": "services/rtvi/rt-vlm README Supported Models", "claim": "Pinned main advertises 11 RT-VLM models."},
    ],
    "thor-edge-model-doc-vs-checkout-skill": [
        {"source_id": "edge-doc-3.2.1", "locator": "AGX/IGX Thor model deployment recipe, updated 2026-07-16", "claim": "The versioned page selects NVIDIA-Nemotron-3-Nano-4B-FP8."},
        {"source_id": "main-repository-7732edf8", "locator": "skills/vss-deploy-profile Thor edge model configuration", "claim": "The checkout skill retains NVIDIA-Nemotron-Edge-4B-v2.1-EA-020126_FP8."},
    ],
    "vss-3.2.1-default-vlm-override": [
        {"source_id": "release-notes-3.2.1", "locator": "VSS 3.2.1 default VLM release note", "claim": "The release-specific default VLM is Cosmos3 Nano."},
        {"source_id": "tagged-repository-3.2.1", "locator": "older Base and RT-VLM default prose/configuration", "claim": "Repository-local prose retains older or alternate model defaults."},
    ],
}

EXISTING_MUST_NOT_CLAIM = {
    "lvs-mcp-doc-13-vs-repository-9": "Do not claim the live repository exposes all 13 documented MCP tools.",
    "rt-vlm-model-table-doc-vs-repository": "Do not claim all 18 documented models are locally staged or runtime-qualified.",
    "thor-edge-model-doc-vs-checkout-skill": "Do not claim the older checkout-skill model is the current official Thor default.",
    "vss-3.2.1-default-vlm-override": "Do not claim older Base or RT-VLM prose overrides the VSS 3.2.1 release-specific default.",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def merge_value(current: Any, addition: Any) -> Any:
    if isinstance(current, dict) and isinstance(addition, dict):
        result = copy.deepcopy(current)
        for key, value in addition.items():
            result[key] = merge_value(result[key], value) if key in result else copy.deepcopy(value)
        return result
    if isinstance(current, list) and isinstance(addition, list):
        result = copy.deepcopy(current)
        for value in addition:
            if value not in result:
                result.append(copy.deepcopy(value))
        return result
    if current != addition:
        raise ValueError(f"unsafe scalar contract conflict: {current!r} != {addition!r}")
    return copy.deepcopy(current)


def fingerprint(items: list[Any]) -> str:
    canonical = sorted(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in items)
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()


def source_hash(ledger: dict[str, Any], source_id: str) -> str:
    claims = []
    for capability in ledger["capabilities"]:
        for claim in capability["source_claims"]:
            if claim["source_id"] == source_id:
                claims.append({"capability_id": capability["id"], "locator": claim["locator"], "contract": capability["contract"]})
    if not claims:
        raise ValueError(f"{source_id}: source has no live capability claim")
    return fingerprint(claims)


def aggregate_family(feature: dict[str, Any], capabilities: list[dict[str, Any]]) -> None:
    classes = {item["acceptance_class"] for item in capabilities}
    feature["acceptance_class"] = "required_local" if "required_local" in classes else "external_optional" if classes == {"external_optional"} else "alternate_local_lane"
    thor = {item["thor_state"] for item in capabilities}
    feature["thor_state"] = next(iter(thor)) if len(thor) == 1 else "partial"
    runtime = {item["runtime_state"] for item in capabilities}
    feature["runtime_state"] = next(iter(runtime)) if len(runtime) == 1 else "not_qualified"


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    package, ledger, manifest, acceptance = load(CANDIDATE), load(LEDGER), load(MANIFEST), load(ACCEPTANCE)
    if package["target"] != ledger["target"]:
        raise ValueError("candidate and live target identities differ")

    source_by_uri = {item["uri"]: item for item in ledger["sources"]}
    source_id_map: dict[str, str] = {}
    for source in package["sources"]:
        existing = source_by_uri.get(source["uri"])
        if existing is None:
            existing = copy.deepcopy(source)
            existing["claim_set_sha256"] = "0" * 64
            ledger["sources"].append(existing)
            source_by_uri[source["uri"]] = existing
        source_id_map[source["id"]] = existing["id"]

    def remap_claims(claims: list[dict[str, str]]) -> list[dict[str, str]]:
        result = []
        for claim in claims:
            item = copy.deepcopy(claim)
            item["source_id"] = source_id_map[item["source_id"]]
            if item not in result:
                result.append(item)
        return result

    capability_by_id = {item["id"]: item for item in ledger["capabilities"]}
    for proposed in package["new_capabilities"]:
        capability_id = proposed["id"]
        if capability_id in capability_by_id:
            continue
        binding = proposed["expected_manifest_binding"]
        contract = copy.deepcopy(proposed["contract"])
        contract["related_expected_manifest"] = binding["path"]
        contract["related_expected_manifest_semantic_coverage"] = False
        contract["related_expected_manifest_reason"] = binding["reason"]
        item = {
            "id": capability_id,
            "feature_id": proposed["feature_id"],
            "kind": proposed["kind"],
            "title": proposed["title"],
            "source_claims": remap_claims(proposed["source_claims"]),
            "acceptance_class": proposed["status"]["acceptance_class"],
            "thor_state": proposed["status"]["thor_state"],
            "runtime_state": proposed["status"]["runtime_state"],
            "contract": contract,
            "scenario_ids": proposed["scenario_ids"],
            "gap": proposed["gap"],
        }
        ledger["capabilities"].append(item)
        capability_by_id[capability_id] = item

    for enrichment in package["enrichments"]:
        target = capability_by_id[enrichment["target_id"]]
        target["contract"] = merge_value(target["contract"], enrichment["contract_merge"])
        target["source_claims"] = merge_value(target["source_claims"], remap_claims(enrichment["source_claims_add"]))

    discrepancy_by_id = {item["id"]: item for item in ledger["source_discrepancies"]}
    for discrepancy in ledger["source_discrepancies"]:
        if discrepancy["id"] in EXISTING_OBSERVATIONS:
            discrepancy["observations"] = EXISTING_OBSERVATIONS[discrepancy["id"]]
            discrepancy["must_not_claim"] = EXISTING_MUST_NOT_CLAIM[
                discrepancy["id"]
            ]
    for proposed in package["discrepancies_and_boundaries"]:
        observations = [
            {"source_id": source_id_map[source_id], "locator": locator, "claim": claim}
            for source_id, locator, claim in OBSERVATION_CLAIMS[proposed["id"]]
        ]
        source_ids = list(dict.fromkeys(item["source_id"] for item in observations))
        item = {
            "id": proposed["id"],
            "source_ids": source_ids,
            "observations": observations,
            "resolution": proposed["resolution"],
            "must_not_claim": proposed["must_not_claim"],
        }
        if proposed["id"] in discrepancy_by_id and discrepancy_by_id[proposed["id"]] != item:
            raise ValueError(f"{proposed['id']}: live discrepancy differs from candidate merge")
        if proposed["id"] not in discrepancy_by_id:
            ledger["source_discrepancies"].append(item)
            discrepancy_by_id[proposed["id"]] = item

    for source in ledger["sources"]:
        source["claim_set_sha256"] = source_hash(ledger, source["id"])

    capabilities_by_feature: dict[str, list[dict[str, Any]]] = {}
    for capability in ledger["capabilities"]:
        capabilities_by_feature.setdefault(capability["feature_id"], []).append(capability)
    for feature in manifest["features"]:
        capabilities = capabilities_by_feature.get(feature["id"])
        if not capabilities:
            continue
        feature["official_capability_ids"] = [item["id"] for item in capabilities]
        for capability in capabilities:
            if capability["title"] not in feature["advertised"]:
                feature["advertised"].append(capability["title"])
        aggregate_family(feature, capabilities)
        if feature["id"] in GAP_SUFFIXES and GAP_SUFFIXES[feature["id"]].strip() not in feature["gap"]:
            feature["gap"] += GAP_SUFFIXES[feature["id"]]
        if feature["id"] in GAP_SUFFIXES and CANDIDATE_EVIDENCE not in feature["thor_evidence"]:
            feature["thor_evidence"].append(CANDIDATE_EVIDENCE)

    coverage_by_feature = {item["feature_id"]: item for item in acceptance["coverage"]["features"]}
    manifest_by_id = {item["id"]: item for item in manifest["features"]}
    for feature_id, feature in manifest_by_id.items():
        record = coverage_by_feature[feature_id]
        record["expected_capability_count"] = len(feature["advertised"])
        record["capabilities_sha256"] = fingerprint(feature["advertised"])
        if feature_id in capabilities_by_feature:
            required_scenarios = set().union(*(set(item["scenario_ids"]) for item in capabilities_by_feature[feature_id]))
            record["scenario_ids"] = sorted(set(record["scenario_ids"]) | required_scenarios)

    return ledger, manifest, acceptance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the compiled live merge")
    args = parser.parse_args()
    ledger, manifest, acceptance = build()
    counts = {
        "sources": len(ledger["sources"]),
        "capabilities": len(ledger["capabilities"]),
        "feature_families": len({item["feature_id"] for item in ledger["capabilities"]}),
        "discrepancies": len(ledger["source_discrepancies"]),
        "manifest_features": len(manifest["features"]),
        "advertised_capabilities": sum(len(item["advertised"]) for item in manifest["features"]),
    }
    if args.apply:
        dump(LEDGER, ledger)
        dump(MANIFEST, manifest)
        dump(ACCEPTANCE, acceptance)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
