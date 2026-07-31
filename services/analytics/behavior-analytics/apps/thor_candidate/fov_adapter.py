# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Normalize RT-CV object metadata into the standard FOV aggregate."""

from mdx.analytics.core.schema.proto import schema_pb2 as nvSchema


def ensure_fov_metric(frame: nvSchema.Frame, target_object_type: str) -> None:
    """Populate the standard FOV metric from detected objects when it is absent.

    RT-CV already performs detection and tracking on Thor. Its ``mdx-raw``
    frames contain ``frame.objects`` but do not include the aggregate
    ``frame.fov`` metric consumed by ``FrameStateMgmt``. This adapter derives
    only that missing aggregate, preserving any producer-supplied metric and
    avoiding a second detector.

    :param frame: Frame to normalize in place.
    :param target_object_type: Configured object class to count.
    """
    target_key = target_object_type.casefold()
    for metric in frame.fov:
        if metric.type.casefold() == target_key:
            metric.type = target_object_type
            return

    object_ids = [obj.id for obj in frame.objects if obj.type.casefold() == target_key and obj.id]
    if not object_ids:
        return

    metric = frame.fov.add()
    metric.type = target_object_type
    metric.count = len(object_ids)
    metric.objectIds.extend(object_ids)
