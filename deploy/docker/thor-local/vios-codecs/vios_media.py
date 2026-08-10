#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Audit, stage, and preflight the Thor VIOS media capability lane.

Only ``stage`` uses the network, explicitly, by delegating to the shared VSS
3.2.1 signed-metadata codec stager. All other commands are read-only. No
command creates, starts, stops, or removes a container.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
DEFAULT_BUNDLE = SCRIPT.parent / "bundle"
AUDIO_STAGER = REPO / "deploy/docker/thor-local/audio/codec_bundle.py"
PACKAGE_SET = "ed28389b37a2d74a484251e874b4a131e9eb2a8350b4013ba0c209154bfdf3b4"
EXPECTED_LABELS = {
    "com.nvidia.vss.thor.vios-codecs": "ubuntu-noble-arm64-offline",
    "com.nvidia.vss.thor.vios-codec-package-set": PACKAGE_SET,
    "com.nvidia.vss.thor.vios-runtime-network-install": "disabled",
}
DEFAULT_IMAGES = (
    "vss-vios-streamprocessing:3.2.1-thor-local",
    "vss-vios-nvstreamer:3.2.1-thor-local",
)

SOURCE_CONTRACT = {
    "services/vios/src/modules/rtsp_server/H264ByteStreamSource.cpp": (
        "f3849194fd9fd17b5c3e10b8799f5d1bc08dbd125bcd122fee429eef3b5a2a12",
        ("isContinuationSlice", "first_slice_segment_in_pic_flag", "m_lastFramePT"),
    ),
    "services/vios/src/modules/rtsp_server/DynamicRTSPServer.cpp": (
        "0592fd4d761e0a2d7409f0a33ca1eb66a87bd93722e99ce3182356ac0e09f8ce",
        ("includeAudio=true", "MediaTypeAudio"),
    ),
    "services/vios/src/modules/rtsp_server/NvMediaServer.cpp": (
        "2225e0fc77557c434af1c0a221abb4675c1c8c81f629bd3b22a6cb14ae426b81",
        ("H265VideoStreamDiscreteFramer::createNew", "H265VideoRTPSink::createNew"),
    ),
    "services/vios/src/framework/live555/inc/live/liveMedia/include/H265VideoRTPSource.hh": (
        "dfdcc154fb7c221072dc3cf336a971fb83573e3ec2457d484f5374da97ec290b",
        ("DONL and DOND fields", "MultiFramedRTPSource"),
    ),
    "services/vios/src/framework/media/media_pipelines/transcode_writer_consumer.cpp": (
        "044efd0c133c17277119e065f035d63fc300c9965fea8c2058c5e606c5b2d787",
        ("hasBframes", "avdec_h265", "x265enc", "avenc_aac"),
    ),
    "services/vios/src/framework/media/media_pipelines/remux_writer_consumer.cpp": (
        "77e09bd3d48b3a1e3eb61794254d2417b74547b303fd42685aa22375013d937a",
        ("audio path set up", "getAudioConsumer"),
    ),
    "services/vios/src/framework/media/media_utils/gst_utils.cpp": (
        "08400fd8679288b2ccb4e2d89d7edbaee6e118ea14345626544339718b3e84a9",
        ("h264parse", "h265parse", "x264enc", "nvv4l2h265enc", "H265 B-frame detected"),
    ),
    "services/vios/src/framework/media/media_utils/mm_utils.cpp": (
        "686a0c7517c9ced807a833c5821f906231783792e525b669bff1ea1b0e1fa651",
        ("parseH265SliceType",),
    ),
    "services/vios/src/modules/storage_management/storage_management_apis.cpp": (
        "8e31cb2c138b98cb08c43a3e04fd6962479c5178fc5bdac13b1e1b5ad9e6d2f0",
        ("disableAudio", "isAacPresent"),
    ),
    "services/vios/src/modules/rtsp_server/AvLoopSyncCoordinator.h": (
        "be82cf19fd0abbf23f8ccc8d5497aa3cd10eacc43d524fb9d0bcdaf74ba482ab",
        ("keep audio and video", "B-frame"),
    ),
}


class ContractError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def codec_module():
    if not AUDIO_STAGER.is_file():
        raise ContractError(f"shared VSS codec stager is missing: {AUDIO_STAGER}")
    spec = importlib.util.spec_from_file_location("vss_thor_codec_bundle", AUDIO_STAGER)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot load shared codec stager: {AUDIO_STAGER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_audit() -> None:
    for relative, (expected_digest, needles) in SOURCE_CONTRACT.items():
        path = REPO / relative
        if not path.is_file():
            raise ContractError(f"VIOS media source is missing: {relative}")
        actual = sha256(path)
        if actual != expected_digest:
            raise ContractError(
                f"VIOS media source drifted: {relative}: expected {expected_digest}, got {actual}"
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [needle for needle in needles if needle not in text]
        if missing:
            raise ContractError(f"VIOS media source contract missing {missing}: {relative}")

    config = json.loads((REPO / "deploy/docker/thor-local/vios/vst_config.json").read_text())
    data = config.get("data", {})
    if data.get("supported_video_codecs") != ["h264", "h265"]:
        raise ContractError("Thor VIOS config must advertise exactly H.264 and H.265")
    if data.get("supported_audio_codecs") != ["pcmu", "pcma", "mpeg4-generic"]:
        raise ContractError("Thor VIOS config must advertise G.711 mu/a-law and AAC")
    if data.get("use_software_path") is not False:
        raise ContractError("Thor default must retain HW path with explicit CPU fallback in source")

    module = codec_module()
    upstream_packages = module.source_packages()
    bundle_packages = module.bundle_packages()
    module.load_canonical_lock()
    print("PASS source: B-frame, HEVC multislice/RTP, H.264/H.265, audio, and CPU paths pinned")
    print(
        f"PASS source: exact {len(upstream_packages)}-package ARM64 VSS source plus "
        f"{len(bundle_packages) - len(upstream_packages)}-package Thor runtime closure pinned"
    )


def stage(bundle: Path, retries: int, timeout: int) -> None:
    source_audit()
    document = codec_module().stage_bundle(bundle, retries, timeout)
    print(f"staged {document['package_count']} checksum-locked packages at {bundle}")


def verify_bundle(bundle: Path) -> None:
    document = codec_module().verify_bundle(bundle)
    if document.get("package_set_sha256") != PACKAGE_SET:
        raise ContractError("verified bundle has the wrong package identity set")
    print(f"PASS bundle: {document['package_count']} ARM64 archives match checksums and metadata")


def inspect_image(image: str) -> list[str]:
    try:
        output = subprocess.check_output(
            ["docker", "image", "inspect", image], text=True, stderr=subprocess.STDOUT
        )
    except (OSError, subprocess.CalledProcessError):
        return [f"image is absent: {image}"]
    document = json.loads(output)[0]
    failures = []
    if document.get("Architecture") != "arm64":
        failures.append(f"image is not ARM64: {image}")
    config = document.get("Config") or {}
    labels = config.get("Labels") or {}
    for name, value in EXPECTED_LABELS.items():
        if labels.get(name) != value:
            failures.append(f"image has stale/missing {name}: {image}")
    if config.get("Entrypoint") != ["/usr/local/bin/vios-offline-entrypoint"]:
        failures.append(f"image does not use the fail-closed offline entrypoint: {image}")
    return failures


def preflight(bundle: Path, images: tuple[str, ...]) -> int:
    blockers = []
    if platform.machine() != "aarch64":
        blockers.append(f"host architecture is {platform.machine()}, expected aarch64")
    try:
        source_audit()
    except (ContractError, RuntimeError) as exc:
        blockers.append(str(exc))
    try:
        verify_bundle(bundle)
    except (ContractError, RuntimeError) as exc:
        blockers.append(str(exc))
    if shutil.which("docker") is None:
        blockers.append("docker client is unavailable for read-only image inspection")
    else:
        for image in images:
            blockers.extend(inspect_image(image))
    if blockers:
        for blocker in blockers:
            print(f"BLOCKED {blocker}")
        return 2
    print("PASS preflight: immutable VIOS and NvStreamer media images are staged")
    return 0


def build_commands(bundle: Path) -> None:
    if bundle != DEFAULT_BUNDLE.resolve():
        raise ContractError(
            f"Dockerfiles consume the canonical bundle path only: {DEFAULT_BUNDLE.resolve()}"
        )
    verify_bundle(bundle)
    print("docker build --network=none -f deploy/docker/thor-local/Dockerfile.vios-streamprocessing \\")
    print("  -t vss-vios-streamprocessing:3.2.1-thor-local .")
    print("docker build --network=none -f deploy/docker/thor-local/Dockerfile.vios-nvstreamer \\")
    print("  -t vss-vios-nvstreamer:3.2.1-thor-local .")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("source-audit")
    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    stage_parser.add_argument("--retries", type=int, default=5)
    stage_parser.add_argument("--timeout", type=int, default=60)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    preflight_parser.add_argument("--image", action="append", dest="images")
    build = sub.add_parser("build-command")
    build.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "source-audit":
            source_audit()
        elif args.command == "stage":
            if args.retries < 1 or args.timeout < 1:
                raise ContractError("retries and timeout must be positive")
            stage(args.bundle.resolve(), args.retries, args.timeout)
        elif args.command == "verify":
            verify_bundle(args.bundle.resolve())
        elif args.command == "preflight":
            return preflight(args.bundle.resolve(), tuple(args.images or DEFAULT_IMAGES))
        else:
            build_commands(args.bundle.resolve())
    except (ContractError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
