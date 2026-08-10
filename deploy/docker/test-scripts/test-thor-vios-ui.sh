#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"

python3 - "${repo_root}" <<'PY'
import json
import sys
from pathlib import Path

import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(
    "!override", lambda loader, node: loader.construct_sequence(node)
)

root = Path(sys.argv[1])
docker_dir = root / "deploy/docker"
released_config_path = docker_dir / "services/vios/configs/vst_config.json"
thor_config_path = docker_dir / "thor-local/vios/vst_config.json"

released = json.loads(released_config_path.read_text(encoding="utf-8"))
thor = json.loads(thor_config_path.read_text(encoding="utf-8"))

# Keep the Thor derivative identical to the released contract except for the
# public STUN endpoints. A loopback target prevents VST's compiled Google-STUN
# fallback while retaining a syntactically valid ICE-server list.
released["network"]["stunurl_list"] = ["127.0.0.1:3478"]
assert thor == released
assert thor["network"]["stunurl_list"] == ["127.0.0.1:3478"]
assert thor["network"]["use_twilio_stun_turn"] is False
assert thor["network"]["static_turnurl_list"] == []
serialized = json.dumps(thor).lower()
for forbidden in ("google.com", "twilio.com", "stun1.l.google"):
    assert forbidden not in serialized, forbidden

overlay = yaml.load(
    (docker_dir / "thor-local/compose.yml").read_text(encoding="utf-8"),
    Loader=ComposeLoader,
)
services = overlay["services"]
ingress = services["vst-ingress"]
assert ingress["image"] == "${THOR_LOCAL_VST_INGRESS_IMAGE:-cti-vss-vios-ingress:3.2.1-thor-local}"
assert ingress["build"]["context"] == "${VSS_REPO_ROOT}/services/vios/ui"
assert ingress["build"]["dockerfile"] == "Dockerfile.thor-local"
expected_mount = (
    "${THOR_LOCAL_VST_CONFIG_FILE:-${VSS_REPO_ROOT}/deploy/docker/thor-local/"
    "vios/vst_config.json}:/home/vst/vst_release/configs/vst_config.json:ro"
)
for service_name in ("sensor-ms", "streamprocessing-ms"):
    assert expected_mount in services[service_name]["volumes"]

ui_dockerfile = (root / "services/vios/ui/Dockerfile.thor-local").read_text()
assert "npm ci --no-audit --no-fund" in ui_dockerfile
assert "NPM_CONFIG_REGISTRY=https://registry.npmmirror.com/" in ui_dockerfile
assert "COPY --from=ui-build --chown=nginx:nginx /src/vios-ui/dist/ /vst-ui/" in ui_dockerfile

video_player = (root / "services/vios/ui/vios-ui/src/components/videoPlayer/VideoPlayer.tsx").read_text()
sensor_utils = (root / "services/vios/ui/vios-ui/src/utils/misc/sensorUtils.ts").read_text()
websocket_endpoint = (
    root
    / "services/vios/ui/vios-ui/src/components/videoPlayer/videoPlayerUtils/websocketEndpoint.ts"
).read_text()
assert "buildWebSocketEndpoint(streamingEndpoint, window.location.pathname)" in video_player
assert "const initialTimelines = sensor?.timelines ?? []" in video_player
assert "availableSensors.flatMap<Sensor>" in sensor_utils
assert "proxyPathname.replace(/^\\/+|\\/+$/g, '')" in websocket_endpoint

foundational = yaml.safe_load(
    (docker_dir / "services/vios/foundational/docker-compose.yaml").read_text(encoding="utf-8")
)
sensor = yaml.safe_load(
    (docker_dir / "services/vios/initiator/docker-compose.yaml").read_text(encoding="utf-8")
)
processor = yaml.safe_load(
    (docker_dir / "services/vios/streamprocessing/docker-compose.yaml").read_text(encoding="utf-8")
)
profile = "bp_developer_thor_full_2d"
assert profile in foundational["services"]["vst-ingress"]["profiles"]
assert profile in sensor["services"]["sensor-ms"]["profiles"]
assert profile in processor["services"]["streamprocessing-ms"]["profiles"]

nginx = (docker_dir / "services/vios/configs/nginx-vst.conf").read_text(encoding="utf-8")
for route in ("location /vst/", "alias /vst-ui/", "location /vst/api/v1/", "location /vst/storage/"):
    assert route in nginx

haproxy = (docker_dir / "services/infra/haproxy/haproxy.cfg.template").read_text(encoding="utf-8")
assert "acl p_vst path /vst" in haproxy
assert "use_backend bk_vst_ingress if h_main p_vst" in haproxy

print("All Thor VIOS UI and offline-WebRTC static contracts passed.")
PY
