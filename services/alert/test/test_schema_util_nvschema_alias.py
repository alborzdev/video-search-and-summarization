# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NvSchema Incident compatibility tests for the documented field-7 alias."""

from copy import deepcopy
from pathlib import Path

import pytest

from utils.schema_util import convert_incident_to_protobuf_incident


def _analytics(identifier: str = "thor-local-analytics") -> dict:
    return {"id": identifier, "info": {"source": "thor-local"}}


def test_documented_analytics_alias_survives_protobuf_roundtrip() -> None:
    payload = {
        "sensorId": "thor-camera-1",
        "analytics": _analytics(),
        "category": "entry",
    }
    original = deepcopy(payload)

    message = convert_incident_to_protobuf_incident(payload)
    encoded = message.SerializeToString(deterministic=True)
    decoded = type(message)()
    decoded.ParseFromString(encoded)

    assert payload == original
    assert decoded.sensorId == "thor-camera-1"
    assert decoded.analyticsModule.id == "thor-local-analytics"
    assert decoded.analyticsModule.info["source"] == "thor-local"
    assert decoded.DESCRIPTOR.fields_by_name["analyticsModule"].number == 7


def test_released_wire_name_remains_supported() -> None:
    message = convert_incident_to_protobuf_incident(
        {"sensorId": "thor-camera-2", "analyticsModule": _analytics("wire-name")}
    )

    assert message.analyticsModule.id == "wire-name"


def test_identical_documented_and_wire_values_are_accepted() -> None:
    value = _analytics("same-value")
    message = convert_incident_to_protobuf_incident(
        {"analytics": deepcopy(value), "analyticsModule": deepcopy(value)}
    )

    assert message.analyticsModule.id == "same-value"


def test_conflicting_documented_and_wire_values_fail_closed() -> None:
    with pytest.raises(ValueError, match="must be identical"):
        convert_incident_to_protobuf_incident(
            {
                "analytics": _analytics("documented"),
                "analyticsModule": _analytics("wire"),
            }
        )


def test_documented_alias_is_not_silently_dropped_with_unknown_fields_allowed() -> None:
    message = convert_incident_to_protobuf_incident(
        {
            "analytics": _analytics("preserved"),
            "futureExtension": {"ignored": True},
        },
        ignore_unknown_fields=True,
    )

    assert message.analyticsModule.id == "preserved"


def test_thor_alert_derivative_installs_the_compatibility_converter() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    dockerfile = (
        repo_root / "deploy/docker/thor-local/Dockerfile.alert-bridge"
    ).read_text()

    assert (
        "COPY services/alert/utils/schema_util.py /app/utils/schema_util.py"
        in dockerfile
    )
