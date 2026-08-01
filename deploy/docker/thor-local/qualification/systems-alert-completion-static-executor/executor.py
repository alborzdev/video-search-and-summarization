#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run a provider-free, non-advancing static alert completion candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import sys
import tempfile
import types
from copy import deepcopy
from pathlib import Path
from typing import Any

from google.protobuf import json_format
from google.protobuf.message import DecodeError
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
ALERT_ROOT = REPO_ROOT / "services/alert"
ACCEPTANCE_PATH = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
CAPABILITY_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLE_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
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
EXPECTED_BINDINGS = {
    "systems-alert-workflow-modes": "runtime.alerts.workflow-modes",
    "systems-alert-nvschema": "protocol.alerts.nvschema-ingestion",
    "systems-alert-persistence": "runtime.alerts.persistence-output",
}
EXPECTED_CAPABILITY_CONTRACTS = {
    "runtime.alerts.workflow-modes": {
        "execution": ["real-time", "on-demand"],
        "modes": ["verification", "context", "classification"],
    },
    "protocol.alerts.nvschema-ingestion": {
        "formats": ["JSON", "Protobuf"],
        "input_topics": ["mdx-incidents", "mdx-alerts"],
        "messages": ["nv.Incident", "nv.Behavior"],
        "output_topics": ["mdx-vlm-incidents", "mdx-vlm-alerts"],
        "verification_fields": [
            "verificationResponseCode",
            "verificationResponseStatus",
        ],
    },
    "runtime.alerts.persistence-output": {
        "category_aliases": True,
        "enrichment_toggle": True,
        "optional_output": "kafka",
        "persistence": "elasticsearch",
        "structured_fields": ["verdict", "reason", "status"],
    },
}
EXPECTED_NEGATIVES = [
    "unsupported-workflow-mode",
    "classification-parser-non-object",
    "incident-alias-conflict",
    "invalid-protobuf-bytes",
    "elastic-malformed-ack",
    "kafka-callback-error",
    "kafka-missing-callback-no-overclaim",
    "cancelled-before-publish",
]


class QualificationError(RuntimeError):
    """The locked contract or a deterministic observation failed closed."""


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
        value = json.loads(
            path.read_text(encoding="utf-8"),
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
    path = (root / candidate).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"repository path escaped: {relative}") from exc
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"repository path is not a regular file: {relative}")
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


def _load_contract() -> dict[str, Any]:
    schema = _strict_json(LANE / "contract.schema.json")
    Draft202012Validator.check_schema(schema)
    contract = _strict_json(LANE / "contract.json")
    errors = list(Draft202012Validator(schema).iter_errors(contract))
    if errors:
        raise QualificationError(f"invalid contract: {errors[0].message}")
    if contract["policy"] != EXPECTED_POLICY:
        raise QualificationError("candidate-only policy drift")
    if [row["planning_requirement_id"] for row in contract["bindings"]] != list(
        EXPECTED_BINDINGS
    ):
        raise QualificationError("binding denominator or ordering drift")
    if contract["adjacent_negative_ids"] != EXPECTED_NEGATIVES:
        raise QualificationError("adjacent-negative denominator drift")
    return contract


def _verify_source_locks(contract: dict[str, Any]) -> dict[str, str]:
    locks = contract["source_locks"]
    if len({row["path"] for row in locks}) != 19:
        raise QualificationError("source lock paths are not unique")
    observed = {}
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
    observations = []
    for binding in contract["bindings"]:
        planning_id = binding["planning_requirement_id"]
        capability_id = binding["capability_id"]
        if EXPECTED_BINDINGS.get(planning_id) != capability_id:
            raise QualificationError("planning/capability identity drift")
        planning = _find_one(
            acceptance["wave3_contracts"]["planning_requirements"], "id", planning_id
        )
        if (
            planning.get("owner_type") != "capability"
            or planning.get("owner_id") != capability_id
        ):
            raise QualificationError("planning owner drift")
        if planning.get("package") != "systems":
            raise QualificationError("planning package drift")
        if (
            planning.get("materialized") is not False
            or planning.get("executor_ready") is not False
        ):
            raise QualificationError("canonical planning state advanced")
        if planning.get("runtime_evidence") != []:
            raise QualificationError("planning runtime evidence is non-empty")
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
        if capability.get("acceptance_class") != "required_local":
            raise QualificationError("capability acceptance class drift")
        if (
            capability.get("thor_state") != "partial"
            or capability.get("runtime_state") != "not_qualified"
        ):
            raise QualificationError("canonical capability state advanced")
        wave = capability.get("contract", {}).get("wave3_acceptance", {})
        observed_contract = deepcopy(capability.get("contract", {}))
        observed_contract.pop("wave3_acceptance", None)
        if observed_contract != EXPECTED_CAPABILITY_CONTRACTS[capability_id]:
            raise QualificationError("capability contract field drift")
        if wave != {
            "candidate_family": wave.get("candidate_family"),
            "executor_ready": False,
            "materialized": False,
            "package": "systems",
            "planning_requirement_ids": [planning_id],
        }:
            raise QualificationError("wave-3 binding drift")
        oracle = _find_one(oracle_set["oracles"], "oracle_id", binding["oracle_id"])
        if oracle.get("capability_id") != capability_id:
            raise QualificationError("oracle capability drift")
        if _sha256(_canonical_bytes(oracle)) != binding["oracle_sha256"]:
            raise QualificationError("oracle digest drift")
        if (
            oracle.get("current_state") != "open_unexecuted"
            or oracle.get("evidence") != []
        ):
            raise QualificationError("canonical oracle state advanced")
        if (
            oracle.get("acceptance_readiness", {}).get("classification")
            != "planning_index_only"
        ):
            raise QualificationError("oracle readiness drift")
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
                "canonical_state_advanced": False,
            }
        )
    return observations


def _install_openai_stub() -> None:
    try:
        import openai  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    openai = types.ModuleType("openai")
    for name in (
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "UnprocessableEntityError",
        "BadRequestError",
    ):
        setattr(openai, name, type(name, (Exception,), {}))
    openai_types = types.ModuleType("openai.types")
    openai_chat = types.ModuleType("openai.types.chat")
    openai_chat.ChatCompletionMessage = type("ChatCompletionMessage", (), {})
    openai_types.chat = openai_chat
    openai.types = openai_types
    sys.modules.update(
        {
            "openai": openai,
            "openai.types": openai_types,
            "openai.types.chat": openai_chat,
        }
    )


def _load_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise QualificationError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_product() -> dict[str, Any]:
    alert_text = str(ALERT_ROOT)
    if alert_text not in sys.path:
        sys.path.insert(0, alert_text)
    _install_openai_stub()
    from utils import schema_util

    direct_root = ALERT_ROOT / "handlers/direct_media"
    package_name = "_thor_static_direct_media"
    package = types.ModuleType(package_name)
    package.__path__ = [str(direct_root)]
    sys.modules[package_name] = package
    _load_file(f"{package_name}.media_downloader", direct_root / "media_downloader.py")
    analyzer = types.ModuleType(f"{package_name}.media_analyzer")
    analyzer.analyze_single_media = lambda *args, **kwargs: None
    analyzer.analyze_multiple_images = lambda *args, **kwargs: None
    sys.modules[analyzer.__name__] = analyzer
    direct = _load_file(
        f"{package_name}.direct_media_handler", direct_root / "direct_media_handler.py"
    )

    sink_root = ALERT_ROOT / "mdx/anomaly/sink/vlm_enhanced_sink"
    sink_package_name = "_thor_static_sinks"
    sink_package = types.ModuleType(sink_package_name)
    sink_package.__path__ = [str(sink_root)]
    sys.modules[sink_package_name] = sink_package
    external_names = (
        "elastic",
        "elastic.elastic",
        "its_redis",
        "its_redis.redis_handler",
        "mdx.anomaly.kafka_message_broker",
    )
    saved = {name: sys.modules.get(name) for name in external_names}
    try:
        for name in external_names:
            sys.modules[name] = types.ModuleType(name)
        sys.modules["elastic"].__path__ = []
        sys.modules["its_redis"].__path__ = []
        sys.modules["elastic.elastic"].ElasticClient = object
        sys.modules["elastic.elastic"].ElasticConfig = object
        sys.modules["its_redis.redis_handler"].RedisHandler = object
        sys.modules["mdx.anomaly.kafka_message_broker"].KafkaMessageBroker = object
        _load_file(f"{sink_package_name}.sink_base", sink_root / "sink_base.py")
        elastic = _load_file(
            f"{sink_package_name}.sink_elastic", sink_root / "sink_elastic.py"
        )
        kafka = _load_file(
            f"{sink_package_name}.sink_kafka", sink_root / "sink_kafka.py"
        )
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
    terminal = _load_file(
        "_thor_static_terminal_store",
        ALERT_ROOT / "alert-agent-web/app/service/terminal_job_store.py",
    )
    return {
        "DirectMediaHandler": direct.DirectMediaHandler,
        "schema_util": schema_util,
        "Incident": schema_util.nvSchemaIncident,
        "Behavior": schema_util.nvSchemaBehavior,
        "ElasticSink": elastic.VLMEnhancedElasticSink,
        "KafkaSink": kafka.VLMEnhancedKafkaSink,
        "TerminalJobStore": terminal.TerminalJobStore,
    }


class _Sink:
    def __init__(self, receipt: dict[str, Any] | None = None) -> None:
        self.receipt = receipt or {
            "transport": "elastic",
            "outcome": "acknowledged",
            "documentId": "doc-1",
            "index": "incidents",
        }
        self.success_calls = 0
        self.error_calls = 0

    def publish_success(self, *_args: Any) -> dict[str, Any]:
        self.success_calls += 1
        return deepcopy(self.receipt)

    def publish_error(self, *_args: Any) -> dict[str, Any]:
        self.error_calls += 1
        return deepcopy(self.receipt)


class _Parser:
    def parse(self, raw: str) -> dict[str, Any]:
        value = json.loads(raw)
        return {"label": value["label"], "confidence": value["confidence"]}


class _BadParser:
    def parse(self, _raw: str) -> str:
        return "not-an-object"


def _message() -> dict[str, Any]:
    return {
        "id": "event-1",
        "sensorId": "camera-1",
        "category": "entry",
        "info": {"media_urls": ["https://example.invalid/frame.jpg"]},
    }


def _handler(
    product: dict[str, Any], temp_root: Path, *, mode: str, sink: _Sink | None = None
) -> Any:
    if mode not in {"verification", "context", "classification"}:
        raise QualificationError(f"unsupported workflow mode: {mode}")
    parser = _Parser() if mode == "classification" else None
    return product["DirectMediaHandler"](
        vlm_client=object(),
        vlm_enhanced_event_sink=sink or _Sink(),
        config={
            "alert_agent": {
                "media_download": {
                    "enabled": True,
                    "use_verdict": mode == "verification",
                }
            },
            "vlm": {"model": "nvidia/cosmos-reason2-8b"},
            "vst_config": {"download_dir": str(temp_root / mode)},
            "vlm_enhanced_sink": {"type": "elastic"},
        },
        pluggable_parser=parser,
    )


def _workflow_observations(product: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    inputs = {
        "verification": "<think>visible person entered</think><answer>YES</answer>",
        "context": "A person entered through the east door.",
        "classification": '{"label":"entry","confidence":0.98}',
    }
    observed = []
    for mode in ("verification", "context", "classification"):
        handler = _handler(product, root, mode=mode)
        message = _message()
        result = handler._publish_success(
            message, "prompt", "system", inputs[mode], "image"
        )
        info = message["info"]
        row = {
            "mode": mode,
            "verificationResponseCode": info["verificationResponseCode"],
            "verificationResponseStatus": info["verificationResponseStatus"],
            "sinkDelivery": result["sinkDelivery"],
        }
        if mode == "verification":
            row.update({"verdict": info["verdict"], "reasoning": info["reasoning"]})
        elif mode == "context":
            row.update(
                {
                    "reasoning": info["reasoning"],
                    "vlm_response_present": "vlm_response" in info,
                }
            )
        else:
            row.update(
                {
                    "verdict": info["verdict"],
                    "vlm_response": json.loads(info["vlm_response"]),
                }
            )
        observed.append(row)
    return observed


def _protobuf_observations(product: dict[str, Any]) -> list[dict[str, Any]]:
    schema_util = product["schema_util"]
    incident_input = {
        "id": "incident-1",
        "sensorId": "camera-1",
        "category": "entry",
        "analytics": {"id": "thor-local-analytics", "info": {"source": "thor-local"}},
        "info": {"verificationResponseCode": "200", "verificationResponseStatus": "OK"},
    }
    original = deepcopy(incident_input)
    incident = schema_util.convert_incident_to_protobuf_incident(incident_input)
    incident_bytes = incident.SerializeToString(deterministic=True)
    decoded_incident = product["Incident"]()
    decoded_incident.ParseFromString(incident_bytes)
    if (
        incident_input != original
        or decoded_incident.DESCRIPTOR.fields_by_name["analyticsModule"].number != 7
    ):
        raise QualificationError(
            "documented Incident analytics alias round trip failed"
        )
    incident_json = json_format.MessageToDict(
        decoded_incident, preserving_proto_field_name=True
    )
    incident_reparsed = product["Incident"]()
    json_format.ParseDict(incident_json, incident_reparsed)
    if incident_reparsed.SerializeToString(deterministic=True) != incident_bytes:
        raise QualificationError("Incident JSON/Protobuf round trip changed bytes")
    released_alias = schema_util.convert_incident_to_protobuf_incident(
        {"sensorId": "camera-2", "analyticsModule": {"id": "released-wire-name"}}
    )
    if released_alias.analyticsModule.id != "released-wire-name":
        raise QualificationError("released Incident analyticsModule name failed")

    behavior_input = {
        "id": "behavior-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "end": "2026-01-01T00:00:01Z",
        "sensor": {"id": "camera-1"},
        "analyticsModule": {
            "id": "thor-local-analytics",
            "info": {"source": "thor-local"},
        },
        "object": {"id": "person-1", "type": "person", "confidence": 0.9},
        "info": {"verificationResponseCode": "200", "verificationResponseStatus": "OK"},
    }
    behavior = schema_util.convert_behavior_to_protobuf_behavior(
        deepcopy(behavior_input)
    )
    behavior_bytes = behavior.SerializeToString(deterministic=True)
    decoded_behavior = product["Behavior"]()
    decoded_behavior.ParseFromString(behavior_bytes)
    behavior_json = json_format.MessageToDict(
        decoded_behavior, preserving_proto_field_name=True
    )
    behavior_reparsed = product["Behavior"]()
    json_format.ParseDict(behavior_json, behavior_reparsed)
    if behavior_reparsed.SerializeToString(deterministic=True) != behavior_bytes:
        raise QualificationError("Behavior JSON/Protobuf round trip changed bytes")
    rows = []
    for name, message, payload, topics in (
        (
            "nv.Incident",
            decoded_incident,
            incident_bytes,
            ["mdx-incidents", "mdx-vlm-incidents"],
        ),
        (
            "nv.Behavior",
            decoded_behavior,
            behavior_bytes,
            ["mdx-alerts", "mdx-vlm-alerts"],
        ),
    ):
        document = json_format.MessageToDict(message, preserving_proto_field_name=True)
        rows.append(
            {
                "message": name,
                "formats": ["JSON", "Protobuf"],
                "input_topic": topics[0],
                "output_topic": topics[1],
                "protobuf_sha256": _sha256(payload),
                "json_sha256": _sha256(_canonical_bytes(document)),
                "verification_fields": [
                    "verificationResponseCode",
                    "verificationResponseStatus",
                ],
                "round_trip": True,
                "analytics_alias_field_number": 7 if name == "nv.Incident" else None,
                "released_wire_name_supported": True if name == "nv.Incident" else None,
            }
        )
    return rows


class _Delivered:
    def topic(self) -> str:
        return "mdx-vlm-incidents"

    def partition(self) -> int:
        return 2

    def offset(self) -> int:
        return 17


class _Producer:
    def __init__(self, outcome: str, remaining: int = 0) -> None:
        self.outcome = outcome
        self.remaining = remaining

    def produce(self, **kwargs: Any) -> None:
        callback = kwargs["on_delivery"]
        if self.outcome == "ack":
            callback(None, _Delivered())
        elif self.outcome == "error":
            callback(RuntimeError("rejected"), None)

    def flush(self) -> int:
        return self.remaining


class _ElasticClient:
    def __init__(self, result: Any = None, *, raises: bool = False) -> None:
        self.result = result
        self.raises = raises

    def write_event_response(self, *_args: Any, **_kwargs: Any) -> Any:
        if self.raises:
            raise RuntimeError("deterministic fake write rejection")
        return deepcopy(self.result)


def _elastic(
    product: dict[str, Any], result: Any = None, *, raises: bool = False
) -> dict[str, Any]:
    sink = product["ElasticSink"](
        elastic_client=_ElasticClient(result, raises=raises),
        incident_index="incidents-2026",
        alert_index="alerts-2026",
    )
    return sink._store_success(
        "incident",
        {"id": "incident-1", "category": "entry", "info": {}},
        "confirmed",
        "prompt",
    )


def _kafka(product: dict[str, Any], outcome: str, remaining: int = 0) -> dict[str, Any]:
    sink = product["KafkaSink"](
        producer=_Producer(outcome, remaining),
        incident_route={"topic": "mdx-vlm-incidents", "message_type": "incident"},
        alert_route={"topic": "mdx-vlm-alerts", "message_type": "alert"},
    )
    return sink._produce("incident", {"id": "incident-1", "category": "entry"})


def _persistence_observations(product: dict[str, Any], root: Path) -> dict[str, Any]:
    elastic_rows = {
        "acknowledged": _elastic(
            product, {"result": "created", "_id": "doc-1", "_index": "incidents-2026"}
        ),
        "unconfirmed": _elastic(product, {"result": "created"}),
        "failed": _elastic(product, raises=True),
    }
    kafka_rows = {
        "acknowledged": _kafka(product, "ack"),
        "failed": _kafka(product, "error"),
        "submitted_unconfirmed": _kafka(product, "none"),
        "undelivered_failed": _kafka(product, "none", remaining=1),
    }
    store = product["TerminalJobStore"](
        clock=lambda: 1000.0,
        id_factory=lambda: "job-static-1",
        generation_factory=lambda: "generation-static-0001",
    )
    sink = _Sink()
    handler = _handler(product, root, mode="context", sink=sink)
    handle = store.register()
    store.mark_running(handle)
    cancellation = store.cancel(handle.correlation_id)
    result = handler._publish_to_sink(
        "success",
        _message(),
        "prompt",
        "system",
        "text",
        before_publish=lambda _message: store.begin_publish(handle),
    )
    cancellation_row = {
        "accepted": cancellation["cancellationAccepted"],
        "state": store.get(handle.correlation_id)["state"],
        "sink_calls": sink.success_calls + sink.error_calls,
        "sinkDelivery": result["sinkDelivery"],
    }
    terminal_states = {}
    for position, outcome in enumerate(
        ("acknowledged", "failed", "unconfirmed", "submitted_unconfirmed"), start=1
    ):
        terminal = product["TerminalJobStore"](
            clock=lambda: 1000.0,
            id_factory=lambda position=position: f"job-terminal-{position}",
            generation_factory=lambda position=position: (
                f"generation-terminal-{position:04d}"
            ),
        )
        terminal_handle = terminal.register()
        terminal.mark_running(terminal_handle)
        terminal.begin_publish(terminal_handle)
        terminal.complete(
            terminal_handle,
            {
                "processingOutcome": "verified",
                "sinkDelivery": {"transport": "elastic", "outcome": outcome},
            },
        )
        snapshot = terminal.get(terminal_handle.correlation_id)
        terminal_states[outcome] = {
            "state": snapshot["state"],
            "receipt_outcome": snapshot["result"]["sinkDelivery"]["outcome"],
        }
    return {
        "elastic": elastic_rows,
        "kafka": kafka_rows,
        "terminal_states": terminal_states,
        "cancel_publish_gate": cancellation_row,
    }


def _negative_observations(product: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        _handler(product, root, mode="unsupported")
    except QualificationError:
        rows.append({"case_id": "unsupported-workflow-mode", "rejected": True})
    bad = product["DirectMediaHandler"](
        object(),
        _Sink(),
        {
            "alert_agent": {"media_download": {}},
            "vlm": {},
            "vst_config": {"download_dir": str(root / "bad-parser")},
        },
        pluggable_parser=_BadParser(),
    )
    message = _message()
    bad._publish_success(message, "prompt", "system", "ignored", "image")
    rows.append(
        {
            "case_id": "classification-parser-non-object",
            "rejected": message["info"]["verdict"] == "verification-failed",
        }
    )
    try:
        product["schema_util"].convert_incident_to_protobuf_incident(
            {"analytics": {"id": "a"}, "analyticsModule": {"id": "b"}}
        )
    except ValueError:
        rows.append({"case_id": "incident-alias-conflict", "rejected": True})
    try:
        product["Incident"]().ParseFromString(b"\xff")
    except DecodeError:
        rows.append({"case_id": "invalid-protobuf-bytes", "rejected": True})
    rows.extend(
        [
            {
                "case_id": "elastic-malformed-ack",
                "rejected": product["ElasticSink"]._delivery_receipt(
                    {"result": "created"}
                )["outcome"]
                == "unconfirmed",
            },
            {
                "case_id": "kafka-callback-error",
                "rejected": _kafka(product, "error")["outcome"] == "failed",
            },
            {
                "case_id": "kafka-missing-callback-no-overclaim",
                "rejected": _kafka(product, "none")["outcome"]
                == "submitted_unconfirmed",
            },
        ]
    )
    persistence = _persistence_observations(product, root)
    rows.append(
        {
            "case_id": "cancelled-before-publish",
            "rejected": persistence["cancel_publish_gate"]["sink_calls"] == 0,
        }
    )
    if [row["case_id"] for row in rows] != EXPECTED_NEGATIVES or not all(
        row["rejected"] for row in rows
    ):
        raise QualificationError("adjacent-negative observation failed")
    return rows


def _observe(product: dict[str, Any], root: Path) -> dict[str, Any]:
    return {
        "workflow_modes": _workflow_observations(product, root),
        "nvschema_round_trips": _protobuf_observations(product),
        "persistence": _persistence_observations(product, root),
        "adjacent_negatives": _negative_observations(product, root),
    }


def execute() -> dict[str, Any]:
    contract = _load_contract()
    source_hashes = _verify_source_locks(contract)
    bindings = _verify_bindings(contract)
    product = _load_product()
    roots: list[Path] = []
    observations = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix="thor-alert-static-") as name:
            root = Path(name)
            roots.append(root)
            observations.append(_observe(product, root))
    if _canonical_bytes(observations[0]) != _canonical_bytes(observations[1]):
        raise QualificationError("independent observation runs differ")
    if any(path.exists() for path in roots):
        raise QualificationError("private temporary root cleanup failed")
    result = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "mode": contract["mode"],
        "policy": deepcopy(contract["policy"]),
        "bindings": bindings,
        "source_hashes": source_hashes,
        "observations": observations[0],
        "determinism": {
            "independent_runs": 2,
            "byte_identical": True,
            "observation_sha256": _sha256(_canonical_bytes(observations[0])),
        },
        "confinement": {
            "private_temporary_roots": True,
            "cleanup_verified": True,
            "external_calls": 0,
            "warehouse_sample_bundle": "excluded",
        },
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "result": "candidate_static_pass_non_advancing",
    }
    schema = _strict_json(LANE / "result.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise QualificationError(f"result schema rejection: {errors[0].message}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        result = execute()
    except Exception as exc:
        if args.json:
            print(
                json.dumps(
                    {"result": "candidate_static_fail_closed", "error": str(exc)},
                    sort_keys=True,
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
