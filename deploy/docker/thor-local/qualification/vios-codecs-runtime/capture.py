#!/usr/bin/env python3
"""Capture a fail-closed Thor VIOS/NvStreamer codec runtime receipt.

This command is read-only with respect to Docker and the product APIs. It
validates artifacts produced by the isolated workflow in this directory,
re-reads the live software-path container, and writes one canonical receipt.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
LOCK = REPO / "deploy/docker/thor-local/audio/codec-bundle.lock.json"
IMAGE = "vss-vios-nvstreamer:3.2.1-thor-local"
CONTAINER = "vss-codec-qualifier-nvstreamer-software"
PACKAGE_SET = "ed28389b37a2d74a484251e874b4a131e9eb2a8350b4013ba0c209154bfdf3b4"
RUNTIME_DEPENDENCIES = ["libbs2b0", "libcdio19t64", "libsbc1", "libsidplay1v5"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CaptureError(RuntimeError):
    """The runtime state or supplied evidence does not satisfy the contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CaptureError(f"missing regular evidence file: {path.name}")
    return path.read_bytes()


def _json(path: Path) -> Any:
    raw = _read(path)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CaptureError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError(f"invalid JSON evidence: {path.name}") from exc


def _run(argv: list[str]) -> str:
    try:
        return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CaptureError(f"command failed: {argv[0]}") from exc


def _stream_signature(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("streams"), list):
        raise CaptureError("ffprobe evidence has no streams")
    signature = []
    for stream in document["streams"]:
        if not isinstance(stream, dict):
            raise CaptureError("ffprobe stream is not an object")
        signature.append(
            {
                key: stream[key]
                for key in (
                    "codec_name",
                    "codec_type",
                    "width",
                    "height",
                    "has_b_frames",
                    "r_frame_rate",
                    "sample_rate",
                    "channels",
                )
                if key in stream
            }
        )
    return signature


def _require_av(
    document: Any, video_codec: str, *, audio: bool, b_frames: int | None = None
) -> list[dict[str, Any]]:
    streams = _stream_signature(document)
    video = [item for item in streams if item.get("codec_type") == "video"]
    sound = [item for item in streams if item.get("codec_type") == "audio"]
    if len(video) != 1 or video[0].get("codec_name") != video_codec:
        raise CaptureError(f"expected one {video_codec} video stream")
    if video[0].get("width") != 640 or video[0].get("height") != 360:
        raise CaptureError("unexpected video dimensions")
    if b_frames is not None and video[0].get("has_b_frames") != b_frames:
        raise CaptureError("unexpected B-frame state")
    if audio:
        if len(sound) != 1 or sound[0].get("codec_name") != "aac":
            raise CaptureError("expected one AAC stream")
        if sound[0].get("sample_rate") != "48000":
            raise CaptureError("unexpected AAC sample rate")
    elif sound:
        raise CaptureError("unexpected audio stream")
    return streams


def _jpeg(path: Path) -> dict[str, Any]:
    document = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    streams = document.get("streams")
    if not isinstance(streams, list) or len(streams) != 1:
        raise CaptureError(f"invalid JPEG evidence: {path.name}")
    stream = streams[0]
    if stream != {"codec_name": "mjpeg", "width": 640, "height": 360}:
        raise CaptureError(f"unexpected JPEG dimensions or codec: {path.name}")
    return {"sha256": _sha256(path), "bytes": path.stat().st_size, **stream}


def _decoded_frames(path: Path, stderr_path: Path) -> int:
    if _read(stderr_path):
        raise CaptureError(f"decoder emitted stderr: {stderr_path.name}")
    frames: int | None = None
    for line in _read(path).decode().splitlines():
        key, separator, value = line.partition("=")
        if separator and key == "frame":
            frames = int(value)
    if frames != 120:
        raise CaptureError(f"expected 120 decoded frames: {path.name}")
    return frames


def _inspect_runtime(container: str) -> tuple[dict[str, Any], list[str]]:
    image = json.loads(_run(["docker", "image", "inspect", IMAGE]))[0]
    labels = (image.get("Config") or {}).get("Labels") or {}
    if image.get("Architecture") != "arm64" or labels.get(
        "com.nvidia.vss.thor.vios-codec-package-set"
    ) != PACKAGE_SET:
        raise CaptureError("NvStreamer image identity or labels drifted")

    instance = json.loads(_run(["docker", "inspect", container]))[0]
    if not (instance.get("State") or {}).get("Running"):
        raise CaptureError("software-path qualifier is not running")
    if (instance.get("Config") or {}).get("Image") != IMAGE:
        raise CaptureError("software-path qualifier uses the wrong image")
    host = instance.get("HostConfig") or {}
    if host.get("Runtime") != "nvidia" or host.get("Memory") != 4 * 1024**3:
        raise CaptureError("software-path qualifier runtime bounds drifted")
    mounts = instance.get("Mounts") or []
    if any(
        str(mount.get("Destination", "")).startswith(("/lib", "/usr/lib"))
        for mount in mounts
    ):
        raise CaptureError("host library is mounted into the repaired qualifier")

    scanner = r'''for plugin in /usr/lib/aarch64-linux-gnu/gstreamer-1.0/*.so; do
  ldd "$plugin" 2>/dev/null | sed -n "s/^[[:space:]]*\([^[:space:]]*\)[[:space:]]*=>[[:space:]]*not found$/$(basename "$plugin"):\1/p"
done'''
    missing = [
        line
        for line in _run(["docker", "exec", container, "sh", "-lc", scanner]).splitlines()
        if line
    ]
    if missing:
        raise CaptureError(f"unresolved GStreamer dependencies: {missing}")
    return (
        {
            "tag": IMAGE,
            "id": image["Id"],
            "architecture": image["Architecture"],
            "size_bytes": image["Size"],
            "codec_package_set": PACKAGE_SET,
            "runtime_network_install": labels.get(
                "com.nvidia.vss.thor.vios-runtime-network-install"
            ),
        },
        missing,
    )


def _transcode(artifacts: Path, stem: str, codec: str) -> dict[str, Any]:
    upload = _json(artifacts / f"{stem}-upload.json")
    media = _json(artifacts / f"{stem}-mediainfo.json")
    probe = _json(artifacts / f"{stem}-rtsp-audio-probe.json")
    expected_probe_codec = "hevc" if codec == "h265" else "h264"
    streams = _require_av(probe, expected_probe_codec, audio=True, b_frames=0)
    if (
        not isinstance(upload, dict)
        or upload.get("streamId") != stem
        or media.get("Codec") != codec
        or not str(media.get("AudioCodec", "")).startswith("AAC")
        or media.get("Framerate") != 12.0
        or media.get("Width") != 640
        or media.get("Height") != 360
    ):
        raise CaptureError(f"software transcode contract failed: {stem}")
    return {
        "stream_id": upload["streamId"],
        "codec": codec,
        "audio_codec": media["AudioCodec"],
        "framerate": media["Framerate"],
        "bitrate_bps": media["Bitrate"],
        "rtsp_streams": streams,
    }


def capture(artifacts: Path, container: str = CONTAINER) -> dict[str, Any]:
    artifacts = artifacts.resolve(strict=True)
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise CaptureError("artifact root must be a regular directory")

    lock = _json(LOCK)
    if (
        lock.get("schema_version") != 2
        or lock.get("architecture") != "arm64"
        or lock.get("package_count") != 63
        or lock.get("package_set_sha256") != PACKAGE_SET
        or lock.get("thor_runtime_dependencies") != RUNTIME_DEPENDENCIES
    ):
        raise CaptureError("codec bundle lock drifted")

    software_config = _json(artifacts / "vst_config_software.json")
    if software_config.get("data", {}).get("use_software_path") is not True:
        raise CaptureError("software qualifier config does not select the CPU path")
    image, missing = _inspect_runtime(container)

    bframe_input = _json(artifacts / "h264_b2_aac-input-probe.json")
    bframe_streams = _require_av(bframe_input, "h264", audio=True, b_frames=2)
    trace = _read(artifacts / "h265_s4_aac-trace-headers.txt").decode(
        errors="strict"
    )
    first_slices = trace.count("first_slice_segment_in_pic_flag                             1 = 1")
    continuation_slices = trace.count(
        "first_slice_segment_in_pic_flag                             0 = 0"
    )
    if (first_slices, continuation_slices) != (120, 360):
        raise CaptureError("HEVC four-slice fixture contract failed")

    hardware_probes = {
        "h264_non_bframe_aac": _require_av(
            _json(artifacts / "h264_b0_aac-hardware-repaired-rtsp-audio-probe.json"),
            "h264",
            audio=True,
            b_frames=0,
        ),
        "h264_two_bframes": _require_av(
            _json(artifacts / "h264_b2_aac-hardware-repaired-rtsp-audio-probe.json"),
            "h264",
            audio=False,
        ),
        "h265_four_slice_aac": _require_av(
            _json(artifacts / "h265_s4_aac-hardware-repaired-rtsp-audio-probe.json"),
            "hevc",
            audio=True,
            b_frames=0,
        ),
    }
    hardware_snapshots = {
        name: _jpeg(artifacts / f"{name}-hardware-repaired.jpg")
        for name in ("h264_b0_aac", "h264_b2_aac", "h265_s4_aac")
    }
    decoded = {
        name: _decoded_frames(
            artifacts / f"{name}-hardware-repaired-decode-progress.txt",
            artifacts / f"{name}-hardware-repaired-decode-stderr.txt",
        )
        for name in ("h264_b2_aac", "h265_s4_aac")
    }

    software_snapshots = {
        name: _jpeg(artifacts / f"{name}-software-final.jpg")
        for name in ("h264_b0_aac", "h265_s4_aac")
    }
    software_transcodes = {
        "h264_aac": _transcode(artifacts, "qual_sw_h264_1200k", "h264"),
        "h265_aac": _transcode(artifacts, "qual_sw_h265_1200k", "h265"),
    }
    selection_log = _read(artifacts / "software-element-selection.log").decode()
    for required in (
        "Return SKIP value for Hardware Decoders",
        "Using: SW decoder + SW encoder",
        "x264enc: bframes=0, key-int-max=24",
        "x264enc: bitrate=1200kbps",
        "x265enc: option-string=bframes=0:b-adapt=0,key-int-max=24",
        "x265enc: bitrate=1200kbps",
        "Linked audio: decodebin -> audioconvert -> ... -> audioencoder -> muxer",
    ):
        if required not in selection_log:
            raise CaptureError(f"software element-selection evidence missing: {required}")

    artifact_names = [
        "h264_b2_aac.mp4",
        "h265_s4_aac.mp4",
        "h264_b2_aac-input-probe.json",
        "h265_s4_aac-trace-headers.txt",
        "h264_b2_aac-hardware-repaired-decode-progress.txt",
        "h265_s4_aac-hardware-repaired-decode-progress.txt",
        "software-element-selection.log",
        "qual_sw_h264_1200k-mediainfo.json",
        "qual_sw_h265_1200k-mediainfo.json",
    ]
    artifact_hashes = {
        name: {"sha256": _sha256(artifacts / name), "bytes": (artifacts / name).stat().st_size}
        for name in artifact_names
    }
    if not all(HEX64.fullmatch(value["sha256"]) for value in artifact_hashes.values()):
        raise CaptureError("invalid artifact digest")

    return {
        "schema_version": 1,
        "qualification_id": "thor-vss-3.2.1-vios-codecs-runtime-2026-08-10",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "passed_with_evidenced_limitation",
        "runtime_evidence": True,
        "bundle": {
            "lock_sha256": _sha256(LOCK),
            "package_count": 63,
            "upstream_package_count": 59,
            "thor_runtime_dependencies": RUNTIME_DEPENDENCIES,
            "package_set_sha256": PACKAGE_SET,
        },
        "image": image,
        "qualification_bounds": {
            "container": container,
            "loopback_http_port": 31000,
            "warehouse_sample_bundle_used": False,
            "main_vios_configuration_changed": False,
            "main_vios_sensor_added": False,
            "host_library_mounts": False,
            "gstreamer_missing_dependencies": missing,
        },
        "fixtures": {
            "h264_two_bframes_aac": bframe_streams,
            "h265_slice_counts": {
                "pictures": first_slices,
                "continuation_slices": continuation_slices,
                "slices_per_picture": 4,
            },
        },
        "hardware_path": {
            "snapshots": hardware_snapshots,
            "rtsp_streams": hardware_probes,
            "decoded_frames": decoded,
        },
        "software_path": {
            "config_use_software_path": True,
            "snapshots": software_snapshots,
            "transcodes": software_transcodes,
            "element_selection_log_sha256": _sha256(
                artifacts / "software-element-selection.log"
            ),
        },
        "capability_results": {
            "b_frame_handling": "passed_current",
            "hevc_multislice_rfc7798": "passed_current",
            "h264_h265": "passed_current",
            "audio_rtsp_republish": "passed_current_for_non_bframe_h264_and_h265",
            "cpu_multimedia_support": "passed_current",
            "vios_audio_recording_from_nvstreamer": "not_executed_requires_stream_add_approval",
        },
        "limitations": [
            {
                "id": "nvstreamer-h264-bframes-aac-direct-republish",
                "observed": "The direct H.264 two-B-frame file exposed video but no audio track over RTSP even with includeAudio=true.",
                "scope": "H.264+B-frames+AAC direct NvStreamer republish only",
                "working_local_substitute": "Software transcode removes B-frames and retains AAC before republish.",
            },
            {
                "id": "vios-nvstreamer-recording-handoff-approval",
                "observed": "No NvStreamer URL was registered into the main VIOS instance during this run.",
                "scope": "VIOS recording/clip verification for NvStreamer RTSP sources",
                "gate": "approve RT-CV sample stream add",
            },
        ],
        "artifact_hashes": artifact_hashes,
    }


def _write_receipt(path: Path, receipt: dict[str, Any], replace: bool) -> None:
    path = path.resolve()
    if path.exists() and not replace:
        raise CaptureError(f"refusing to overwrite receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", default=CONTAINER)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = capture(args.artifacts, args.container)
        _write_receipt(args.output, receipt, args.replace)
    except CaptureError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
