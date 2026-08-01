#!/usr/bin/env python3

"""Fail-closed validation for the isolated Wave-3 systems candidate."""

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
PARITY_DIR = SCRIPT_DIR.parents[2]
CANDIDATE = SCRIPT_DIR / "candidate.json"
SCHEMA = SCRIPT_DIR / "candidate.schema.json"
LIVE_LEDGER = PARITY_DIR / "official-capabilities.json"
LIVE_ACCEPTANCE = REPO_ROOT / "deploy/docker/thor-local/qualification/acceptance_inventory.json"
sys.path.insert(0, str(SCRIPT_DIR.parent))
import lifecycle as wave3_lifecycle  # noqa: E402

EXPECTED_COUNTS = {
    "sources": 23,
    "proposed_capabilities": 55,
    "enrichments": 19,
    "discrepancies_and_boundaries": 18,
    "faq_duplicate_groups": 4,
    "faq_external_groups": 5,
    "performance_fixture_requirements": 7,
}

EXPECTED_SOURCE_PATHS = frozenset(
    """JSON-Schema.html
NvSchema.html
Protobuf-Schema.html
alert-verification-service.html
behavior-analytics.html
elk.html
faq.html
kafka.html
message-broker.html
object-detection-tracking.html
observability.html
performance-alert-verification.html
performance-lvs.html
performance-rt-cv.html
performance-rt-embed.html
performance-rt-vlm.html
performance-search.html
performance-vios.html
redis.html
release-notes.html
video-analytics-api-server.html
vios-microservices.html
vios-nvstreamer.html""".splitlines()
)

EXPECTED_NEW_IDS = frozenset(
    """behavior.base.cr2-nim-recovery
behavior.docker.ngc-pull-29-5
behavior.elk.disk-watermark-recovery
behavior.lvs.caption-spurious-index
behavior.lvs.live-caption-empty-window
behavior.lvs.shared-caption-prompt
behavior.rt-cv.delete-ended-stream
behavior.search-upload.content-type
behavior.search.retention-indexing-quality
behavior.video-analytics.optional-kafka
behavior.vios.upload-playback-remediation
calibration.behavior.dynamic
configuration.alerts.prompt-vlm-warmup
configuration.behavior.dynamic-update
configuration.elk.stack
configuration.lvs.custom-model-prompt
configuration.message-broker.profile-choice
configuration.nvstreamer.full-contract
configuration.nvstreamer.sync
configuration.video-analytics.bootstrap
configuration.vios.upload-effective-limit
customization.alerts.pluggable-parser
customization.behavior.sink-extension
deployment.base.shared-gpu-memory
deployment.elk.gpu-vector-indexing
deployment.network.bridge-firewall
deployment.release.mixed-container-tags
deployment.remote-nim.video-fetch
deployment.rt-cv.compose-extension-contract
deployment.vios.horizontal-scaling
model.alerts.vlm-backends
observability.alerts.prometheus
observability.system.prometheus-stack
performance.alerts.worker-scaling
protocol.alerts.nvschema-ingestion
protocol.behavior.broker-sinks
protocol.elk.logstash-ingestion
protocol.nvschema.format-selection
protocol.nvschema.json-frame
protocol.nvschema.protobuf-messages
runtime.alerts.persistence-output
runtime.alerts.workflow-modes
runtime.base.report-persistence
runtime.behavior.embedding-downsampling
runtime.behavior.events-incidents
runtime.behavior.pipeline
runtime.behavior.space-utilization
runtime.lvs.single-request-queue
runtime.lvs.supported-formats
runtime.nvstreamer.file-streaming
runtime.rt-cv.model-pipelines
runtime.rtvi.input-codec-boundary
runtime.video-analytics.query-and-library-contract
runtime.vios.modular-capabilities
storage.elk.indices-ilm""".splitlines()
)

EXPECTED_ENRICHMENTS = frozenset(
    """api.core.alerts-19
api.core.rt-cv-9
api.core.video-analytics-56
api.core.vst-live-20
api.core.vst-proxy-7
api.core.vst-record-16
api.core.vst-replay-21
api.core.vst-sensor-28
api.core.vst-storage-26-25
model.rt-vlm.default-cosmos3-nano-bf16
performance.alert-verification
performance.rt-cv
performance.rt-embed
performance.rt-vlm
performance.search
performance.video-summarization
performance.vios
protocol.kafka.nvschema
protocol.redis.events""".splitlines()
)

EXPECTED_PERFORMANCE_IDS = frozenset(
    {
        "performance.alert-verification",
        "performance.lvs",
        "performance.search",
        "performance.rt-cv",
        "performance.rt-vlm",
        "performance.rt-embed",
        "performance.vios",
    }
)

EXPECTED_DISCREPANCY_IDS = frozenset(
    """systems.alert-prompt-restart-boundary
systems.alert-workers-default-conflict
systems.elk-gpu-license-external
systems.faq-firewall-subnet-example
systems.faq-hardware-not-thor-evidence
systems.json-schema-illustrative
systems.kafka-redis-topic-asymmetry
systems.nvschema-single-format
systems.observability-insecure-defaults
systems.perf-alert-h100-v31-scope
systems.perf-alert-spark-subsecond-conflict
systems.perf-lvs-model-name-conflict
systems.perf-rt-vlm-model-name-conflict
systems.performance-v32-not-v321
systems.release-cpu-multimedia-vague
systems.release-smartcity-v320-components-vague
systems.vios-https-http-conflict
systems.vios-scaling-service-boundary""".splitlines()
)

EXPECTED_FAQ_DUPLICATES = frozenset(
    {
        "faq.duplicate.rt-input-protocols",
        "faq.duplicate.rt-codecs",
        "faq.duplicate.elk-health-timeout",
        "faq.duplicate.elk-watermark",
    }
)

EXPECTED_FAQ_EXTERNAL = frozenset(
    {
        "faq.external.remote-nim",
        "faq.external.a100-dedicated",
        "faq.external.h200-overrides",
        "faq.external.rtx4500-remote-llm",
        "faq.external.rtx-vlm-settings",
    }
)
EXPECTED_CANDIDATE_SHA256 = "b4417c11a667bf4a6b2fa8c780f90e5504107c25821e117f6a5adc83af19af93"
EXPECTED_EVIDENCE_SHA256 = {
    "evidence/broker-topic-contracts.json": "21d6fd0724ce292ab0e09098485d3d12c8f3e357e81253c2e72ffdc07960b5ef",
    "evidence/nvstreamer-config-contract.json": "968f413829ce9b14efa06f6128258e7ad25cd156bf71a37a5986928abc653e05",
    "evidence/performance-reference-contracts.json": "f5095fa0fbd5d26791c6dfe6d153ba97b63b6d46c51a6a09856c0f14bb089cec",
}


class CandidateError(ValueError):
    """The isolated systems candidate is malformed or overclaims parity."""


def _reject_constant(value: str) -> None:
    raise CandidateError(f"non-finite JSON number is forbidden: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateError(f"duplicate JSON key: {key!r}")
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
        raise CandidateError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateError(f"invalid JSON in {path}: {exc}") from exc


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_schema(document: Any, schema: Any) -> None:
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
    except (SchemaError, ValidationError) as exc:
        raise CandidateError(f"candidate schema validation failed: {exc.message}") from exc


def _unique_ids(values: list[str], label: str) -> set[str]:
    if len(values) != len(set(values)):
        raise CandidateError(f"{label} contains duplicate IDs")
    return set(values)


def _source_refs(package: dict[str, Any]) -> list[str]:
    refs = [item["source"]["source_id"] for item in package["proposed_capabilities"]]
    for item in package["enrichments"]:
        refs.extend(source["source_id"] for source in item["sources"])
    for item in package["discrepancies_and_boundaries"]:
        refs.extend(source["source_id"] for source in item["sources"])
    refs.extend(item["source_id"] for item in package["performance_fixture_requirements"])
    return refs


def _evidence_file(relative: str) -> dict[str, Any]:
    if relative not in EXPECTED_EVIDENCE_SHA256:
        raise CandidateError(f"unreviewed evidence file: {relative}")
    path = SCRIPT_DIR / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(SCRIPT_DIR.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CandidateError(f"missing or unsafe evidence file: {relative}") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise CandidateError(f"evidence must be a regular non-symlink file: {relative}")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != EXPECTED_EVIDENCE_SHA256[relative]:
        raise CandidateError(f"evidence content digest drift: {relative}")
    value = load_json(resolved)
    if not isinstance(value, dict):
        raise CandidateError(f"evidence root must be an object: {relative}")
    return value


def validate(package: dict[str, Any] | None = None) -> dict[str, Any]:
    package = load_json(CANDIDATE) if package is None else package
    if not isinstance(package, dict):
        raise CandidateError("candidate root must be an object")
    validate_schema(package, load_json(SCHEMA))

    observed_counts = {
        "sources": len(package["sources"]),
        "proposed_capabilities": len(package["proposed_capabilities"]),
        "enrichments": len(package["enrichments"]),
        "discrepancies_and_boundaries": len(package["discrepancies_and_boundaries"]),
        "faq_duplicate_groups": len(package["faq_groups"]["duplicates"]),
        "faq_external_groups": len(package["faq_groups"]["external_requirements"]),
        "performance_fixture_requirements": len(package["performance_fixture_requirements"]),
    }
    if observed_counts != EXPECTED_COUNTS or package["expected_counts"] != EXPECTED_COUNTS:
        raise CandidateError(f"exact count drift: {observed_counts}")

    source_ids = _unique_ids([item["id"] for item in package["sources"]], "sources")
    source_paths = {item["url"].rsplit("/", 1)[-1] for item in package["sources"]}
    if source_paths != EXPECTED_SOURCE_PATHS:
        raise CandidateError("exact 23-page source set drifted")
    if Counter(item["category"] for item in package["sources"]) != {
        "system": 14,
        "performance": 7,
        "release": 1,
        "faq": 1,
    }:
        raise CandidateError("source category counts drifted")
    unknown_sources = set(_source_refs(package)) - source_ids
    if unknown_sources:
        raise CandidateError(f"unknown source reference: {sorted(unknown_sources)[0]}")

    new_ids = _unique_ids(
        [item["id"] for item in package["proposed_capabilities"]],
        "proposed capabilities",
    )
    if new_ids != EXPECTED_NEW_IDS:
        raise CandidateError("exact proposed capability set drifted")
    enrichment_ids = _unique_ids(
        [item["target_id"] for item in package["enrichments"]], "enrichments"
    )
    if enrichment_ids != EXPECTED_ENRICHMENTS:
        raise CandidateError("exact enrichment target set drifted")
    discrepancy_ids = _unique_ids(
        [item["id"] for item in package["discrepancies_and_boundaries"]],
        "discrepancies and boundaries",
    )
    if discrepancy_ids != EXPECTED_DISCREPANCY_IDS:
        raise CandidateError("exact discrepancy and boundary set drifted")

    live_ledger = load_json(wave3_lifecycle.validation_path(LIVE_LEDGER))
    if package["target"] != live_ledger.get("target"):
        raise CandidateError("candidate target identity differs from the live ledger")
    live_ids = {item["id"] for item in live_ledger["capabilities"]}
    overlap = new_ids & live_ids
    if overlap:
        raise CandidateError(
            f"isolated proposal overlaps the live ledger: {sorted(overlap)[0]}"
        )
    missing_targets = enrichment_ids - live_ids
    if missing_targets:
        raise CandidateError(
            f"enrichment target missing from live ledger: {sorted(missing_targets)[0]}"
        )

    acceptance = load_json(wave3_lifecycle.validation_path(LIVE_ACCEPTANCE))
    scenario_ids = {item["id"] for item in acceptance["scenarios"]}
    for capability in package["proposed_capabilities"]:
        state = capability["acceptance"]
        if state["scenario_id"] not in scenario_ids:
            raise CandidateError(
                f"{capability['id']}: unknown acceptance scenario {state['scenario_id']}"
            )
        if state["runtime_state"] == "passed_current":
            raise CandidateError(f"{capability['id']}: proposal cannot claim passed_current")

    performance = package["performance_fixture_requirements"]
    performance_ids = _unique_ids([item["id"] for item in performance], "performance")
    if performance_ids != EXPECTED_PERFORMANCE_IDS:
        raise CandidateError("performance requirement set drifted")
    for requirement in performance:
        if requirement["reference_only"] is not True:
            raise CandidateError(f"{requirement['id']}: benchmark must remain reference-only")
        if requirement["thor_remeasurement_required"] is not True:
            raise CandidateError(f"{requirement['id']}: Thor remeasurement is mandatory")

    broker = _evidence_file("evidence/broker-topic-contracts.json")
    if len(broker["kafka"]) != 18 or len(broker["redis"]) != 16:
        raise CandidateError("broker topic evidence count drifted")
    if broker.get("must_not_claim_equivalent_topic_sets") is not True:
        raise CandidateError("broker asymmetry boundary was removed")

    nvstreamer = _evidence_file("evidence/nvstreamer-config-contract.json")
    if nvstreamer.get("reference_only") is not True:
        raise CandidateError("nvStreamer documentation contract must remain reference-only")

    perf_evidence = _evidence_file("evidence/performance-reference-contracts.json")
    if perf_evidence.get("reference_only") is not True or perf_evidence.get("thor_results") is not False:
        raise CandidateError("performance evidence was promoted to a Thor result")
    if {item["id"] for item in perf_evidence.get("fixtures", [])} != EXPECTED_PERFORMANCE_IDS:
        raise CandidateError("performance evidence fixture set drifted")
    if not all(item.get("must_transcribe_all_source_rows") is True for item in perf_evidence["fixtures"]):
        raise CandidateError("a performance fixture no longer requires full source transcription")

    duplicate_claims = {
        item["canonical_claim"] for item in package["faq_groups"]["duplicates"]
    }
    duplicate_ids = _unique_ids(
        [item["id"] for item in package["faq_groups"]["duplicates"]],
        "FAQ duplicates",
    )
    external_ids = _unique_ids(
        [item["id"] for item in package["faq_groups"]["external_requirements"]],
        "FAQ external requirements",
    )
    if duplicate_ids != EXPECTED_FAQ_DUPLICATES or external_ids != EXPECTED_FAQ_EXTERNAL:
        raise CandidateError("exact FAQ classification set drifted")
    if not duplicate_claims <= new_ids:
        raise CandidateError("FAQ duplicate points at a missing canonical claim")
    if any(item["thor_result"] for item in package["faq_groups"]["external_requirements"]):
        raise CandidateError("FAQ external hardware cannot be Thor evidence")

    required_invariants = package["invariants"]
    if not all(required_invariants.values()):
        raise CandidateError("all fail-closed invariants must remain true")

    candidate_sha256 = canonical_sha256(package)
    if candidate_sha256 != EXPECTED_CANDIDATE_SHA256:
        raise CandidateError("candidate content digest drift")

    return {
        **observed_counts,
        "candidate_sha256": candidate_sha256,
        "live_ledger_capabilities": len(live_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        report = validate()
    except CandidateError as exc:
        print(f"systems candidate validation failed: {exc}", file=sys.stderr)
        return 1
    if args.report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("systems candidate validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
