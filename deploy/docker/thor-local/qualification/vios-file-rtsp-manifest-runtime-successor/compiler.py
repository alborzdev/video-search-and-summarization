#!/usr/bin/env python3
"""Bind the retained NvStreamer file workflow to manifest row 413."""

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
CAPABILITY_IDS = ["manifest-entry.vios-core.02-file-to-rtsp-republish"]
OFFICIAL_INDICES = [413]


class EvidenceError(RuntimeError):
    pass


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


def build_receipt() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    if contract.get("capability_ids") != CAPABILITY_IDS or contract.get("official_indices") != OFFICIAL_INDICES:
        raise EvidenceError("contract capability binding differs")
    sources = _sources(contract)
    raw_path = sources["deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/runtime-receipt.json"]
    wrapper_path = sources["deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/official-runtime-evidence.json"]
    fixture_path = sources["deploy/docker/thor-local/qualification/nvstreamer-file-workflow-runtime/fixture-contract.json"]
    raw = _load(raw_path)
    wrapper = _load(wrapper_path)
    obs = raw.get("observations", {})
    rtsp = obs.get("rtsp_probe", {})
    ui_webrtc = obs.get("ui", {}).get("webrtc", {})
    cleanup = raw.get("cleanup", {})
    video = next((item for item in raw.get("fixture", {}).get("streams", []) if item.get("codec_type") == "video"), {})
    if (
        raw.get("status") != "passed"
        or raw.get("runtime_evidence") is not True
        or raw.get("capability_results", {}).get("runtime.nvstreamer.file-streaming") != "passed_current"
        or raw.get("target", {}).get("product_version") != "3.2.1"
        or raw.get("identity", {}).get("service_version", {}).get("version") != contract["service_version"]
        or raw.get("identity", {}).get("image", {}).get("image_id") != "sha256:b3e5b92fa2546e9b69a3dba7cac324ce36a3cce65f2e0d61ad41a8a84a74a563"
        or obs.get("input_modes") != ["upload", "ui", "local-mount"]
        or obs.get("automatic_output") != "RTSP"
        or video.get("codec_name") != "h264"
        or video.get("width") != 320
        or video.get("height") != 180
        or rtsp.get("video", {}).get("codec_name") != "h264"
        or rtsp.get("audio", {}).get("codec_name") != "aac"
        or rtsp.get("audio", {}).get("sample_rate") != "48000"
        or obs.get("snapshot", {}).get("codec") != "mjpeg"
        or obs.get("snapshot", {}).get("bytes", 0) < 1
        or ui_webrtc.get("first_frame_observed") is not True
        or ui_webrtc.get("video_samples", [{}, {}])[-1].get("current_time", 0) <= 0
        or obs.get("invalid_media_status") != 400
    ):
        raise EvidenceError("file-to-RTSP runtime semantics differ")
    if (
        cleanup.get("result") != "passed"
        or len(cleanup.get("owned_stream_ids", [])) != 3
        or not all(item.get("status") == 200 for item in cleanup.get("attempts", []) if item.get("operation") == "owned-file-delete")
        or not all(cleanup.get(key) is True for key in ("owned_media_absent", "owned_sensors_absent", "exact_container_inventory_restored", "exact_running_set_restored", "all_reserved_ports_released"))
        or wrapper.get("result") != "passed_current"
        or wrapper.get("observations", [{}])[0].get("value", {}).get("raw_receipt_sha256") != _sha(raw_path)
    ):
        raise EvidenceError("file-to-RTSP cleanup or wrapper differs")
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": CAPABILITY_IDS,
        "official_indices": OFFICIAL_INDICES,
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH),
        "source_identity": {
            "raw_receipt_sha256": _sha(raw_path),
            "official_wrapper_sha256": _sha(wrapper_path),
            "fixture_contract_sha256": _sha(fixture_path),
        },
        "runtime": {
            "product_version": "3.2.1",
            "service_version": contract["service_version"],
            "captured_at": raw["captured_at"],
            "image_id": raw["identity"]["image"]["image_id"],
            "image_architecture": raw["identity"]["image"]["image_architecture"],
        },
        "republish": {
            "input_modes": obs["input_modes"],
            "automatic_output": obs["automatic_output"],
            "source_codec": video["codec_name"],
            "source_width": video["width"],
            "source_height": video["height"],
            "rtsp_video_codec": rtsp["video"]["codec_name"],
            "rtsp_audio_codec": rtsp["audio"]["codec_name"],
            "rtsp_audio_sample_rate_hz": int(rtsp["audio"]["sample_rate"]),
            "live_snapshot_decoded": obs["snapshot"]["bytes"] > 0,
            "webrtc_first_frame_observed": ui_webrtc["first_frame_observed"],
            "webrtc_clock_advanced": ui_webrtc["video_samples"][-1]["current_time"] > 0,
            "invalid_media_status": obs["invalid_media_status"],
        },
        "cleanup": {
            "three_owned_streams_deleted": len(cleanup["owned_stream_ids"]) == 3,
            "owned_media_absent": cleanup["owned_media_absent"],
            "owned_sensors_absent": cleanup["owned_sensors_absent"],
            "exact_container_inventory_restored": cleanup["exact_container_inventory_restored"],
            "exact_running_set_restored": cleanup["exact_running_set_restored"],
            "all_reserved_ports_released": cleanup["all_reserved_ports_released"],
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
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=HERE, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
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
