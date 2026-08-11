#!/usr/bin/env python3
"""Exercise the complete 2D Behavior Analytics pipeline in one released-image run."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

from google.protobuf.json_format import ParseDict


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "services/analytics/behavior-analytics/src"))
HELPER_PATH = REPO / "deploy/docker/thor-local/qualification/behavior-analytics-broker-control-runtime-successor/run_broker_probe.py"
SPEC = importlib.util.spec_from_file_location("behavior_pipeline_helper", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

from mdx.analytics.core.schema.proto import ext_pb2, schema_pb2  # noqa: E402


INPUT: dict[str, Any] = {}
ORIGINAL_OUTPUT_SUMMARY = helper._output_summary


def _publish_pipeline_frames(transport: Any, fixture: Path, count: int, fps: int) -> None:
    base_ms = int(time.time() * 1000) - 1000
    published = 0
    objects = 0
    bbox_objects = 0
    tracking_id_objects = 0
    embedded_objects = 0
    embedding_dimensions: set[int] = set()
    embedding_finite = True
    sensors: set[str] = set()
    with fixture.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            frame = ParseDict(json.loads(line), schema_pb2.Frame(), ignore_unknown_fields=False)
            frame.timestamp.FromMilliseconds(base_ms + int(published * 1000 / fps))
            sensors.add(frame.sensorId)
            for obj in frame.objects:
                objects += 1
                if (
                    obj.HasField("bbox")
                    and obj.bbox.rightX > obj.bbox.leftX
                    and obj.bbox.bottomY > obj.bbox.topY
                ):
                    bbox_objects += 1
                if obj.id:
                    tracking_id_objects += 1
                seed = (sum(obj.id.encode("utf-8")) % 97) / 97.0
                vector = [1.0, seed, 1.0 - seed, 0.5]
                obj.confidence = 0.99
                obj.embedding.vector.extend(vector)
                embedded_objects += 1
                embedding_dimensions.add(len(obj.embedding.vector))
                embedding_finite = embedding_finite and all(math.isfinite(value) for value in vector)
            transport.publish("raw", frame.sensorId.encode("utf-8"), frame.SerializeToString(), {})
            published += 1
            if published >= count:
                break
    if published != count:
        raise RuntimeError(f"fixture contained only {published} frames")
    INPUT.update({
        "frames": published,
        "objects": objects,
        "sensors": sorted(sensors),
        "bbox_objects": bbox_objects,
        "tracking_id_objects": tracking_id_objects,
        "embedded_objects": embedded_objects,
        "embedding_dimensions": sorted(embedding_dimensions),
        "embedding_finite": embedding_finite,
    })


def _pipeline_output_summary(transport: Any) -> dict[str, Any]:
    summary = ORIGINAL_OUTPUT_SUMMARY(transport)
    behaviors = []
    for record in transport.records("behavior"):
        value = ext_pb2.Behavior()
        try:
            value.ParseFromString(record["value"])
        except Exception:
            continue
        behaviors.append(value)
    frames = []
    for record in transport.records("frames"):
        value = schema_pb2.Frame()
        try:
            value.ParseFromString(record["value"])
        except Exception:
            continue
        frames.append(value)
    vectors = [embedding.vector for behavior in behaviors for embedding in behavior.embeddings]
    summary.update({
        "behavior_identity_count": len({(value.sensor.id, value.object.id) for value in behaviors}),
        "behaviors_with_locations": sum(bool(value.locations.coordinates) for value in behaviors),
        "behaviors_with_embeddings": sum(bool(value.embeddings) for value in behaviors),
        "behavior_embedding_dimensions": sorted({len(vector) for vector in vectors}),
        "behavior_embeddings_finite": all(
            math.isfinite(component) for vector in vectors for component in vector
        ),
        "enhanced_frame_objects": sum(len(value.objects) for value in frames),
        "positive_fov_metric_entries": sum(
            metric.count > 0 for value in frames for metric in value.fov
        ),
        "positive_roi_metric_entries": sum(
            metric.count > 0 for value in frames for metric in value.rois
        ),
    })
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    helper._publish_frames = _publish_pipeline_frames
    helper._output_summary = _pipeline_output_summary
    result = helper._run_probe(args)
    outputs = result["outputs"]
    if not INPUT or INPUT["objects"] <= 0:
        raise RuntimeError("pipeline input contract was not observed")
    for name in ("bbox_objects", "tracking_id_objects", "embedded_objects"):
        if INPUT[name] != INPUT["objects"]:
            raise RuntimeError(f"not every input object satisfied {name}: {INPUT}")
    if INPUT["embedding_dimensions"] != [4] or not INPUT["embedding_finite"]:
        raise RuntimeError(f"input embedding contract drifted: {INPUT}")
    if outputs["behaviors_with_embeddings"] <= 0:
        raise RuntimeError(f"embedding did not reach behavior state: {outputs}")
    if outputs["behavior_embedding_dimensions"] != [4] or not outputs["behavior_embeddings_finite"]:
        raise RuntimeError(f"output embedding contract drifted: {outputs}")
    if outputs["behaviors_with_locations"] <= 0:
        raise RuntimeError(f"coordinate transform did not reach behavior output: {outputs}")
    if outputs["positive_fov_metric_entries"] <= 0 or outputs["positive_roi_metric_entries"] <= 0:
        raise RuntimeError(f"ROI/FOV metrics were not positive: {outputs}")
    result["input_contract"] = dict(INPUT)
    result["stage_coverage"] = {
        "dynamic-config": result["ack_status"] == "success" and outputs["max_behavior_points"] == 3,
        "calibration": result["dynamic_calibration_version"] == "qualification-kafka-2.0",
        "coordinate-transform": outputs["behaviors_with_locations"] > 0,
        "roi": outputs["positive_roi_metric_entries"] > 0,
        "behavior-state": outputs["behaviors"] > 0 and outputs["behavior_identity_count"] > 0,
        "metrics": outputs["positive_fov_metric_entries"] > 0 and outputs["positive_roi_metric_entries"] > 0,
        "bbox": INPUT["bbox_objects"] == INPUT["objects"],
        "tracking": INPUT["tracking_id_objects"] == INPUT["objects"],
        "embedding": outputs["behaviors_with_embeddings"] > 0,
    }
    if not all(result["stage_coverage"].values()):
        raise RuntimeError(f"pipeline stage coverage drifted: {result['stage_coverage']}")
    normal_containers = {}
    for name in ("vss-behavior-analytics", "vss-behavior-analytics-thor-candidates"):
        inspected = json.loads(helper._run("docker", "inspect", name).stdout)[0]
        normal_containers[name] = {
            "running": inspected["State"]["Running"],
            "oom_killed": inspected["State"]["OOMKilled"],
            "restart_count": inspected["RestartCount"],
        }
    expected_normal = {"running": True, "oom_killed": False, "restart_count": 0}
    if not all(value == expected_normal for value in normal_containers.values()):
        raise RuntimeError(f"normal Behavior Analytics containers drifted: {normal_containers}")
    result["cleanup"]["normal_behavior_containers"] = normal_containers
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--frame-count", type=int, default=600)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--output-timeout", type=float, default=90)
    parsed = parser.parse_args()
    args = argparse.Namespace(backend="kafka", **vars(parsed))
    try:
        print(json.dumps(run(args), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
