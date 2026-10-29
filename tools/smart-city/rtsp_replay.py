#!/usr/bin/env python3
"""CPU-only, explicitly labelled RTSP replay fixture for VSS integration tests.

The publisher copies H.264 packets; it does not generate detections or city data.
It listens on Docker's host bridge so VSS containers can also reach it. This is
test media, not a simulator stream. No current source is replaced or removed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import socket
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

from manage import ROOT, ensure_headroom

VERSION = "1.21.2"
URL = f"https://github.com/bluenviron/mediamtx/releases/download/v{VERSION}/mediamtx_v{VERSION}_linux_arm64.tar.gz"
SHA256 = "180a235374a548d9133cdd5e20f5dbd8b01317be1c86e0d7e66df585dc42ed6f"
ADDRESS = "172.17.0.1"
PORT = 18554
DIRECTORY = ROOT / ".spark/city/runtime/rtsp-replay"


def stage() -> None:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    archive = DIRECTORY / "mediamtx.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read(32 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError("MediaMTX release hash mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Cached MediaMTX release hash mismatch")
    # Extract only the known executable, never arbitrary archive paths.
    with tarfile.open(fileobj=io.BytesIO(archive.read_bytes()), mode="r:gz") as bundle:
        member = bundle.getmember("mediamtx")
        if not member.isfile() or member.size > 100 * 1024 * 1024:
            raise RuntimeError("Unexpected MediaMTX executable")
        executable = bundle.extractfile(member)
        if executable is None:
            raise RuntimeError("Release executable is missing")
        (DIRECTORY / "mediamtx").write_bytes(executable.read())
    (DIRECTORY / "mediamtx").chmod(0o755)
    (DIRECTORY / "artifact.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "url": URL,
                "sha256": SHA256,
                "license": "MIT",
                "purpose": "recorded-video-RTSP-replay-fixture",
            },
            indent=2,
        )
        + "\n"
    )


def render() -> Path:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    media = ROOT / ".spark/city/media"
    config = {
        "logLevel": "info",
        "rtsp": True,
        "rtspTransports": ["tcp"],
        "rtspAddress": f"{ADDRESS}:{PORT}",
        "api": False,
        "metrics": False,
        "pprof": False,
        "playback": False,
        "rtmp": False,
        "hls": False,
        "webrtc": False,
        "srt": False,
        "moq": False,
        "paths": {"city-traffic": {}, "city-pedestrians": {}},
    }
    # JSON is valid YAML; use no YAML dependency in this host-side utility.
    (DIRECTORY / "mediamtx.yml").write_text(json.dumps(config, indent=2) + "\n")
    services = {
        "server": {
            "image": "vss-city-analytics:dev",
            "container_name": "vss-city-replay-server",
            "entrypoint": ["/replay/mediamtx", "/replay/mediamtx.yml"],
            "volumes": [f"{DIRECTORY}:/replay:ro"],
            "network_mode": "host",
            "user": "1000:1000",
            "runtime": "runc",
            "mem_limit": "128m",
            "memswap_limit": "128m",
            "cpus": 0.5,
            "security_opt": ["no-new-privileges:true"],
            "cap_drop": ["ALL"],
            "read_only": True,
            "restart": "no",
        }
    }
    for name, filename in (
        ("traffic", "traffic-sample.mp4"),
        ("pedestrians", "pedestrian-replay-single-slice.mp4"),
    ):
        if not (media / filename).is_file():
            raise RuntimeError(
                f"Stage the controlled recording first: {filename}; use prepare_replay_fixture.py for the canonical pedestrian input"
            )
        if name == "pedestrians":
            receipt = json.loads((media / filename).with_suffix(".json").read_text())
            if (
                receipt.get("outputSha256")
                != hashlib.sha256((media / filename).read_bytes()).hexdigest()
                or receipt.get("sourceSha256")
                != hashlib.sha256(
                    (media / "pedestrian-sample.mp4").read_bytes()
                ).hexdigest()
            ):
                raise RuntimeError(
                    "Canonical pedestrian replay derivative/provenance hashes do not match"
                )
        services[name] = {
            "image": "vss-rtvi-vlm:3.3-sbsa-codecs",
            "container_name": f"vss-city-replay-{name}",
            "runtime": "runc",
            "entrypoint": ["/work/export-env/bin/python"],
            "command": [
                "/tools/replay_publisher.py",
                "--file",
                f"/media/{filename}",
                "--url",
                f"rtsp://{ADDRESS}:{PORT}/city-{name}",
            ],
            "network_mode": "host",
            "user": "1000:1000",
            "cpus": 0.5,
            "mem_limit": "192m",
            "memswap_limit": "192m",
            "read_only": True,
            "environment": {"NVIDIA_VISIBLE_DEVICES": "void"},
            "security_opt": ["no-new-privileges:true"],
            "cap_drop": ["ALL"],
            "volumes": [
                f"{media}:/media:ro",
                f"{ROOT}/tools/smart-city:/tools:ro",
                f"{ROOT}/.spark/city:/work:ro",
            ],
            "restart": "no",
        }
    path = DIRECTORY / "compose.json"
    path.write_text(
        json.dumps({"name": "vss-city-replay-fixture", "services": services}, indent=2)
        + "\n"
    )
    return path


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", "-f", str(render()), *args], check=True)


def ready(path: str) -> bool:
    try:
        with socket.create_connection((ADDRESS, PORT), timeout=2) as connection:
            connection.sendall(
                (
                    f"DESCRIBE rtsp://{ADDRESS}:{PORT}/{path} RTSP/1.0\r\n"
                    "CSeq: 1\r\nAccept: application/sdp\r\n\r\n"
                ).encode()
            )
            return b"RTSP/1.0 200" in connection.recv(8192)
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "start", "stop", "status"))
    args = parser.parse_args()
    if args.action == "stage":
        stage()
    elif args.action == "start":
        ensure_headroom("spark")
        if not (DIRECTORY / "mediamtx").is_file():
            raise RuntimeError("Stage the pinned MediaMTX executable first")
        compose("up", "-d", "--no-build", "--pull", "never", "server")
        for _ in range(30):
            try:
                with socket.create_connection((ADDRESS, PORT), timeout=1):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("RTSP fixture server did not start")
        compose("up", "-d", "--no-build", "--pull", "never", "traffic", "pedestrians")
        for _ in range(50):
            if all(ready(path) for path in ("city-traffic", "city-pedestrians")):
                print(
                    "Ready: recorded-video RTSP replay fixtures, not live city cameras"
                )
                return
            time.sleep(0.2)
        raise RuntimeError(
            "RTSP replay publishers did not become ready; inspect their logs"
        )
    elif args.action == "stop":
        compose("down")
    else:
        print(
            json.dumps(
                {
                    "kind": "recorded-video-RTSP-replay-fixture",
                    "paths": {
                        name: ready(name)
                        for name in ("city-traffic", "city-pedestrians")
                    },
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
