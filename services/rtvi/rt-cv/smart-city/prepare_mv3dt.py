#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Prepare an experimental, fail-closed MV3DT package from measured evidence.

This does not enable MV3DT in the running application or qualify fused identities.
No homography-to-3D guess, default vehicle dimensions, or default clock alignment
is permitted. See README.md for the required handoff and qualification limits.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
from typing import Any

CLASSES = {"person": 0, "bicycle": 1, "car": 2, "motorcycle": 3, "bus": 4, "truck": 5}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def finite(value: Any, name: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{name}: finite number required")
    result = float(value)
    require(math.isfinite(result), f"{name}: finite number required")
    return result


def matrix(value: Any, rows: int, cols: int, name: str) -> list[list[float]]:
    require(isinstance(value, list), f"{name}: matrix required")
    if len(value) == rows * cols and all(isinstance(v, (float, int)) for v in value):
        value = [value[i * cols:(i + 1) * cols] for i in range(rows)]
    require(len(value) == rows and all(isinstance(row, list) and len(row) == cols for row in value),
            f"{name}: expected {rows} by {cols}")
    return [[finite(v, name) for v in row] for row in value]


def det3(a: list[list[float]]) -> float:
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))


def projection(camera: dict[str, Any]) -> list[list[float]]:
    if "projectionMatrix3x4" in camera:
        p = matrix(camera["projectionMatrix3x4"], 3, 4, "projectionMatrix3x4")
    else:
        k = matrix(camera.get("K"), 3, 3, "K")
        t = matrix(camera.get("T_cv_from_site"), 4, 4, "T_cv_from_site")
        require(k[0][0] > 0 and k[1][1] > 0 and abs(k[2][2] - 1) < 1e-8, "K: positive focal length / normalized pinhole matrix required")
        require(all(abs(t[3][j] - (1 if j == 3 else 0)) < 1e-8 for j in range(4)), "T_cv_from_site: invalid homogeneous row")
        r = [row[:3] for row in t[:3]]
        require(abs(det3(r) - 1) < 1e-4, "T_cv_from_site: rotation must have determinant +1")
        for a in range(3):
            for b in range(3):
                require(abs(sum(r[a][j] * r[b][j] for j in range(3)) - (1 if a == b else 0)) < 1e-4,
                        "T_cv_from_site: rotation is not orthonormal")
        p = [[sum(k[i][k_idx] * t[k_idx][j] for k_idx in range(3)) for j in range(4)] for i in range(3)]
    require(any(abs(det3([[row[j] for j in cols] for row in p])) > 1e-10 for cols in itertools.combinations(range(4), 3)),
            "Camera projection matrix has rank below three")
    return p


def validate(package: dict[str, Any], evidence: dict[str, Any], *, max_skew_ms: float = 50,
             max_error_px: float = 3, allow_fixtures: bool = False) -> dict[str, Any]:
    require(package.get("schemaVersion") == "city.mv3dt.preflight.v1", "MV3DT package schemaVersion required")
    require(package.get("units") == "metres" and package.get("axes") == "right-handed-x-y-ground-z-up",
            "MV3DT needs one explicit shared metre coordinate frame")
    site = package.get("siteId", "")
    require(isinstance(site, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]+", site)), "Safe nonempty siteId required")
    require(evidence.get("kind") in ("test-fixture", "source-clock-measurement", "simulator-common-capture-clock"), "Labeled timing evidence kind required")
    fixture = evidence.get("kind") == "test-fixture"
    capture_only = evidence.get("kind") == "simulator-common-capture-clock"
    require(not fixture or allow_fixtures, "Synthetic timing evidence is a test fixture; not a recording qualification")
    if capture_only:
        require(evidence.get("clockBasis") == "same-rendered-batch-unix-clock", "Explicit simulator capture clock required")
        require(package.get("cameraGeometryQualification") == "simulator-usd-gf-readout", "Capture-only diagnostics require the explicit simulator camera readout")
    else:
        require(evidence.get("clockBasis") in ("source-rtcp", "recorded-common-clock"), "Measured common source clock required")
    cameras = package.get("cameras", [])
    require(isinstance(cameras, list) and len(cameras) >= 2, "At least two overlapping calibrated cameras required")
    ids = [c.get("sourceId") for c in cameras]
    require(all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]+", v) for v in ids) and len(set(ids)) == len(ids),
            "Distinct safe camera source IDs required")
    dimensions = {(c.get("width"), c.get("height")) for c in cameras}
    require(len(dimensions) == 1, "Official MV3DT reference requires equal camera resolutions")
    require(all(isinstance(v, int) and v > 0 for v in next(iter(dimensions))), "Positive image dimensions required")
    pairs = evidence.get("pairs", [])
    require(isinstance(pairs, list) and len(pairs) >= 100, "At least 100 measured paired source timestamps required")
    largest_skew = 0.
    previous_times = {}
    for pair in pairs:
        require(set(pair) == set(ids), "Each timing sample must cover every camera ID")
        times = []
        for source_id in ids:
            value = pair[source_id]
            require(isinstance(value, str) and value.isdigit(), "Source nanoseconds must be integer strings")
            time_value = int(value)
            require(time_value > previous_times.get(source_id, -1), "Paired source timestamps must increase strictly")
            previous_times[source_id] = time_value
            times.append(time_value)
        largest_skew = max(largest_skew, (max(times) - min(times)) / 1e6)
    require(largest_skew <= max_skew_ms, f"Measured camera skew {largest_skew:.3f} ms exceeds {max_skew_ms} ms")
    geometry = package.get("classGeometry", [])
    require(isinstance(geometry, list), "Explicit per-class geometry required")
    by_class = {g.get("class"): g for g in geometry}
    require(set(by_class) == set(CLASSES) and len(geometry) == len(CLASSES), "Provide geometry for all six RF-DETR city output classes")
    for name, item in by_class.items():
        require(item.get("shape") == "cylinder", f"{name}: this generator supports the documented objectModelType=0 cylinder template only")
        require(finite(item.get("heightM"), name) > 0 and finite(item.get("radiusM"), name) > 0,
                f"{name}: positive measured geometry required")
        require(isinstance(item.get("provenance"), str) and item["provenance"].strip(), f"{name}: dimension provenance required")
        if name != "person":
            require(item.get("approximationAcknowledged") is True,
                    f"{name}: cylinder approximation must be acknowledged and subsequently evaluated")
    camera_results = []
    for camera in cameras:
        require(camera.get("calibrationRevision"), f"{camera['sourceId']}: calibration revision required")
        require(camera.get("lensModel") == "pinhole-rectified", "Rectified pinhole image geometry required")
        p = projection(camera)
        landmarks = camera.get("landmarks", [])
        require(len(landmarks) >= 6, "Six or more held-out 3D/image landmarks required")
        points = [matrix([l.get("worldM")], 1, 3, "worldM")[0] for l in landmarks]
        # Ground-only points cannot verify the vertical component of a 3x4 calibration.
        require(any(abs(det3([[points[b][j] - points[a][j] for j in range(3)],
                              [points[c][j] - points[a][j] for j in range(3)],
                              [points[d][j] - points[a][j] for j in range(3)]])) > 1e-6
                    for a, b, c, d in itertools.combinations(range(len(points)), 4)),
                "Held-out landmarks must span 3D; a ground homography alone is insufficient")
        errors = []
        for landmark, point in zip(landmarks, points):
            image = matrix([landmark.get("imagePx")], 1, 2, "imagePx")[0]
            q = [sum(row[j] * (point + [1.])[j] for j in range(4)) for row in p]
            require(q[2] > 1e-8, "Calibration landmark is behind the CV camera or unstable")
            errors.append(math.hypot(q[0] / q[2] - image[0], q[1] / q[2] - image[1]))
        require(max(errors) <= max_error_px, f"{camera['sourceId']}: held-out reprojection error exceeds {max_error_px} pixels")
        camera_results.append({"sourceId": camera["sourceId"], "projection": p, "maximumReprojectionErrorPx": max(errors)})
    overlap = package.get("overlapPolygonM", [])
    require(len(overlap) >= 3, "Explicit shared overlap polygon required")
    overlap = matrix(overlap, len(overlap), 2, "overlapPolygonM")
    area = abs(sum(overlap[i][0] * overlap[(i + 1) % len(overlap)][1] - overlap[(i + 1) % len(overlap)][0] * overlap[i][1]
                   for i in range(len(overlap)))) / 2
    require(area > 1e-6, "Overlap polygon must have positive area")
    width, height = next(iter(dimensions))
    for camera in camera_results:
        for x, y in overlap:
            point = [x, y, 0., 1.]
            q = [sum(row[j] * point[j] for j in range(4)) for row in camera["projection"]]
            require(q[2] > 1e-8 and 0 <= q[0] / q[2] <= width and 0 <= q[1] / q[2] <= height,
                    "Claimed overlap polygon is not visible in every calibrated camera")
    return {"siteId": site, "cameras": camera_results, "geometry": by_class,
            "maximumSourceSkewMs": largest_skew, "fixtureOnly": fixture, "overlapAreaM2": area,
            "diagnosticOnly": capture_only or fixture, "transportClockQualified": not capture_only and not fixture}


def prepare(package: dict[str, Any], evidence: dict[str, Any], output: Path, *, container_root: str = "/opt/city/mv3dt",
            broker: str = "vss-city-mqtt", port: int = 1883, allow_fixtures: bool = False,
            tracker_resolution: tuple[int, int] | None = None) -> dict[str, Any]:
    result = validate(package, evidence, allow_fixtures=allow_fixtures)
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", broker)) and 1 <= port <= 65535, "Valid MQTT broker host/port required")
    require(container_root.startswith("/") and "\n" not in container_root and '"' not in container_root,
            "Absolute controlled container root required")
    output.mkdir(parents=True, exist_ok=True)
    if tracker_resolution is not None:
        require(len(tracker_resolution) == 2 and all(type(value) is int and 1 <= value <= 16384 for value in tracker_resolution),
                "Explicit positive tracker width/height required")
    paths = []
    for index, camera in enumerate(result["cameras"]):
        name = f"camera-{index}.yml";paths.append(f"{container_root}/{name}")
        projection_matrix = camera["projection"]
        if tracker_resolution is not None:
            source = package["cameras"][index]
            scales = [tracker_resolution[0] / source["width"], tracker_resolution[1] / source["height"], 1.]
            projection_matrix = [[value * scales[row] for value in values] for row, values in enumerate(projection_matrix)]
        text = "projectionMatrix_3x4_w2p:\n" + "".join(f"  - {v:.17g}\n" for row in projection_matrix for v in row)
        text += "modelInfo:\n"
        for cls, class_id in CLASSES.items():
            g = result["geometry"][cls]
            text += f"  - classID: {class_id}\n    height: {g['heightM']:.17g}\n    radius: {g['radiusM']:.17g}\n"
        (output / name).write_text(text)
    ids = [c["sourceId"] for c in result["cameras"]]
    # MV3DT 9.2's communicator takes host:port;topic, not the lower-level
    # MQTT adaptor's host;port;topic connection string.
    topics = [f"{broker}:{port};ct-city/{result['siteId']}/{source_id}" for source_id in ids]
    peer = {"pubBrokerTopicStr": topics, "subPeerBrokerTopicStrs": [[topic for j, topic in enumerate(topics) if j != i] for i in range(len(ids))]}
    # JSON is a YAML subset, accepted by yaml-cpp; quote all broker/topic strings.
    (output / "pub-sub.yml").write_text(json.dumps(peer, indent=2) + "\n")
    (output / "mqtt.ini").write_text("[message-broker]\nset-threaded=0\n# Add broker credentials through deployment secrets when required.\n")
    base = (Path(__file__).parent / "configs" / "tracker.yml").read_text()
    base = base.replace("stateEstimatorType: 1", "stateEstimatorType: 3").replace("useUniqueID: 1", "useUniqueID: 0")
    base = base.replace("TargetManagement:\n", "TargetManagement:\n  outputVisibility: 1\n")
    base += "\nObjectModelProjection:\n  objectModelType: 0\n  outputFootLocation: 1\n  outputVisibility: 1\n  cameraModelFilepath:\n"
    base += "".join(f"    - {json.dumps(path)}\n" for path in paths)
    base += f"""MultiViewAssociator:
  multiViewAssociatorType: 1
  enableLatePeerReAssoc: 1
  enableIDCorrection: 1
  enableSeeThrough: 1
  enableMsgSync: 1
Communicator:
  communicatorType: 2
  pubSubInfoConfigPath: {container_root}/pub-sub.yml
  mqttProtoAdaptorConfigPath: {container_root}/mqtt.ini
PoseEstimator:
  poseEstimatorType: 0
"""
    (output / "tracker-mv3dt.experimental.yml").write_text(base)
    manifest = {"schemaVersion": "city.mv3dt.prepared.v1", "siteId": result["siteId"], "enabled": False,
                "runtimeQualified": False, "fixtureOnly": result["fixtureOnly"], "cameraOrder": ids,
                "diagnosticOnly": result["diagnosticOnly"], "transportClockQualified": result["transportClockQualified"],
                "trackerInputResolution": list(tracker_resolution) if tracker_resolution else None,
                "maximumSourceSkewMs": result["maximumSourceSkewMs"],
                "maximumReprojectionErrorPx": max(c["maximumReprojectionErrorPx"] for c in result["cameras"]),
                "poseEnabled": False, "vehicleGeometry": "acknowledged cylinder approximation; must be evaluated",
                "inputSha256": hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest(),
                "timingEvidenceSha256": hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
                "remainingGates": ["Run the paired recordings with the native tracker and MQTT broker",
                    "Verify fused IDs, calibration, occlusions and per-class position error against held-out ground truth",
                    "Compare IDF1/HOTA, duplicate IDs and compute cost against calibrated association",
                    "Validate fused-ID/3D metadata adapter before enabling global identities in the UI"]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("timing_evidence", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--container-root", default="/opt/city/mv3dt")
    parser.add_argument("--mqtt-host", default="vss-city-mqtt")
    parser.add_argument("--mqtt-port", default=1883, type=int)
    parser.add_argument("--allow-test-fixtures", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare(json.loads(args.package.read_text()), json.loads(args.timing_evidence.read_text()), args.output,
                         container_root=args.container_root, broker=args.mqtt_host, port=args.mqtt_port,
                         allow_fixtures=args.allow_test_fixtures)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"MV3DT preparation stopped: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
