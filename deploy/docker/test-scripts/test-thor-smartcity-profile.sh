#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
profile_dir="${repo_root}/deploy/docker/developer-profiles/dev-profile-thor-smartcity"

bash -n "${profile_dir}/scripts/import-calibration.sh"
bash -n "${repo_root}/deploy/docker/scripts/thor-local.sh"
node --check "${profile_dir}/map/app.js"
python3 "${profile_dir}/scripts/derive-smartcity-assets.py" --check

python3 - "${repo_root}" <<'PY'
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

root = Path(sys.argv[1])
docker_dir = root / "deploy/docker"
profile = docker_dir / "developer-profiles/dev-profile-thor-smartcity"

with (profile / "assets/calibration.json").open(encoding="utf-8") as stream:
    calibration = json.load(stream)
assert calibration["calibrationType"] == "geo"
assert [sensor["id"] for sensor in calibration["sensors"]] == ["Agnew_head_on"]

with (profile / "assets/road-network.json").open(encoding="utf-8") as stream:
    road_network = json.load(stream)
assert [item["name"] for item in road_network["intersections"]] == ["Agnew_head_on"]
assert len(road_network["intersections"][0]["segments"]) == 39

graph_root = ET.parse(profile / "assets/agnew-head-on.graphml").getroot()
namespace = {"g": "http://graphml.graphdrawing.org/xmlns"}
graph_nodes = graph_root.findall(".//g:node", namespace)
graph_edges = graph_root.findall(".//g:edge", namespace)
graph_keys = graph_root.findall("./g:key", namespace)
assert len(graph_nodes) >= 2
assert len(graph_edges) == 39
assert all(node.attrib["id"].isdigit() for node in graph_nodes)
assert all(edge.attrib["id"].isdigit() for edge in graph_edges)
assert all(key.attrib["attr.type"] == "string" for key in graph_keys)
key_ids = {key.attrib["attr.name"]: key.attrib["id"] for key in graph_keys}
assert {"crs", "simplified", "x", "y", "street_count", "osmid", "length", "geometry", "segment_id"} <= key_ids.keys()
for edge in graph_edges:
    attributes = {item.attrib["key"]: item.text for item in edge.findall("g:data", namespace)}
    assert attributes[key_ids["osmid"]].isdigit()
    assert attributes[key_ids["segment_id"]]
graph_data = {
    item.attrib["key"]: item.text
    for item in graph_root.findall(".//g:graph/g:data", namespace)
}
assert "EPSG:4326" in graph_data.values()

with (profile / "vss-behavior-analytics/configs/vss-behavior-analytics-kafka-config.json").open(encoding="utf-8") as stream:
    behavior = json.load(stream)
assert behavior["kafka"]["group"] == "mdx-its-thor-agnew-v1"
graph = behavior["coordinateReferenceSystem"]["roadNetwork"]["graph"]
assert graph["graphFromOSM"] is True
assert graph["osmLoadMethod"] == "from_file"
assert graph["osmQueryFile"] == "/resources/agnew-head-on.graphml"
settings = {item["name"]: item["value"] for item in behavior["app"]}
assert settings["numWorkersForBehaviorCreation"] == "1"
assert settings["numWorkersForBehaviorClustering"] == "1"
assert "car" in settings["mapMatchingClasses"]

with (profile / "compose.yml").open(encoding="utf-8") as stream:
    overlay = yaml.safe_load(stream)
services = overlay["services"]
expected = {
    "perception-2d-smartcity-thor",
    "vss-behavior-analytics-smartcity-thor",
    "smartcity-calibration-import-thor",
    "smartcity-map-thor",
}
assert set(services) == expected
for service in services.values():
    assert service["profiles"] == ["bp_developer_thor_smartcity_2d"]
assert services["perception-2d-smartcity-thor"]["environment"]["NUM_SENSORS"] == "1"
assert services["perception-2d-smartcity-thor"]["environment"]["MODEL_NAME_2D"] == "RTDETR"
assert services["vss-behavior-analytics-smartcity-thor"]["container_name"] != "vss-behavior-analytics"
assert services["vss-behavior-analytics-smartcity-thor"]["image"] == "${THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE:-cti-vss-behavior-analytics:thor-local}"
assert "PYTHONPATH" not in services["vss-behavior-analytics-smartcity-thor"].get("environment", {})
assert all("thor-local-src" not in mount for mount in services["vss-behavior-analytics-smartcity-thor"]["volumes"])
assert services["smartcity-map-thor"]["network_mode"] == "host"
assert services["smartcity-map-thor"]["read_only"] is True

with (docker_dir / "developer-profiles/compose.yml").open(encoding="utf-8") as stream:
    developer_profiles = yaml.safe_load(stream)
includes = {item["path"] for item in developer_profiles["include"]}
assert "./dev-profile-thor-smartcity/compose.yml" in includes

with (docker_dir / "developer-profiles/dev-profile-search/video-analytics-2d-app/compose.yml").open(encoding="utf-8") as stream:
    search = yaml.safe_load(stream)["services"]
for service_name in ("perception-2d-init", "perception-2d-fusion"):
    profiles = search[service_name]["profiles"]
    assert "bp_developer_thor_search_perception_2d" in profiles
    assert "bp_developer_thor_full_2d" not in profiles
for service_name in ("vss-search-analytics-2d-fusion", "vss-video-analytics-api-fusion"):
    assert "bp_developer_thor_full_2d" in search[service_name]["profiles"]

source_env = (docker_dir / "developer-profiles/dev-profile-thor-full/.env").read_text(encoding="utf-8")
assert "COMPOSE_PROFILES=bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d" in source_env
assert "NEXT_PUBLIC_MAP_URL=${VSS_PUBLIC_HTTP_PROTOCOL}://${VSS_PUBLIC_HOST}:${VSS_PUBLIC_PORT}/smartcity-map/" in source_env

thor_local = (docker_dir / "scripts/thor-local.sh").read_text(encoding="utf-8")
assert "bp_developer_thor_full_2d,bp_developer_thor_smartcity_2d" in thor_local
assert "bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d" in thor_local
assert 'SMARTCITY_MAP_PORT="${SMARTCITY_MAP_PORT:-3002}"' in thor_local
assert 'THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE="${THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE:-cti-vss-behavior-analytics:thor-local}"' in thor_local
assert 'require_available_port "${SMARTCITY_MAP_PORT}" vss-smartcity-map-thor' in thor_local
assert 'http://127.0.0.1:${SMARTCITY_MAP_PORT}/ is not ready' in thor_local

haproxy = (docker_dir / "services/infra/haproxy/haproxy.cfg.template").read_text(encoding="utf-8")
assert "backend bk_smartcity_map_strip" in haproxy
assert 'server s1 "127.0.0.1:${SMARTCITY_MAP_PORT}" check' in haproxy
assert "use_backend bk_smartcity_map_strip if h_main p_smartcity_map" in haproxy

map_sources = "\n".join(
    (profile / relative).read_text(encoding="utf-8")
    for relative in ("map/index.html", "map/styles.css", "map/app.js")
)
for forbidden in ("maps.google", "googleapis", "mapbox", "unpkg", "jsdelivr", "openstreetmap.org", "fonts.googleapis"):
    assert forbidden not in map_sources.lower(), forbidden
assert not re.search(r"fetch\(\s*['\"]https?://", map_sources)
assert '"./assets/calibration.json"' in map_sources
assert '"./assets/road-network.json"' in map_sources
assert "prefers-reduced-motion" in map_sources

importer = (profile / "scripts/import-calibration.sh").read_text(encoding="utf-8")
assert "SMARTCITY_IMPORT_MAX_ATTEMPTS" in importer
assert "while [" in importer
assert "until " not in importer

print("All Thor Smart City static contracts passed.")
PY

grep -Fq 'COPY services/analytics/behavior-analytics/src/mdx/analytics/core/utils/crs.py' \
  "${repo_root}/deploy/docker/thor-local/Dockerfile.behavior-analytics"

behavior_image="${THOR_LOCAL_BEHAVIOR_ANALYTICS_IMAGE:-cti-vss-behavior-analytics:thor-local}"
if docker image inspect "${behavior_image}" >/dev/null 2>&1; then
  docker run --rm --network none --read-only --cap-drop all \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --env MPLCONFIGDIR=/tmp/matplotlib \
    --env PYTHONDONTWRITEBYTECODE=1 \
    --entrypoint python3 \
    --volume "${profile_dir}/assets/agnew-head-on.graphml:/asset.graphml:ro" \
    "${behavior_image}" -c '
import osmnx as ox
from mdx.analytics.core.schema.config import GraphConfig
from mdx.analytics.core.utils.crs import RoadNetworkGraph

graph = ox.load_graphml("/asset.graphml")
assert graph.number_of_nodes() == 53
assert graph.number_of_edges() == 39
assert graph.graph["crs"] == "EPSG:4326"
assert graph.graph["simplified"] is False
assert all(isinstance(node, int) for node in graph.nodes)
assert all(isinstance(data["osmid"], int) for *_, data in graph.edges(data=True))
assert all(data["segment_id"] for *_, data in graph.edges(data=True))
nodes, edges = ox.graph_to_gdfs(graph, nodes=True, edges=True)
assert set(nodes.geometry.geom_type) == {"Point"}
assert set(edges.geometry.geom_type) == {"LineString"}
config = GraphConfig(
    graphFromOSM=True,
    osmLoadMethod="from_file",
    osmType="drive",
    osmSimplify=False,
    osmQueryFile="/asset.graphml",
)
behavior_graph = RoadNetworkGraph(config).graph
assert behavior_graph.number_of_nodes() == 53
assert behavior_graph.number_of_edges() == 39
print("Exact behavior image loaded offline GraphML through OSMnx and RoadNetworkGraph: 53 nodes, 39 edges")
'
else
  printf 'SKIP: exact behavior image is not staged: %s\n' "${behavior_image}"
fi
