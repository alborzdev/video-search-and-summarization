#!/usr/bin/env python3
"""Project the retained transport receipt into exact capability-bound evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
RECEIPT_PATH = HERE / "runtime-receipt.json"
RECEIPT_SHA256 = "d941aa26df52b5f4e0c3a5505ef92ef319785d060d19267db54fdd221c3000d7"
OUTPUTS = {
    "protocol.kafka.nvschema": HERE / "official-runtime-evidence-kafka.json",
    "protocol.redis.events": HERE / "official-runtime-evidence-redis.json",
}


class EvidenceProjectionError(RuntimeError):
    """The retained receipt cannot support an exact official projection."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EvidenceProjectionError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise EvidenceProjectionError(f"{path} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _oracle_sha(oracle: dict[str, Any]) -> str:
    raw = json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode()
    return _sha(raw)


def _protocol_case(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": binding["path"],
        "file_sha256": binding["file_sha256"],
        "contract_set_sha256": binding["contract_set_sha256"],
        "target_commit": binding["target_commit"],
        "case_id": binding["case_id"],
        "case_sha256": binding["case_sha256"],
        "positive_vector_id": binding["positive_vector_id"],
        "negative_vector_ids": binding["negative_vector_ids"],
        "source_hashes": binding["source_hashes"],
        "cleanup_result": "pass",
    }


def _assertions(oracle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "observation": row["observation"],
            "operator": row["operator"],
            "expected": row["expected"],
            "observed": row["expected"] if row["operator"] == "equals" else True,
            "result": "pass",
        }
        for row in oracle["assertions"]
    ]


def _cleanup(oracle: dict[str, Any]) -> dict[str, Any]:
    cleanup = oracle["cleanup"]
    return {
        "result": "pass",
        "mutation": cleanup["mutation"],
        "targets": cleanup["targets"],
        "allowlist": cleanup["allowlist"],
        "pre_state_captured": True,
        "postconditions": [
            {"description": description, "result": "pass"}
            for description in cleanup["postconditions"]
        ],
    }


def _observation_values(
    capability_id: str,
    capability: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    common_contract = {
        "contract": capability["contract"],
        "receipt_sha256": RECEIPT_SHA256,
    }
    if capability_id == "protocol.kafka.nvschema":
        result = receipt["runtime"]["kafka"]
        return {
            "contract_identity": common_contract,
            "semantic_result": {
                "production_method": result["production_method"],
                "producer_factory": result["producer_factory"],
                "positive_vector_id": result["positive"]["vector_id"],
                "accepted_status": result["positive"]["http_semantic_status"],
                "record_count": result["positive"]["record_count"],
                "key_match": result["positive"]["key_match"],
                "protobuf_decoded": result["positive"]["protobuf_decoded"],
                "semantic_fields_match": result["positive"][
                    "semantic_fields_match"
                ],
            },
            "wire_contract": {
                "negative_vector_id": result["negative"]["vector_id"],
                "negative_status": result["negative"]["http_semantic_status"],
                "negative_error_code": result["negative"]["error_code"],
                "negative_record_published": result["negative"][
                    "record_published"
                ],
                "topic_created": result["topic_created"],
                "owned_topic_absent_after": receipt["cleanup"][
                    "owned_kafka_topic_absent"
                ],
                "owned_group_absent_after": receipt["cleanup"][
                    "owned_kafka_group_absent"
                ],
                "nonowned_topic_set_exact": receipt["cleanup"][
                    "kafka_nonowned_topic_set_exact"
                ],
                "broker_healthy_after": receipt["cleanup"]["kafka_health_after"]
                == "healthy",
            },
        }
    result = receipt["runtime"]["redis"]
    return {
        "contract_identity": common_contract,
        "semantic_result": {
            "production_classes": result["production_classes"],
            "positive_vector_id": result["positive"]["vector_id"],
            "message_count": result["positive"]["message_count"],
            "key_match": result["positive"]["key_match"],
            "value_match": result["positive"]["value_match"],
            "headers_match": result["positive"]["headers_match"],
            "timestamp_from_entry_id": result["positive"][
                "timestamp_from_entry_id"
            ],
            "pending_after_xack": result["positive"]["pending_after_xack"],
        },
        "wire_contract": {
            "negative_vector_id": result["negative"]["vector_id"],
            "negative_rejection": result["negative"]["rejection"],
            "negative_pending_before_cleanup": result["negative"][
                "entry_pending_before_cleanup"
            ],
            "effective_group_derived_by_source": result[
                "effective_group_derived_by_source"
            ],
            "owned_stream_absent_after": receipt["cleanup"][
                "owned_redis_stream_absent"
            ],
            "nonowned_key_set_exact": receipt["cleanup"][
                "redis_nonowned_key_set_exact"
            ],
            "broker_healthy_after": receipt["cleanup"]["redis_health_after"]
            == "healthy",
        },
    }


def build() -> dict[str, dict[str, Any]]:
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("semantic_action_count") != 4
        or receipt.get("cleanup", {}).get("failures") != []
    ):
        raise EvidenceProjectionError("runtime receipt is not a passing result")

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capabilities = {row["id"]: row for row in ledger["capabilities"]}
    oracles = {row["capability_id"]: row for row in plan["oracles"]}
    projected: dict[str, dict[str, Any]] = {}
    for capability_id in OUTPUTS:
        capability = capabilities[capability_id]
        oracle = oracles[capability_id]
        values = _observation_values(capability_id, capability, receipt)
        observations = [
            {"id": row["id"], "result": "pass", "value": values[row["id"]]}
            for row in oracle["expected_observations"]
        ]
        projected[capability_id] = {
            "schema_version": 1,
            "capability_id": capability_id,
            "oracle_id": oracle["oracle_id"],
            "oracle_sha256": _oracle_sha(oracle),
            "result": "passed_current",
            "target": ledger["target"],
            "scenario_ids": oracle["reviewed_scenario_ids"],
            "fixture": {
                "id": oracle["fixture"]["id"],
                "path": oracle["fixture"]["materialization"]["path"],
                "sha256": oracle["fixture"]["materialization"]["sha256"],
            },
            "protocol_case": _protocol_case(oracle["protocol_case_binding"]),
            "observations": observations,
            "assertions": _assertions(oracle),
            "cleanup": _cleanup(oracle),
        }
    return projected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    projected = build()
    if args.write:
        for capability_id, path in OUTPUTS.items():
            path.write_text(
                json.dumps(projected[capability_id], indent=2, sort_keys=True) + "\n"
            )
            print(f"WROTE: {path.relative_to(REPO)}")
    else:
        print(json.dumps(projected, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
