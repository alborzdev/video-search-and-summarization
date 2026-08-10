#!/usr/bin/env python3
"""Verify retained Video Analytics API evidence and official projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(PARITY))

import capability_oracles  # noqa: E402
import verify_official_capabilities  # noqa: E402


CAPABILITIES = {
    "runtime.video-analytics.query-and-library-contract": {
        "evidence_file": "official-runtime-evidence-query-library.json",
        "evidence_sha256": "895962811784eb8b03897f048fb9ed5d31156fc0443384ad39c49c1ed13bf8f5",
        "oracle_sha256": "cb013af999e6287d8a95343bb6a4f18adb3cfc38cf1215f1010d262f867aa09d",
    },
    "behavior.video-analytics.optional-kafka": {
        "evidence_file": "official-runtime-evidence-optional-kafka.json",
        "evidence_sha256": "125f3ab237b425c3d0bbd530755f26040d66fc13664fab43626da26d563eb1b3",
        "oracle_sha256": "9b06fffbab0e64fe16bf3a01184ce92b6a2582be7b3526e5689ed4a31c56b1c8",
    },
}
EXPECTED = {
    "contract": "7cbe3cdb682e0180e835eddb703920afc3538645e2669d73076ef3e6c123502b",
    "receipt": "5917fead7e3c57a4f34ab4fb26a4c19489b534f01050f7d1c7d9be1d00fa1222",
}


class VideoAnalyticsEvidenceError(RuntimeError):
    """The retained Video Analytics evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise VideoAnalyticsEvidenceError(
                    f"duplicate JSON key in {path.name}: {key}"
                )
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise VideoAnalyticsEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _observation(evidence: dict[str, Any], observation_id: str) -> Any:
    return next(
        row["value"]
        for row in evidence["observations"]
        if row["id"] == observation_id
    )


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise VideoAnalyticsEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise VideoAnalyticsEvidenceError("runtime receipt digest drifted")
    if (
        receipt.get("status") != "passed"
        or receipt.get("tool_id") != contract["tool_id"]
        or receipt.get("blockers") != []
        or receipt.get("failure") is not None
    ):
        raise VideoAnalyticsEvidenceError("runtime receipt is not a passing result")
    if receipt.get("openapi") != {
        "version": "3.2.0",
        "source_sha256": contract["openapi"]["sha256"],
        "container_sha256": contract["openapi"]["sha256"],
        "operation_count": 56,
        "method_counts": {"GET": 48, "POST": 8},
        "exact_operation_set_match": True,
    }:
        raise VideoAnalyticsEvidenceError("exact OpenAPI identity drifted")
    if receipt.get("request_counts") != {
        "total": 71,
        "positive": 60,
        "negative": 8,
        "status_5xx": 0,
    }:
        raise VideoAnalyticsEvidenceError("request accounting drifted")

    operations = receipt["operations"]
    get_result = operations["get"]
    post_result = operations["post"]
    negatives = operations["post_negatives"]
    brokerless = operations["brokerless"]
    if (
        get_result.get("expected") != 48
        or get_result.get("exercised") != 48
        or get_result.get("all_http_200") is not True
        or get_result.get("exact_openapi_set") is not True
        or get_result["semantic_readbacks"].get("non_empty_data_endpoints") != 40
        or not all(get_result["semantic_readbacks"]["analytics_metrics"].values())
        or post_result.get("expected") != 8
        or post_result.get("exercised") != 8
        or post_result.get("all_positive_201") is not True
        or post_result.get("exact_openapi_set") is not True
        or negatives != {
            "expected": 8,
            "exercised": 8,
            "exact_openapi_set": True,
            "no_5xx": True,
        }
    ):
        raise VideoAnalyticsEvidenceError("query/library runtime semantics drifted")
    if brokerless != {
        "config_brokers": None,
        "api_started": True,
        "livez_http_status": 200,
        "non_kafka_endpoint": {
            "path": "/frames",
            "http_status": 200,
            "fixture_frame_id": "150",
        },
        "kafka_dependent_endpoint": {
            "path": "/tracker/unique-object-count-with-locations",
            "http_status": 422,
            "exact_message_contract": True,
        },
        "kafka_connection_attempt_observed": False,
    }:
        raise VideoAnalyticsEvidenceError("optional-Kafka boundary drifted")

    cleanup = receipt["cleanup"]
    if cleanup != {
        "attempted": True,
        "qualifier_indices_absent": True,
        "qualifier_templates_absent": True,
        "upload_file_set_exact": True,
        "upload_file_count_after": 0,
        "disposable_container_absent": True,
        "brokerless_container_absent": True,
        "original_behavior_containers_restored": True,
        "failures": [],
    }:
        raise VideoAnalyticsEvidenceError("cleanup/restoration drifted")

    ledger_by_id = {row["id"]: row for row in ledger["capabilities"]}
    oracle_by_id = {row["capability_id"]: row for row in plan["oracles"]}
    evidence_hashes: dict[str, str] = {}
    for capability_id, expected in CAPABILITIES.items():
        evidence, evidence_raw = _load(HERE / expected["evidence_file"])
        evidence_sha = _sha(evidence_raw)
        evidence_hashes[capability_id] = evidence_sha
        if evidence_sha != expected["evidence_sha256"]:
            raise VideoAnalyticsEvidenceError(
                f"{capability_id}: official evidence digest drifted"
            )
        capability = ledger_by_id[capability_id]
        oracle = oracle_by_id[capability_id]
        oracle_sha = capability_oracles.canonical_oracle_sha256(oracle)
        if oracle_sha != expected["oracle_sha256"]:
            raise VideoAnalyticsEvidenceError(
                f"{capability_id}: capability oracle digest drifted"
            )
        evidence_path = (
            "deploy/docker/thor-local/qualification/video-analytics-api-runtime/"
            f"{expected['evidence_file']}"
        )
        if (
            capability.get("runtime_state") != "passed_current"
            or capability.get("thor_state") != "wired"
            or capability.get("runtime_evidence")
            != [{"path": evidence_path, "sha256": evidence_sha}]
        ):
            raise VideoAnalyticsEvidenceError(
                f"{capability_id}: official capability binding drifted"
            )

    query_evidence, _ = _load(
        HERE / CAPABILITIES["runtime.video-analytics.query-and-library-contract"][
            "evidence_file"
        ]
    )
    kafka_evidence, _ = _load(
        HERE / CAPABILITIES["behavior.video-analytics.optional-kafka"][
            "evidence_file"
        ]
    )
    query_semantic = _observation(query_evidence, "semantic_result")
    kafka_boundary = _observation(kafka_evidence, "boundary_pair")
    if (
        query_semantic.get("exact_openapi_operations")
        != receipt["openapi"]["operation_count"]
        or query_semantic.get("data_bearing_get_endpoints_non_empty")
        != get_result["semantic_readbacks"]["non_empty_data_endpoints"]
        or kafka_boundary.get("kafka_dependent_http_status")
        != brokerless["kafka_dependent_endpoint"]["http_status"]
        or kafka_boundary.get("non_kafka_http_status")
        != brokerless["non_kafka_endpoint"]["http_status"]
    ):
        raise VideoAnalyticsEvidenceError(
            "official evidence projections differ from runtime receipt"
        )

    counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "capability_ids": sorted(CAPABILITIES),
        "evidence_sha256": evidence_hashes,
        "official_capability_count": counts["capabilities"],
        "receipt_sha256": EXPECTED["receipt"],
        "status": "passed",
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        StopIteration,
        json.JSONDecodeError,
        VideoAnalyticsEvidenceError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
