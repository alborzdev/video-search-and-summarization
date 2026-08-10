#!/usr/bin/env python3
"""Verify retained Thor alert WebSocket evidence and official projection."""

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


CAPABILITY_ID = "protocol.alert.websocket"
EXPECTED = {
    "contract": "bb96e55fe28f1c480175086e4f6cfc1dc1b0216d72a825fb73eb6c9f2722953f",
    "receipt": "356960435b16060d3ff879aeff1ace27988379993833f43ccb8989a5346dcb0d",
    "evidence": "66ed95ec555d38d32a745c14e6ff8a1af4af0e56c6874f0fb1c6d2975444b44a",
    "oracle": "e82640a315847718181cb67eff191e6206ec3e903b531016f5086545fc1c4b1a",
}


class AlertWebSocketEvidenceError(RuntimeError):
    """Retained alert WebSocket evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AlertWebSocketEvidenceError(
                    f"duplicate JSON key in {path.name}: {key}"
                )
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise AlertWebSocketEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify() -> dict[str, Any]:
    contract, contract_raw = _load(HERE / "contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    if _sha(contract_raw) != EXPECTED["contract"]:
        raise AlertWebSocketEvidenceError("fixture contract digest drifted")
    if _sha(receipt_raw) != EXPECTED["receipt"]:
        raise AlertWebSocketEvidenceError("runtime receipt digest drifted")
    if (
        receipt.get("status") != "passed"
        or receipt.get("failure") is not None
        or receipt.get("blockers") != []
        or receipt.get("semantic_action_count") != 2
        or receipt.get("forbidden_actions_observed") != []
        or receipt.get("warehouse_sample_bundle") is not False
        or receipt.get("network_scope") != "loopback_only"
    ):
        raise AlertWebSocketEvidenceError("runtime receipt is not passing and bounded")
    if receipt.get("contract_sha256") != EXPECTED["contract"]:
        raise AlertWebSocketEvidenceError("runtime receipt is not contract-bound")

    runtime = receipt["runtime"]
    positive = runtime["positive"]
    negative = runtime["negative"]
    if (
        runtime["status"] != "passed"
        or positive["vector_id"] != "alert-ws-one-owned-entry"
        or positive["handshake"] != "HTTP Upgrade to WebSocket"
        or positive["pong_observed"] is not True
        or positive["alert_frame_count"] != 1
        or positive["redis_fields_preserved"] is not True
        or positive["message_id_match"] is not True
        or positive["alert_type"] != "original"
        or positive["status_connections"] != 1
        or positive["frames"] != ["pong", "alert", "status"]
        or positive["pending_after_callback"] != 0
    ):
        raise AlertWebSocketEvidenceError("positive WebSocket semantics drifted")
    if negative != {
        "application_response_observed": False,
        "frame": "non-json",
        "socket_remained_open": True,
        "vector_id": "alert-ws-non-json",
    }:
        raise AlertWebSocketEvidenceError("adjacent-negative semantics drifted")
    if runtime["connection_cleanup"] != {
        "active_connections_after_close": 0,
        "connection_removed": True,
    }:
        raise AlertWebSocketEvidenceError("connection cleanup drifted")

    cleanup = receipt["cleanup"]
    if (
        cleanup["failures"] != []
        or cleanup["isolated_container_absent"] is not True
        or cleanup["isolated_listener_absent"] is not True
        or cleanup["owned_input_stream_absent"] is not True
        or cleanup["owned_enhanced_stream_absent"] is not True
        or cleanup["redis_nonowned_key_set_exact"] is not True
        or cleanup["normal_service_state_exact"] is not True
        or cleanup["redis_health_after"] != "healthy"
    ):
        raise AlertWebSocketEvidenceError("cleanup/restoration drifted")

    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")
    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    rebuilt = build_official_evidence.build()
    if evidence != rebuilt:
        raise AlertWebSocketEvidenceError("retained projection is not reproducible")
    evidence_sha = _sha(evidence_raw)
    if evidence_sha != EXPECTED["evidence"]:
        raise AlertWebSocketEvidenceError("official evidence digest drifted")
    if capability_oracles.canonical_oracle_sha256(oracle) != EXPECTED["oracle"]:
        raise AlertWebSocketEvidenceError("capability oracle digest drifted")
    evidence_path = (
        "deploy/docker/thor-local/qualification/alert-websocket-runtime/"
        "official-runtime-evidence.json"
    )
    if (
        capability.get("runtime_state") != "passed_current"
        or capability.get("thor_state") != "wired"
        or capability.get("runtime_evidence")
        != [{"path": evidence_path, "sha256": evidence_sha}]
        or oracle["acceptance_readiness"]
        != {"classification": "executor_ready", "blockers": []}
        or oracle["cleanup"]["targets"]
        != capability_oracles.ALERT_WEBSOCKET_RUNTIME_NAMESPACES
    ):
        raise AlertWebSocketEvidenceError("official WebSocket binding drifted")

    counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "status": "passed",
        "capability_id": CAPABILITY_ID,
        "official_capability_count": counts["capabilities"],
        "receipt_sha256": EXPECTED["receipt"],
        "evidence_sha256": evidence_sha,
        "oracle_sha256": EXPECTED["oracle"],
    }


def main() -> int:
    try:
        result = verify()
    except (
        OSError,
        KeyError,
        StopIteration,
        json.JSONDecodeError,
        AlertWebSocketEvidenceError,
        build_official_evidence.EvidenceProjectionError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
