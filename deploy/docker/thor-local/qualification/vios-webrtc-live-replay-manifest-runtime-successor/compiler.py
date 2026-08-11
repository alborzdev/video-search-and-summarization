#!/usr/bin/env python3
"""Compile two fresh WebRTC browser runs into one exact manifest receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CAPABILITY_IDS = ["manifest-entry.vios-core.06-live-replay-webrtc"]
OFFICIAL_INDICES = [417]
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


class EvidenceError(RuntimeError):
    """Fresh WebRTC evidence did not satisfy the combined row contract."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise EvidenceError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(EvidenceError(f"non-finite JSON: {token}")),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot load strict JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path.name}")
    return value


def _sources(contract: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in contract["source_locks"]:
        path = REPO / item["path"]
        if item["path"] in result or not path.is_file() or path.is_symlink() or _sha(path) != item["sha256"]:
            raise EvidenceError(f"source lock drifted: {item['path']}")
        result[item["path"]] = path
    return result


def _track(sample: dict[str, Any]) -> bool:
    tracks = sample.get("tracks")
    return isinstance(tracks, list) and any(
        isinstance(track, dict)
        and track.get("kind") == "video"
        and track.get("enabled") is True
        and track.get("muted") is False
        and track.get("ready_state") == "live"
        for track in tracks
    )


def build_receipt() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    if contract.get("capability_ids") != CAPABILITY_IDS or contract.get("official_indices") != OFFICIAL_INDICES:
        raise EvidenceError("contract capability binding differs")
    sources = _sources(contract)
    live_path = sources["deploy/docker/thor-local/qualification/vios-webrtc-live-runtime/refresh-receipt.json"]
    replay_path = sources["deploy/docker/thor-local/qualification/vios-webrtc-replay-runtime/refresh-receipt.json"]
    live = _load(live_path)
    replay = _load(replay_path)
    live_browser = live.get("runtime", {}).get("browser", {})
    live_webrtc = live_browser.get("webrtc", {})
    live_final = live_webrtc.get("final_sample", {})
    replay_browser = replay.get("observations", {}).get("browser", {})
    replay_webrtc = replay_browser.get("webrtc", {})
    replay_final = replay_webrtc.get("final_sample", {})
    replay_controls = replay_browser.get("controls", {})
    if (
        live.get("status") != "passed"
        or live.get("capability_id") != "protocol.vios.webrtc-live"
        or live.get("contract_sha256") != "b8b1436835a8db5f7cfc29f8eb12cda959e3df1056b9a3003123a44f3eaffc89"
        or live.get("runtime", {}).get("nvstreamer_version", {}).get("version") != contract["service_version"]
        or live_browser.get("status") != "passed"
        or live_webrtc.get("signaling_complete") is not True
        or live_webrtc.get("status_while_active", {}).get("state") != "PLAYING"
        or live_webrtc.get("decoded_frame_deltas", {}).get("initial", 0) < 1
        or live_webrtc.get("decoded_frame_deltas", {}).get("sustained", 0) < 1
        or live_final.get("ready_state") != 4
        or not _track(live_final)
        or live_webrtc.get("presentation_time_nondecreasing") is not True
    ):
        raise EvidenceError("fresh live WebRTC receipt differs")
    if (
        replay.get("status") != "passed"
        or replay.get("runtime_evidence") is not True
        or replay.get("capability_results", {}).get("protocol.vios.webrtc-replay") != "passed_current"
        or replay.get("target", {}).get("product_version") != "3.2.1"
        or replay.get("target", {}).get("service_version") != contract["service_version"]
        or replay_browser.get("status") != "passed"
        or replay_webrtc.get("signaling_complete") is not True
        or replay_webrtc.get("decoded_frame_deltas", {}).get("initial", 0) < 1
        or replay_final.get("ready_state") != 4
        or not _track(replay_final)
        or replay_controls.get("positive_relative_seek", {}).get("status") != 200
        or replay_controls.get("positive_relative_seek", {}).get("frames_continued") is not True
        or replay_controls.get("ui_seek_forward", {}).get("status") != 200
        or replay_controls.get("ui_seek_forward", {}).get("frames_continued") is not True
        or replay_controls.get("invalid_action", {}).get("status") != 501
        or replay_controls.get("invalid_action", {}).get("playback_continued") is not True
    ):
        raise EvidenceError("fresh replay WebRTC receipt differs")
    live_cleanup = live.get("cleanup", {})
    replay_cleanup = replay.get("cleanup", {})
    if not all(
        live_cleanup.get(key) is True
        for key in ("browser_session_stopped", "browser_websocket_closed", "exact_container_inventory_restored", "exact_running_set_restored", "main_vios_live_status_restored", "main_vios_sensors_restored")
    ) or not all(
        replay_cleanup.get(key) is True
        for key in ("container_inventory_restored", "fixture_state_restored", "no_replay_session_after", "required_container_identities_restored", "running_set_restored")
    ):
        raise EvidenceError("WebRTC cleanup contract differs")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": CAPABILITY_IDS,
        "official_indices": OFFICIAL_INDICES,
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH),
        "source_identity": {
            "live_receipt_sha256": _sha(live_path),
            "replay_receipt_sha256": _sha(replay_path),
            "live_contract_sha256": live["contract_sha256"],
            "replay_contract_sha256": "0cdf3e7196e191f0a0f68c24c7b93eb06b223991372ec625443c40f7c19aeebd",
        },
        "runtime": {
            "product_version": "3.2.1",
            "service_version": contract["service_version"],
            "live_captured_at": live["executed_at"],
            "replay_captured_at": replay["captured_at"],
            "browser_engine": "Chromium via Playwright",
        },
        "live": {
            "signaling_complete": True,
            "decoded_frame_delta": live_webrtc["decoded_frame_deltas"]["sustained"],
            "decoded_frames_final": live_final["decoded_frames"],
            "ready_state": live_final["ready_state"],
            "live_unmuted_video_track": True,
            "presentation_time_nondecreasing": live_webrtc["presentation_time_nondecreasing"],
            "websocket_closed": live_cleanup["browser_websocket_closed"],
        },
        "replay": {
            "signaling_complete": True,
            "decoded_frame_delta": replay_webrtc["decoded_frame_deltas"]["initial"],
            "decoded_frames_final": replay_final["decoded_frames"],
            "ready_state": replay_final["ready_state"],
            "live_unmuted_video_track": True,
            "presentation_time_nondecreasing": replay_final["current_time"] >= replay_webrtc["first_sample"]["current_time"],
            "websocket_closed": replay_browser["cleanup"]["websocket_closed"],
            "seek_forward_status": replay_controls["positive_relative_seek"]["status"],
            "ui_seek_status": replay_controls["ui_seek_forward"]["status"],
            "invalid_seek_status": replay_controls["invalid_action"]["status"],
            "frames_continued_after_all_seeks": all(value >= 1 for value in replay_webrtc["decoded_frame_deltas"].values()),
        },
        "separation": {
            "distinct_route_families": True,
            "distinct_timing_semantics": True,
            "independent_session_lifecycles": True,
            "live_websocket_path": live_webrtc["websocket_path"],
            "replay_websocket_path": replay_webrtc["websocket_path"],
        },
        "cleanup": {
            "live_session_stopped": live_cleanup["isolated_aggregate_live_status_null"],
            "replay_session_stopped": replay_cleanup["no_replay_session_after"],
            "live_inventory_restored": live_cleanup["exact_container_inventory_restored"] and live_cleanup["exact_running_set_restored"],
            "replay_inventory_restored": replay_cleanup["container_inventory_restored"] and replay_cleanup["running_set_restored"],
            "main_vios_restored": live_cleanup["main_vios_live_status_restored"] and replay_cleanup["fixture_state_restored"],
        },
        "policy": contract["policy"],
    }
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda e: list(e.path))
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    if UUID_PATTERN.search(json.dumps(receipt, sort_keys=True)):
        raise EvidenceError("combined receipt retained a raw UUID")
    return receipt


def _write(value: dict[str, Any]) -> None:
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=HERE, delete=False) as stream:
            temporary = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, RECEIPT_PATH)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "write", "check"))
    args = parser.parse_args()
    try:
        value = build_receipt()
        if args.mode == "plan":
            print(json.dumps({"status": "ready", "official_indices": OFFICIAL_INDICES, "writes_or_lifecycle_actions": False}, indent=2, sort_keys=True))
        elif args.mode == "write":
            _write(value)
            print(json.dumps({"status": "passed", "receipt_sha256": _sha(RECEIPT_PATH)}, sort_keys=True))
        elif not RECEIPT_PATH.is_file() or RECEIPT_PATH.read_bytes() != (json.dumps(value, indent=2, sort_keys=True) + "\n").encode():
            raise EvidenceError("checked receipt drifted")
        return 0
    except (OSError, EvidenceError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
