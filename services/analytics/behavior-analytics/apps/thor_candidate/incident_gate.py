# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bound candidate notifications to one incident per continuous activity."""

from typing import TypeVar

T = TypeVar("T")


def first_incident_per_activity(
    sensor_id: str,
    incidents: list[T],
    activity_active: bool,
    reported_sensors: set[str],
) -> list[T]:
    """Return at most one incident for a continuous sensor activity.

    The shared behavior state manager intentionally reports updated active
    incidents as their end time advances. A verifier needs one bounded
    candidate instead, so remember the active activity until it expires.

    :param sensor_id: Sensor owning the candidate activity.
    :param incidents: Incidents reported by the shared state manager.
    :param activity_active: Whether the FOV violation remains active.
    :param reported_sensors: Mutable set of sensors already reported.
    :return: Zero or one incident for downstream verification.
    """
    if activity_active:
        if not incidents or sensor_id in reported_sensors:
            return []
        reported_sensors.add(sensor_id)
        return incidents[:1]

    was_reported = sensor_id in reported_sensors
    reported_sensors.discard(sensor_id)
    if was_reported:
        return []
    return incidents[:1]


def gate_fov_incidents(
    sensor_id: str,
    incidents: list[T],
    activity_active: bool,
    reported_sensors: set[str],
) -> list[T]:
    """Bound generic FOV notifications while retaining authored rule events.

    Always drain the state manager's complete incident list. Area/proximity
    events must pass through even while a previously reported person remains
    visible, and completed states must be consumed regularly.
    """
    fov_incidents = [incident for incident in incidents
                     if getattr(incident, "category", None) == "FOV Count Violation"]
    rule_incidents = [incident for incident in incidents
                      if getattr(incident, "category", None) != "FOV Count Violation"]
    return rule_incidents + first_incident_per_activity(
        sensor_id, fov_incidents, activity_active, reported_sensors,
    )
