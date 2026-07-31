#!/usr/bin/env python3

"""Fail-closed validation for the isolated Wave-3 docs denominator."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[6]
COVERAGE = SCRIPT_DIR / "coverage.json"
COVERAGE_SCHEMA = SCRIPT_DIR / "coverage.schema.json"
TARGETS = SCRIPT_DIR / "docs-index-targets.json"
TARGETS_SCHEMA = SCRIPT_DIR / "docs-index-targets.schema.json"
BASE_URL = "https://docs.nvidia.com/vss/3.2.1/"
TARGET_SET_SHA256 = "b70c4d6979c3ea2b60e41a5352704aba8e14c39773bde8159e1c725242265f28"

SEMANTIC_OMISSIONS = frozenset(
    """Calibration-Camera-Positioning-Guide.html
JSON-Schema.html
NvSchema.html
Protobuf-Schema.html
VSS-Agents.html
agent-workflow-alert-verification.html
agent-workflow-lvs.html
agent-workflow-rt-alert.html
agent-workflow-search.html
alert-verification-service.html
autocalib-troubleshooting.html
behavior-analytics.html
calibration-schema.html
elk.html
faq.html
kafka.html
message-broker.html
nemoclaw-configuration.html
nemoclaw-deploy-vss-and-skills.html
nemoclaw-troubleshooting.html
nemoclaw.html
object-detection-tracking.html
observability.html
performance-alert-verification.html
performance-lvs.html
performance-rt-cv.html
performance-rt-embed.html
performance-rt-vlm.html
performance-search.html
performance-vios.html
quickstart.html
redis.html
release-notes.html
sdg-calibration.html
smartcity-docs/Blueprint-deep-dive.html
smartcity-docs/Calibration.html
smartcity-docs/Deployment.html
smartcity-docs/Introduction.html
smartcity-docs/Known-Limitations.html
smartcity-docs/Prerequisites.html
smartcity-docs/Quickstart-Guide.html
smartcity-docs/smartcity-toc.html
video-analytics-api-server.html
vios-microservices.html
vios-nvstreamer.html
vss-agent/VSS-Agent-Overview.html
vss-agent/VSS-Agent-Profiles.html
vss-agent/Video-Analytics-MCP-Server.html
vss-ui.html
warehouse-docs/Accuracy-Performance-Benchmarks.html
warehouse-docs/FAQ.html
warehouse-docs/Introduction.html
warehouse-docs/Prerequisites.html
warehouse-docs/Quickstart-Guide.html
warehouse-docs/Release-Notes.html
warehouse-docs/System-Sizing-Guide.html
warehouse-docs/Troubleshooting-Guide.html
warehouse-docs/blueprint-profiles.html
warehouse-docs/warehouse-toc.html""".splitlines()
)

NAVIGATION_REFERENCE = frozenset(
    """API-Reference.html
agent-workflows.html
analytics-microservices.html
api-gateway-mcp.html
calibration.html
configuration-management.html
database.html
deployments.html
genindex.html
getting-started.html
industry-examples.html
middleware.html
models/index.html
performance.html
release-notes-ver-2.html
search.html
smartcity-docs/FAQ.html
smartcity-docs/Operations.html
smartcity-docs/Smartcity-Development-Workflow.html
smartcity-docs/Troubleshooting-Guide.html
vision-microservices.html
vss-agent/vss-agent-api.html
vss-vios.html
vst-live-stream-management-api-reference.html
vst-proxy-stream-management-api-reference.html
vst-record-stream-management-api-reference.html
vst-replay-stream-management-api-reference.html
vst-sensor-management-api-reference.html
vst-storage-management-api-reference.html
warehouse-docs/Appendix-toc.html
warehouse-docs/Core-Development-Workflow.html
warehouse-docs/Models.html
warehouse-docs/Perception.html
warehouse-docs/microservices-configs-and-outputs.html""".splitlines()
)

EXTERNAL_DEPENDENCIES = frozenset(
    """License-Information.html
cloud-brev.html
licenses.html
smartcity-docs/License-Information.html
smartcity-docs/Model-Fine-Tuning.html
smartcity-docs/Simulation-SDG.html
warehouse-docs/License-Information.html
warehouse-docs/Simulation-and-Synthetic-Data-Generation.html""".splitlines()
)


class CoverageError(ValueError):
    """The isolated denominator is malformed, stale, or overclaims coverage."""


def _reject_constant(value: str) -> None:
    raise CoverageError(f"non-finite JSON number is forbidden: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoverageError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except OSError as exc:
        raise CoverageError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CoverageError(f"invalid JSON in {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def repo_file(binding: dict[str, Any]) -> Path:
    relative = Path(binding["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise CoverageError(f"unsafe repository path: {relative}")
    candidate = REPO_ROOT / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise CoverageError(f"bound input is not a regular non-symlink file: {relative}")
    if candidate.resolve().is_relative_to(REPO_ROOT.resolve()) is False:
        raise CoverageError(f"bound input escapes the repository: {relative}")
    observed = sha256_file(candidate)
    if observed != binding["sha256"]:
        raise CoverageError(
            f"bound input hash drift for {relative}: {observed} != {binding['sha256']}"
        )
    return candidate


def validate_schema(document: Any, schema: Any, label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
    except (SchemaError, ValidationError) as exc:
        raise CoverageError(f"{label} schema validation failed: {exc.message}") from exc


def _page_paths(pages: list[dict[str, Any]], category: str) -> set[str]:
    return {
        page["url"].removeprefix(BASE_URL)
        for page in pages
        if page["category"] == category
    }


def validate() -> dict[str, Any]:
    targets = load_json(TARGETS)
    coverage = load_json(COVERAGE)
    validate_schema(targets, load_json(TARGETS_SCHEMA), "docs-index targets")
    validate_schema(coverage, load_json(COVERAGE_SCHEMA), "coverage")

    target_urls = targets["targets"]
    if target_urls != sorted(target_urls):
        raise CoverageError("docs-index targets must be lexicographically sorted")
    if canonical_sha256(target_urls) != TARGET_SET_SHA256:
        raise CoverageError("docs-index canonical URL-set hash differs from the audit")
    target_binding = coverage["docs_index_binding"]
    if target_binding["target_file_sha256"] != sha256_file(TARGETS):
        raise CoverageError("coverage does not bind the exact docs-index target file")

    pages = coverage["pages"]
    page_urls = [page["url"] for page in pages]
    if page_urls != sorted(page_urls):
        raise CoverageError("coverage pages must be lexicographically sorted")
    if len(set(page_urls)) != 152 or set(page_urls) != set(target_urls):
        raise CoverageError("coverage must classify every exact index target once")

    if _page_paths(pages, "semantic_omission") != SEMANTIC_OMISSIONS:
        raise CoverageError("the exact 59-page semantic-omission set drifted")
    if _page_paths(pages, "navigation_duplicate_reference") != NAVIGATION_REFERENCE:
        raise CoverageError("the exact 34-page navigation/reference set drifted")
    if (
        _page_paths(pages, "external_license_sample_dependency")
        != EXTERNAL_DEPENDENCIES
    ):
        raise CoverageError("the exact 8-page external dependency set drifted")

    observed_counts = Counter(page["category"] for page in pages)
    expected_counts = {
        "covered_live": 51,
        "semantic_omission": 59,
        "navigation_duplicate_reference": 34,
        "external_license_sample_dependency": 8,
    }
    if observed_counts != expected_counts:
        raise CoverageError(f"classification count drift: {dict(observed_counts)}")

    bindings = coverage["live_input_bindings"]
    ledger = load_json(repo_file(bindings["official_capability_ledger"]))
    source_lock = load_json(repo_file(bindings["current_source_lock"]))
    api_inventory = load_json(repo_file(bindings["api_inventory"]))
    qualify_path = repo_file(bindings["qualification_implementation"])
    oracles = load_json(repo_file(bindings["capability_oracles"]))
    repo_file(bindings["acceptance_inventory"])

    if len(ledger["sources"]) != 55 or len(ledger["capabilities"]) != 161:
        raise CoverageError("bound live ledger counts differ from 55 sources / 161 claims")

    uri_sources: dict[str, list[str]] = {}
    source_caps: dict[str, list[str]] = {item["id"]: [] for item in ledger["sources"]}
    for source in ledger["sources"]:
        uri = source.get("uri", "")
        if uri.startswith(BASE_URL):
            uri_sources.setdefault(uri, []).append(source["id"])
    release_ref_count = 0
    for capability in ledger["capabilities"]:
        source_ids = {claim["source_id"] for claim in capability["source_claims"]}
        if "release-notes-3.2.1" in source_ids:
            release_ref_count += 1
        for source_id in source_ids:
            source_caps[source_id].append(capability["id"])
    if release_ref_count != 34:
        raise CoverageError("release-note-linked live capability count differs from 34")

    locked_urls = {record["url"] for record in source_lock["records"]}
    if len(source_lock["records"]) != 53 or len(locked_urls & set(target_urls)) != 52:
        raise CoverageError("current source-lock transition no longer matches 53/52")
    if BASE_URL + "release-notes.html" not in locked_urls:
        raise CoverageError("release notes are not present in the current source lock")

    for page in pages:
        source_ids = sorted(uri_sources.get(page["url"], []))
        capability_ids = sorted(
            {cap for source_id in source_ids for cap in source_caps[source_id]}
        )
        if page["live_source_ids"] != source_ids:
            raise CoverageError(f"live source linkage drift: {page['url']}")
        if page["live_capability_ids"] != capability_ids:
            raise CoverageError(f"live capability linkage drift: {page['url']}")
        expected_lock_state = (
            "byte_locked_current"
            if page["url"] in locked_urls
            else "not_in_current_source_lock"
        )
        if page["source_lock_state"] != expected_lock_state:
            raise CoverageError(f"source-lock linkage drift: {page['url']}")
        if page["semantic_proof_from_byte_lock"] is not False:
            raise CoverageError("byte locks may never be represented as semantic proof")
        if page["semantic_proof_from_route_hash"] is not False:
            raise CoverageError("route hashes may never be represented as semantic proof")

    manifest_bindings = bindings["operation_manifests"]
    for item in manifest_bindings["files"]:
        repo_file(item)
    expected_manifest_files = sorted(
        (REPO_ROOT / "deploy/docker/thor-local/qualification/expected").glob("*.json")
    )
    expected_paths = [str(path.relative_to(REPO_ROOT)) for path in expected_manifest_files]
    bound_paths = [item["path"] for item in manifest_bindings["files"]]
    if bound_paths != expected_paths:
        raise CoverageError("operation-manifest binding set is incomplete or unsorted")
    if canonical_sha256(manifest_bindings["files"]) != manifest_bindings[
        "canonical_binding_set_sha256"
    ]:
        raise CoverageError("operation-manifest canonical binding hash drift")

    manifests = [load_json(path) for path in expected_manifest_files]
    rest_operations = [
        operation
        for manifest in manifests
        if manifest["kind"] == "rest"
        for operation in manifest["operations"]
    ]
    hashed = sum(item.get("schema_hash") is not None for item in rest_operations)
    null_hashed = sum(item.get("schema_hash") is None for item in rest_operations)
    tools = sum(len(item.get("tools", [])) for item in manifests)
    prompts = sum(len(item.get("prompts", [])) for item in manifests)
    audit = coverage["api_semantic_audit"]
    derived = {
        "surface_count": len(api_inventory["surfaces"]),
        "declared_rest_operations": api_inventory["expected_totals"][
            "declared_rest_operations"
        ],
        "normalized_unique_rest_operations": api_inventory["expected_totals"][
            "normalized_unique_rest_operations"
        ],
        "rest_operations_with_schema_hash": hashed,
        "rest_operations_with_null_schema_hash": null_hashed,
        "mcp_tools": tools,
        "mcp_prompts": prompts,
        "capability_oracles": len(oracles["oracles"]),
        "executor_ready_capability_oracles": sum(
            item["acceptance_readiness"]["classification"] == "executor_ready"
            for item in oracles["oracles"]
        ),
    }
    for key, value in derived.items():
        if audit[key] != value:
            raise CoverageError(f"API semantic-audit drift for {key}: {value}")
    qualify_source = qualify_path.read_text(encoding="utf-8")
    if 'live_set = {(item["method"], item["path"])' not in qualify_source:
        raise CoverageError("live OpenAPI comparison is no longer visibly method/path-only")
    if audit["route_or_schema_hash_is_semantic_test"] is not False:
        raise CoverageError("route/schema hashes may not be called semantic tests")
    if audit["byte_lock_is_semantic_test"] is not False:
        raise CoverageError("byte locks may not be called semantic tests")

    release = coverage["release_note_audit"]
    if (
        release["v3_2_0_global_feature_bullets"]
        + release["v3_2_0_agent_workflow_top_level_bullets"]
        + release["v3_2_0_system_component_top_level_bullets"]
        + release["v3_2_0_global_known_issue_bullets"]
        != release["v3_2_0_top_level_bullet_total"]
    ):
        raise CoverageError("release-note 3.2.0 bullet arithmetic is inconsistent")
    if (
        release["v3_2_0_top_level_bullet_total"]
        + release["v3_2_1_top_level_feature_bullets"]
        != release["combined_v3_2_1_and_v3_2_0_top_level_bullet_total"]
    ):
        raise CoverageError("combined release-note bullet arithmetic is inconsistent")
    if release["complete_transcription"] is not False:
        raise CoverageError("incomplete release-note transcription cannot be marked complete")

    return {
        "targets": len(target_urls),
        "counts": dict(sorted(observed_counts.items())),
        "release_top_level_bullets": release[
            "combined_v3_2_1_and_v3_2_0_top_level_bullet_total"
        ],
        "rest_operations": len(rest_operations),
        "schema_hashed": hashed,
        "schema_null": null_hashed,
        "mcp_tools": tools,
        "mcp_prompts": prompts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        result = validate()
    except CoverageError as exc:
        print(f"wave3 coverage: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.report:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            "wave3 coverage: PASS: "
            f"{result['targets']} exact index targets; "
            f"classifications={result['counts']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
