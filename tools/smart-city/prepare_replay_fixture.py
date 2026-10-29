#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CPU-only canonical single-slice H.264 derivative for the RTSP test fixture.

Preserves the NVIDIA original. This controls an integration input; it does not
repair VIOS forwarding of arbitrary multi-slice H.264 camera streams.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "pedestrian-sample.mp4"
OUTPUT = "pedestrian-replay-single-slice.mp4"
X264 = (
    "slices=1:sliced-threads=0:keyint=10:min-keyint=10:scenecut=0:bframes=0:force-cfr=1"
)


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def vcl_slices(data: bytes, length_bytes: int) -> int:
    """Count H.264 VCL NAL units in one length-prefixed MP4 packet."""
    offset, count = 0, 0
    while offset < len(data):
        if offset + length_bytes > len(data):
            raise ValueError("Truncated AVC NAL length")
        size = int.from_bytes(data[offset : offset + length_bytes], "big")
        offset += length_bytes
        if size <= 0 or offset + size > len(data):
            raise ValueError("Invalid AVC NAL size")
        count += (data[offset] & 31) in {1, 5}
        offset += size
    return count


def prepare(directory: Path) -> dict:
    import av

    source, output = directory / SOURCE, directory / OUTPUT
    receipt = output.with_suffix(".json")
    original_hash = sha256(source)
    if output.exists():
        if not receipt.exists():
            raise ValueError(
                "Existing derivative lacks provenance; preserve it for review"
            )
        saved = json.loads(receipt.read_text())
        if saved.get("sourceSha256") != original_hash or saved.get(
            "outputSha256"
        ) != sha256(output):
            raise ValueError("Existing derivative/provenance hash mismatch")
        return saved
    temporary = output.with_suffix(".partial.mp4")
    if temporary.exists():
        raise ValueError(
            "Incomplete derivative already exists; review it before retrying"
        )
    frames = 0
    try:
        with (
            av.open(str(source)) as input_video,
            av.open(str(temporary), "w", format="mp4") as encoded,
        ):
            original = input_video.streams.video[0]
            if (original.width, original.height, original.average_rate) != (
                768,
                576,
                Fraction(10),
            ):
                raise ValueError(
                    "The controlled pedestrian fixture must be 768x576 at 10 FPS"
                )
            stream = encoded.add_stream("libx264", rate=10)
            stream.width, stream.height, stream.pix_fmt = 768, 576, "yuv420p"
            stream.time_base = Fraction(1, 10)
            stream.codec_context.time_base = Fraction(1, 10)
            stream.codec_context.thread_count = 2
            stream.options = {"preset": "fast", "crf": "21", "x264-params": X264}
            for frame in input_video.decode(original):
                frame = frame.reformat(width=768, height=576, format="yuv420p")
                frame.pts, frame.time_base = frames, Fraction(1, 10)
                frame.pict_type = 0
                for packet in stream.encode(frame):
                    encoded.mux(packet)
                frames += 1
            for packet in stream.encode():
                encoded.mux(packet)
        if frames != 795:
            raise ValueError(f"Expected all 795 original frames, decoded {frames}")
        slice_counts, key_frames, pts, packet_count = [], [], [], 0
        with av.open(str(temporary)) as check:
            stream = check.streams.video[0]
            extra = stream.codec_context.extradata
            if not extra or extra[0] != 1:
                raise ValueError("Derivative lacks AVC decoder configuration")
            length_bytes = (extra[4] & 3) + 1
            for packet in check.demux(stream):
                if packet.dts is None:
                    continue
                slice_counts.append(vcl_slices(bytes(packet), length_bytes))
                if packet.is_keyframe:
                    key_frames.append(packet_count)
                if packet.pts != packet.dts:
                    raise ValueError(
                        "Derivative unexpectedly contains reordered/B frames"
                    )
                pts.append(float(packet.pts * packet.time_base))
                packet_count += 1
        if (
            packet_count != 795
            or set(slice_counts) != {1}
            or key_frames != list(range(0, 795, 10))
        ):
            raise ValueError(
                "Derivative did not satisfy one slice/frame and fixed 10-frame GOP"
            )
        if any(
            abs((right - left) - 0.1) > 1e-6 for left, right in itertools.pairwise(pts)
        ):
            raise ValueError("Derivative is not a uniform 10 FPS media timeline")
        with av.open(str(temporary)) as check:
            if sum(1 for _ in check.decode(video=0)) != 795:
                raise ValueError("Derivative failed the complete CPU decode check")
        if sha256(source) != original_hash:
            raise ValueError("Original changed while producing the derivative")
        result = {
            "schemaVersion": "city.rtsp-fixture-derivative.v1",
            "createdAt": datetime.now(UTC).isoformat(),
            "source": SOURCE,
            "sourceSha256": original_hash,
            "output": OUTPUT,
            "outputSha256": sha256(temporary),
            "purpose": "recorded-video-RTSP-replay-fixture",
            "encoder": "CPU libx264",
            "pyavVersion": av.__version__,
            "width": 768,
            "height": 576,
            "frames": 795,
            "fps": 10,
            "firstMediaTimeSeconds": pts[0],
            "lastMediaTimeSeconds": pts[-1],
            "x264Params": X264,
            "maximumVclSlicesPerFrame": max(slice_counts),
            "bFrames": 0,
            "keyFrameInterval": 10,
            "qualification": "Canonical integration encoding; arbitrary multi-slice VIOS inputs remain unqualified.",
        }
        temporary.replace(output)
        receipt.write_text(json.dumps(result, indent=2) + "\n")
        return result
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-dir", type=Path, default=ROOT / ".spark/city/media")
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.media_dir), indent=2))


if __name__ == "__main__":
    main()
