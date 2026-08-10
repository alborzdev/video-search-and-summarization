from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_live_verify", HERE / "verify.py")
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_fixture_is_bounded_generated_media() -> None:
    contract = json.loads((HERE / "fixture-contract.json").read_text())
    media = contract["fixture"]["media"]
    assert media["bytes"] == 55942
    assert media["duration_seconds"] == 2.0
    assert media["video"] == {
        "codec": "h264",
        "width": 320,
        "height": 180,
        "frame_rate": "10/1",
        "b_frames": 0,
    }
    assert media["audio"] == {
        "codec": "aac",
        "sample_rate": 48000,
        "channels": 1,
    }
    assert contract["bounds"]["persistent_mutation_allowed"] is False
    assert contract["fixture"]["warehouse_sample_bundle"] is False
    assert contract["fixture"]["main_vios_sensor_mutation"] is False


def test_retained_runtime_receipt_is_bounded_and_private() -> None:
    raw = (HERE / "runtime-receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == VERIFY.EXPECTED["receipt"]
    receipt = json.loads(raw)
    assert receipt["status"] == "passed"
    assert receipt["runtime"]["browser"]["webrtc"]["signaling_complete"] is True
    assert receipt["runtime"]["browser"]["webrtc"]["final_sample"][
        "decoded_frames"
    ] == 26
    assert receipt["runtime"]["negative"]["request"]["status"] == 400
    assert receipt["cleanup"]["exact_container_inventory_restored"] is True
    assert receipt["cleanup"]["exact_running_set_restored"] is True
    for forbidden in (b'"peerId":', b'"mediaSessionId":', b'"sdp":', b'"candidate":'):
        assert forbidden not in raw


def test_official_projection_is_fail_closed() -> None:
    result = VERIFY.verify()
    assert result["status"] == "passed"
    assert result["capability_id"] == "protocol.vios.webrtc-live"
    assert result["official_capability_count"] == 289
