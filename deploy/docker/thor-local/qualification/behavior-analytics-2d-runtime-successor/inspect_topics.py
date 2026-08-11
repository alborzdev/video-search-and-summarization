#!/usr/bin/env python3
"""Consume qualification-only Behavior Analytics topics and summarize protobufs."""

from __future__ import annotations

from collections import Counter
import json
import sys
import time

from confluent_kafka import Consumer
from mdx.analytics.core.schema.proto import ext_pb2, schema_pb2


TOPICS = {
    "vss-oracle-ba-behavior": ext_pb2.Behavior,
    "vss-oracle-ba-frames": schema_pb2.Frame,
    "vss-oracle-ba-events": ext_pb2.Behavior,
    "vss-oracle-ba-incidents": ext_pb2.Incident,
}


def main() -> int:
    consumer = Consumer({
        "bootstrap.servers": "localhost:9092",
        "group.id": "vss-oracle-ba-inspector",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe(list(TOPICS))
    counts: Counter[str] = Counter()
    sensors: dict[str, set[str]] = {topic: set() for topic in TOPICS}
    event_types: Counter[str] = Counter()
    incident_categories: Counter[str] = Counter()
    behavior_points = 0
    behavior_identity_keys: set[str] = set()
    trajectories_with_multiple_points = 0
    max_trajectory_points = 0
    frame_objects = 0
    fov_metric_entries = 0
    fov_positive_count_entries = 0
    roi_metric_entries = 0
    roi_positive_count_entries = 0
    proximity_detection_total = 0
    cluster_entries = 0
    last_message_at = time.monotonic()
    deadline = last_message_at + 60
    try:
        while time.monotonic() < deadline:
            message = consumer.poll(1.0)
            if message is None:
                if counts and time.monotonic() - last_message_at >= 5:
                    break
                continue
            if message.error():
                raise RuntimeError(str(message.error()))
            topic = message.topic()
            value = TOPICS[topic]()
            value.ParseFromString(message.value())
            counts[topic] += 1
            last_message_at = time.monotonic()
            if topic == "vss-oracle-ba-frames":
                sensors[topic].add(value.sensorId)
                frame_objects += len(value.objects)
                fov_metric_entries += len(value.fov)
                fov_positive_count_entries += sum(metric.count > 0 for metric in value.fov)
                roi_metric_entries += len(value.rois)
                roi_positive_count_entries += sum(metric.count > 0 for metric in value.rois)
                proximity_detection_total += value.socialDistancing.proximityDetections
                cluster_entries += len(value.socialDistancing.clusters)
            elif topic == "vss-oracle-ba-incidents":
                sensors[topic].add(value.sensorId)
                incident_categories[value.category] += 1
            else:
                sensors[topic].add(value.sensor.id)
                point_count = len(value.locations.coordinates)
                behavior_points += point_count
                behavior_identity_keys.add(f"{value.sensor.id}:{value.object.id}")
                trajectories_with_multiple_points += point_count > 1
                max_trajectory_points = max(max_trajectory_points, point_count)
                if topic == "vss-oracle-ba-events":
                    event_types[f"{value.event.info.get('class', '')}:{value.event.type}"] += 1
    finally:
        consumer.close()
    result = {
        "counts": {topic: counts[topic] for topic in sorted(TOPICS)},
        "sensors": {topic: sorted(sensors[topic]) for topic in sorted(TOPICS)},
        "event_types": dict(sorted(event_types.items())),
        "incident_categories": dict(sorted(incident_categories.items())),
        "behavior_location_points": behavior_points,
        "behavior_identity_count": len(behavior_identity_keys),
        "trajectories_with_multiple_points": trajectories_with_multiple_points,
        "max_trajectory_points": max_trajectory_points,
        "frame_objects": frame_objects,
        "fov_metric_entries": fov_metric_entries,
        "fov_positive_count_entries": fov_positive_count_entries,
        "roi_metric_entries": roi_metric_entries,
        "roi_positive_count_entries": roi_positive_count_entries,
        "proximity_detection_total": proximity_detection_total,
        "cluster_entries": cluster_entries,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if all(counts[topic] > 0 for topic in TOPICS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
