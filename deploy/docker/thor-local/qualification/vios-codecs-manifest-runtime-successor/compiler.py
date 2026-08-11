#!/usr/bin/env python3
"""Bind the retained Thor NvStreamer codec run to four exact VSS manifest rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"
CAPABILITY_IDS = [
    "manifest-entry.vios-codecs-audio.00-b-frame-handling",
    "manifest-entry.vios-codecs-audio.01-hevc-multislice-rfc7798",
    "manifest-entry.vios-codecs-audio.02-h-264-h-265",
    "manifest-entry.vios-codecs-audio.04-audio-rtsp-republish",
]
OFFICIAL_INDICES = [420, 421, 422, 424]


class EvidenceError(RuntimeError):
    """The retained runtime evidence does not prove the exact row semantics."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

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


def _stream(streams: list[dict[str, Any]], codec: str, codec_type: str) -> dict[str, Any]:
    matches = [item for item in streams if item.get("codec_name") == codec and item.get("codec_type") == codec_type]
    if len(matches) != 1:
        raise EvidenceError(f"expected one {codec_type} {codec} stream")
    return matches[0]


def _snapshot_ok(value: dict[str, Any]) -> bool:
    return (
        value.get("codec_name") == "mjpeg"
        and value.get("width") == 640
        and value.get("height") == 360
        and value.get("bytes", 0) > 0
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
    )


def build_receipt() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    if contract.get("capability_ids") != CAPABILITY_IDS or contract.get("official_indices") != OFFICIAL_INDICES:
        raise EvidenceError("contract capability binding differs")
    sources = _sources(contract)
    raw_path = sources["deploy/docker/thor-local/qualification/vios-codecs-runtime/runtime-receipt.json"]
    wrapper_path = sources["deploy/docker/thor-local/qualification/vios-codecs-runtime/official-runtime-evidence.json"]
    capture_path = sources["deploy/docker/thor-local/qualification/vios-codecs-runtime/capture.py"]
    raw = _load(raw_path)
    wrapper = _load(wrapper_path)
    expected_results = {
        "audio_rtsp_republish": "passed_current_for_non_bframe_h264_and_h265",
        "b_frame_handling": "passed_current",
        "cpu_multimedia_support": "passed_current",
        "h264_h265": "passed_current",
        "hevc_multislice_rfc7798": "passed_current",
        "vios_audio_recording_from_nvstreamer": "not_executed_requires_stream_add_approval",
    }
    if (
        raw.get("status") != "passed_with_evidenced_limitation"
        or raw.get("runtime_evidence") is not True
        or raw.get("capability_results") != expected_results
        or raw.get("image") != {
            **contract["image"],
            "runtime_network_install": "disabled",
            "size_bytes": 3456921334,
        }
    ):
        raise EvidenceError("raw runtime identity or capability result differs")

    bframe_streams = raw["fixtures"]["h264_two_bframes_aac"]
    bframe_video = _stream(bframe_streams, "h264", "video")
    _stream(bframe_streams, "aac", "audio")
    slices = raw["fixtures"]["h265_slice_counts"]
    hardware = raw["hardware_path"]
    software = raw["software_path"]
    h264_hw = hardware["rtsp_streams"]["h264_non_bframe_aac"]
    h265_hw = hardware["rtsp_streams"]["h265_four_slice_aac"]
    h264_sw = software["transcodes"]["h264_aac"]
    h265_sw = software["transcodes"]["h265_aac"]
    if (
        bframe_video.get("has_b_frames") != 2
        or hardware["decoded_frames"] != {"h264_b2_aac": 120, "h265_s4_aac": 120}
        or slices != {"continuation_slices": 360, "pictures": 120, "slices_per_picture": 4}
        or not all(_snapshot_ok(item) for item in hardware["snapshots"].values())
        or not all(_snapshot_ok(item) for item in software["snapshots"].values())
        or _stream(h264_hw, "aac", "audio").get("sample_rate") != "48000"
        or _stream(h265_hw, "aac", "audio").get("sample_rate") != "48000"
        or _stream(h265_hw, "hevc", "video").get("width") != 640
    ):
        raise EvidenceError("hardware codec evidence differs")
    for result, codec in ((h264_sw, "h264"), (h265_sw, "hevc")):
        video = _stream(result["rtsp_streams"], codec, "video")
        audio = _stream(result["rtsp_streams"], "aac", "audio")
        if video.get("has_b_frames") != 0 or audio.get("sample_rate") != "48000" or result.get("framerate") != 12.0:
            raise EvidenceError("software codec/audio evidence differs")

    cleanup = wrapper.get("cleanup", {})
    if (
        wrapper.get("raw_receipt", {}).get("sha256") != _sha(raw_path)
        or cleanup.get("result") != "passed"
        or len(cleanup.get("api_deleted_stream_ids", [])) != 6
        or cleanup.get("isolated_sensor_list_before_shutdown") != []
        or cleanup.get("container_absent") != raw["qualification_bounds"]["container"]
        or len(cleanup.get("temporary_paths_absent", [])) != 2
        or cleanup.get("main_vios_configuration_changed") is not False
    ):
        raise EvidenceError("cleanup wrapper differs")
    limitations = {item["id"]: item for item in raw["limitations"]}
    if (
        "nvstreamer-h264-bframes-aac-direct-republish" not in limitations
        or limitations["nvstreamer-h264-bframes-aac-direct-republish"].get("working_local_substitute")
        != "Software transcode removes B-frames and retains AAC before republish."
    ):
        raise EvidenceError("bounded audio limitation differs")

    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": CAPABILITY_IDS,
        "official_indices": OFFICIAL_INDICES,
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH),
        "source_identity": {
            "raw_receipt_sha256": _sha(raw_path),
            "cleanup_wrapper_sha256": _sha(wrapper_path),
            "capture_sha256": _sha(capture_path),
        },
        "runtime": {
            "product_version": "3.2.1",
            "captured_at": raw["captured_at"],
            "image_id": raw["image"]["id"],
            "image_architecture": raw["image"]["architecture"],
            "networkless_derivative": raw["image"]["runtime_network_install"] == "disabled",
            "gstreamer_dependency_closure": raw["qualification_bounds"]["gstreamer_missing_dependencies"] == [],
        },
        "b_frame_handling": {
            "input_codec": "h264",
            "input_b_frames": bframe_video["has_b_frames"],
            "decoded_frames": hardware["decoded_frames"]["h264_b2_aac"],
            "snapshot_decoded": _snapshot_ok(hardware["snapshots"]["h264_b2_aac"]),
            "presentation_order_decode_completed": True,
        },
        "hevc_multislice_rfc7798": {
            "codec": "hevc",
            "pictures": slices["pictures"],
            "slices_per_picture": slices["slices_per_picture"],
            "continuation_slices": slices["continuation_slices"],
            "rtsp_decoded_frames": hardware["decoded_frames"]["h265_s4_aac"],
            "snapshot_decoded": _snapshot_ok(hardware["snapshots"]["h265_s4_aac"]),
        },
        "h264_h265": {
            "hardware_h264_decode": hardware["decoded_frames"]["h264_b2_aac"] == 120,
            "hardware_h265_decode": hardware["decoded_frames"]["h265_s4_aac"] == 120,
            "software_h264_snapshot": _snapshot_ok(software["snapshots"]["h264_b0_aac"]),
            "software_h265_snapshot": _snapshot_ok(software["snapshots"]["h265_s4_aac"]),
            "software_h264_transcode": _stream(h264_sw["rtsp_streams"], "h264", "video")["has_b_frames"] == 0,
            "software_h265_transcode": _stream(h265_sw["rtsp_streams"], "hevc", "video")["has_b_frames"] == 0,
            "software_output_b_frames": 0,
        },
        "audio_rtsp_republish": {
            "hardware_h264_aac": _stream(h264_hw, "aac", "audio")["sample_rate"] == "48000",
            "hardware_h265_aac": _stream(h265_hw, "aac", "audio")["sample_rate"] == "48000",
            "software_h264_aac": _stream(h264_sw["rtsp_streams"], "aac", "audio")["sample_rate"] == "48000",
            "software_h265_aac": _stream(h265_sw["rtsp_streams"], "aac", "audio")["sample_rate"] == "48000",
            "sample_rate_hz": 48000,
            "direct_bframe_aac_limitation_observed": True,
            "working_transcode_substitute": True,
        },
        "cleanup": {
            "six_owned_streams_deleted": len(cleanup["api_deleted_stream_ids"]) == 6,
            "isolated_sensor_list_empty": cleanup["isolated_sensor_list_before_shutdown"] == [],
            "owned_container_absent": cleanup["container_absent"] == raw["qualification_bounds"]["container"],
            "temporary_trees_absent": len(cleanup["temporary_paths_absent"]) == 2,
            "main_vios_unchanged": cleanup["main_vios_configuration_changed"] is False,
        },
        "policy": contract["policy"],
    }
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda error: list(error.path))
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
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
            print(json.dumps({"status": "ready", "official_indices": OFFICIAL_INDICES, "writes_or_lifecycle_actions": False}, sort_keys=True))
        elif args.mode == "write":
            _write(value)
            print(json.dumps({"status": "passed", "receipt_sha256": _sha(RECEIPT_PATH)}, sort_keys=True))
        elif not RECEIPT_PATH.is_file() or RECEIPT_PATH.read_bytes() != (json.dumps(value, indent=2, sort_keys=True) + "\n").encode():
            raise EvidenceError("checked receipt drifted")
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
