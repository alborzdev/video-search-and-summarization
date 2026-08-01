#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Execute deterministic, provider-free Behavior Analytics product logic."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import threading
import types
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

from google.protobuf.timestamp_pb2 import Timestamp
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
PRODUCT_SRC = REPO_ROOT / "services/analytics/behavior-analytics/src"
ACCEPTANCE_PATH = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
CAPABILITY_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLE_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
MAX_JSON_BYTES = 4 * 1024 * 1024
sys.dont_write_bytecode = True

EXPECTED_POLICY = {
    "candidate_only": True,
    "advances_live_acceptance": False,
    "can_mark_passed_current": False,
    "runtime_evidence": [],
    "network_allowed": False,
    "docker_allowed": False,
    "subprocess_allowed": False,
    "service_lifecycle_allowed": False,
    "downloads_allowed": False,
    "credentials_allowed": False,
    "warehouse_sample_bundle": "excluded",
    "writes": "none",
}
EXPECTED_BINDINGS = {
    "systems-behavior-pipeline": "runtime.behavior.pipeline",
    "systems-behavior-dynamic-config": "configuration.behavior.dynamic-update",
    "systems-behavior-calibration": "calibration.behavior.dynamic",
    "systems-behavior-events": "runtime.behavior.events-incidents",
    "systems-behavior-embedding-downsampling": "runtime.behavior.embedding-downsampling",
    "systems-behavior-sinks": "protocol.behavior.broker-sinks",
}
EXPECTED_PLANNING_STATE = {
    planning_id: (planning_id == "systems-behavior-dynamic-config")
    for planning_id in EXPECTED_BINDINGS
}
EXPECTED_CAPABILITY_CONTRACTS = {
    "runtime.behavior.pipeline": {
        "inputs": ["bbox", "tracking", "embedding"],
        "stages": [
            "dynamic-config",
            "calibration",
            "coordinate-transform",
            "roi",
            "behavior-state",
            "metrics",
        ],
    },
    "configuration.behavior.dynamic-update": {
        "ack_every_update": True,
        "atomic_persist": True,
        "event_types": ["upsert", "upsert-all", "ack", "request-config"],
        "key": "behavior-analytics-config",
        "startup_timeout_seconds": 15,
        "statuses": ["success", "partial-success", "failure"],
        "timeout_fallback": "disk-baseline",
        "topic": "mdx-notification",
    },
    "calibration.behavior.dynamic": {
        "acknowledgement": False,
        "default_type": "image",
        "event_types": ["upsert", "upsert-all", "delete"],
        "existing_file_type_switch": False,
        "invalid_payload_changes_live_state": False,
        "key": "calibration",
        "types": ["image", "cartesian", "geo"],
    },
    "runtime.behavior.events-incidents": {
        "events": ["tripwire", "roi"],
        "violations": [
            "proximity",
            "restricted-area",
            "confined-area",
            "fov-count",
        ],
    },
    "runtime.behavior.embedding-downsampling": {
        "modes": ["sdt", "sliding-window"],
        "optional": True,
    },
    "protocol.behavior.broker-sinks": {
        "outputs": [
            "frames",
            "behaviors",
            "events",
            "incidents",
            "anomalies",
            "cluster",
            "space-utilization",
        ],
        "sink_types": ["kafka", "redisStream", "mqtt"],
    },
}
EXPECTED_CASE_OUTCOMES = {
    "config-non-object": "rejected",
    "config-read-only-section": "rejected",
    "config-invalid-value": "rejected",
    "calibration-invalid-type": "rejected",
    "calibration-unknown-action": "rejected",
    "calibration-existing-file-reload": "delegated_without_type_switch",
    "event-empty-identifier": "ignored_without_mutation",
    "embedding-invalid-record": "filtered",
    "sink-unsupported-type": "rejected",
    "sink-missing-route": "rejected",
}
OUTPUT_ROUTE_MAP = {
    "frames": "frames",
    "behaviors": "behavior",
    "events": "events",
    "incidents": "incidents",
    "anomalies": "anomaly",
    "cluster": "behaviorPlus",
    "space-utilization": "spaceUtilization",
}
EXPECTED_BINDINGS_SHA256 = (
    "5bfaeec23c6317a076e3f370fa9571fb2d215159b179fa217e5f83c31fc0864e"
)
EXPECTED_SOURCE_LOCKS_SHA256 = (
    "4c8b3a2e6e0c37be7ff1b998e767513be6fd6aa031a3fc8b7bee2e8acbdb1071"
)
PRODUCT_MODULE_PREFIXES = ("mdx",)
DEPENDENCY_STUB_NAMES = {
    "omegaconf",
    "matplotlib",
    "matplotlib.path",
    "watchdog",
    "watchdog.events",
    "watchdog.observers",
    "redis",
    "confluent_kafka",
    "pyproj",
    "shapely",
    "shapely.geometry",
}


class QualificationError(RuntimeError):
    """A lock, policy, or deterministic product observation failed closed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise QualificationError(f"not a regular non-symlink JSON file: {path}")
        if metadata.st_size > MAX_JSON_BYTES:
            raise QualificationError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise QualificationError(f"opened JSON is not a regular file: {path}")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_JSON_BYTES:
            raise QualificationError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationError(f"non-finite JSON number: {token}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root must be an object: {path}")
    return value


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    unresolved = root / candidate
    metadata = unresolved.lstat()
    if unresolved.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(f"repository path is not a regular file: {relative}")
    path = unresolved.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"repository path escaped: {relative}") from exc
    return path


def _find_one(rows: Any, key: str, expected: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise QualificationError(f"row set for {expected} is not an array")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get(key) == expected
    ]
    if len(matches) != 1:
        raise QualificationError(f"expected exactly one {key}={expected}")
    return matches[0]


def _load_contract(path: Path = LANE / "contract.json") -> dict[str, Any]:
    if path.resolve(strict=True) != (LANE / "contract.json").resolve(strict=True):
        raise QualificationError("only the lane-owned contract may be executed")
    schema = _strict_json(LANE / "contract.schema.json")
    Draft202012Validator.check_schema(schema)
    contract = _strict_json(path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(contract),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise QualificationError(f"invalid contract: {errors[0].message}")
    if contract["policy"] != EXPECTED_POLICY:
        raise QualificationError("candidate-only policy drift")
    if [row["planning_requirement_id"] for row in contract["bindings"]] != list(
        EXPECTED_BINDINGS
    ):
        raise QualificationError("binding denominator or ordering drift")
    if _sha256(_canonical_bytes(contract["bindings"])) != EXPECTED_BINDINGS_SHA256:
        raise QualificationError("exact binding lock drift")
    if (
        _sha256(_canonical_bytes(contract["source_locks"]))
        != EXPECTED_SOURCE_LOCKS_SHA256
    ):
        raise QualificationError("exact source-lock set drift")
    if contract["adjacent_case_ids"] != list(EXPECTED_CASE_OUTCOMES):
        raise QualificationError("adjacent-case denominator drift")
    return contract


def _verify_source_locks(contract: dict[str, Any]) -> dict[str, str]:
    locks = contract["source_locks"]
    if len({row["path"] for row in locks}) != 75:
        raise QualificationError("source lock paths are not exactly 75 unique files")
    observed: dict[str, str] = {}
    for row in locks:
        digest = _sha256(_repo_file(row["path"]).read_bytes())
        if digest != row["sha256"]:
            raise QualificationError(f"source lock mismatch: {row['path']}")
        observed[row["path"]] = digest
    return observed


def _verify_bindings(contract: dict[str, Any]) -> list[dict[str, Any]]:
    acceptance = _strict_json(_repo_file(ACCEPTANCE_PATH))
    official = _strict_json(_repo_file(CAPABILITY_PATH))
    oracle_set = _strict_json(_repo_file(ORACLE_PATH))
    observations: list[dict[str, Any]] = []
    for binding in contract["bindings"]:
        planning_id = binding["planning_requirement_id"]
        capability_id = binding["capability_id"]
        if EXPECTED_BINDINGS.get(planning_id) != capability_id:
            raise QualificationError("planning/capability identity drift")
        planning = _find_one(
            acceptance["wave3_contracts"]["planning_requirements"],
            "id",
            planning_id,
        )
        if (
            planning.get("owner_type") != "capability"
            or planning.get("owner_id") != capability_id
            or planning.get("package") != "systems"
        ):
            raise QualificationError("planning ownership drift")
        expected_materialized = EXPECTED_PLANNING_STATE[planning_id]
        if (
            planning.get("materialized") is not expected_materialized
            or planning.get("executor_ready") is not expected_materialized
            or planning.get("runtime_evidence") != []
        ):
            raise QualificationError("canonical planning state drifted")
        if (
            _sha256(_canonical_bytes(planning))
            != binding["planning_requirement_sha256"]
        ):
            raise QualificationError("planning requirement digest drift")
        if (
            planning.get("payload_canonical_sha256")
            != binding["planning_payload_sha256"]
        ):
            raise QualificationError("planning payload digest drift")
        capability = _find_one(official["capabilities"], "id", capability_id)
        if _sha256(_canonical_bytes(capability)) != binding["capability_sha256"]:
            raise QualificationError("capability digest drift")
        if (
            capability.get("acceptance_class") != "required_local"
            or capability.get("thor_state") != "partial"
            or capability.get("runtime_state") != "not_qualified"
        ):
            raise QualificationError("canonical capability state advanced")
        wave = capability.get("contract", {}).get("wave3_acceptance", {})
        observed_contract = deepcopy(capability.get("contract", {}))
        observed_contract.pop("wave3_acceptance", None)
        if observed_contract != EXPECTED_CAPABILITY_CONTRACTS[capability_id]:
            raise QualificationError("capability contract drift")
        if (
            wave.get("executor_ready") is not False
            or wave.get("materialized") is not False
            or wave.get("package") != "systems"
            or wave.get("planning_requirement_ids") != [planning_id]
        ):
            raise QualificationError("wave-3 binding drift")
        oracle = _find_one(oracle_set["oracles"], "oracle_id", binding["oracle_id"])
        if (
            oracle.get("capability_id") != capability_id
            or _sha256(_canonical_bytes(oracle)) != binding["oracle_sha256"]
        ):
            raise QualificationError("oracle binding or digest drift")
        if (
            oracle.get("current_state") != "open_unexecuted"
            or oracle.get("evidence") != []
            or oracle.get("acceptance_readiness", {}).get("classification")
            != "planning_index_only"
        ):
            raise QualificationError("canonical oracle state advanced")
        observations.append(
            {
                "planning_requirement_id": planning_id,
                "capability_id": capability_id,
                "oracle_id": binding["oracle_id"],
                "owner_type": "capability",
                "package": "systems",
                "acceptance_class": "required_local",
                "thor_state": "partial",
                "runtime_state": "not_qualified",
                "oracle_state": "open_unexecuted",
                "oracle_classification": "planning_index_only",
                "planning_materialized": expected_materialized,
                "planning_executor_ready": expected_materialized,
                "canonical_state_advanced": False,
            }
        )
    return observations


def _install_dependency_stubs() -> None:
    """Install import-only stubs; every external constructor fails closed."""

    omegaconf = types.ModuleType("omegaconf")
    omegaconf.MISSING = "???"

    matplotlib = types.ModuleType("matplotlib")
    matplotlib_path = types.ModuleType("matplotlib.path")
    matplotlib_path.Path = type("ImportOnlyPath", (), {})
    matplotlib.path = matplotlib_path

    watchdog = types.ModuleType("watchdog")
    watchdog_events = types.ModuleType("watchdog.events")
    watchdog_events.FileSystemEvent = type("FileSystemEvent", (), {})
    watchdog_events.FileSystemEventHandler = type("FileSystemEventHandler", (), {})
    watchdog_observers = types.ModuleType("watchdog.observers")

    class ForbiddenObserver:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise QualificationError("watchdog lifecycle is forbidden")

    watchdog_observers.Observer = ForbiddenObserver
    watchdog.events = watchdog_events
    watchdog.observers = watchdog_observers

    redis = types.ModuleType("redis")

    class ForbiddenRedis:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise QualificationError("Redis connection is forbidden")

    redis.Redis = ForbiddenRedis

    confluent = types.ModuleType("confluent_kafka")

    class ForbiddenProducer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise QualificationError("Kafka connection is forbidden")

    confluent.Producer = ForbiddenProducer

    pyproj = types.ModuleType("pyproj")

    class ForbiddenTransformer:
        @classmethod
        def from_crs(cls, *_args: Any, **_kwargs: Any) -> None:
            raise QualificationError("coordinate CRS provider is outside this tranche")

    pyproj.Transformer = ForbiddenTransformer

    shapely = types.ModuleType("shapely")
    shapely_geometry = types.ModuleType("shapely.geometry")
    shapely_geometry.LineString = type("ImportOnlyLineString", (), {})
    shapely_geometry.Point = type("ImportOnlyPoint", (), {})
    shapely.geometry = shapely_geometry

    sys.modules.update(
        {
            "omegaconf": omegaconf,
            "matplotlib": matplotlib,
            "matplotlib.path": matplotlib_path,
            "watchdog": watchdog,
            "watchdog.events": watchdog_events,
            "watchdog.observers": watchdog_observers,
            "redis": redis,
            "confluent_kafka": confluent,
            "pyproj": pyproj,
            "shapely": shapely,
            "shapely.geometry": shapely_geometry,
        }
    )


def _load_product() -> dict[str, Any]:
    product_text = str(PRODUCT_SRC)
    if product_text not in sys.path:
        sys.path.insert(0, product_text)
    _install_dependency_stubs()

    from mdx.analytics.core.schema import config as config_schema
    from mdx.analytics.core.schema import models
    from mdx.analytics.core.schema.proto import schema_pb2
    from mdx.analytics.core.stream.sink import sink_base, sink_factory
    from mdx.analytics.core.stream.state.behavior import state_management_base
    from mdx.analytics.core.stream.state.frame import frame_state_management
    from mdx.analytics.core.stream.state.video_embedding import (
        video_embedding_state_mgmt,
    )
    from mdx.analytics.core.transform.calibration import (
        calibration_base,
        calibration_dynamic,
        calibration_validator,
    )
    from mdx.analytics.core.transform.config import config_applier, config_validator
    from mdx.analytics.core.transform.event import roi_event, tripwire_event

    return {
        "config": config_schema,
        "models": models,
        "proto": schema_pb2,
        "sink_base": sink_base,
        "sink_factory": sink_factory,
        "behavior_state": state_management_base,
        "frame_state": frame_state_management,
        "embedding_state": video_embedding_state_mgmt,
        "calibration_base": calibration_base,
        "calibration_dynamic": calibration_dynamic,
        "calibration_validator": calibration_validator,
        "config_applier": config_applier,
        "config_validator": config_validator,
        "roi_event": roi_event,
        "tripwire_event": tripwire_event,
    }


def _is_isolated_module(name: str) -> bool:
    return name in DEPENDENCY_STUB_NAMES or any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in PRODUCT_MODULE_PREFIXES
    )


@contextmanager
def _isolated_product() -> Iterator[dict[str, Any]]:
    """Load fresh product modules and restore the caller's import state."""
    original_path = list(sys.path)
    preserved = {
        name: module
        for name, module in sys.modules.items()
        if _is_isolated_module(name)
    }
    try:
        for name in list(sys.modules):
            if _is_isolated_module(name):
                sys.modules.pop(name, None)
        yield _load_product()
    finally:
        for name in list(sys.modules):
            if _is_isolated_module(name):
                sys.modules.pop(name, None)
        sys.modules.update(preserved)
        sys.path[:] = original_path


def _verify_loaded_product_closure(contract: dict[str, Any]) -> int:
    locked = {row["path"] for row in contract["source_locks"]}
    root = REPO_ROOT.resolve(strict=True)
    loaded: set[str] = set()
    for name, module in sys.modules.items():
        if not (name == "mdx" or name.startswith("mdx.")):
            continue
        source = getattr(module, "__file__", None)
        if not source:
            continue
        try:
            relative = Path(source).resolve(strict=True).relative_to(root).as_posix()
        except ValueError as exc:
            raise QualificationError(
                f"loaded mdx module escaped repository: {name}"
            ) from exc
        loaded.add(relative)
    missing = sorted(loaded - locked)
    if missing:
        raise QualificationError(f"unlocked loaded product module: {missing[0]}")
    if len(loaded) != 54:
        raise QualificationError(
            f"loaded product-module denominator drift: {len(loaded)}"
        )
    return len(loaded)


def _observe_dynamic_config(product: dict[str, Any]) -> dict[str, Any]:
    validator = product["config_validator"]
    applier_cls = product["config_applier"].ConfigApplier
    app_config = product["config"].AppConfig()
    good = {
        "app": [
            {"name": "behaviorWatermarkSec", "value": "45"},
            {"name": "fovCountViolationIncidentEnable", "value": "true"},
        ],
        "sensors": [
            {
                "id": "cam-1",
                "configs": [{"name": "tripwireMinPoints", "value": "3"}],
            }
        ],
    }
    success = validator.validate(good)
    if success.status != "success" or success.error is not None:
        raise QualificationError("valid dynamic configuration was not accepted")
    applier_cls(app_config).apply(success.applied_app, success.applied_sensors)
    if (
        app_config.get_app_config("behaviorWatermarkSec") != "45"
        or app_config.get_sensor_config(
            "tripwireMinPoints", sensor_id="cam-1", default_value=""
        )
        != "3"
    ):
        raise QualificationError("validated configuration did not apply")

    partial = validator.validate(
        {
            "app": [
                {"name": "behaviorWatermarkSec", "value": "60"},
                {"name": "behaviorMaxPoints", "value": "not-an-int"},
            ],
            "kafka": {"brokers": "forbidden"},
        }
    )
    non_object = validator.validate(["not", "an", "object"])
    read_only = validator.validate({"kafka": {"brokers": "forbidden"}})
    invalid_value = validator.validate(
        {"app": [{"name": "behaviorMaxPoints", "value": "not-an-int"}]}
    )
    if (
        partial.status != "partial-success"
        or len(partial.applied_app) != 1
        or non_object.status != "failure"
        or read_only.status != "failure"
        or invalid_value.status != "failure"
    ):
        raise QualificationError("dynamic configuration boundary semantics drifted")
    return {
        "success": {
            "status": success.status,
            "applied_app": len(success.applied_app),
            "applied_sensor_items": sum(
                len(sensor["configs"]) for sensor in success.applied_sensors
            ),
            "snapshot_sha256": _sha256(
                _canonical_bytes(app_config.to_mutable_snapshot())
            ),
        },
        "partial": {
            "status": partial.status,
            "applied_app": len(partial.applied_app),
            "rejection_present": bool(partial.error),
        },
        "negative_statuses": {
            "config-non-object": non_object.status,
            "config-read-only-section": read_only.status,
            "config-invalid-value": invalid_value.status,
        },
    }


def _calibration_payload(calibration_type: str, sensor_id: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "osmURL": "",
        "calibrationType": calibration_type,
        "sensors": [
            {
                "type": "camera",
                "id": sensor_id,
                "origin": {"lat": 0.0, "lng": 0.0},
                "geoLocation": {"lat": 0.0, "lng": 0.0},
                "coordinates": {"x": 0.0, "y": 0.0},
                "scaleFactor": 1.0,
                "attributes": [],
                "place": [],
                "imageCoordinates": [],
                "globalCoordinates": [],
            }
        ],
    }


def _observe_calibration(product: dict[str, Any]) -> dict[str, Any]:
    validator = product["calibration_validator"]
    constants = __import__(
        "mdx.analytics.core.constants", fromlist=["CALIBRATION_ACTION_UPSERT"]
    )
    accepted_types = []
    for calibration_type in ("image", "cartesian", "geo"):
        validator.validate(
            _calibration_payload(calibration_type, f"cam-{calibration_type}"),
            constants.CALIBRATION_ACTION_UPSERT_ALL,
        )
        accepted_types.append(calibration_type)
    validator.validate(
        _calibration_payload("image", "cam-upsert"),
        constants.CALIBRATION_ACTION_UPSERT,
    )
    validator.validate(
        {"sensors": [{"id": "cam-delete"}]}, constants.CALIBRATION_ACTION_DELETE
    )

    calibration = object.__new__(product["calibration_base"].CalibrationBase)
    calibration.calibration_info = {
        "calibrationType": "image",
        "sensors": [{"id": "cam-a", "type": "camera"}],
    }
    calibration.update_calibration_info(
        {"sensors": [{"id": "cam-a", "type": "camera", "version": "2"}]},
        constants.CALIBRATION_ACTION_UPSERT,
    )
    calibration.update_calibration_info(
        {"sensors": [{"id": "cam-b", "type": "camera"}]},
        constants.CALIBRATION_ACTION_UPSERT,
    )
    merged_ids = sorted(item["id"] for item in calibration.calibration_info["sensors"])
    calibration.update_calibration_info(
        {"sensors": [{"id": "cam-a"}]}, constants.CALIBRATION_ACTION_DELETE
    )
    deleted_ids = sorted(item["id"] for item in calibration.calibration_info["sensors"])
    before_invalid = deepcopy(calibration.calibration_info)
    invalid_type_rejected = False
    unknown_action_rejected = False
    previous_disabled = validator.logger.disabled
    validator.logger.disabled = True
    try:
        try:
            validator.validate(
                _calibration_payload("lidar", "cam-invalid"),
                constants.CALIBRATION_ACTION_UPSERT_ALL,
            )
        except validator.CalibrationValidationError:
            invalid_type_rejected = True
        try:
            validator.validate(_calibration_payload("image", "cam-x"), "replace")
        except validator.CalibrationValidationError:
            unknown_action_rejected = True
    finally:
        validator.logger.disabled = previous_disabled
    if calibration.calibration_info != before_invalid:
        raise QualificationError("invalid calibration mutated live state")

    class Delegate:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def reload_data(self, path: str) -> None:
            self.paths.append(path)

    dynamic = object.__new__(product["calibration_dynamic"].DynamicCalibration)
    delegate = Delegate()
    dynamic._started_with_file = True
    dynamic._switch_lock = threading.Lock()
    dynamic._calibrator = delegate
    dynamic.reload_data("/qualified/upsert-calibration.json")
    if delegate.paths != ["/qualified/upsert-calibration.json"]:
        raise QualificationError(
            "existing calibration did not delegate without switching"
        )
    if not invalid_type_rejected or not unknown_action_rejected:
        raise QualificationError("calibration negatives were not rejected")
    return {
        "accepted_types": accepted_types,
        "accepted_actions": ["upsert", "upsert-all", "delete"],
        "merge_ids": merged_ids,
        "after_delete_ids": deleted_ids,
        "invalid_payload_preserved_state": True,
        "existing_file_reload_delegated": True,
        "existing_file_type_switch_attempted": False,
        "negative_rejections": {
            "calibration-invalid-type": invalid_type_rejected,
            "calibration-unknown-action": unknown_action_rejected,
        },
    }


def _fixed_timestamp(offset_seconds: int) -> Timestamp:
    value = Timestamp()
    value.FromDatetime(datetime(2025, 1, 1, 0, 0, offset_seconds, tzinfo=timezone.utc))
    return value


def _observe_events_and_incidents(product: dict[str, Any]) -> dict[str, Any]:
    config = product["config"].AppConfig()
    for key, value in (
        ("behaviorTimeThreshold", "2020-01-01T00:00:00.000Z"),
        ("behaviorWatermarkSec", "3600"),
        ("proximityViolationIncidentEnable", "true"),
        ("proximityViolationIncidentExpirationWindow", "2"),
        ("restrictedAreaViolationIncidentEnable", "true"),
        ("restrictedAreaViolationIncidentExpirationWindow", "2"),
        ("confinedAreaViolationIncidentEnable", "true"),
        ("confinedAreaViolationIncidentExpirationWindow", "2"),
        ("fovCountViolationIncidentEnable", "true"),
        ("fovCountViolationIncidentObjectThreshold", "2"),
        ("fovCountViolationIncidentExpirationWindow", "2"),
        ("fovCountViolationIncidentObjectType", "Person"),
    ):
        config.set_app_config(key, value)
    config.set_sensor_config("sensorMinFrames", "10", "cam-1")

    proto = product["proto"]
    frame = proto.Frame(version="3.0", sensorId="cam-1", id="frame-1")
    frame.timestamp.CopyFrom(_fixed_timestamp(0))
    frame.socialDistancing.info["proximityViolationObjects"] = "p1,p2"
    roi = frame.rois.add(id="restricted-1")
    roi.info["restrictedAreaViolation"] = "true"
    roi.objectIds.append("r1")
    frame.info["confinedAreaViolationObjects"] = "c1"
    fov = frame.fov.add(type="Person", count=2)
    fov.objectIds.extend(["f1", "f2"])

    manager = product["frame_state"].FrameStateMgmt(config)
    manager.update_frames("cam-1", [frame])
    state = manager.get_state("cam-1")
    counts = {
        "proximity": len(state.safety_violation_states),
        "restricted-area": len(state.restricted_area_violation_states),
        "confined-area": len(state.confined_area_violation_states),
        "fov-count": int(state.fov_count_violation_state is not None),
    }
    if counts != {
        "proximity": 1,
        "restricted-area": 1,
        "confined-area": 1,
        "fov-count": 1,
    }:
        raise QualificationError(f"violation matrix drifted: {counts}")

    class CandidateBehaviorState(product["behavior_state"].StateMgmtBase):
        def _update_object_state_model(
            self, _state: Any, _embeddings: list[list[float]]
        ) -> None:
            """Keep the state machine deterministic without a clustering provider."""

    behavior_manager = CandidateBehaviorState(config, None)
    messages = [
        product["models"].Message(
            messageid=f"tracking-{index}",
            timestamp=datetime(2025, 1, 1, 0, 0, index, tzinfo=timezone.utc),
            sensor=product["models"].Sensor(id="cam-1"),
            object=product["models"].Object(
                id="track-1",
                type="Person",
                confidence=0.9,
                coordinate=product["models"].Coordinate(x=float(index), y=float(index)),
            ),
        )
        for index in (1, 2)
    ]
    behavior_state, trip_state, last_message = (
        behavior_manager._get_object_trip_state_and_message(
            "cam-1 #-# track-1", messages
        )
    )
    behavior_state_observation = {
        "state_created": behavior_state is not None,
        "trip_state_created": trip_state is not None,
        "tracked_points": len(behavior_state.points) if behavior_state else 0,
        "last_message_id": last_message.messageid if last_message else "",
    }
    if behavior_state_observation != {
        "state_created": True,
        "trip_state_created": True,
        "tracked_points": 2,
        "last_message_id": "tracking-2",
    }:
        raise QualificationError("tracking/behavior-state semantics drifted")

    class CalibrationFake:
        def __init__(self) -> None:
            self.sensor_map = {
                "cam-1": SimpleNamespace(
                    rois=[SimpleNamespace(id="roi-1")],
                    tripwires={"trip-1": SimpleNamespace(id="trip-1", wires=[])},
                )
            }

        @staticmethod
        def point_in_polygon(point: Any, sensor_id: str, obj_id: str) -> bool:
            return sensor_id == "cam-1" and obj_id == "roi-1" and point.x >= 0

        @staticmethod
        def point_in_tripwire(point: Any, sensor_id: str, obj_id: str) -> bool:
            return sensor_id == "cam-1" and obj_id == "trip-1" and point.y >= 0

    fake = CalibrationFake()
    roi_event = product["roi_event"].ROIEvent(config, fake)
    tripwire_event = product["tripwire_event"].TripwireEvent(config, fake)
    point_in = product["models"].Point2D(x=1.0, y=1.0)
    point_out = product["models"].Point2D(x=-1.0, y=-1.0)
    event_checks = {
        "roi": roi_event._intersect([point_out, point_in], "cam-1", "roi-1"),
        "tripwire": tripwire_event._check_point(point_in, "cam-1", "trip-1"),
    }
    if event_checks != {"roi": True, "tripwire": True}:
        raise QualificationError("ROI/tripwire product event checks drifted")
    before_empty = len(state.confined_area_violation_states)
    manager._get_confined_area_violation_state("cam-1", "", frame, state)
    empty_rejected = len(state.confined_area_violation_states) == before_empty
    if not empty_rejected:
        raise QualificationError("empty violation identifier mutated state")
    return {
        "event_checks": event_checks,
        "event_objects": {
            "roi": len(roi_event._get_objects("cam-1")),
            "tripwire": len(tripwire_event._get_objects("cam-1")),
        },
        "behavior_state": behavior_state_observation,
        "violation_state_counts": counts,
        "event-empty-identifier": empty_rejected,
    }


def _embedding(proto: Any, timestamp_ms: int, vector: list[float]) -> Any:
    value = proto.VisionLLM()
    timestamp = Timestamp()
    timestamp.FromMilliseconds(timestamp_ms)
    value.end.CopyFrom(timestamp)
    item = value.llm.visionEmbeddings.add()
    item.vector.extend(vector)
    return value


def _observe_embeddings(product: dict[str, Any]) -> dict[str, Any]:
    config_cls = product["config"].VideoEmbeddingConfig
    manager_cls = product["embedding_state"].VideoEmbeddingStateMgmt
    proto = product["proto"]
    repeated = [_embedding(proto, 1000 * (i + 1), [1.0, 0.0, 0.0]) for i in range(5)]
    invalid = proto.VisionLLM()

    passthrough = manager_cls(config_cls(enable_downsampling=False))
    pass_input = [repeated[0], invalid]
    pass_output = passthrough.update_video_embeddings("cam-pass", pass_input)
    if pass_output is not pass_input:
        raise QualificationError("disabled downsampling was not pass-through")

    sdt = manager_cls(
        config_cls(
            enable_downsampling=True,
            downsampler_type="sdt",
            sensor_ttl_sec=10,
            downsample_tolerance_mode="distance",
            downsample_distance_threshold=0.15,
            downsample_max_interval_sec=300,
        )
    )
    sdt_output = sdt.update_video_embeddings("cam-sdt", repeated + [invalid])
    pending = sdt.get_pending_video_embeddings()
    window = manager_cls(
        config_cls(
            enable_downsampling=True,
            downsampler_type="window",
            sensor_ttl_sec=10,
            downsample_tolerance_mode="distance",
            downsample_distance_threshold=0.15,
            downsample_max_interval_sec=300,
            downsample_window_size=5,
            downsample_min_neighbours=2,
        )
    )
    window_output = window.update_video_embeddings("cam-window", repeated + [invalid])
    if len(sdt_output) != 1 or len(pending) != 1 or len(window_output) >= len(repeated):
        raise QualificationError("embedding reduction semantics drifted")
    return {
        "optional_passthrough_identity": True,
        "input_valid_records": len(repeated),
        "invalid_records_filtered": 1,
        "modes": {
            "sdt": {
                "output_records": len(sdt_output),
                "pending_flushed": len(pending),
            },
            "sliding-window": {"output_records": len(window_output)},
        },
        "embedding-invalid-record": True,
    }


class _FakeKafkaProducer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.polls = 0

    def produce(self, **kwargs: Any) -> None:
        self.records.append(kwargs)

    def poll(self, _timeout: int) -> None:
        self.polls += 1


class _FakeRedisProducer:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def xadd(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class _FakeMQTTClient:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def publish(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def _sink_config(product: dict[str, Any], sink_type: str) -> Any:
    config = product["config"]
    routes = [
        config.KeyValuePair(name=route, value=f"qualified-{route}")
        for route in OUTPUT_ROUTE_MAP.values()
    ]
    app = [config.KeyValuePair(name="sinkType", value=sink_type)]
    if sink_type == "kafka":
        return config.AppConfig(
            app=app,
            kafka=config.AppKafkaConfig(
                brokers="qualified.invalid:9092", topics=routes
            ),
        )
    if sink_type == "redisStream":
        return config.AppConfig(
            app=app,
            redisStream=config.AppRedisStreamConfig(
                host="qualified.invalid", streams=routes
            ),
        )
    return config.AppConfig(
        app=app,
        mqtt=config.AppMQTTConfig(
            host="qualified.invalid", port=1883, clientId="qualified", topics=routes
        ),
    )


def _observe_sinks(product: dict[str, Any]) -> dict[str, Any]:
    sink_factory = product["sink_factory"]
    sink_base = product["sink_base"]
    observations: dict[str, Any] = {}
    missing_route_rejected = False
    for sink_type in ("kafka", "redisStream", "mqtt"):
        sink = sink_factory.get_sink(_sink_config(product, sink_type))
        if sink_type == "kafka":
            fake: Any = _FakeKafkaProducer()
            sink._producer = fake
        elif sink_type == "redisStream":
            fake = _FakeRedisProducer()
            sink._conn = fake
        else:
            fake = _FakeMQTTClient()
            sink._client = fake
        for advertised, route in OUTPUT_ROUTE_MAP.items():
            sink.write(
                dest_key=route,
                messages=[{"output": advertised}],
                value_serializer=sink_base.JsonBytesSerializer,
            )
        try:
            sink.write(
                dest_key="missing-route",
                messages=[{}],
                value_serializer=sink_base.JsonBytesSerializer,
            )
        except ValueError:
            missing_route_rejected = True
        observations[sink_type] = {
            "class": sink.__class__.__name__,
            "writes": len(fake.records),
            "routes": list(OUTPUT_ROUTE_MAP.values()),
            "connections_opened": 0,
        }
    unsupported_rejected = False
    try:
        sink_factory.get_sink(_sink_config(product, "unsupported"))
    except ValueError:
        unsupported_rejected = True
    if (
        not unsupported_rejected
        or not missing_route_rejected
        or any(row["writes"] != 7 for row in observations.values())
    ):
        raise QualificationError("broker sink matrix or negatives drifted")
    return {
        "output_route_map": OUTPUT_ROUTE_MAP,
        "sink_types": observations,
        "sink-unsupported-type": unsupported_rejected,
        "sink-missing-route": missing_route_rejected,
    }


def _run_observations(product: dict[str, Any]) -> dict[str, Any]:
    config = _observe_dynamic_config(product)
    calibration = _observe_calibration(product)
    events = _observe_events_and_incidents(product)
    embeddings = _observe_embeddings(product)
    sinks = _observe_sinks(product)
    case_checks = {
        "config-non-object": config["negative_statuses"]["config-non-object"]
        == "failure",
        "config-read-only-section": config["negative_statuses"][
            "config-read-only-section"
        ]
        == "failure",
        "config-invalid-value": config["negative_statuses"]["config-invalid-value"]
        == "failure",
        "calibration-invalid-type": calibration["negative_rejections"][
            "calibration-invalid-type"
        ],
        "calibration-unknown-action": calibration["negative_rejections"][
            "calibration-unknown-action"
        ],
        "calibration-existing-file-reload": calibration[
            "existing_file_reload_delegated"
        ]
        and not calibration["existing_file_type_switch_attempted"],
        "event-empty-identifier": events["event-empty-identifier"],
        "embedding-invalid-record": embeddings["embedding-invalid-record"],
        "sink-unsupported-type": sinks["sink-unsupported-type"],
        "sink-missing-route": sinks["sink-missing-route"],
    }
    if list(case_checks) != list(EXPECTED_CASE_OUTCOMES) or not all(
        case_checks.values()
    ):
        raise QualificationError("adjacent-case results drifted")
    return {
        "pipeline_subset": {
            "actual_product_modules": True,
            "inputs_exercised": ["tracking", "embedding"],
            "stages_exercised": [
                "dynamic-config",
                "calibration",
                "roi",
                "behavior-state",
                "metrics",
            ],
            "full_pipeline_claimed": False,
        },
        "dynamic_config": config,
        "calibration": calibration,
        "events_incidents": events,
        "embedding_downsampling": embeddings,
        "broker_sinks": sinks,
        "adjacent_cases": [
            {"case_id": case_id, "outcome": EXPECTED_CASE_OUTCOMES[case_id]}
            for case_id in case_checks
        ],
    }


def execute() -> dict[str, Any]:
    contract = _load_contract()
    source_hashes = _verify_source_locks(contract)
    bindings = _verify_bindings(contract)
    with _isolated_product() as product:
        loaded_product_files = _verify_loaded_product_closure(contract)
        first = _run_observations(product)
    with _isolated_product() as product:
        if _verify_loaded_product_closure(contract) != loaded_product_files:
            raise QualificationError(
                "loaded product-module denominator changed between runs"
            )
        second = _run_observations(product)
    first_bytes = _canonical_bytes(first)
    second_bytes = _canonical_bytes(second)
    if first_bytes != second_bytes:
        raise QualificationError(
            "independent product observations were not deterministic"
        )
    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": contract["mode"],
        "policy": contract["policy"],
        "bindings": bindings,
        "source_hashes": source_hashes,
        "observations": first,
        "determinism": {
            "independent_runs": 2,
            "byte_identical": True,
            "observation_sha256": _sha256(first_bytes),
        },
        "confinement": {
            "filesystem_writes": 0,
            "network_calls": 0,
            "broker_connections": 0,
            "subprocess_calls": 0,
            "service_lifecycle_calls": 0,
            "warehouse_sample_bundle": "excluded",
            "counter_basis": "locked_source_and_forbidden_constructor_audit",
            "product_and_stub_import_state_restored": True,
            "loaded_repo_product_files": loaded_product_files,
        },
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "residual_blockers": [
            "full bbox/tracking/media pipeline is not executed",
            "coordinate-transform provider path is not executed",
            "dynamic-config broker listener, atomic persistence, acknowledgement, and timeout fallback are not executed",
            "calibration filesystem watcher and live multi-worker reload are not executed",
            "full tripwire trajectory and incident completion media fixtures are not executed",
            "real Kafka, Redis Streams, and MQTT transports are not connected",
            "Thor service deployment, load, persistence, and restart behavior remain unqualified",
        ],
        "result": "candidate_static_pass_non_advancing",
    }
    schema = _strict_json(LANE / "result.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(result),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise QualificationError(f"invalid result: {errors[0].message}")
    return result


def _self_test() -> None:
    result = execute()
    if result["result"] != "candidate_static_pass_non_advancing":
        raise QualificationError("self-test result drifted")
    if result["runtime_evidence"] != []:
        raise QualificationError("self-test found runtime evidence")
    if any(
        result["confinement"][field] != 0
        for field in (
            "filesystem_writes",
            "network_calls",
            "broker_connections",
            "subprocess_calls",
            "service_lifecycle_calls",
        )
    ):
        raise QualificationError("self-test confinement drifted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=LANE / "contract.json")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.contract.resolve(strict=True) != (LANE / "contract.json").resolve(
            strict=True
        ):
            raise QualificationError("only the lane-owned contract may be executed")
        if args.self_test:
            _self_test()
            print("PASS: Behavior Analytics candidate-static executor self-test")
        else:
            print(json.dumps(execute(), sort_keys=True, separators=(",", ":")))
    except (QualificationError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
