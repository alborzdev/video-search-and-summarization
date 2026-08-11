#!/usr/bin/env python3
"""Bind complete Video Analytics HTTP and read-only VA-MCP runtime evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CONTRACT_PATH = HERE / "contract.json"
SCHEMA_PATH = HERE / "receipt.schema.json"
RECEIPT_PATH = HERE / "runtime-receipt.json"


class EvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(EvidenceError(f"non-finite JSON: {token}")),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read strict JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path.name}")
    return value


def _locked_sources(contract: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for item in contract["source_locks"]:
        path = REPO / item["path"]
        if item["path"] in result or not path.is_file() or path.is_symlink() or _sha(path) != item["sha256"]:
            raise EvidenceError(f"source lock drifted: {item['path']}")
        result[item["path"]] = path
    return result


def build_receipt() -> dict[str, Any]:
    contract = _load(CONTRACT_PATH)
    sources = _locked_sources(contract)
    api_path = sources["deploy/docker/thor-local/qualification/video-analytics-api-runtime/runtime-receipt.json"]
    query_wrapper_path = sources["deploy/docker/thor-local/qualification/video-analytics-api-runtime/official-runtime-evidence-query-library.json"]
    kafka_wrapper_path = sources["deploy/docker/thor-local/qualification/video-analytics-api-runtime/official-runtime-evidence-optional-kafka.json"]
    api_contract_path = sources["deploy/docker/thor-local/qualification/video-analytics-api-runtime/contract.json"]
    va_path = sources["deploy/docker/thor-local/qualification/va-mcp-runtime-successor/runtime-receipt.json"]
    va_contract_path = sources["deploy/docker/thor-local/qualification/va-mcp-runtime-successor/contract.json"]
    va_schema_path = sources["deploy/docker/thor-local/qualification/va-mcp-runtime-successor/receipt.schema.json"]
    api = _load(api_path)
    query_wrapper = _load(query_wrapper_path)
    kafka_wrapper = _load(kafka_wrapper_path)
    va = _load(va_path)
    va_schema = _load(va_schema_path)

    get_ops = api.get("operations", {}).get("get", {})
    post_ops = api.get("operations", {}).get("post", {})
    negative_ops = api.get("operations", {}).get("post_negatives", {})
    brokerless = api.get("operations", {}).get("brokerless", {})
    semantic = get_ops.get("semantic_readbacks", {})
    fixtures = api.get("fixtures", {})
    cleanup = api.get("cleanup", {})
    if (
        api.get("status") != "passed"
        or api.get("openapi", {}).get("operation_count") != 56
        or api.get("openapi", {}).get("method_counts") != {"GET": 48, "POST": 8}
        or get_ops.get("exercised") != 48
        or get_ops.get("all_http_200") is not True
        or semantic.get("non_empty_data_endpoints") != 40
        or post_ops.get("exercised") != 8
        or post_ops.get("all_positive_201") is not True
        or negative_ops.get("exercised") != 8
        or negative_ops.get("no_5xx") is not True
        or api.get("request_counts", {}).get("status_5xx") != 0
        or fixtures.get("semantic_documents", {}).get("document_count") != 14
        or fixtures.get("semantic_documents", {}).get("index_count") != 13
        or fixtures.get("dynamic_config_checkpoint_observed") is not True
        or fixtures.get("dynamic_calibration_checkpoints_observed") is not True
        or brokerless.get("api_started") is not True
        or brokerless.get("non_kafka_endpoint", {}).get("http_status") != 200
        or brokerless.get("kafka_dependent_endpoint", {}).get("http_status") != 422
        or brokerless.get("kafka_dependent_endpoint", {}).get("exact_message_contract") is not True
        or brokerless.get("kafka_connection_attempt_observed") is not False
        or cleanup.get("failures") != []
        or not all(cleanup.get(key) is True for key in ("qualifier_indices_absent", "qualifier_templates_absent", "upload_file_set_exact", "disposable_container_absent", "brokerless_container_absent", "original_behavior_containers_restored"))
    ):
        raise EvidenceError("Video Analytics API runtime semantics differ")
    if (
        query_wrapper.get("result") != "passed_current"
        or query_wrapper.get("capability_id") != "runtime.video-analytics.query-and-library-contract"
        or query_wrapper.get("fixture", {}).get("sha256") != _sha(api_contract_path)
        or query_wrapper.get("observations", [{}])[0].get("value", {}).get("receipt_sha256") != _sha(api_path)
        or kafka_wrapper.get("result") != "passed_current"
        or kafka_wrapper.get("capability_id") != "behavior.video-analytics.optional-kafka"
        or kafka_wrapper.get("fixture", {}).get("sha256") != _sha(api_contract_path)
        or kafka_wrapper.get("observations", [{}])[0].get("value", {}).get("receipt_sha256") != _sha(api_path)
    ):
        raise EvidenceError("Video Analytics official wrapper binding differs")

    Draft202012Validator.check_schema(va_schema)
    va_errors = sorted(Draft202012Validator(va_schema).iter_errors(va), key=lambda error: list(error.path))
    va_queries = va.get("queries", {})
    if (
        va_errors
        or va.get("status") != "passed"
        or va.get("contract_sha256") != _sha(va_contract_path)
        or va.get("tool_surface", {}).get("tool_count") != 9
        or va_queries.get("unique_tool_count") != 8
        or va_queries.get("tool_call_count") != 9
        or va_queries.get("all_succeeded") is not True
        or va_queries.get("incidents", {}).get("count", 0) < 1
        or va_queries.get("specific_incident", {}).get("matched_first_incident") is not True
        or va.get("state") != {"docker_running_set_exact": True, "vst_sensor_set_exact": True, "writes_observed": False}
        or va.get("policy", {}).get("react_agent_calls") != 0
        or va.get("policy", {}).get("agent_generate_calls") != 0
    ):
        raise EvidenceError("VA-MCP runtime semantics differ")

    metric_probes = [va_queries[name] for name in ("places", "fov_histogram", "average_speeds", "analysis")]
    receipt = {
        "schema_version": 1,
        "package_id": contract["package_id"],
        "capability_ids": contract["capability_ids"],
        "official_indices": contract["official_indices"],
        "status": "passed",
        "contract_sha256": _sha(CONTRACT_PATH),
        "source_identity": {
            "api_receipt_sha256": _sha(api_path),
            "api_query_wrapper_sha256": _sha(query_wrapper_path),
            "api_optional_kafka_wrapper_sha256": _sha(kafka_wrapper_path),
            "va_mcp_receipt_sha256": _sha(va_path),
        },
        "video_analytics_api": {
            "image": api["runtime"]["api_image"],
            "openapi_operations": api["openapi"]["operation_count"],
            "get_operations": get_ops["exercised"],
            "post_operations": post_ops["exercised"],
            "data_bearing_gets_nonempty": semantic["non_empty_data_endpoints"],
            "positive_posts_201": post_ops["exercised"],
            "adjacent_negative_posts": negative_ops["exercised"],
            "http_5xx": api["request_counts"]["status_5xx"],
            "semantic_document_count": fixtures["semantic_documents"]["document_count"],
            "semantic_index_count": fixtures["semantic_documents"]["index_count"],
            "query_families": ["speed-flow-travel-occupancy-space", "objects-locations", "frames-bev-alerts-proximity", "behaviors-incidents-clustering", "tripwire-roi-amr-events", "dynamic-config-audit", "calibration-road-network-usd-images", "sensor-lookup"],
            "dynamic_config_checkpoint": fixtures["dynamic_config_checkpoint_observed"],
            "dynamic_calibration_checkpoints": fixtures["dynamic_calibration_checkpoints_observed"],
            "optional_kafka_contract": {
                "brokerless_started": brokerless["api_started"],
                "non_kafka_read_status": brokerless["non_kafka_endpoint"]["http_status"],
                "kafka_required_status": brokerless["kafka_dependent_endpoint"]["http_status"],
                "exact_error_contract": brokerless["kafka_dependent_endpoint"]["exact_message_contract"],
                "connection_attempt_observed": brokerless["kafka_connection_attempt_observed"],
            },
        },
        "va_mcp": {
            "image": va["runtime"]["image"],
            "healthy": va["runtime"]["healthy"],
            "transport": va["transport"]["protocol"],
            "tool_count": va["tool_surface"]["tool_count"],
            "read_only_unique_tools": va_queries["unique_tool_count"],
            "read_only_tool_calls": va_queries["tool_call_count"],
            "all_succeeded": va_queries["all_succeeded"],
            "sensor_count": va_queries["sensor_ids"]["count"],
            "vst_sensor_count": va_queries["vst_sensors"]["count"],
            "sensor_overlap_count": len(va_queries["sensor_overlap"]),
            "incident_count": va_queries["incidents"]["count"],
            "specific_incident_matched": va_queries["specific_incident"]["matched_first_incident"],
            "metric_probes_nonempty": all(probe.get("nonempty_response") is True for probe in metric_probes),
            "react_agent_advertised_not_invoked": va["tool_surface"]["react_agent_advertised_not_invoked"],
            "session_per_query": va["transport"]["session_per_query"],
        },
        "cleanup": {
            "api_qualifier_state_absent": all(cleanup[key] is True for key in ("qualifier_indices_absent", "qualifier_templates_absent", "upload_file_set_exact", "disposable_container_absent", "brokerless_container_absent")),
            "api_consumers_restored": cleanup["original_behavior_containers_restored"],
            "va_docker_running_set_exact": va["state"]["docker_running_set_exact"],
            "va_vst_sensor_set_exact": va["state"]["vst_sensor_set_exact"],
        },
        "policy": contract["policy"],
    }
    schema = _load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=lambda error: list(error.path))
    if errors:
        raise EvidenceError(f"receipt schema violation: {errors[0].message}")
    return receipt


def _write(value: dict[str, Any]) -> None:
    rendered = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=HERE, delete=False) as stream:
            temporary = stream.name
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, RECEIPT_PATH)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "write", "check"))
    args = parser.parse_args()
    try:
        value = build_receipt()
        if args.mode == "plan":
            print(json.dumps({"status": "ready", "official_indices": value["official_indices"], "writes_or_lifecycle_actions": False}, sort_keys=True))
        elif args.mode == "write":
            _write(value)
            print(json.dumps({"status": "passed", "receipt_sha256": _sha(RECEIPT_PATH)}, sort_keys=True))
        elif not RECEIPT_PATH.is_file() or RECEIPT_PATH.read_bytes() != (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"):
            raise EvidenceError("checked receipt drifted")
        return 0
    except (EvidenceError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
