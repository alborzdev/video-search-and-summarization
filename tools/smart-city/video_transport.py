#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render the bounded CPU relay for shared, timestamp-preserving city WebRTC."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

# Already installed and used by the local RTSP tooling. No network install or
# unpinned executable is involved when selecting the WebRTC display transport.
RELAY_VERSION = "v1.21.2"
RELAY_SHA256 = "f8676d0ed8f210453a722fdad76fe6e52cf764fdcf9930e8c7d242d02da57c2b"


def relay_service(root: Path, device: str, camera_ids: list[str]) -> dict:
    if device != "spark" or not 1 <= len(camera_ids) <= 2 or any(not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", item) for item in camera_ids):
        raise ValueError("WebRTC display requires the explicit Spark camera profile")
    binary = root / ".spark/city/runtime/rtsp-replay/mediamtx"
    if not binary.is_file() or binary.is_symlink() or hashlib.sha256(binary.read_bytes()).hexdigest() != RELAY_SHA256:
        raise ValueError("The pinned city video relay is unavailable or changed")
    directory = root / ".spark/city/state/video"
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "relay.json"
    cameras = "|".join(re.escape(item) for item in camera_ids)
    body = {
        "logLevel": "warn", "readTimeout": "30s", "writeTimeout": "10s", "writeQueueSize": 256,
        "rtsp": True, "rtspAddress": "127.0.0.1:18558", "rtspTransports": ["tcp"],
        "rtmp": False, "hls": False, "srt": False, "moq": False, "playback": False,
        "api": True, "apiAddress": "127.0.0.1:9193",
        "webrtc": True, "webrtcAddress": "127.0.0.1:9192", "webrtcLocalUDPAddress": ":8192",
        "webrtcIPsFromInterfaces": True, "webrtcHandshakeTimeout": "5s", "webrtcTrackGatherTimeout": "3s",
        "authInternalUsers": [{"user": "any", "pass": "", "ips": ["127.0.0.1", "::1"],
                               "permissions": [{"action": action, "path": ""} for action in ("publish", "read", "api")]}],
        "paths": {"~^city/(" + cameras + ")/[A-Za-z0-9-]{1,200}$": {"source": "publisher", "overridePublisher": False, "maxReaders": 16}},
    }
    encoded = json.dumps(body, indent=2) + "\n"
    if not config.exists() or config.read_text() != encoded:
        temporary = config.with_suffix(".tmp")
        temporary.write_text(encoded)
        temporary.replace(config)
    return {
        "image": "vss-city-analytics:dev", "container_name": "vss-city-video", "network_mode": "host",
        "runtime": "runc", "user": "1000:1000", "mem_limit": "256m", "memswap_limit": "256m", "cpus": 1,
        "read_only": True, "security_opt": ["no-new-privileges:true"], "cap_drop": ["ALL"],
        "labels": {"com.connecttech.vss.city": "video-relay", "com.connecttech.vss.city.video-config": hashlib.sha256(encoded.encode()).hexdigest()},
        "entrypoint": ["/opt/city-video/mediamtx"], "command": ["/opt/city-video/relay.json"],
        "volumes": [str(binary) + ":/opt/city-video/mediamtx:ro", str(config) + ":/opt/city-video/relay.json:ro"],
        "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9193/v3/paths/list',timeout=2)"],
                        "interval": "10s", "timeout": "3s", "retries": 3},
    }
