#!/usr/bin/env python3
"""Execute a bounded, provider-free NvSchema JSON product-code subset."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator


LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
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
    "writes": "executor_owned_private_temporary_directory_only",
}
EXPECTED_FRAME_CONTRACT = {
    "frame_fields": ["version", "id", "@timestamp", "sensorId", "objects"],
    "event_values": [
        "entry",
        "exit",
        "moving",
        "stopped",
        "parked",
        "empty",
        "reset",
    ],
    "object_delimiters": ["|", "|#|"],
    "illustrative_not_complete_validator": True,
}
ACCEPTANCE_INVENTORY_PATH = (
    "deploy/docker/thor-local/qualification/acceptance_inventory.json"
)
EXPECTED_LOCKS = {
    ACCEPTANCE_INVENTORY_PATH: "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    "deploy/docker/thor-local/parity/official-capabilities.json": "65241b3ad56f5d9bb817ba040c06abdbfe034701be645c845d94e4f065514f0e",
    "deploy/docker/thor-local/parity/capability-oracles.json": "daccf4e9d198ad3fab762a2f0bcab2e06d093ba92dfb50513f7966b4b5c40dff",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave7/inventory.json": "d670829d85239bfb924737d32565eb3b87a0378df2520d225df72a75617122d9",
    "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json": "0abc81c383a9db122d2ad74c4dbb6c85cc00caf032abd94c4e7d632ce97ff539",
    "services/analytics/behavior-analytics/src/mdx/analytics/core/utils/schema_util.py": "3c7c8d16b6c58fb01adea07b4dfde27104a62454a545fe0afbd623274f92ecca",
    "services/analytics/behavior-analytics/src/mdx/analytics/core/schema/proto/schema_pb2.py": "bfa3727bc8c72cd1975eb3169caae768a0e6a4e7fb0f72aa610747cf5ddde87c",
    "services/analytics/behavior-analytics/src/mdx/analytics/core/schema/proto/ext_pb2.py": "ca1719b0f731f023592cc6b51f0b0640b677bfccc6ae6c60448746404da0ad4a",
    "services/analytics/behavior-analytics/tests/unit/mdx/analytics/core/utils/test_schema_util.py": "1cde76d582690f6c0de979eb5c641b849ad510365bdfdeefcca3761d2202f218",
    "libs/analytics/spatialai-data-utils/spatialai_data_utils/loaders/nvschema.py": "81faba50eaf2a239e0bbc7b9022c33baeea123ccae49812ca95a0ca060dc6f3e",
    "libs/analytics/spatialai-data-utils/tests/loaders/test_nvschema_loader.py": "b9563cb1404cb5bc30796b6c1c70a3440f9ed510a0808784888d8fa0cdec710e",
    "services/agent/src/vss_agents/video_analytics/nvschema.py": "8c71e67e1fe1329d87486b46b57e35c271352cf0fe37c1c7bd0687939e15efe6",
    "services/agent/tests/unit_test/video_analytics/test_nvschema.py": "caf91635661f4e85aca872a910aa0e9d6eb57f7e57e9a7a836d27bfa5775f834",
}
EXPECTED_NEGATIVES = [
    "legacy-frame-missing-sensor-id",
    "legacy-object-short-primary-segment",
    "legacy-frame-invalid-timestamp",
    "spatial-loader-unsupported-output-format",
    "spatial-row-official-timestamp-not-projected",
    "unsupported-event-value-not-validated",
]
PRODUCT_MODULE_PREFIXES = ("mdx", "spatialai_data_utils")
AGENT_MODULE_NAME = "thor_nvschema_agent_models"


class QualificationError(RuntimeError):
    """The locked candidate contract or an observation failed closed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise QualificationError(f"non-finite JSON number: {value}")


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
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except QualificationError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON root is not an object: {path}")
    return value


def _repo_file(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise QualificationError(f"unsafe repository path: {relative}")
    root = REPO_ROOT.resolve(strict=True)
    path = root.joinpath(candidate)
    if path.is_symlink():
        raise QualificationError(f"repository source is a symlink: {relative}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"repository source escaped: {relative}") from exc
    if not resolved.is_file():
        raise QualificationError(f"repository source is not a file: {relative}")
    return resolved


def _find_one(rows: Any, key: str, expected: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise QualificationError(f"row set for {expected} is not an array")
    matches = [
        row for row in rows if isinstance(row, dict) and row.get(key) == expected
    ]
    if len(matches) != 1:
        raise QualificationError(f"expected exactly one {key}={expected}")
    return matches[0]


def _load_contract() -> dict[str, Any]:
    schema = _strict_json(LANE / "contract.schema.json")
    Draft202012Validator.check_schema(schema)
    contract = _strict_json(LANE / "contract.json")
    errors = list(Draft202012Validator(schema).iter_errors(contract))
    if errors:
        raise QualificationError(f"contract schema rejection: {errors[0].message}")
    if contract["policy"] != EXPECTED_POLICY:
        raise QualificationError("candidate-only policy drift")
    observed_locks = {row["path"]: row["sha256"] for row in contract["source_locks"]}
    if observed_locks != EXPECTED_LOCKS or len(contract["source_locks"]) != len(
        EXPECTED_LOCKS
    ):
        raise QualificationError("exact source-lock set drift")
    if contract["adjacent_negative_ids"] != EXPECTED_NEGATIVES:
        raise QualificationError("adjacent-negative denominator drift")
    return contract


def _verify_sources(contract: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for lock in contract["source_locks"]:
        digest = _sha256(_repo_file(lock["path"]).read_bytes())
        if digest != lock["sha256"]:
            raise QualificationError(f"source lock mismatch: {lock['path']}")
        observed[lock["path"]] = digest
    return observed


def _verify_binding(contract: dict[str, Any]) -> dict[str, Any]:
    binding = contract["binding"]
    acceptance = _strict_json(_repo_file(ACCEPTANCE_INVENTORY_PATH))
    official = _strict_json(
        _repo_file("deploy/docker/thor-local/parity/official-capabilities.json")
    )
    oracle_set = _strict_json(
        _repo_file("deploy/docker/thor-local/parity/capability-oracles.json")
    )
    planning = _find_one(
        acceptance["wave3_contracts"]["planning_requirements"],
        "id",
        binding["planning_requirement_id"],
    )
    if _sha256(_canonical_bytes(planning)) != binding["planning_requirement_sha256"]:
        raise QualificationError("planning requirement digest drift")
    if planning.get("payload_canonical_sha256") != binding["planning_payload_sha256"]:
        raise QualificationError("planning payload digest drift")
    if (
        planning.get("owner_id") != binding["capability_id"]
        or planning.get("package") != "systems"
        or planning.get("materialized") is not False
        or planning.get("executor_ready") is not False
        or planning.get("runtime_evidence") != []
    ):
        raise QualificationError("canonical planning boundary drift")
    capability = _find_one(official["capabilities"], "id", binding["capability_id"])
    if _sha256(_canonical_bytes(capability)) != binding["capability_sha256"]:
        raise QualificationError("capability digest drift")
    product_contract = dict(capability.get("contract", {}))
    wave_acceptance = product_contract.pop("wave3_acceptance", None)
    if product_contract != EXPECTED_FRAME_CONTRACT:
        raise QualificationError("NvSchema frame contract drift")
    if (
        capability.get("acceptance_class") != "required_local"
        or capability.get("thor_state") != "partial"
        or capability.get("runtime_state") != "not_qualified"
        or not isinstance(wave_acceptance, dict)
        or wave_acceptance.get("materialized") is not False
        or wave_acceptance.get("executor_ready") is not False
    ):
        raise QualificationError("canonical capability boundary drift")
    oracle = _find_one(oracle_set["oracles"], "oracle_id", binding["oracle_id"])
    if _sha256(_canonical_bytes(oracle)) != binding["oracle_sha256"]:
        raise QualificationError("oracle digest drift")
    if (
        oracle.get("capability_id") != binding["capability_id"]
        or oracle.get("current_state") != "open_unexecuted"
        or oracle.get("evidence") != []
        or oracle.get("execution_bounds", {}).get("executor") is not None
        or oracle.get("execution_bounds", {}).get("collectors") != []
    ):
        raise QualificationError("canonical oracle boundary drift")
    predecessor = _strict_json(
        _repo_file(
            "deploy/docker/thor-local/qualification/planning-requirement-executors-wave7/inventory.json"
        )
    )
    predecessor_case = _find_one(
        predecessor["cases"],
        "planning_requirement_id",
        binding["planning_requirement_id"],
    )
    if (
        predecessor_case.get("capability_id") != binding["capability_id"]
        or predecessor_case.get("evidence_class") != "static_protocol_subset_only"
        or predecessor_case.get("runtime_evidence") != []
    ):
        raise QualificationError("Wave 7 predecessor boundary drift")
    return {
        "planning_requirement_id": binding["planning_requirement_id"],
        "capability_id": binding["capability_id"],
        "oracle_id": binding["oracle_id"],
        "planning_materialized": False,
        "planning_executor_ready": False,
        "capability_thor_state": "partial",
        "capability_runtime_state": "not_qualified",
        "oracle_state": "open_unexecuted",
        "canonical_runtime_evidence": [],
    }


def _install_behavior_import_stubs() -> None:
    models = types.ModuleType("mdx.analytics.core.schema.models")
    for name in (
        "ROI",
        "AnalyticsModule",
        "Bbox",
        "Bbox3d",
        "Behavior",
        "Coordinate",
        "Embedding",
        "Event",
        "Frame",
        "GeoLocation",
        "Incident",
        "Line",
        "Location",
        "Message",
        "Object",
        "Place",
        "Point",
        "Point2D",
        "Pose",
        "Keypoint",
        "Action",
        "Sensor",
        "Tripwire",
        "TypeMetrics",
    ):
        setattr(models, name, type(name, (), {}))
    crp = types.ModuleType("mdx.analytics.core.utils.crp")
    crp.Model = type("Model", (), {})
    distance = types.ModuleType("mdx.analytics.core.utils.distance_util")
    distance.orientation = lambda *_args, **_kwargs: 0.0
    util = types.ModuleType("mdx.analytics.core.utils.util")
    util.iso_to_epoch = lambda *_args, **_kwargs: 0
    sys.modules[models.__name__] = models
    sys.modules[crp.__name__] = crp
    sys.modules[distance.__name__] = distance
    sys.modules[util.__name__] = util


def _load_product_modules() -> tuple[Any, Any, Any]:
    behavior_root = REPO_ROOT / "services/analytics/behavior-analytics/src"
    spatial_root = REPO_ROOT / "libs/analytics/spatialai-data-utils"
    for path in (str(spatial_root), str(behavior_root)):
        if path not in sys.path:
            sys.path.insert(0, path)
    _install_behavior_import_stubs()
    behavior = importlib.import_module("mdx.analytics.core.utils.schema_util")
    spatial = importlib.import_module("spatialai_data_utils.loaders.nvschema")
    agent_path = REPO_ROOT / "services/agent/src/vss_agents/video_analytics/nvschema.py"
    spec = importlib.util.spec_from_file_location(AGENT_MODULE_NAME, agent_path)
    if spec is None or spec.loader is None:
        raise QualificationError("cannot load agent NvSchema models")
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return behavior, spatial, agent


def _is_product_module(name: str) -> bool:
    return name == AGENT_MODULE_NAME or any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in PRODUCT_MODULE_PREFIXES
    )


@contextmanager
def _isolated_product_modules() -> Iterator[tuple[Any, Any, Any]]:
    """Load a fresh product subset and restore every touched import entry."""
    original_path = list(sys.path)
    preserved = {
        name: module for name, module in sys.modules.items() if _is_product_module(name)
    }
    try:
        for name in list(sys.modules):
            if _is_product_module(name):
                sys.modules.pop(name, None)
        yield _load_product_modules()
    finally:
        for name in list(sys.modules):
            if _is_product_module(name):
                sys.modules.pop(name, None)
        sys.modules.update(preserved)
        sys.path[:] = original_path


def _capture_exception(
    case_id: str, expected: type[BaseException], call: Any
) -> dict[str, str]:
    try:
        call()
    except expected as exc:
        return {"id": case_id, "outcome": "rejected", "exception": type(exc).__name__}
    except Exception as exc:
        raise QualificationError(
            f"{case_id} raised unexpected {type(exc).__name__}"
        ) from exc
    raise QualificationError(f"{case_id} did not reject")


def _observe_loaded(
    root: Path, behavior: Any, spatial: Any, agent: Any
) -> dict[str, Any]:
    object_string = (
        "object-7|10|20|30|40|Person|#|||||||0.75"
        "|#|pose3D|head,1,2,3,4,0.1,0.2,0.3,0.4"
        "|#|embedding|1,2,3"
    )
    legacy = {
        "version": "4.0",
        "id": 17,
        "@timestamp": "2026-08-01T12:00:00Z",
        "sensorId": "camera-legacy",
        "objects": [object_string],
    }
    frame = behavior.dict_frame_to_protobuf_frame_legacy(legacy)
    wire = frame.SerializeToString(deterministic=True)
    decoded = behavior.nvSchema.Frame()
    decoded.ParseFromString(wire)
    if decoded.SerializeToString(deterministic=True) != wire:
        raise QualificationError("legacy frame protobuf wire roundtrip changed bytes")

    modern = {
        "id": 19,
        "sensorId": "camera-3d",
        "timestamp": "2026-08-01T12:00:01Z",
        "objects": [
            {
                "id": "object-19",
                "type": "person",
                "confidence": 0.9,
                "bbox3d": {"coordinates": [1, 2, 3, 4, 5, 6, 0.1, 0.2, 0.3]},
                "custom": "preserved",
            }
        ],
        "info": {"camera-3d": "2026-08-01T12:00:01Z"},
    }
    modern_path = root / "modern.jsonl"
    modern_path.write_text(
        json.dumps(modern, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    legacy_path = root / "legacy.jsonl"
    legacy_path.write_text(
        json.dumps(legacy, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    raw = spatial.load_nvschema(str(modern_path))
    flat = spatial.load_nvschema(str(modern_path), output_format=spatial.GT_JSON_FORMAT)
    row = list(spatial.iter_frame_rows(str(modern_path)))[0]
    legacy_row = list(spatial.iter_frame_rows(str(legacy_path)))[0]

    incident = agent.Incident(
        Id="incident-1",
        sensorId="camera-legacy",
        timestamp="2026-08-01T12:00:00Z",
        end="2026-08-01T12:00:02Z",
        objectIds=["object-7"],
        analyticsModule="behavior-analytics",
        type="entry",
    )
    incident_aliases = incident.model_dump(by_alias=True, exclude_none=True)

    negatives = [
        _capture_exception(
            "legacy-frame-missing-sensor-id",
            KeyError,
            lambda: behavior.dict_frame_to_protobuf_frame_legacy(
                {key: value for key, value in legacy.items() if key != "sensorId"}
            ),
        ),
        _capture_exception(
            "legacy-object-short-primary-segment",
            IndexError,
            lambda: behavior.str_object_to_protobuf_object_legacy("object-only|1"),
        ),
        _capture_exception(
            "legacy-frame-invalid-timestamp",
            ValueError,
            lambda: behavior.dict_frame_to_protobuf_frame_legacy(
                {**legacy, "@timestamp": "not-a-timestamp"}
            ),
        ),
        _capture_exception(
            "spatial-loader-unsupported-output-format",
            ValueError,
            lambda: spatial.load_nvschema(
                str(modern_path), output_format="unsupported"
            ),
        ),
    ]
    if legacy_row["timestamp"] is not None:
        raise QualificationError("spatial iterator unexpectedly projected @timestamp")
    negatives.append(
        {
            "id": "spatial-row-official-timestamp-not-projected",
            "outcome": "accepted_limited",
            "exception": "none",
        }
    )
    unsupported_event = behavior.dict_frame_to_protobuf_frame_legacy(
        {**legacy, "event": {"type": "teleporting"}}
    )
    if unsupported_event.id != "17":
        raise QualificationError("unsupported-event limited observation changed frame")
    negatives.append(
        {
            "id": "unsupported-event-value-not-validated",
            "outcome": "accepted_limited",
            "exception": "none",
        }
    )
    if [item["id"] for item in negatives] != EXPECTED_NEGATIVES:
        raise QualificationError("adjacent-negative observation order drift")
    raw_object = raw[19]["camera-3d"][0]
    flat_object = flat[19]["camera-3d"][0]
    return {
        "legacy_behavior_frame": {
            "version": decoded.version,
            "id": decoded.id,
            "sensor_id": decoded.sensorId,
            "timestamp": decoded.timestamp.ToJsonString(),
            "object_count": len(decoded.objects),
            "object_id": decoded.objects[0].id,
            "object_type": decoded.objects[0].type,
            "bbox": [
                decoded.objects[0].bbox.leftX,
                decoded.objects[0].bbox.topY,
                decoded.objects[0].bbox.rightX,
                decoded.objects[0].bbox.bottomY,
            ],
            "confidence": decoded.objects[0].confidence,
            "pose_keypoints": len(decoded.objects[0].pose.keypoints),
            "embedding": list(decoded.objects[0].embedding.vector),
            "wire_sha256": _sha256(wire),
            "wire_roundtrip_byte_identical": True,
        },
        "spatial_3d_frame": {
            "raw_id": raw_object["id"],
            "raw_custom_field": raw_object["custom"],
            "flat_object_id": flat_object["object id"],
            "flat_location": flat_object["3d location"],
            "flat_scale": flat_object["3d bounding box scale"],
            "flat_rotation": flat_object["3d bounding box rotation"],
            "row_timestamp": row["timestamp"],
            "row_info": row["info"],
        },
        "agent_incident_aliases": {
            "Id": incident_aliases["Id"],
            "sensorId": incident_aliases["sensorId"],
            "timestamp": incident_aliases["timestamp"],
            "end": incident_aliases["end"],
            "objectIds": incident_aliases["objectIds"],
            "analyticsModule": incident_aliases["analyticsModule"],
            "type": incident_aliases["type"],
        },
        "adjacent_negatives": negatives,
    }


def _observe(root: Path) -> dict[str, Any]:
    with _isolated_product_modules() as (behavior, spatial, agent):
        return _observe_loaded(root, behavior, spatial, agent)


def execute() -> dict[str, Any]:
    contract = _load_contract()
    sources = _verify_sources(contract)
    binding = _verify_binding(contract)
    roots: list[Path] = []
    runs: list[dict[str, Any]] = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix="thor-nvschema-json-") as name:
            root = Path(name)
            roots.append(root)
            runs.append(_observe(root))
    if _canonical_bytes(runs[0]) != _canonical_bytes(runs[1]):
        raise QualificationError("independent observations are not deterministic")
    if any(root.exists() for root in roots):
        raise QualificationError("temporary root cleanup failed")
    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": contract["mode"],
        "result": "candidate_static_pass_non_advancing",
        "policy": contract["policy"],
        "binding": binding,
        "source_hashes": sources,
        "observations": runs[0],
        "determinism": {
            "independent_runs": 2,
            "byte_identical": True,
            "observation_sha256": _sha256(_canonical_bytes(runs[0])),
        },
        "confinement": {
            "private_temporary_roots": True,
            "cleanup_verified": True,
            "external_calls": 0,
            "warehouse_sample_bundle": "excluded",
            "counter_basis": "locked_source_and_import_boundary_audit",
            "import_state_restored": True,
        },
        "limitations": [
            "illustrative_contract_has_no_complete_json_schema_validator",
            "documented_event_enum_is_not_enforced_by_the_executed_frame_converter",
            "spatial_iterator_does_not_project_the_official_legacy_at_timestamp_field",
            "legacy_2d_string_objects_and_modern_3d_dictionary_objects_use_distinct_consumers",
            "full_behavior_test_import_is_blocked_by_host_numpy2_matplotlib_numpy1_abi_mismatch",
            "no_deployed_service_or_broker_protocol_roundtrip_executed",
        ],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
    }
    schema = _strict_json(LANE / "result.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise QualificationError(f"result schema rejection: {errors[0].message}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json", action="store_true", help="print the strict candidate receipt"
    )
    output.add_argument(
        "--check", action="store_true", help="run and print only the status"
    )
    args = parser.parse_args()
    try:
        result = execute()
    except Exception as exc:
        if args.json:
            print(
                json.dumps(
                    {"result": "candidate_static_fail_closed", "error": str(exc)}
                )
            )
        else:
            print(
                f"candidate static qualification failed closed: {exc}", file=sys.stderr
            )
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(result["result"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
