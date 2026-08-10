from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_codec_runtime_capture", HERE / "capture.py")
assert SPEC is not None and SPEC.loader is not None
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


def test_current_receipt_is_runtime_evidence_with_one_explicit_gate() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["schema_version"] == 1
    assert receipt["status"] == "passed_with_evidenced_limitation"
    assert receipt["runtime_evidence"] is True
    assert receipt["bundle"] == {
        "lock_sha256": "e15b1ec7a68ca4087669a395148a1dea1e9d18288dcd072a259a43bcfe67f197",
        "package_count": 63,
        "package_set_sha256": capture.PACKAGE_SET,
        "thor_runtime_dependencies": capture.RUNTIME_DEPENDENCIES,
        "upstream_package_count": 59,
    }
    assert receipt["qualification_bounds"]["gstreamer_missing_dependencies"] == []
    assert receipt["qualification_bounds"]["host_library_mounts"] is False
    assert receipt["qualification_bounds"]["main_vios_sensor_added"] is False
    assert receipt["capability_results"]["cpu_multimedia_support"] == "passed_current"
    assert receipt["capability_results"]["b_frame_handling"] == "passed_current"
    assert (
        receipt["capability_results"]["vios_audio_recording_from_nvstreamer"]
        == "not_executed_requires_stream_add_approval"
    )
    assert [item["id"] for item in receipt["limitations"]] == [
        "nvstreamer-h264-bframes-aac-direct-republish",
        "vios-nvstreamer-recording-handoff-approval",
    ]


def test_receipt_proves_bframes_multislice_and_cpu_transcodes() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    bframe_video = next(
        stream
        for stream in receipt["fixtures"]["h264_two_bframes_aac"]
        if stream["codec_type"] == "video"
    )
    assert bframe_video["has_b_frames"] == 2
    assert receipt["fixtures"]["h265_slice_counts"] == {
        "continuation_slices": 360,
        "pictures": 120,
        "slices_per_picture": 4,
    }
    assert receipt["hardware_path"]["decoded_frames"] == {
        "h264_b2_aac": 120,
        "h265_s4_aac": 120,
    }
    for result in receipt["software_path"]["transcodes"].values():
        assert result["framerate"] == 12.0
        assert result["bitrate_bps"] > 1_000_000
        codecs = {stream["codec_name"] for stream in result["rtsp_streams"]}
        assert "aac" in codecs
        video = next(
            stream for stream in result["rtsp_streams"] if stream["codec_type"] == "video"
        )
        assert video["has_b_frames"] == 0


def test_stream_contract_rejects_missing_audio_and_wrong_bframes() -> None:
    document = {
        "streams": [
            {
                "codec_name": "h264",
                "codec_type": "video",
                "width": 640,
                "height": 360,
                "has_b_frames": 2,
            }
        ]
    }
    with pytest.raises(capture.CaptureError, match="AAC"):
        capture._require_av(document, "h264", audio=True, b_frames=2)
    with pytest.raises(capture.CaptureError, match="B-frame"):
        capture._require_av(document, "h264", audio=False, b_frames=0)


def test_decoded_frame_counter_fails_closed(tmp_path: Path) -> None:
    progress = tmp_path / "progress.txt"
    stderr = tmp_path / "stderr.txt"
    progress.write_text("frame=119\nprogress=end\n")
    stderr.write_bytes(b"")
    with pytest.raises(capture.CaptureError, match="120 decoded frames"):
        capture._decoded_frames(progress, stderr)
    progress.write_text("frame=120\nprogress=end\n")
    assert capture._decoded_frames(progress, stderr) == 120
    stderr.write_text("decoder error\n")
    with pytest.raises(capture.CaptureError, match="emitted stderr"):
        capture._decoded_frames(progress, stderr)
