#!/usr/bin/env python3
"""Verify the retained VIOS WebRTC replay receipt and oracle projection."""

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


CAPABILITY_ID = "protocol.vios.webrtc-replay"
EXPECTED = {
    "fixture": "0cdf3e7196e191f0a0f68c24c7b93eb06b223991372ec625443c40f7c19aeebd",
    "receipt": "77f99ba9d383838e53e39ce6c9e38f2e2df89d7ae1632014a29a017afe581adf",
    "evidence": "1475508276dc062fccd070d696718a7b10a88c8a613778aa2b30d822728dba1f",
    "oracle": "44890e277752ed50faabd548d2423aea19c8e4af87fa16a6ae3eecdb2b89495b",
}


class ReplayEvidenceError(RuntimeError):
    """The retained replay evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ReplayEvidenceError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ReplayEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify() -> dict[str, Any]:
    fixture, fixture_raw = _load(HERE / "fixture-contract.json")
    receipt, receipt_raw = _load(HERE / "runtime-receipt.json")
    evidence, evidence_raw = _load(HERE / "official-runtime-evidence.json")
    ledger, _ = _load(PARITY / "official-capabilities.json")
    plan, _ = _load(PARITY / "capability-oracles.json")

    observed = {
        "fixture": _digest(fixture_raw),
        "receipt": _digest(receipt_raw),
        "evidence": _digest(evidence_raw),
    }
    if observed != {key: EXPECTED[key] for key in observed}:
        raise ReplayEvidenceError("fixture, receipt, or evidence digest drifted")

    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    oracle_digest = capability_oracles.canonical_oracle_sha256(oracle)
    if oracle_digest != EXPECTED["oracle"]:
        raise ReplayEvidenceError("capability oracle digest drifted")
    if capability.get("runtime_state") != "passed_current":
        raise ReplayEvidenceError("official capability is not passed_current")
    if receipt.get("status") != "passed" or receipt.get("runtime_evidence") is not True:
        raise ReplayEvidenceError("runtime receipt is not a retained passing result")
    if receipt.get("capability_results") != {CAPABILITY_ID: "passed_current"}:
        raise ReplayEvidenceError("runtime receipt capability result drifted")
    if receipt.get("bounds") != {
        "agent_generate_called": False,
        "browser_external_request_count": 0,
        "browser_http_response_count": 29,
        "browser_websocket_frame_count": 21,
        "docker_lifecycle_actions": 0,
        "http_loopback_only": True,
        "main_vios_sensor_added": False,
        "persistent_mutations": 0,
        "rt_cv_stream_added": False,
        "warehouse_sample_bundle_used": False,
    }:
        raise ReplayEvidenceError("runtime confinement accounting drifted")
    semantic = receipt.get("observations", {}).get("semantic_result")
    wire = receipt.get("observations", {}).get("wire_contract")
    if semantic != evidence["observations"][1]["value"]:
        raise ReplayEvidenceError("semantic replay projection differs from receipt")
    if (
        wire.get("positive_seek_status") != 200
        or wire.get("get_position_without_action_status") != 200
        or wire.get("invalid_action_status") != 501
        or wire.get("invalid_action_error_code") != "VMSNotSupportedError"
        or wire.get("ui_seek_status") != 200
        or wire.get("signaling_complete") is not True
        or wire.get("stop_frame_observed") is not True
        or wire.get("websocket_closed") is not True
    ):
        raise ReplayEvidenceError("wire-level replay result drifted")
    privacy = receipt.get("observations", {}).get("browser", {}).get("privacy")
    if privacy != {
        "ice_candidates_retained": False,
        "media_session_ids_retained": False,
        "peer_ids_retained": False,
        "sdp_retained": False,
    }:
        raise ReplayEvidenceError("ephemeral WebRTC privacy contract drifted")
    if receipt.get("cleanup", {}).get("result") != "passed":
        raise ReplayEvidenceError("runtime cleanup did not pass")

    counts = verify_official_capabilities.validate(repo_root=REPO)
    return {
        "capability_id": CAPABILITY_ID,
        "evidence_sha256": observed["evidence"],
        "oracle_sha256": oracle_digest,
        "official_capability_count": counts["capabilities"],
        "status": "passed",
    }


def main() -> int:
    try:
        result = verify()
    except (OSError, KeyError, StopIteration, json.JSONDecodeError, ReplayEvidenceError,
            verify_official_capabilities.CapabilityContractError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
