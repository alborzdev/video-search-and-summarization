#!/usr/bin/env python3
"""Verify retained Thor event-transport evidence and official projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PARITY))

import build_official_evidence  # noqa: E402
import capability_oracles  # noqa: E402
import verify_official_capabilities  # noqa: E402


EXPECTED = {
    "contract": "2229e2ff89a22fe0454bab8028d5d3764d5d21908fc2e9c742e6e208a29ef043",
    "receipt": "d941aa26df52b5f4e0c3a5505ef92ef319785d060d19267db54fdd221c3000d7",
}
CAPABILITIES = {
    "protocol.kafka.nvschema": {
        "evidence_file": "official-runtime-evidence-kafka.json",
        "evidence_sha256": "c17aa7a3747f60498e3f5ede7897fae415ddabec2fe1cfa377c1e572cb41f192",
        "oracle_sha256": "8aeb8570676e3a8affe79638ac83fdd32eeaf6cb3bf9c89f94f55093c0a25d08",
    },
    "protocol.redis.events": {
        "evidence_file": "official-runtime-evidence-redis.json",
        "evidence_sha256": "ddd6ee935c5a8da3d231d226d9695091ba90d28e9e094335e82137ced124a2e6",
        "oracle_sha256": "a04de14c719c715e5593628de16a4eaf6370341430d31b1a854352e661a901e0",
    },
}


class EventTransportEvidenceError(RuntimeError):
    """Retained event-transport evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EventTransportEvidenceError(
                    f"duplicate JSON key in {path.name}: {key}"
                )
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise EventTransportEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise EventTransportEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise EventTransportEvidenceError("runtime receipt digest drifted")
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("semantic_action_count") != 4
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("warehouse_sample_bundle") is not False
    ):
        raise EventTransportEvidenceError("runtime receipt is not passing and bounded")
    if receipt.get("contract_sha256") != EXPECTED["contract"]:
        raise EventTransportEvidenceError("runtime receipt is not contract-bound")

    kafka = receipt["runtime"]["kafka"]
    redis = receipt["runtime"]["redis"]
    if (
        kafka["status"] != "passed"
        or kafka["positive"]["http_semantic_status"] != 202
        or kafka["positive"]["record_count"] != 1
        or kafka["positive"]["key_match"] is not True
        or kafka["positive"]["protobuf_decoded"] is not True
        or kafka["positive"]["semantic_fields_match"] is not True
        or kafka["negative"]
        != {
            "error_code": "invalid_payload",
            "http_semantic_status": 400,
            "record_published": False,
            "vector_id": "kafka-invalid-protobuf",
        }
    ):
        raise EventTransportEvidenceError("Kafka runtime semantics drifted")
    if (
        redis["status"] != "passed"
        or redis["positive"]["message_count"] != 1
        or redis["positive"]["key_match"] is not True
        or redis["positive"]["value_match"] is not True
        or redis["positive"]["headers_match"] is not True
        or redis["positive"]["timestamp_from_entry_id"] is not True
        or redis["positive"]["pending_after_xack"] != 0
        or redis["negative"]["rejection"] != "JSONDecodeError"
        or redis["negative"]["entry_pending_before_cleanup"] != 1
    ):
        raise EventTransportEvidenceError("Redis runtime semantics drifted")
    cleanup = receipt["cleanup"]
    if (
        cleanup["failures"] != []
        or cleanup["owned_kafka_topic_absent"] is not True
        or cleanup["owned_kafka_group_absent"] is not True
        or cleanup["owned_redis_stream_absent"] is not True
        or cleanup["kafka_nonowned_topic_set_exact"] is not True
        or cleanup["redis_nonowned_key_set_exact"] is not True
        or cleanup["kafka_health_after"] != "healthy"
        or cleanup["redis_health_after"] != "healthy"
    ):
        raise EventTransportEvidenceError("cleanup/restoration drifted")

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    ledger_by_id = {row["id"]: row for row in ledger["capabilities"]}
    oracle_by_id = {row["capability_id"]: row for row in plan["oracles"]}
    rebuilt = build_official_evidence.build()
    evidence_hashes: dict[str, str] = {}
    for capability_id, expected in CAPABILITIES.items():
        evidence, evidence_raw = _load(HERE / expected["evidence_file"])
        if evidence != rebuilt[capability_id]:
            raise EventTransportEvidenceError(
                f"{capability_id}: retained projection is not reproducible"
            )
        evidence_sha = _sha(evidence_raw)
        evidence_hashes[capability_id] = evidence_sha
        if evidence_sha != expected["evidence_sha256"]:
            raise EventTransportEvidenceError(
                f"{capability_id}: official evidence digest drifted"
            )
        oracle = oracle_by_id[capability_id]
        if (
            capability_oracles.canonical_oracle_sha256(oracle)
            != expected["oracle_sha256"]
        ):
            raise EventTransportEvidenceError(
                f"{capability_id}: capability oracle digest drifted"
            )
        capability = ledger_by_id[capability_id]
        evidence_path = (
            "deploy/docker/thor-local/qualification/event-transports-runtime/"
            f"{expected['evidence_file']}"
        )
        if (
            capability.get("runtime_state") != "passed_current"
            or capability.get("thor_state") != "wired"
            or capability.get("runtime_evidence")
            != [{"path": evidence_path, "sha256": evidence_sha}]
            or oracle["acceptance_readiness"]
            != {"classification": "executor_ready", "blockers": []}
        ):
            raise EventTransportEvidenceError(
                f"{capability_id}: official binding drifted"
            )

    counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "status": "passed",
        "capability_ids": sorted(CAPABILITIES),
        "official_capability_count": counts["capabilities"],
        "receipt_sha256": EXPECTED["receipt"],
        "evidence_sha256": evidence_hashes,
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        json.JSONDecodeError,
        EventTransportEvidenceError,
        build_official_evidence.EvidenceProjectionError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
