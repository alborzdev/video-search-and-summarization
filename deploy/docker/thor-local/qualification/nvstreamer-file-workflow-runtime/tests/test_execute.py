from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
SPEC = importlib.util.spec_from_file_location("nvstreamer_file_workflow_execute", HERE / "execute.py")
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def test_strict_json_rejects_duplicate_keys() -> None:
    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._strict_json(b'{"status":"pass","status":"fail"}', "test")


def test_multipart_is_single_file_part_without_chunk_headers() -> None:
    body, content_type = executor._multipart("fixture.mp4", b"media-bytes", "abc123")
    assert content_type == "multipart/form-data; boundary=vss-nvstreamer-abc123"
    assert body.count(b'Content-Disposition: form-data; name="file"; filename="fixture.mp4"') == 1
    assert body.count(b"media-bytes") == 1
    assert b"nvstreamer-chunk" not in body
    with pytest.raises(executor.QualificationError, match="unsafe multipart filename"):
        executor._multipart("../fixture.mp4", b"x", "abc123")


def test_rtsp_media_validation_accepts_server_advertised_rate() -> None:
    value = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 320,
                "height": 180,
                "r_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 1,
            },
        ]
    }
    result = executor._validate_media_streams(value, require_audio=True)
    assert result["video"]["r_frame_rate"] == "30/1"
    assert result["audio"]["codec_name"] == "aac"


def test_media_validation_rejects_wrong_dimensions_or_missing_audio() -> None:
    with pytest.raises(executor.QualificationError, match="video contract"):
        executor._validate_media_streams(
            {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 640, "height": 360}]},
            require_audio=False,
        )
    with pytest.raises(executor.QualificationError, match="audio contract"):
        executor._validate_media_streams(
            {
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 320, "height": 180}
                ]
            },
            require_audio=True,
        )


def test_sensor_and_stream_identity_are_exact() -> None:
    sensors = [{"name": "owned", "sensorId": "owned_0", "state": "online"}]
    assert executor._find_sensor(sensors, "owned")["sensorId"] == "owned_0"
    assert executor._find_sensor(sensors, "absent") is None
    with pytest.raises(executor.QualificationError, match="duplicate"):
        executor._find_sensor(sensors + sensors, "owned")

    streams = [{"owned_0": [{"streamId": "owned_0", "type": "Rtsp"}]}]
    assert executor._stream_for_sensor(streams, "owned_0")["type"] == "Rtsp"
    with pytest.raises(executor.QualificationError, match="expected one stream"):
        executor._stream_for_sensor([], "owned_0")


def test_configs_fix_http_rtsp_and_webrtc_to_reserved_local_ports() -> None:
    config = json.loads((HERE / "configs" / "vst_config.json").read_text())
    network = config["network"]
    assert network["http_port"] == "31000"
    assert network["server_domain_name"] == "127.0.0.1"
    assert network["stunurl_list"] == ["127.0.0.1:3478"]
    assert network["rtsp_server_port"] == 31554
    assert network["webrtc_port_range"] == {"min": 32200, "max": 32220}
    assert config["notifications"]["enable_notification"] is False
    assert config["observability"]["enable_telemetry"] is False


def test_executor_and_browser_are_fail_closed_and_isolated() -> None:
    source = (HERE / "execute.py").read_text()
    harness = (HERE / "ui-harness.mjs").read_text()
    assert '"--network",\n        "bridge"' in source
    assert '"--cap-drop",\n        "ALL"' in source
    assert "agent_generate_called\": False" in source
    assert "rt_cv_stream_added\": False" in source
    assert "http://127.0.0.1:31000" in harness
    assert "external_request_count !== 0" in harness
    assert "first_frame_observed" in harness


def test_retained_receipt_closes_every_advertised_field_when_present() -> None:
    path = HERE / "runtime-receipt.json"
    if not path.exists():
        pytest.skip("runtime receipt is created only by an explicit qualification run")
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "passed"
    assert receipt["capability_results"][executor.CAPABILITY_ID] == "passed_current"
    assert receipt["observations"]["input_modes"] == ["upload", "ui", "local-mount"]
    assert receipt["observations"]["automatic_output"] == "RTSP"
    assert receipt["observations"]["playback"] == "WebRTC"
    assert receipt["observations"]["remove_supported"] is True
    assert receipt["observations"]["ui"]["webrtc"]["first_frame_observed"] is True
    assert receipt["cleanup"]["result"] == "passed"
    assert receipt["cleanup"]["exact_container_inventory_restored"] is True
    assert receipt["cleanup"]["exact_running_set_restored"] is True
    assert receipt["cleanup"]["all_reserved_ports_released"] is True


def test_official_evidence_is_hash_bound_to_the_current_oracle_and_ledger() -> None:
    evidence_path = HERE / "official-runtime-evidence.json"
    evidence = json.loads(evidence_path.read_text())
    fixture_path = HERE / "fixture-contract.json"
    receipt_path = HERE / "runtime-receipt.json"
    ledger = json.loads((REPO / "deploy/docker/thor-local/parity/official-capabilities.json").read_text())
    oracles = json.loads((REPO / "deploy/docker/thor-local/parity/capability-oracles.json").read_text())
    capability = next(row for row in ledger["capabilities"] if row["id"] == executor.CAPABILITY_ID)
    oracle = next(row for row in oracles["oracles"] if row["capability_id"] == executor.CAPABILITY_ID)

    assert capability["runtime_state"] == "passed_current"
    assert capability["thor_state"] == "wired"
    assert capability["runtime_evidence"] == [
        {
            "path": (
                "deploy/docker/thor-local/qualification/"
                "nvstreamer-file-workflow-runtime/official-runtime-evidence.json"
            ),
            "sha256": executor._sha(evidence_path.read_bytes()),
        }
    ]
    assert evidence["oracle_sha256"] == executor._sha(executor._canonical(oracle))
    assert evidence["fixture"]["sha256"] == executor._sha(fixture_path.read_bytes())
    assert evidence["observations"][0]["value"]["raw_receipt_sha256"] == executor._sha(
        receipt_path.read_bytes()
    )
    assert len(evidence["assertions"]) == len(oracle["assertions"]) == 11
    assert oracle["acceptance_readiness"] == {"classification": "executor_ready", "blockers": []}
