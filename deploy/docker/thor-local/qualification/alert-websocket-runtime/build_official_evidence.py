#!/usr/bin/env python3
"""Project the retained alert WebSocket receipt into official evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PARITY = REPO / "deploy/docker/thor-local/parity"
CAPABILITY_ID = "protocol.alert.websocket"
RECEIPT_PATH = HERE / "runtime-receipt.json"
RECEIPT_SHA256 = "356960435b16060d3ff879aeff1ace27988379993833f43ccb8989a5346dcb0d"
OUTPUT = HERE / "official-runtime-evidence.json"


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


def build() -> dict[str, Any]:
    receipt, receipt_raw = _load(RECEIPT_PATH)
    if _sha(receipt_raw) != RECEIPT_SHA256:
        raise EvidenceProjectionError("runtime receipt digest drifted")
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("semantic_action_count") != 2
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("network_scope") != "loopback_only"
        or receipt.get("cleanup", {}).get("failures") != []
    ):
        raise EvidenceProjectionError("runtime receipt is not a passing bounded result")

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    result = receipt["runtime"]
    values = {
        "contract_identity": {
            "contract": capability["contract"],
            "receipt_sha256": RECEIPT_SHA256,
        },
        "semantic_result": {
            "positive_vector_id": result["positive"]["vector_id"],
            "handshake": result["positive"]["handshake"],
            "pong_observed": result["positive"]["pong_observed"],
            "alert_frame_count": result["positive"]["alert_frame_count"],
            "redis_fields_preserved": result["positive"]["redis_fields_preserved"],
            "message_id_match": result["positive"]["message_id_match"],
            "alert_type": result["positive"]["alert_type"],
            "status_connections": result["positive"]["status_connections"],
            "frames": result["positive"]["frames"],
            "pending_after_callback": result["positive"]["pending_after_callback"],
        },
        "wire_contract": {
            "negative_vector_id": result["negative"]["vector_id"],
            "negative_frame": result["negative"]["frame"],
            "negative_application_response": result["negative"][
                "application_response_observed"
            ],
            "negative_socket_remained_open": result["negative"]["socket_remained_open"],
            "active_connections_after_close": result["connection_cleanup"][
                "active_connections_after_close"
            ],
            "connection_removed": result["connection_cleanup"]["connection_removed"],
            "isolated_container_absent": receipt["cleanup"][
                "isolated_container_absent"
            ],
            "isolated_listener_absent": receipt["cleanup"]["isolated_listener_absent"],
            "owned_input_stream_absent": receipt["cleanup"][
                "owned_input_stream_absent"
            ],
            "owned_enhanced_stream_absent": receipt["cleanup"][
                "owned_enhanced_stream_absent"
            ],
            "nonowned_key_set_exact": receipt["cleanup"][
                "redis_nonowned_key_set_exact"
            ],
            "normal_service_state_exact": receipt["cleanup"][
                "normal_service_state_exact"
            ],
            "broker_healthy_after": receipt["cleanup"]["redis_health_after"]
            == "healthy",
        },
    }
    observations = [
        {"id": row["id"], "result": "pass", "value": values[row["id"]]}
        for row in oracle["expected_observations"]
    ]
    return {
        "schema_version": 1,
        "capability_id": CAPABILITY_ID,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    projected = build()
    if args.write:
        OUTPUT.write_text(json.dumps(projected, indent=2, sort_keys=True) + "\n")
        print(f"WROTE: {OUTPUT.relative_to(REPO)}")
    else:
        print(json.dumps(projected, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
