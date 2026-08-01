#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed validation for the isolated calibration and Warehouse candidate."""

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
sys.path.insert(0, str(SCRIPT_DIR.parent))
import lifecycle as wave3_lifecycle  # noqa: E402
RECURSIVE_TARGETS = SCRIPT_DIR.parent / "recursive-coverage" / "recursive-targets.json"
AGENT_CANDIDATE = SCRIPT_DIR.parent / "agent-smartcity" / "candidate.json"
SYSTEMS_CANDIDATE = SCRIPT_DIR.parent / "systems" / "candidate.json"
PLAIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
EXPECTED_COUNTS = {
    "reviewed_sources": 33,
    "claim_bearing_sources": 27,
    "navigation_duplicate_sources": 6,
    "new_capabilities": 26,
    "enrichments": 20,
    "discrepancies": 4,
    "guardrails": 6,
    "acceptance_vectors": 7,
}
EXPECTED_CLASSES = {"claim_bearing": 27, "navigation_duplicate_reference": 6}
EXPECTED_CANDIDATE_SHA256 = "e8aa7045c93cf0ef73e70034dd7d8efedb4f2c5e54153f10008c83eb70911783"
EXPECTED_CROSS_PACKAGE_SHA256 = {
    "wave3/agent-smartcity": "a0c366965541898d6c9f978f938a1fe8fc77fac84c1b992af09f96fc8d5ea9b7",
    "wave3/systems": "b4417c11a667bf4a6b2fa8c780f90e5504107c25821e117f6a5adc83af19af93",
}


class CandidateContractError(ValueError):
    """The candidate package is inconsistent, unsafe, or no longer isolated."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateContractError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    if not isinstance(value, dict):
        raise CandidateContractError(f"{path.name}: root must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_ids(values: list[Any], label: str) -> set[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or PLAIN_ID.fullmatch(value) is None:
            raise CandidateContractError(f"{label}: invalid id {value!r}")
        result.append(value)
    if len(result) != len(set(result)):
        raise CandidateContractError(f"{label}: duplicate ids")
    return set(result)


def _claims(package: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in package["new_capabilities"]:
        result.extend(item["source_claims"])
    for item in package["enrichments"]:
        result.extend(item["source_claims_add"])
    for key in ("discrepancies", "guardrails"):
        for item in package[key]:
            result.extend(item["source_claims"])
    return result


def _candidate_ids(package: dict[str, Any]) -> set[str]:
    result = {item["id"] for item in package.get("new_capabilities", [])}
    result.update(item["target_id"] for item in package.get("enrichments", []))
    return result


def _validate_live_hashes(package: dict[str, Any], repo_root: Path) -> None:
    expected = {
        "deploy/docker/thor-local/parity/official-capabilities.json",
        "deploy/docker/thor-local/parity/manifest.json",
        "deploy/docker/thor-local/parity/capability-oracles.json",
        "deploy/docker/thor-local/qualification/acceptance_inventory.json",
    }
    if {item["path"] for item in package["live_inputs"]} != expected:
        raise CandidateContractError("live input set drift")
    root = repo_root.resolve(strict=True)
    for item in package["live_inputs"]:
        path = repo_root / item["path"]
        if repo_root.resolve() == REPO_ROOT.resolve():
            path = wave3_lifecycle.validation_path(path)
        path = path.resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CandidateContractError(f"unsafe live input {item['path']}") from exc
        if not path.is_file() or path.is_symlink() or _sha256(path) != item["sha256"]:
            raise CandidateContractError(f"live input hash drift: {item['path']}")


def validate(
    package: dict[str, Any] | None = None,
    *,
    live_ledger: dict[str, Any] | None = None,
    live_manifest: dict[str, Any] | None = None,
    live_acceptance: dict[str, Any] | None = None,
    recursive_targets: dict[str, Any] | None = None,
    agent_candidate: dict[str, Any] | None = None,
    systems_candidate: dict[str, Any] | None = None,
    check_live_hashes: bool = True,
    repo_root: Path = REPO_ROOT,
) -> dict[str, int]:
    package = load_json(CANDIDATE) if package is None else package
    live_ledger = load_json(wave3_lifecycle.validation_path(LIVE_LEDGER)) if live_ledger is None else live_ledger
    live_manifest = load_json(wave3_lifecycle.validation_path(LIVE_MANIFEST)) if live_manifest is None else live_manifest
    live_acceptance = load_json(wave3_lifecycle.validation_path(LIVE_ACCEPTANCE)) if live_acceptance is None else live_acceptance
    if live_ledger == load_json(LIVE_LEDGER) and wave3_lifecycle.state() == "wholly_merged":
        live_ledger = load_json(wave3_lifecycle.validation_path(LIVE_LEDGER))
        if live_manifest == load_json(LIVE_MANIFEST):
            live_manifest = load_json(wave3_lifecycle.validation_path(LIVE_MANIFEST))
        if live_acceptance == load_json(LIVE_ACCEPTANCE):
            live_acceptance = load_json(wave3_lifecycle.validation_path(LIVE_ACCEPTANCE))
    recursive_targets = load_json(RECURSIVE_TARGETS) if recursive_targets is None else recursive_targets
    agent_candidate = load_json(AGENT_CANDIDATE) if agent_candidate is None else agent_candidate
    systems_candidate = load_json(SYSTEMS_CANDIDATE) if systems_candidate is None else systems_candidate
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
        raise CandidateContractError(f"schema violation at {location}: {error.message}")

    counts = {
        "reviewed_sources": len(package["sources"]),
        "claim_bearing_sources": sum(item["classification"] == "claim_bearing" for item in package["sources"]),
        "navigation_duplicate_sources": sum(item["classification"] == "navigation_duplicate_reference" for item in package["sources"]),
        "new_capabilities": len(package["new_capabilities"]),
        "enrichments": len(package["enrichments"]),
        "discrepancies": len(package["discrepancies"]),
        "guardrails": len(package["guardrails"]),
        "acceptance_vectors": len(package["acceptance_vectors"]),
    }
    if package["expected_counts"] != EXPECTED_COUNTS or counts != EXPECTED_COUNTS:
        raise CandidateContractError(f"exact count drift: {counts}")
    if Counter(item["classification"] for item in package["sources"]) != Counter(EXPECTED_CLASSES):
        raise CandidateContractError("source classification count drift")

    source_ids = _unique_ids([item["id"] for item in package["sources"]], "sources")
    source_uris = [item["uri"] for item in package["sources"]]
    if len(source_uris) != len(set(source_uris)):
        raise CandidateContractError("duplicate source URIs")
    binding = package["recursive_coverage_binding"]
    if _sha256(RECURSIVE_TARGETS) != binding["sha256"]:
        raise CandidateContractError("recursive target binding hash drift")
    reachable = set(recursive_targets.get("targets", []))
    if len(reachable) != binding["reachable_count"]:
        raise CandidateContractError("recursive target count drift")
    for source in package["sources"]:
        if source["uri"] != source["recursive_target_uri"]:
            raise CandidateContractError(f"recursive source binding mismatch: {source['id']}")
        if source["uri"] not in reachable:
            raise CandidateContractError(f"source outside recursive coverage: {source['uri']}")

    new_ids = _unique_ids([item["id"] for item in package["new_capabilities"]], "new capabilities")
    enrichment_ids = _unique_ids([item["target_id"] for item in package["enrichments"]], "enrichments")
    _unique_ids([item["id"] for item in package["discrepancies"]], "discrepancies")
    _unique_ids([item["id"] for item in package["guardrails"]], "guardrails")
    vector_ids = _unique_ids([item["id"] for item in package["acceptance_vectors"]], "acceptance vectors")
    live_ids = {item["id"] for item in live_ledger.get("capabilities", [])}
    if new_ids & live_ids:
        raise CandidateContractError(f"new capability already exists live: {sorted(new_ids & live_ids)[0]}")
    if enrichment_ids - live_ids:
        raise CandidateContractError(f"live enrichment target missing: {sorted(enrichment_ids - live_ids)[0]}")
    package_targets = {
        "live_ledger": live_ids,
        "wave3/agent-smartcity": _candidate_ids(agent_candidate),
        "wave3/systems": _candidate_ids(systems_candidate),
    }
    for item in package["enrichments"]:
        targets = {(target["package"], target["id"]) for target in item["merge_targets"]}
        if not any(target_id == item["target_id"] for _, target_id in targets):
            raise CandidateContractError(f"{item['target_id']}: primary merge target absent")
        for package_name, target_id in targets:
            if target_id not in package_targets[package_name]:
                raise CandidateContractError(f"cross-package merge target missing: {package_name}:{target_id}")

    features = {item["id"] for item in live_manifest.get("features", [])}
    scenarios = {item["id"] for item in live_acceptance.get("scenarios", [])}
    status_contract = live_manifest.get("status_contract", {})
    for item in package["new_capabilities"]:
        if item["feature_id"] not in features:
            raise CandidateContractError(f"{item['id']}: unknown feature family")
        for key in ("acceptance_class", "thor_state", "runtime_state"):
            if item["status"][key] not in status_contract.get(key, []):
                raise CandidateContractError(f"{item['id']}: invalid {key}")
        if item["status"]["runtime_state"] in {"passed_current", "passed_prior"}:
            raise CandidateContractError(f"{item['id']}: extraction cannot claim runtime pass")
    for item in [*package["new_capabilities"], *package["enrichments"]]:
        if set(item["qualification"]["scenario_ids"]) - scenarios:
            raise CandidateContractError(f"{item.get('id', item.get('target_id'))}: unknown scenario")
        if set(item["qualification"]["acceptance_vector_ids"]) - vector_ids:
            raise CandidateContractError(f"{item.get('id', item.get('target_id'))}: unknown acceptance vector")

    source_by_id = {item["id"]: item for item in package["sources"]}
    referenced = {claim["source_id"] for claim in _claims(package)}
    if referenced - source_ids:
        raise CandidateContractError(f"unknown source claim: {sorted(referenced - source_ids)[0]}")
    non_claim = {item for item in referenced if source_by_id[item]["classification"] != "claim_bearing"}
    if non_claim:
        raise CandidateContractError(f"non-claim-bearing source used as claim: {sorted(non_claim)[0]}")
    expected_claims = {item["id"] for item in package["sources"] if item["classification"] == "claim_bearing"}
    if referenced != expected_claims:
        raise CandidateContractError(f"claim-bearing source lacks claim: {sorted(expected_claims - referenced)[0]}")

    scope = package["scope"]
    if scope["warehouse_sample_bundle"] != "excluded_optional" or any(item["sample_bundle_required"] for item in package["acceptance_vectors"]):
        raise CandidateContractError("Warehouse sample bundle became required")
    custom_inputs = next(item for item in package["new_capabilities"] if item["id"] == "configuration.warehouse.custom-inputs")["contract"]
    if custom_inputs.get("sample_bundle_required") is not False:
        raise CandidateContractError("Warehouse sample bundle became required")
    prereq = next(item for item in package["new_capabilities"] if item["id"] == "prereq.warehouse.thor-platform")["contract"]
    expected_platform = {"official_platform":"IGX-THOR","official_bsp":"38.5","official_driver":"580.00","host_platform":"AGX-Thor","host_bsp":"38.4","official_host_match":False,"must_not_claim_official_support":True}
    if prereq != expected_platform:
        raise CandidateContractError("AGX/IGX or 38.4/38.5 support boundary drift")
    agent_profile = next(item for item in package["new_capabilities"] if item["id"] == "configuration.warehouse.profile-hardware-matrix")["contract"]
    if agent_profile.get("igx_thor_local_agent_vlm_requires") != "iGPU+dGPU" or agent_profile.get("single_gpu_agent_vlm_officially_supported") is not False:
        raise CandidateContractError("single-GPU Warehouse Agent-VLM support overclaim")
    auto_discrepancy = next(item for item in package["discrepancies"] if item["id"] == "warehouse-autocalibration-platform-surface")
    if "Do not infer official AMC-on-Thor support" not in auto_discrepancy["must_not_claim"]:
        raise CandidateContractError("AMC-on-Thor support boundary drift")
    destructive = next(item for item in package["new_capabilities"] if item["id"] == "behavior.warehouse.destructive-troubleshooting-boundaries")["contract"]
    if destructive.get("automatic_execution_forbidden") is not True or destructive.get("explicit_operator_authorization_required") is not True:
        raise CandidateContractError("destructive FAQ command boundary drift")
    stale = next(item for item in package["discrepancies"] if item["id"] == "warehouse-sdg-stale-repository-paths")
    if "tools/sdg-postprocessing" not in " ".join(stale["observations"]):
        raise CandidateContractError("stale SDG path boundary drift")
    benchmark = next(item for item in package["new_capabilities"] if item["id"] == "performance.warehouse.profile-latency")["contract"]
    if benchmark.get("reference_only") is not True or benchmark.get("must_not_claim_as_thor_result") is not True:
        raise CandidateContractError("benchmark numbers became Thor results")
    for item in package["new_capabilities"]:
        if item["id"].startswith("boundary.warehouse.sdg") or item["id"] == "boundary.warehouse.sim2real":
            if item["contract"].get("runtime_dependency") is not False or item["status"] != {"acceptance_class":"external_optional","thor_state":"external_optional","runtime_state":"not_applicable"}:
                raise CandidateContractError("simulation or training became a Thor runtime dependency")
    expected_guardrails = {
        "guardrail.warehouse-sample-excluded",
        "guardrail.warehouse-operator-data-in-scope",
        "guardrail.warehouse-platform-scope",
        "guardrail.warehouse-agent-vlm-topology",
        "guardrail.warehouse-external-development",
        "guardrail.warehouse-destructive-and-benchmark",
    }
    if {item["id"] for item in package["guardrails"]} != expected_guardrails:
        raise CandidateContractError("guardrail set drift")
    if _canonical_sha256(agent_candidate) != EXPECTED_CROSS_PACKAGE_SHA256["wave3/agent-smartcity"]:
        raise CandidateContractError("Agent/SmartCity cross-package candidate digest drift")
    if _canonical_sha256(systems_candidate) != EXPECTED_CROSS_PACKAGE_SHA256["wave3/systems"]:
        raise CandidateContractError("Systems cross-package candidate digest drift")
    if _canonical_sha256(package) != EXPECTED_CANDIDATE_SHA256:
        raise CandidateContractError("canonical candidate digest drift")
    if check_live_hashes:
        _validate_live_hashes(package, repo_root)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        counts = validate()
    except (OSError, json.JSONDecodeError, KeyError, StopIteration, CandidateContractError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: calibration and Warehouse Wave3 candidate is strict, isolated, sample-free, and boundary-safe")
    if args.report:
        print(", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
