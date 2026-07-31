#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Derive the bounded, offline Agnew_head_on Smart City fixture.

The NVIDIA Smart City sample contains four camera calibrations and eight road
network intersections. Thor runs one RT-CV stream, so this script selects the
single matching camera/intersection and emits an OSMnx-compatible GraphML file
from the selected road segments. No network access is used.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


SENSOR_ID = "Agnew_head_on"
PROFILE_DIR = Path(__file__).resolve().parents[1]
DOCKER_DIR = PROFILE_DIR.parents[1]
SOURCE_DIR = DOCKER_DIR / "industry-profiles" / "smartcities"
SOURCE_ASSET_DIR = SOURCE_DIR / "smc-app" / "calibration" / "sample-data"
SOURCE_CONFIG = SOURCE_DIR / "vss-behavior-analytics" / "configs" / "vss-behavior-analytics-kafka-config.json"
OUTPUT_DIR = PROFILE_DIR / "assets"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()


def select_exact(items: list[dict], key: str, value: str, source: Path) -> dict:
    selected = [item for item in items if item.get(key) == value]
    if len(selected) != 1:
        raise ValueError(f"expected exactly one {key}={value!r} in {source}; found {len(selected)}")
    return copy.deepcopy(selected[0])


def derive_calibration() -> dict:
    source = SOURCE_ASSET_DIR / "calibration.json"
    payload = load_json(source)
    sensor = select_exact(payload.get("sensors", []), "id", SENSOR_ID, source)
    return {
        "version": payload["version"],
        "osmURL": "",
        "calibrationType": payload["calibrationType"],
        "sensors": [sensor],
    }


def derive_road_network() -> dict:
    source = SOURCE_ASSET_DIR / "road-network.json"
    payload = load_json(source)
    intersection = select_exact(payload.get("intersections", []), "name", SENSOR_ID, source)
    if not intersection.get("segments"):
        raise ValueError(f"{SENSOR_ID} has no road segments in {source}")
    return {
        "docType": payload["docType"],
        "city": payload["city"],
        "intersections": [intersection],
    }


def replace_app_setting(config: dict, name: str, value: str) -> None:
    matches = [setting for setting in config.get("app", []) if setting.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one app setting named {name!r}")
    matches[0]["value"] = value


def replace_sensor_setting(config: dict, name: str, value: str) -> None:
    defaults = [sensor for sensor in config.get("sensors", []) if sensor.get("id") == "default"]
    if len(defaults) != 1:
        raise ValueError("expected exactly one default sensor configuration")
    matches = [setting for setting in defaults[0].get("configs", []) if setting.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one sensor setting named {name!r}")
    matches[0]["value"] = value


def derive_behavior_config() -> dict:
    config = copy.deepcopy(load_json(SOURCE_CONFIG))
    config["kafka"]["brokers"] = "127.0.0.1:9092"
    config["kafka"]["group"] = "mdx-its-thor-agnew-v1"
    replace_sensor_setting(config, "anomalyIgnoreSensors", "[]")
    replace_sensor_setting(
        config,
        "anomalyClasses",
        '["car","bicycle","person","Vehicle","Car","Bicycle","Person"]',
    )
    replace_app_setting(config, "mapMatchingClasses", '["car","bicycle","person","Vehicle","Car","Bicycle","Person"]')
    replace_app_setting(config, "numWorkersForBehaviorCreation", "1")
    replace_app_setting(config, "numWorkersForBehaviorClustering", "1")

    road_network = config["coordinateReferenceSystem"]["roadNetwork"]
    graph = road_network["graph"]
    graph["graphFromOSM"] = True
    graph["osmLoadMethod"] = "from_file"
    graph["osmQueryFile"] = "/resources/agnew-head-on.graphml"
    graph["osmQueryPoint"] = {"lat": 37.392908, "lon": -121.946801}
    graph["osmQueryPointDistMeters"] = 500
    road_network["visualization"]["visualizationMapUseBackground"] = False
    return config


def coordinate_key(point: dict) -> tuple[str, str]:
    return (format(float(point["lat"]), ".12g"), format(float(point["lon"]), ".12g"))


def haversine_meters(first: dict, second: dict) -> float:
    radius = 6_371_008.8
    lat1 = math.radians(float(first["lat"]))
    lat2 = math.radians(float(second["lat"]))
    delta_lat = lat2 - lat1
    delta_lon = math.radians(float(second["lon"]) - float(first["lon"]))
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


def graphml_bytes(road_network: dict) -> bytes:
    namespace = "http://graphml.graphdrawing.org/xmlns"
    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    ET.register_namespace("", namespace)
    ET.register_namespace("xsi", xsi)
    root = ET.Element(
        f"{{{namespace}}}graphml",
        {f"{{{xsi}}}schemaLocation": f"{namespace} http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd"},
    )

    keys = (
        ("d0", "graph", "crs", "string"),
        # OSMnx serializes every GraphML attribute as a string, then applies
        # its own dtype conversion in load_graphml. Native GraphML numeric
        # types arrive in OSMnx as Python values and fail its string parser.
        ("d1", "graph", "simplified", "string"),
        ("d2", "node", "x", "string"),
        ("d3", "node", "y", "string"),
        ("d4", "node", "street_count", "string"),
        ("d5", "edge", "osmid", "string"),
        ("d6", "edge", "length", "string"),
        ("d7", "edge", "geometry", "string"),
        ("d8", "edge", "direction", "string"),
        ("d9", "edge", "segment_id", "string"),
    )
    for key_id, scope, name, value_type in keys:
        ET.SubElement(
            root,
            f"{{{namespace}}}key",
            {"id": key_id, "for": scope, "attr.name": name, "attr.type": value_type},
        )

    graph = ET.SubElement(root, f"{{{namespace}}}graph", {"edgedefault": "directed"})
    ET.SubElement(graph, f"{{{namespace}}}data", {"key": "d0"}).text = "EPSG:4326"
    ET.SubElement(graph, f"{{{namespace}}}data", {"key": "d1"}).text = "False"

    intersection = road_network["intersections"][0]
    points_by_key: dict[tuple[str, str], dict] = {}
    degree_by_key: dict[tuple[str, str], int] = {}
    edges: list[tuple[dict, int, dict, dict]] = []
    for segment in intersection["segments"]:
        points = segment.get("points") or [segment["start"], segment["end"]]
        for index, (first, second) in enumerate(zip(points, points[1:])):
            first_key = coordinate_key(first)
            second_key = coordinate_key(second)
            points_by_key.setdefault(first_key, first)
            points_by_key.setdefault(second_key, second)
            degree_by_key[first_key] = degree_by_key.get(first_key, 0) + 1
            degree_by_key[second_key] = degree_by_key.get(second_key, 0) + 1
            edges.append((segment, index, first, second))

    # OSMnx loads GraphML node identifiers with ``int`` as the node type.
    # Numeric strings preserve deterministic ordering and round-trip through
    # ox.load_graphml; decorative identifiers such as ``n0001`` do not.
    node_ids = {key: str(index) for index, key in enumerate(sorted(points_by_key), start=1)}
    for key in sorted(points_by_key):
        point = points_by_key[key]
        node = ET.SubElement(graph, f"{{{namespace}}}node", {"id": node_ids[key]})
        ET.SubElement(node, f"{{{namespace}}}data", {"key": "d2"}).text = format(float(point["lon"]), ".12g")
        ET.SubElement(node, f"{{{namespace}}}data", {"key": "d3"}).text = format(float(point["lat"]), ".12g")
        ET.SubElement(node, f"{{{namespace}}}data", {"key": "d4"}).text = str(degree_by_key[key])

    for edge_index, (segment, part_index, first, second) in enumerate(edges, start=1):
        edge = ET.SubElement(
            graph,
            f"{{{namespace}}}edge",
            {
                "id": str(edge_index - 1),
                "source": node_ids[coordinate_key(first)],
                "target": node_ids[coordinate_key(second)],
            },
        )
        # OSMnx converts the conventional osmid attribute to int. Preserve the
        # source road-segment identifier separately for traceability.
        ET.SubElement(edge, f"{{{namespace}}}data", {"key": "d5"}).text = str(edge_index)
        ET.SubElement(edge, f"{{{namespace}}}data", {"key": "d6"}).text = f"{haversine_meters(first, second):.6f}"
        geometry = f"LINESTRING ({float(first['lon']):.12g} {float(first['lat']):.12g}, {float(second['lon']):.12g} {float(second['lat']):.12g})"
        ET.SubElement(edge, f"{{{namespace}}}data", {"key": "d7"}).text = geometry
        ET.SubElement(edge, f"{{{namespace}}}data", {"key": "d8"}).text = str(segment.get("direction", ""))
        ET.SubElement(edge, f"{{{namespace}}}data", {"key": "d9"}).text = f"{segment['id']}:{part_index}"

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def expected_outputs() -> dict[Path, bytes]:
    calibration = derive_calibration()
    road_network = derive_road_network()
    return {
        OUTPUT_DIR / "calibration.json": json_bytes(calibration),
        OUTPUT_DIR / "road-network.json": json_bytes(road_network),
        OUTPUT_DIR / "agnew-head-on.graphml": graphml_bytes(road_network),
        PROFILE_DIR / "vss-behavior-analytics" / "configs" / "vss-behavior-analytics-kafka-config.json": json_bytes(
            derive_behavior_config()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if checked-in outputs differ from a fresh derivation")
    args = parser.parse_args()

    outputs = expected_outputs()
    if args.check:
        stale = []
        for path, expected in outputs.items():
            if not path.is_file() or path.read_bytes() != expected:
                stale.append(path.relative_to(PROFILE_DIR))
        if stale:
            print("stale Smart City derived assets: " + ", ".join(map(str, stale)), file=sys.stderr)
            return 1
    else:
        for path, content in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    digest = hashlib.sha256(b"".join(outputs[path] for path in sorted(outputs))).hexdigest()
    print(f"Smart City assets are deterministic ({len(outputs)} files, sha256={digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
