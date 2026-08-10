#!/usr/bin/env python3
"""Verify the retained VIOS WebRTC live receipt and oracle projection."""

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


CAPABILITY_ID = "protocol.vios.webrtc-live"
EXPECTED = {
    "fixture": "b8b1436835a8db5f7cfc29f8eb12cda959e3df1056b9a3003123a44f3eaffc89",
    "receipt": "1d482e06ea5a2a59eb1d064ee475f67c4d6303461864b390f5847999f9d93fe4",
    "evidence": "01a6f1e7e37445235256218ea9d87268d1b8fefbbc5d3766b789a93951d8009c",
    "oracle": "bcce967d3f8c6dedd4be5d0da3afc586db751cd5c74abafca87e319da85048f8",
}


class LiveEvidenceError(RuntimeError):
    """The retained live evidence is inconsistent."""


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise LiveEvidenceError(f"duplicate JSON key in {path.name}: {key}")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise LiveEvidenceError(f"{path.name} is not a JSON object")
    return value, raw


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _observation(evidence: dict[str, Any], observation_id: str) -> Any:
    return next(
        row["value"]
        for row in evidence["observations"]
        if row["id"] == observation_id
    )


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
        raise LiveEvidenceError("fixture, receipt, or evidence digest drifted")

    capability = next(
        row for row in ledger["capabilities"] if row["id"] == CAPABILITY_ID
    )
    oracle = next(
        row for row in plan["oracles"] if row["capability_id"] == CAPABILITY_ID
    )
    oracle_digest = capability_oracles.canonical_oracle_sha256(oracle)
    if oracle_digest != EXPECTED["oracle"]:
        raise LiveEvidenceError("capability oracle digest drifted")
    if capability.get("runtime_state") != "passed_current":
        raise LiveEvidenceError("official capability is not passed_current")
    if capability.get("thor_state") != "wired":
        raise LiveEvidenceError("official capability is not wired")
    if capability.get("runtime_evidence") != [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "vios-webrtc-live-runtime/official-runtime-evidence.json"
            ),
            "sha256": observed["evidence"],
        }
    ]:
        raise LiveEvidenceError("official capability evidence binding drifted")

    if (
        receipt.get("status") != "passed"
        or receipt.get("capability_id") != CAPABILITY_ID
        or receipt.get("oracle_id") != "oracle.protocol.vios.webrtc-live"
        or receipt.get("contract_sha256") != EXPECTED["fixture"]
    ):
        raise LiveEvidenceError("runtime receipt identity is not passing/current")
    if receipt["fixture"]["sha256"] != fixture["fixture"]["media"]["sha256"]:
        raise LiveEvidenceError("runtime media fixture differs from contract")
    if receipt["fixture"]["warehouse_sample_bundle"] is not False:
        raise LiveEvidenceError("excluded Warehouse sample bundle was used")

    browser = receipt["runtime"]["browser"]
    webrtc = browser["webrtc"]
    first = webrtc["first_sample"]
    final = webrtc["final_sample"]
    if (
        browser.get("status") != "passed"
        or browser["network"]["external_requests"] != 0
        or browser["network"]["request_failure_count"] != 0
        or browser["network"]["http_response_count"] != 26
        or browser["network"]["websocket_frame_count"] != 19
        or webrtc.get("signaling_complete") is not True
        or webrtc.get("decoded_frame_deltas") != {"initial": 12, "sustained": 12}
        or first.get("decoded_frames") != 2
        or final.get("decoded_frames") != 26
        or first.get("ready_state") != 4
        or final.get("ready_state") != 4
        or first.get("video_width") != 1920
        or first.get("video_height") != 1080
        or final.get("video_width") != 320
        or final.get("video_height") != 180
        or webrtc.get("presentation_time_nondecreasing") is not True
        or webrtc["timestamp_query"] != {
            "first_integer": True,
            "nondecreasing": True,
            "second_integer": True,
            "statuses": [200, 200],
        }
        or webrtc["status_while_active"] != {
            "error": False,
            "state": "PLAYING",
            "status": 200,
        }
    ):
        raise LiveEvidenceError("semantic live WebRTC result drifted")
    for sample in (first, final):
        if sample.get("media_error") is not None or sample.get("paused") is not False:
            raise LiveEvidenceError("retained media sample is not playing cleanly")
        if sample.get("tracks") != [
            {"enabled": True, "kind": "video", "muted": False, "ready_state": "live"}
        ]:
            raise LiveEvidenceError("retained live video track contract drifted")

    negative = receipt["runtime"]["negative"]
    if (
        negative.get("id") != "vios-live-missing-peer"
        or negative.get("error_code") != "InvalidParameterError"
        or negative.get("no_peer_retained") is not True
        or negative["request"].get("status") != 400
    ):
        raise LiveEvidenceError("adjacent missing-peer negative drifted")
    browser_cleanup = browser["cleanup"]
    if (
        browser_cleanup.get("stop_frame_observed") is not True
        or browser_cleanup.get("video_removed") is not True
        or browser_cleanup.get("websocket_closed") is not True
        or browser_cleanup["post_stop_status"]["aggregate"] != {
            "body_is_null": True,
            "status": 200,
        }
        or browser_cleanup["post_stop_status"]["targeted"] != {
            "error_code": "InvalidParameterError",
            "error_message": "getStreamStatus",
            "status": 400,
        }
    ):
        raise LiveEvidenceError("explicit live-session cleanup drifted")

    if receipt.get("privacy") != {
        "retain_ice_candidates": False,
        "retain_media_session_ids": False,
        "retain_peer_ids": False,
        "retain_sdp": False,
    } or browser.get("privacy") != {
        "ice_candidates_retained": False,
        "media_session_ids_retained": False,
        "peer_ids_retained": False,
        "sdp_retained": False,
    }:
        raise LiveEvidenceError("ephemeral WebRTC privacy contract drifted")

    cleanup = receipt["cleanup"]
    cleanup_bools = (
        "all_reserved_ports_released",
        "browser_session_stopped",
        "browser_websocket_closed",
        "exact_container_inventory_restored",
        "exact_running_set_restored",
        "isolated_aggregate_live_status_null",
        "main_vios_live_status_restored",
        "main_vios_sensor_count_restored",
        "main_vios_sensors_restored",
        "temporary_tree_removed",
    )
    if not all(cleanup.get(key) is True for key in cleanup_bools):
        raise LiveEvidenceError("runtime cleanup did not pass")
    if cleanup.get("main_vios_pre_state_sha256") != cleanup.get(
        "main_vios_post_state_sha256"
    ):
        raise LiveEvidenceError("main VIOS state was not restored")

    semantic = _observation(evidence, "semantic_result")
    wire = _observation(evidence, "wire_contract")
    if (
        semantic.get("decoded_frames_first") != first["decoded_frames"]
        or semantic.get("decoded_frames_final") != final["decoded_frames"]
        or semantic.get("final_width") != final["video_width"]
        or semantic.get("final_height") != final["video_height"]
        or wire.get("active_state") != webrtc["status_while_active"]["state"]
        or wire.get("missing_peer_status") != negative["request"]["status"]
        or wire.get("websocket_path") != webrtc["websocket_path"]
    ):
        raise LiveEvidenceError("official evidence differs from runtime receipt")

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
    except (
        OSError,
        KeyError,
        StopIteration,
        json.JSONDecodeError,
        LiveEvidenceError,
        verify_official_capabilities.CapabilityContractError,
    ) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
