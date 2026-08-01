#!/usr/bin/env python3
"""Candidate-only, file-only executor for advertised-entry gap wave three."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 1_000_000

EXPECTED_SOURCE_PLAN = {
    "path": "deploy/docker/thor-local/qualification/advertised-entry-gaps/plan.json",
    "raw_sha256": "dd3c8cbbcae859137e73da4a8d4d9227f535dd674979b5d9e8f5cf25b885d122",
    "plan_payload_sha256": "97cb92ffb83d05388759f7428324344f91ec294116e5d24721c1ba21d994ab7d",
}
EXPECTED_SOURCE_MANIFEST = {
    "path": "deploy/docker/thor-local/parity/manifest.json",
    "raw_sha256": "6b041fbd169649b6dac5e68908e4a6dd219da9160cf72594219058885a9b9127",
}
EXPECTED_PREDECESSORS = [
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors/inventory.json",
        "raw_sha256": "91406a15ff1340b9b4dba988507470234971fa4905997bc52e64fb983fc12a18",
    },
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave2/inventory.json",
        "raw_sha256": "2c14f8ae5ade22ccbc556a844b4fcb63661048826660073fb21c5f882047c5d2",
    },
]

CAPTIONS = "services/rtvi/rt-vlm/src/api_models/captions.py"
NIM_COMPAT = "services/rtvi/rt-vlm/src/api_models/nim_compat.py"
LIVE_STREAM = "services/rtvi/rt-vlm/src/api_models/live_stream.py"
FILE_MODELS = "services/rtvi/rt-vlm/src/api_models/file.py"
VLM_SERVER = "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py"
STREAM_HANDLER = "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py"
OPENAI_COMPAT = "services/rtvi/rt-vlm/src/models/openai_compat/openai_compat_model.py"
VLLM_COMPAT = "services/rtvi/rt-vlm/src/models/vllm_compatible/vllm_compatible_model.py"
OTEL_HELPER = "services/rtvi/rt-vlm/src/utils/otel_helper.py"
RT_VLM_README = "services/rtvi/rt-vlm/README.md"
AGENT_WORKER = "services/agent/src/vss_agents/api/custom_fastapi_worker.py"
VIDEO_INGEST = "services/agent/src/vss_agents/api/video_ingest.py"
VIDEO_DELETE = "services/agent/src/vss_agents/api/video_delete.py"
RTSP_INGEST = "services/agent/src/vss_agents/api/rtsp_ingest.py"
RTSP_DELETE = "services/agent/src/vss_agents/api/rtsp_delete.py"
VA_MCP_README = "services/agent/src/vss_agents/video_analytics/README.md"
VA_MCP_COMPOSE = "deploy/docker/services/agent/compose.yml"
LVS_MCP = "services/video-summarization/src/lvs_mcp.py"
LVS_SERVER = "services/video-summarization/src/via_server.py"
LVS_COMPOSE = "deploy/docker/services/video-summarization/compose.yml"
VIOS_MCP_SERVER = "services/vios/mcp/src/server.py"
VIOS_MCP_README = "services/vios/mcp/README.md"
MV3DT_APP = (
    "deploy/docker/industry-profiles/warehouse-operations/"
    "warehouse-mv3dt-app/warehouse-mv3dt-app.yml"
)
MV3DT_THOR = "deploy/docker/thor-local/warehouse-mv3dt.compose.yml"


EXPECTED_CASE_BINDINGS = {
    "manifest-gap.video-summarization-live.05-sse-mcp-server": (
        "/features/2/advertised/5", "lvs_sse_mcp_source", {LVS_MCP, LVS_SERVER, LVS_COMPOSE}
    ),
    "manifest-gap.rt-vlm-media.08-categories": (
        "/features/8/advertised/8", "category_source", {CAPTIONS, STREAM_HANDLER}
    ),
    "manifest-gap.rt-vlm-media.10-audio-transcript": (
        "/features/8/advertised/10", "audio_transcript_source", {CAPTIONS, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.00-openai-compatible-chat-completions": (
        "/features/9/advertised/0", "openai_routes_source", {NIM_COMPAT, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.01-text-only-chat": (
        "/features/9/advertised/1", "text_chat_source", {NIM_COMPAT, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.02-multimodal-multi-turn-chat": (
        "/features/9/advertised/2", "multimodal_chat_source", {NIM_COMPAT, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.03-token-sse": (
        "/features/9/advertised/3", "token_sse_source", {NIM_COMPAT, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.04-original-stream-api": (
        "/features/9/advertised/4", "original_stream_source", {LIVE_STREAM, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.05-cv-compatible-stream-api": (
        "/features/9/advertised/5", "cv_stream_source", {LIVE_STREAM, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.06-file-api": (
        "/features/9/advertised/6", "file_api_source", {FILE_MODELS, VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-api.07-health-metadata-models-metrics": (
        "/features/9/advertised/7", "service_info_source", {VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-models.04-remote-openai-compatible-endpoint": (
        "/features/10/advertised/4", "remote_endpoint_source", {OPENAI_COMPAT, RT_VLM_README}
    ),
    "manifest-gap.rt-vlm-performance-observability.03-vllm-tuning": (
        "/features/11/advertised/3", "vllm_tuning_source", {VLLM_COMPAT, RT_VLM_README}
    ),
    "manifest-gap.rt-vlm-performance-observability.05-kafka-redis-error-publication": (
        "/features/11/advertised/5", "error_publication_source", {STREAM_HANDLER, RT_VLM_README}
    ),
    "manifest-gap.rt-vlm-performance-observability.06-prometheus-and-opentelemetry": (
        "/features/11/advertised/6", "telemetry_source", {OTEL_HELPER, VLM_SERVER}
    ),
    "manifest-gap.rt-cv-3d-mv3dt.04-compose-deployment": (
        "/features/15/advertised/4", "mv3dt_compose_source", {MV3DT_APP, MV3DT_THOR}
    ),
    "manifest-gap.agent-and-mcp-apis.01-health": (
        "/features/27/advertised/1", "agent_health_source", {AGENT_WORKER}
    ),
    "manifest-gap.agent-and-mcp-apis.02-upload-handshake-and-completion": (
        "/features/27/advertised/2", "upload_routes_source", {AGENT_WORKER, VIDEO_INGEST}
    ),
    "manifest-gap.agent-and-mcp-apis.03-video-delete": (
        "/features/27/advertised/3", "video_delete_source", {AGENT_WORKER, VIDEO_DELETE}
    ),
    "manifest-gap.agent-and-mcp-apis.04-rtsp-add-delete": (
        "/features/27/advertised/4", "rtsp_routes_source", {AGENT_WORKER, RTSP_INGEST, RTSP_DELETE}
    ),
    "manifest-gap.agent-and-mcp-apis.05-va-mcp": (
        "/features/27/advertised/5", "va_mcp_source", {VA_MCP_README, VA_MCP_COMPOSE}
    ),
    "manifest-gap.agent-and-mcp-apis.06-lvs-mcp": (
        "/features/27/advertised/6", "lvs_mcp_source", {LVS_MCP, LVS_SERVER, LVS_COMPOSE}
    ),
    "manifest-gap.agent-and-mcp-apis.07-vios-mcp": (
        "/features/27/advertised/7", "vios_mcp_source", {VIOS_MCP_SERVER, VIOS_MCP_README}
    ),
}


CONTRACT_FRAGMENTS = {
    "lvs_sse_mcp_source": {
        LVS_MCP: ["SseServerTransport", 'SseServerTransport("/messages")', 'path == "/sse"', "LVS_MCP_PORT"],
        LVS_SERVER: ["LVS_ENABLE_MCP", "run_mcp_server", "asyncio.create_task"],
        LVS_COMPOSE: ["LVS_MCP_PORT=${LVS_MCP_PORT:-38112}", "LVS_ENABLE_MCP=${LVS_ENABLE_MCP:-false}"],
    },
    "category_source": {
        CAPTIONS: ["alert_category: Optional[str]", "Used for incident.category"],
        STREAM_HANDLER: ['incident.info["alertCategory"] = alert_category'],
    },
    "audio_transcript_source": {
        CAPTIONS: ["audio_transcript: Optional[str]", "Audio transcript for this chunk"],
        VLM_SERVER: ["if enable_audio and resp.audio_transcript", 'chunk_response["audio_transcript"]'],
    },
    "openai_routes_source": {
        NIM_COMPAT: ["class ChatCompletionRequest", "class CompletionRequest"],
        VLM_SERVER: ['f"{API_PREFIX}/chat/completions"', 'f"{API_PREFIX}/completions"'],
    },
    "text_chat_source": {
        NIM_COMPAT: ["class ChatMessage", 'Literal["system", "user", "assistant"]'],
        VLM_SERVER: ["text_only_stream_generator", "For text-only"],
    },
    "multimodal_chat_source": {
        NIM_COMPAT: ["class ContentPart", 'Literal["text", "image_url", "video_url"]', "multi-turn conversations"],
        VLM_SERVER: ["chat_messages", "get_media_urls"],
    },
    "token_sse_source": {
        NIM_COMPAT: ["stream: Optional[bool]", "class ChatCompletionChoice"],
        VLM_SERVER: ["EventSourceResponse(chat_message_generator()", 'yield "[DONE]"'],
    },
    "original_stream_source": {
        LIVE_STREAM: ["original RTVI stream management models", "class AddLiveStreams", "class DeleteLiveStreamsRequest"],
        VLM_SERVER: ['f"{API_PREFIX}/streams/add"', 'f"{API_PREFIX}/streams/delete/{{stream_id}}"'],
    },
    "cv_stream_source": {
        LIVE_STREAM: ["CV-Compatible Stream API Models", "class StreamAddRequest", "class StreamRemoveRequest"],
        VLM_SERVER: ['f"{API_PREFIX}/stream/add"', 'f"{API_PREFIX}/stream/remove"'],
    },
    "file_api_source": {
        FILE_MODELS: ["class AddFileInfoResponse", "class DeleteFileResponse", "class ListFilesResponse"],
        VLM_SERVER: ['f"{API_PREFIX}/files"', 'f"{API_PREFIX}/files/{{file_id}}"', 'f"{API_PREFIX}/files/{{file_id}}/content"'],
    },
    "service_info_source": {
        VLM_SERVER: [
            'f"{API_PREFIX}/metrics"', 'f"{API_PREFIX}/metadata"', 'f"{API_PREFIX}/models"',
            'f"{API_PREFIX}/health/live"', 'f"{API_PREFIX}/health/ready"',
        ],
    },
    "remote_endpoint_source": {
        OPENAI_COMPAT: ["VIA_VLM_ENDPOINT", "VIA_VLM_OPENAI_MODEL_DEPLOYMENT_NAME", "OpenAI(base_url=base_url"],
        RT_VLM_README: ["remote OpenAI-compatible endpoints", "VLM_MODEL_TO_USE=openai-compat"],
    },
    "vllm_tuning_source": {
        VLLM_COMPAT: ["VLLM_GPU_MEMORY_UTILIZATION", "VLLM_MAX_NUM_BATCHED_TOKENS", "VLLM_KV_CACHE_MEMORY_BYTES", "VLLM_ENABLE_PREFIX_CACHING"],
        RT_VLM_README: ["VLLM_DISABLE_MM_PREPROCESSOR_CACHE", "VLLM_MM_ENCODER_ATTN_BACKEND"],
    },
    "error_publication_source": {
        STREAM_HANDLER: ["ENABLE_REDIS_ERROR_MESSAGES", "KafkaProducer", "redis.Redis", "ERROR_MESSAGE_TOPIC"],
        RT_VLM_README: ["Using Redis for Error Messages", "Kafka Consumer"],
    },
    "telemetry_source": {
        OTEL_HELPER: ["def init_otel", "def get_prometheus_metrics", "OTEL_EXPORTER_OTLP_ENDPOINT"],
        VLM_SERVER: ['f"{API_PREFIX}/metrics"', "init_otel", "get_prometheus_metrics"],
    },
    "mv3dt_compose_source": {
        MV3DT_APP: ["services:", "vss-rtvi-cv-mv3dt:", "vss-rtvi-cv-bev-fusion:"],
        MV3DT_THOR: ["services:", "vss-rtvi-cv-mv3dt:", "vss-rtvi-cv-bev-fusion:", "TRANSFORMERS_OFFLINE"],
    },
    "agent_health_source": {
        AGENT_WORKER: ['@app.get("/health"', 'return {"value": {"isAlive": True}}'],
    },
    "upload_routes_source": {
        AGENT_WORKER: ["register_video_upload(app", "register_video_upload_complete(app"],
        VIDEO_INGEST: ['"/api/v1/videos"', '"/api/v1/videos/{sensor_id}/complete"', "VideoUploadUrlResponse", "VideoUploadCompleteInput"],
    },
    "video_delete_source": {
        AGENT_WORKER: ["register_video_delete_routes(app"],
        VIDEO_DELETE: ['"/api/v1/videos/{video_id}"', "create_video_delete_router", "register_video_delete_routes"],
    },
    "rtsp_routes_source": {
        AGENT_WORKER: ["register_rtsp_ingest_routes(app", "register_rtsp_delete_routes(app"],
        RTSP_INGEST: ['"/api/v1/rtsp-streams/add"', "create_rtsp_ingest_router", "register_rtsp_ingest_routes"],
        RTSP_DELETE: ['"/api/v1/rtsp-streams/delete/{name}"', "create_rtsp_delete_router", "register_rtsp_delete_routes"],
    },
    "va_mcp_source": {
        VA_MCP_README: ["nat mcp serve", "http://localhost:9901/mcp"],
        VA_MCP_COMPOSE: ["vss-va-mcp:", "- mcp", "- serve", "${VSS_VA_MCP_PORT}"],
    },
    "lvs_mcp_source": {
        LVS_MCP: ["class LvsMCPServer", "SseServerTransport", "run_mcp_server"],
        LVS_SERVER: ["LVS_ENABLE_MCP", "LVS_MCP_PORT", "run_mcp_server"],
        LVS_COMPOSE: ["LVS_MCP_PORT=${LVS_MCP_PORT:-38112}", "LVS_ENABLE_MCP=${LVS_ENABLE_MCP:-false}"],
    },
    "vios_mcp_source": {
        VIOS_MCP_SERVER: ["def run_http_server", 'mcp.run(transport="streamable-http")', "/mcp (without trailing slash)"],
        VIOS_MCP_README: ["streamable HTTP at `/mcp`", "http://<host>:<port>/mcp"],
    },
}


class QualificationError(RuntimeError):
    """A source lock, inventory contract, or source-contract assertion failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _read_bytes(relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {relative_path}")
    repository = REPO_ROOT.resolve(strict=True)
    try:
        resolved = (repository / path).resolve(strict=True)
        resolved.relative_to(repository)
    except (OSError, ValueError) as exc:
        raise QualificationError(f"repository path does not resolve inside checkout: {relative_path}") from exc
    data = resolved.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(f"source exceeds {max_bytes} bytes: {relative_path}")
    return data


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid JSON schema: {schema_path.name}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(f"{label} schema validation failed at {where}: {first.message}")


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _verify_raw_lock(spec: dict[str, str], label: str) -> bytes:
    raw = _read_bytes(spec["path"])
    actual = _sha256(raw)
    if actual != spec["raw_sha256"]:
        raise QualificationError(f"{label} source lock mismatch: {actual} != {spec['raw_sha256']}")
    return raw


def _verify_source_lock(lock: dict[str, str]) -> bytes:
    raw = _read_bytes(lock["path"])
    actual = _sha256(raw)
    if actual != lock["sha256"]:
        raise QualificationError(f"source lock mismatch for {lock['path']}: {actual} != {lock['sha256']}")
    return raw


def _load_and_validate_inventory() -> tuple[dict[str, Any], bytes]:
    raw = INVENTORY_PATH.read_bytes()
    inventory = _strict_json_bytes(raw, INVENTORY_PATH.name)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    expected_policy = {
        "candidate_only": True,
        "can_mark_passed_current": False,
        "live_acceptance_mutation_allowed": False,
        "live_oracle_mutation_allowed": False,
        "runtime_evidence": [],
        "network_allowed": False,
        "docker_allowed": False,
        "subprocess_allowed": False,
        "lifecycle_allowed": False,
        "downloads_allowed": False,
        "credentials_allowed": False,
        "file_writes_allowed": False,
    }
    if inventory.get("policy") != expected_policy:
        raise QualificationError("candidate-only policy is not exact")
    expected_denominator = {
        "advertised_gap_entries": 87,
        "previously_selected_candidate_entries": 29,
        "prior_open_entries": 58,
        "selected_candidate_entries": 23,
        "entries_left_open": 35,
    }
    if inventory.get("denominator") != expected_denominator:
        raise QualificationError("87/29/58/23/35 denominator is not exact")

    if inventory["source_plan"] != EXPECTED_SOURCE_PLAN:
        raise QualificationError("exact advertised-entry plan input drifted")
    if inventory["source_manifest"] != EXPECTED_SOURCE_MANIFEST:
        raise QualificationError("exact parity manifest input drifted")
    if inventory["previous_candidate_inventories"] != EXPECTED_PREDECESSORS:
        raise QualificationError("exact predecessor inventory chain drifted")

    plan_spec = inventory["source_plan"]
    plan_raw = _verify_raw_lock(plan_spec, "advertised-entry gap plan")
    plan = _strict_json_bytes(plan_raw, plan_spec["path"])
    if plan.get("plan_payload_sha256") != plan_spec["plan_payload_sha256"]:
        raise QualificationError("gap plan payload identity mismatch")
    if len(plan.get("entries", [])) != 87:
        raise QualificationError("advertised-entry gap plan denominator is not 87")

    manifest_spec = inventory["source_manifest"]
    manifest = _strict_json_bytes(_verify_raw_lock(manifest_spec, "manifest"), manifest_spec["path"])

    predecessors = []
    predecessor_ids: set[str] = set()
    expected_counts = [(8, 79), (21, 58)]
    for index, (spec, (case_count, open_count)) in enumerate(
        zip(inventory["previous_candidate_inventories"], expected_counts, strict=True)
    ):
        previous = _strict_json_bytes(_verify_raw_lock(spec, f"predecessor {index}"), spec["path"])
        ids = [case["entry_id"] for case in previous.get("cases", [])]
        if len(ids) != case_count or len(set(ids)) != case_count:
            raise QualificationError(f"predecessor {index} case count is not exact")
        if previous.get("denominator", {}).get("entries_left_open") != open_count:
            raise QualificationError(f"predecessor {index} open count is not exact")
        if predecessor_ids & set(ids):
            raise QualificationError("predecessor inventories overlap")
        predecessor_ids.update(ids)
        predecessors.append(previous)
    wave2_predecessor = predecessors[1].get("previous_candidate_inventory", {})
    if wave2_predecessor != inventory["previous_candidate_inventories"][0]:
        raise QualificationError("wave-two predecessor chain does not bind exact wave one")
    if len(predecessor_ids) != 29:
        raise QualificationError("predecessor union is not the exact 29 selected entries")

    cases = inventory.get("cases", [])
    current_ids = [case["entry_id"] for case in cases]
    if len(current_ids) != 23 or len(set(current_ids)) != 23 or set(current_ids) != set(EXPECTED_CASE_BINDINGS):
        raise QualificationError("inventory must contain the exact 23-entry wave")
    if set(current_ids) & predecessor_ids:
        raise QualificationError("wave three overlaps a predecessor candidate entry")

    plan_by_pointer = {entry["manifest_pointer"]: entry for entry in plan["entries"]}
    for case in cases:
        pointer = case["manifest_pointer"]
        expected_pointer, expected_adapter, expected_sources = EXPECTED_CASE_BINDINGS[case["entry_id"]]
        if pointer != expected_pointer or case["adapter_id"] != expected_adapter:
            raise QualificationError(f"bounded adapter binding mismatch for {case['entry_id']}")
        source_paths = [lock["path"] for lock in case["source_locks"]]
        if len(source_paths) != len(set(source_paths)) or set(source_paths) != expected_sources:
            raise QualificationError(f"bounded source set mismatch for {case['entry_id']}")
        if set(CONTRACT_FRAGMENTS.get(expected_adapter, {})) != expected_sources:
            raise QualificationError(f"contract source set mismatch for {case['entry_id']}")
        gap = plan_by_pointer.get(pointer)
        if not gap or gap.get("coverage_state") != "open_missing_entry_capability_and_oracle":
            raise QualificationError(f"case is not an exact open gap-plan entry: {pointer}")
        comparisons = {
            "entry_id": gap["entry_id"],
            "proposed_capability_id": gap["proposed_capability"]["id"],
            "advertised": gap["advertised"],
            "advertised_utf8_sha256": gap["advertised_utf8_sha256"],
            "advertised_canonical_sha256": gap["advertised_canonical_sha256"],
        }
        for field, expected in comparisons.items():
            if case.get(field) != expected:
                raise QualificationError(f"{pointer} differs from gap plan at {field}")
        if _resolve_pointer(manifest, pointer) != case["advertised"]:
            raise QualificationError(f"{pointer} differs from manifest literal")
        if not case["evidence_scope"].startswith("subset:"):
            raise QualificationError(f"{pointer} lacks subset scope label")
        for lock in case["source_locks"]:
            _verify_source_lock(lock)
    return inventory, raw


def _source_contract(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    adapter_id = case["adapter_id"]
    contract = CONTRACT_FRAGMENTS[adapter_id]
    matched: list[dict[str, Any]] = []
    python_ast_parsed: list[str] = []
    for path in sorted(contract):
        raw = _read_bytes(path)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise QualificationError(f"source is not UTF-8: {path}") from exc
        if path.endswith(".py"):
            ast.parse(text, filename=path)
            python_ast_parsed.append(path)
        for fragment in contract[path]:
            count = text.count(fragment)
            if count < 1:
                raise QualificationError(f"required source fragment missing from {path}: {fragment!r}")
            matched.append(
                {
                    "path": path,
                    "fragment_sha256": _sha256(fragment.encode("utf-8")),
                    "occurrences": count,
                }
            )
    fixture = {
        "adapter_id": adapter_id,
        "source_paths": sorted(contract),
        "fragment_sha256": [item["fragment_sha256"] for item in matched],
    }
    output = {
        "contract_scope": "exact-digest-locked-source-fragments-only",
        "matched_source_files": sorted(contract),
        "matched_fragments": matched,
        "python_ast_parsed": python_ast_parsed,
        "runtime_executed": False,
        "workflow_proven": False,
        "service_readiness_proven": False,
        "model_availability_proven": False,
        "real_file_writes": 0,
    }
    return fixture, output


ADAPTERS = {adapter_id: _source_contract for adapter_id in CONTRACT_FRAGMENTS}


def execute(selected_ids: list[str] | None = None) -> dict[str, Any]:
    inventory, inventory_raw = _load_and_validate_inventory()
    cases_by_id = {case["entry_id"]: case for case in inventory["cases"]}
    selected = selected_ids or list(cases_by_id)
    if len(selected) != len(set(selected)):
        raise QualificationError("duplicate --case selection")
    unknown = sorted(set(selected) - set(cases_by_id))
    if unknown:
        raise QualificationError(f"unknown case selection: {unknown}")

    results = []
    for entry_id in selected:
        case = cases_by_id[entry_id]
        adapter = ADAPTERS.get(case["adapter_id"])
        if adapter is None:
            raise QualificationError(f"no bounded adapter: {case['adapter_id']}")
        fixture, semantic_output = adapter(case)
        input_payload = {"case": case, "fixture": fixture}
        results.append(
            {
                "manifest_pointer": case["manifest_pointer"],
                "entry_id": entry_id,
                "proposed_capability_id": case["proposed_capability_id"],
                "advertised": case["advertised"],
                "evidence_scope": case["evidence_scope"],
                "observation": "observed_match",
                "input_sha256": _sha256(_canonical_bytes(input_payload)),
                "semantic_output_sha256": _sha256(_canonical_bytes(semantic_output)),
                "semantic_output": semantic_output,
                "runtime_evidence": [],
                "official_capability_effect": "none_candidate_only",
            }
        )
    result = {
        "schema_version": 1,
        "mode": inventory["mode"],
        "candidate_only": True,
        "inventory_sha256": _sha256(inventory_raw),
        "denominator": inventory["denominator"],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list exact candidate case IDs")
    parser.add_argument("--case", action="append", dest="cases", help="run one exact candidate case; repeatable")
    args = parser.parse_args()
    try:
        if args.list:
            inventory, _ = _load_and_validate_inventory()
            print("\n".join(case["entry_id"] for case in inventory["cases"]))
            return 0
        print(json.dumps(execute(args.cases), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except QualificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
