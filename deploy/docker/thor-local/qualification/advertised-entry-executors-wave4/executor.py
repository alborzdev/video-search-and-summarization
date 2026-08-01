#!/usr/bin/env python3
"""Candidate-only cross-layer source executor for five LVS advertised entries."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Callable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
import yaml


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 1_000_000

EXPECTED_INVENTORY_SHA256 = (
    "1de6e9be3c93c349e45b192506e3081758553582dda6f73b79877bc4ff5155a6"
)
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
    {
        "path": "deploy/docker/thor-local/qualification/advertised-entry-executors-wave3/inventory.json",
        "raw_sha256": "0b7056eafce7686fc2b7315fef8ae491ddef03d2e52f41e7c7861247933f90ab",
    },
]
EXPECTED_POLICY = {
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
EXPECTED_DENOMINATOR = {
    "advertised_gap_entries": 87,
    "previously_selected_candidate_entries": 52,
    "prior_open_entries": 35,
    "selected_candidate_entries": 5,
    "entries_left_open": 30,
}

LVS_CONFIG_MEDIA = "services/agent/src/vss_agents/tools/lvs_config_media.py"
LVS_STREAM_TOOL = "services/agent/src/vss_agents/tools/lvs_stream_understanding.py"
VIDEO_REPORT = "services/agent/src/vss_agents/tools/video_report_gen.py"
VIA_SERVER = "services/video-summarization/src/via_server.py"
VIA_HANDLER = "services/video-summarization/src/via_stream_handler.py"
RTVI_CLIENT = "services/video-summarization/src/rtvi_vlm_client.py"
VSS_MODELS = "services/video-summarization/src/vss_api_models.py"
RAG_ADAPTER = "services/video-summarization/src/rag_adapter.py"
RTVI_HANDLER = "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py"
LOGSTASH = "services/video-summarization/docker/logstash/pipeline/visionllm.conf"
LVS_CONFIG = "deploy/docker/services/video-summarization/configs/config.yaml"

EXPECTED_CASE_BINDINGS = {
    "manifest-gap.video-summarization-live.00-live-captions": (
        "/features/2/advertised/0",
        "live_captions_cross_layer",
        {LVS_CONFIG_MEDIA, VIA_SERVER, VIA_HANDLER, RTVI_CLIENT, RTVI_HANDLER},
    ),
    "manifest-gap.video-summarization-live.01-live-stream-summaries": (
        "/features/2/advertised/1",
        "live_stream_summary_cross_layer",
        {LVS_STREAM_TOOL, VIA_SERVER, VIA_HANDLER, LVS_CONFIG},
    ),
    "manifest-gap.video-summarization-live.02-stream-reports": (
        "/features/2/advertised/2",
        "stream_report_cross_layer",
        {LVS_STREAM_TOOL, VIDEO_REPORT, VIA_SERVER, VIA_HANDLER, LVS_CONFIG},
    ),
    "manifest-gap.video-summarization-live.03-caption-backed-q-a": (
        "/features/2/advertised/3",
        "caption_qa_cross_layer",
        {VIA_SERVER, VIA_HANDLER, VSS_MODELS, RAG_ADAPTER},
    ),
    "manifest-gap.video-summarization-live.04-elasticsearch-caption-storage": (
        "/features/2/advertised/4",
        "elasticsearch_caption_storage_cross_layer",
        {RTVI_HANDLER, LOGSTASH, LVS_CONFIG, VIA_HANDLER},
    ),
}


class QualificationError(RuntimeError):
    """A lock, source graph, bounded config, or output contract failed."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


def _safe_repo_path(relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise QualificationError(f"unsafe repository path: {relative_path}")
    path = REPO_ROOT.joinpath(*pure.parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationError(
            f"repository input is unavailable: {relative_path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(
            f"repository input must be a regular non-symlink: {relative_path}"
        )
    if path.resolve().parent != REPO_ROOT and REPO_ROOT not in path.resolve().parents:
        raise QualificationError(f"repository input escaped root: {relative_path}")
    return path


def _read_bytes(relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    path = _safe_repo_path(relative_path)
    if path.stat().st_size > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    data = path.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(
            f"repository input exceeds {max_bytes} bytes: {relative_path}"
        )
    return data


def _validate_schema(instance: Any, schema_path: Path, label: str) -> None:
    schema = _strict_json_bytes(schema_path.read_bytes(), schema_path.name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise QualificationError(f"invalid JSON schema: {schema_path.name}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        where = "/" + "/".join(str(item) for item in first.absolute_path)
        raise QualificationError(
            f"{label} schema validation failed at {where}: {first.message}"
        )


def _resolve_pointer(document: Any, pointer: str) -> Any:
    value = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _verify_sha(path: str, expected: str, label: str) -> bytes:
    raw = _read_bytes(path)
    actual = _sha256(raw)
    if actual != expected:
        raise QualificationError(f"{label} mismatch for {path}: {actual} != {expected}")
    return raw


def _qname(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_qname(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return f"{_qname(node.value)}[]"
    return type(node).__name__


def _parse_python(path: str) -> ast.Module:
    try:
        return ast.parse(_read_bytes(path), filename=path)
    except SyntaxError as exc:
        raise QualificationError(f"Python AST parse failed: {path}") from exc


def _find_definition(tree: ast.Module, name: str, node_type: type[ast.AST]) -> ast.AST:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, node_type) and getattr(node, "name", None) == name
    ]
    if len(matches) != 1:
        raise QualificationError(
            f"expected one {name} definition, found {len(matches)}"
        )
    return matches[0]


def _assert_function(
    path: str,
    name: str,
    *,
    calls: tuple[str, ...] = (),
    attributes: tuple[str, ...] = (),
    strings: tuple[str, ...] = (),
    constants: tuple[int, ...] = (),
) -> list[str]:
    tree = _parse_python(path)
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(nodes) != 1:
        raise QualificationError(
            f"expected one function {name} in {path}, found {len(nodes)}"
        )
    node = nodes[0]
    actual_calls = {
        _qname(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)
    }
    actual_attributes = {
        _qname(item) for item in ast.walk(node) if isinstance(item, ast.Attribute)
    }
    actual_strings = {
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }
    actual_constants = {
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant)
        and isinstance(item.value, int)
        and not isinstance(item.value, bool)
    }
    missing_calls = sorted(set(calls) - actual_calls)
    missing_attributes = sorted(set(attributes) - actual_attributes)
    missing_strings = sorted(set(strings) - actual_strings)
    missing_constants = sorted(set(constants) - actual_constants)
    if missing_calls or missing_attributes or missing_strings or missing_constants:
        raise QualificationError(
            f"AST contract failed for {path}:{name}: calls={missing_calls}, "
            f"attributes={missing_attributes}, strings={missing_strings}, constants={missing_constants}"
        )
    assertions = [f"ast:{path}:{name}:definition"]
    assertions.extend(f"ast-call:{name}:{item}" for item in calls)
    assertions.extend(f"ast-attribute:{name}:{item}" for item in attributes)
    assertions.extend(f"ast-string:{name}:{_sha256(item.encode())}" for item in strings)
    assertions.extend(f"ast-constant:{name}:{item}" for item in constants)
    return assertions


def _assert_classes(path: str, names: tuple[str, ...]) -> list[str]:
    tree = _parse_python(path)
    actual = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    missing = sorted(set(names) - actual)
    if missing:
        raise QualificationError(f"class contract failed for {path}: {missing}")
    return [f"ast-class:{path}:{name}" for name in names]


def _assert_fragments(path: str, fragments: tuple[str, ...]) -> list[str]:
    text = _read_bytes(path).decode("utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        raise QualificationError(
            f"bounded source fragment missing in {path}: {missing}"
        )
    return [
        f"bounded-fragment:{path}:{_sha256(fragment.encode())}"
        for fragment in fragments
    ]


class _EnvLoader(yaml.SafeLoader):
    pass


def _env_constructor(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> str:
    return loader.construct_scalar(node)


_EnvLoader.add_multi_constructor("!ENV", _env_constructor)


def _assert_lvs_yaml() -> tuple[list[str], dict[str, Any]]:
    raw = _read_bytes(LVS_CONFIG)
    try:
        document = yaml.load(raw, Loader=_EnvLoader)
    except yaml.YAMLError as exc:
        raise QualificationError("bounded LVS YAML parse failed") from exc
    if not isinstance(document, dict):
        raise QualificationError("LVS YAML root is not an object")
    functions = document.get("functions")
    context = document.get("context_manager")
    if not isinstance(functions, dict) or not isinstance(context, dict):
        raise QualificationError("LVS YAML functions/context_manager missing")
    output: dict[str, Any] = {}
    for name in ("summarization", "summarization_online"):
        entry = functions.get(name)
        if not isinstance(entry, dict):
            raise QualificationError(f"LVS YAML function missing: {name}")
        params = entry.get("params")
        tools = entry.get("tools")
        if entry.get("type") != "vlm_structured_summarization_online":
            raise QualificationError(f"LVS YAML function has wrong type: {name}")
        if not isinstance(params, dict) or params.get("kafka_enabled") is not True:
            raise QualificationError(f"LVS YAML function is not Kafka-backed: {name}")
        if (
            not isinstance(tools, dict)
            or tools.get("db") != "${LVS_DATABASE_BACKEND:elasticsearch_db}"
        ):
            raise QualificationError(
                f"LVS YAML function is not Elasticsearch-backed: {name}"
            )
        output[name] = {"type": entry["type"], "kafka_enabled": True, "db": tools["db"]}
    registered = context.get("functions")
    if not isinstance(registered, list) or not {
        "summarization",
        "summarization_online",
    }.issubset(registered):
        raise QualificationError(
            "LVS YAML context does not register both summary functions"
        )
    assertions = [
        "yaml:summarization:kafka-elasticsearch",
        "yaml:summarization_online:kafka-elasticsearch",
        "yaml:context_manager:summary-functions-registered",
    ]
    return assertions, output


def _assert_logstash_contract() -> tuple[list[str], dict[str, Any]]:
    text = _read_bytes(LOGSTASH).decode("utf-8")
    patterns = {
        "stream_identity": r'raw_sid = \(cm\["streamId"\] \|\| "unknown"\)\.to_s',
        "sanitization": r'safe_sid = raw_sid\.gsub\(/\[-\\/\\\\ \]/, "_"\)',
        "collection": r'coll = cm\.delete\("collection_name"\) \|\| "default_#\{safe_sid\}"',
        "doc_type": r'cm\["doc_type"\] \|\|= "raw_events"',
        "doc_index": r'cm\["doc_i"\] \|\|= \(q_id =~ /\\A\\d\+\\z/ \? q_id : cm\["chunkIdx"\] \|\| ""\)',
        "uuid": r'cm\["uuid"\] \|\|= raw_sid',
        "es_index": r'index\s+=>\s+"%\{\[@metadata\]\[collection\]\}"',
        "es_document_id": r'document_id\s+=>\s+"%\{\[@metadata\]\[es_id\]\}"',
    }
    for label, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if len(matches) != 1:
            raise QualificationError(
                f"Logstash contract {label} matched {len(matches)} times"
            )
    fixture_stream = "123e4567-e89b-12d3-a456-426614174000"
    safe_stream = fixture_stream.replace("-", "_")
    output = {
        "fixture_stream_id": fixture_stream,
        "derived_collection": f"default_{safe_stream}",
        "default_doc_type": "raw_events",
        "uuid_source": "streamId",
        "doc_i_fallback": "chunkIdx",
        "elasticsearch_index_source": "metadata.collection",
        "elasticsearch_id_source": "metadata.es_id",
    }
    return [f"logstash:{label}" for label in patterns], output


def _live_captions() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_function(
        LVS_CONFIG_MEDIA,
        "_lvs_config_media",
        calls=("session.post", "remember_configured_media", "get_stream_info_by_name"),
        strings=("id", "model", "scenario", "events", "chunk_duration"),
        constants=(200, 201, 202),
    )
    assertions += _assert_function(
        VIA_SERVER,
        "generate_captions",
        calls=("loop.run_in_executor", "GenerateCaptionsResponse"),
        attributes=("self._stream_handler.start_stream_captions",),
        strings=(
            "/v1/generate_captions",
            "accepted",
            "Livestream APIs require KAFKA_ENABLED=true",
        ),
    )
    assertions += _assert_function(
        VIA_HANDLER,
        "start_stream_captions",
        calls=("self._vlm_pipeline.start_captions", "self._store_event_prompt_in_db"),
        strings=("source_id", "start_captions", "video"),
    )
    assertions += _assert_function(
        RTVI_CLIENT,
        "start_captions",
        calls=(
            "self._session.post",
            "resp.close",
            "self._build_generate_captions_request",
        ),
        strings=("/v1/generate_captions", "x-stream-id"),
        constants=(200, 409),
    )
    assertions += _assert_function(
        RTVI_HANDLER,
        "_on_vlm_chunk_response",
        calls=("self._chunk_result_to_vision_llm", "self._send_protobuf_to_kafka"),
    )
    assertions += _assert_function(
        RTVI_HANDLER,
        "_chunk_result_to_vision_llm",
        strings=("streamId", "chunkIdx", "requestId"),
    )
    edges = [
        "agent.lvs_config_media -> LVS.POST./v1/generate_captions",
        "LVS.generate_captions -> ViaStreamHandler.start_stream_captions",
        "ViaStreamHandler.start_stream_captions -> RtviVlmClient.start_captions",
        "RTVI.chunk_response -> Kafka.VisionLLM",
    ]
    detail = {
        "endpoint": "/v1/generate_captions",
        "accepted_statuses": [200, 201, 202],
        "sticky_header": "x-stream-id",
        "duplicate_caption_client_status": 409,
    }
    return assertions, edges, detail


def _live_stream_summary() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_function(
        LVS_STREAM_TOOL,
        "_lvs_stream_understanding",
        calls=(
            "configured_media",
            "get_timeline",
            "datetime_to_iso8601",
            "session.post",
        ),
        strings=("id", "model", "start_time", "end_time"),
        constants=(200, 201, 202),
    )
    assertions += _assert_function(
        VIA_SERVER,
        "stream_summarize",
        calls=("loop.run_in_executor", "CompletionResponse"),
        attributes=("self._stream_handler.summarize_stream",),
        strings=(
            "/v1/stream_summarize",
            "Livestream APIs require KAFKA_ENABLED=true",
            "CA-RAG is required for stream summarization",
        ),
    )
    assertions += _assert_function(
        VIA_HANDLER,
        "summarize_stream",
        calls=("ctx_mgr.call", "ctx_mgr.configure", "self._publish_aggregate_to_kafka"),
        strings=("summarization_online", "uuids", "events", "video_summary"),
    )
    yaml_assertions, yaml_detail = _assert_lvs_yaml()
    assertions += yaml_assertions
    edges = [
        "agent.lvs_stream_understanding -> LVS.POST./v1/stream_summarize",
        "LVS.stream_summarize -> ViaStreamHandler.summarize_stream",
        "ViaStreamHandler.summarize_stream -> CA-RAG.summarization_online",
        "ViaStreamHandler.summarize_stream -> Kafka.structured_events+aggregated_summary",
    ]
    detail = {
        "endpoint": "/v1/stream_summarize",
        "zero_bounds_skip_timeline": True,
        "nonzero_bounds_iso8601": True,
        "config": yaml_detail,
    }
    return assertions, edges, detail


def _stream_report() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_function(
        VIDEO_REPORT,
        "_video_report_gen",
        calls=("_stream_report_gen_single",),
        strings=("rtsp",),
    )
    assertions += _assert_function(
        VIDEO_REPORT,
        "_stream_report_gen_single",
        calls=(
            "lvs_stream_understanding_tool.ainvoke",
            "_save_markdown_to_object_store",
            "_save_pdf_to_object_store",
            "_format_lvs_response",
        ),
        strings=("response_type", "report", "events", "video_summary", ".md", ".pdf"),
    )
    assertions += _assert_function(
        LVS_STREAM_TOOL,
        "_lvs_stream_understanding",
        calls=("session.post",),
        strings=("id", "model", "start_time", "end_time"),
    )
    assertions += _assert_function(
        VIA_SERVER,
        "stream_summarize",
        attributes=("self._stream_handler.summarize_stream",),
        strings=("/v1/stream_summarize",),
    )
    assertions += _assert_function(
        VIA_HANDLER,
        "summarize_stream",
        calls=("ctx_mgr.call",),
        strings=("summarization_online", "events", "video_summary"),
    )
    yaml_assertions, yaml_detail = _assert_lvs_yaml()
    assertions += yaml_assertions
    edges = [
        "video_report_gen[rtsp] -> _stream_report_gen_single",
        "_stream_report_gen_single -> agent.lvs_stream_understanding[report]",
        "agent.lvs_stream_understanding -> LVS.POST./v1/stream_summarize",
        "LVS.summary_content -> report.markdown+pdf",
    ]
    detail = {
        "media_type": "rtsp",
        "response_type": "report",
        "artifacts": ["markdown", "pdf"],
        "config": yaml_detail,
    }
    return assertions, edges, detail


def _caption_qa() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_function(
        VIA_SERVER,
        "chat_completions",
        calls=(
            "loop.run_in_executor",
            "CompletionResponse",
            "ChatCompletionResponseMessage",
        ),
        attributes=("self._stream_handler.chat_completion",),
        strings=(
            "/v1/chat/completions",
            "CA-RAG is required for chat completions",
            "answer",
        ),
    )
    assertions += _assert_function(
        VIA_HANDLER,
        "chat_completion",
        calls=(
            "reversed",
            "qa_ctx.configure",
            "qa_ctx.call",
            "self._remove_think_tags",
        ),
        strings=(
            "user",
            "question",
            "is_live",
            "is_last",
            "retriever_function",
            "ingestion_function",
            "answer",
            "reasoning",
        ),
    )
    assertions += _assert_classes(
        VSS_MODELS,
        ("ChatMessage", "ChatCompletionQuery", "ChatCompletionResponseMessage"),
    )
    assertions += _assert_function(
        RAG_ADAPTER, "configure", calls=("self._ctx_mgr.configure",)
    )
    assertions += _assert_function(RAG_ADAPTER, "call", calls=("self._ctx_mgr.call",))
    edges = [
        "LVS.POST./v1/chat/completions -> ViaStreamHandler.chat_completion",
        "ViaStreamHandler.chat_completion -> CA-RAG.retriever_function",
        "CA-RAG.retriever_response -> CompletionResponse.assistant",
    ]
    detail = {
        "endpoint": "/v1/chat/completions",
        "question_source": "last user message",
        "retriever_is_last": False,
        "context_identity": "request asset UUID",
    }
    return assertions, edges, detail


def _elasticsearch_caption_storage() -> tuple[list[str], list[str], dict[str, Any]]:
    assertions: list[str] = []
    assertions += _assert_function(
        RTVI_HANDLER,
        "_chunk_result_to_vision_llm",
        strings=("streamId", "chunkIdx", "requestId"),
    )
    assertions += _assert_function(
        RTVI_HANDLER,
        "_on_vlm_chunk_response",
        calls=("self._chunk_result_to_vision_llm", "self._send_protobuf_to_kafka"),
    )
    assertions += _assert_function(
        VIA_HANDLER,
        "summarize_stream",
        calls=("ctx_mgr.call",),
        strings=("summarization_online", "uuids", "start_time", "end_time"),
    )
    logstash_assertions, logstash_detail = _assert_logstash_contract()
    yaml_assertions, yaml_detail = _assert_lvs_yaml()
    assertions += logstash_assertions + yaml_assertions
    edges = [
        "RTVI.caption_chunk -> Kafka.VisionLLM[streamId+chunkIdx]",
        "Kafka.VisionLLM -> Logstash.default_<streamId>.raw_events",
        "Logstash.raw_events -> Elasticsearch.deterministic_document",
        "Elasticsearch.default_<streamId> -> CA-RAG.summarization_online[uuids]",
    ]
    detail = {"logstash": logstash_detail, "config": yaml_detail}
    return assertions, edges, detail


ADAPTERS: dict[str, Callable[[], tuple[list[str], list[str], dict[str, Any]]]] = {
    "live_captions_cross_layer": _live_captions,
    "live_stream_summary_cross_layer": _live_stream_summary,
    "stream_report_cross_layer": _stream_report,
    "caption_qa_cross_layer": _caption_qa,
    "elasticsearch_caption_storage_cross_layer": _elasticsearch_caption_storage,
}


def _load_inventory() -> tuple[dict[str, Any], bytes, dict[str, Any], dict[str, Any]]:
    raw = INVENTORY_PATH.read_bytes()
    if _sha256(raw) != EXPECTED_INVENTORY_SHA256:
        raise QualificationError("wave-four inventory identity drifted")
    inventory = _strict_json_bytes(raw, INVENTORY_PATH.name)
    _validate_schema(inventory, INVENTORY_SCHEMA_PATH, "inventory")
    if inventory.get("source_plan") != EXPECTED_SOURCE_PLAN:
        raise QualificationError("source plan lock drifted")
    if inventory.get("source_manifest") != EXPECTED_SOURCE_MANIFEST:
        raise QualificationError("source manifest lock drifted")
    if inventory.get("previous_candidate_inventories") != EXPECTED_PREDECESSORS:
        raise QualificationError("predecessor inventory chain drifted")
    if inventory.get("policy") != EXPECTED_POLICY:
        raise QualificationError("candidate-only policy drifted")
    if inventory.get("denominator") != EXPECTED_DENOMINATOR:
        raise QualificationError("87/52/35/5/30 denominator drifted")

    plan_raw = _verify_sha(
        EXPECTED_SOURCE_PLAN["path"],
        EXPECTED_SOURCE_PLAN["raw_sha256"],
        "gap plan lock",
    )
    plan = _strict_json_bytes(plan_raw, EXPECTED_SOURCE_PLAN["path"])
    if plan.get("plan_payload_sha256") != EXPECTED_SOURCE_PLAN["plan_payload_sha256"]:
        raise QualificationError("gap plan payload identity drifted")
    manifest_raw = _verify_sha(
        EXPECTED_SOURCE_MANIFEST["path"],
        EXPECTED_SOURCE_MANIFEST["raw_sha256"],
        "manifest lock",
    )
    manifest = _strict_json_bytes(manifest_raw, EXPECTED_SOURCE_MANIFEST["path"])

    predecessor_ids: set[str] = set()
    for spec in EXPECTED_PREDECESSORS:
        previous_raw = _verify_sha(spec["path"], spec["raw_sha256"], "predecessor lock")
        previous = _strict_json_bytes(previous_raw, spec["path"])
        ids = {case["entry_id"] for case in previous.get("cases", [])}
        if ids & predecessor_ids:
            raise QualificationError("predecessor inventories overlap")
        predecessor_ids.update(ids)
    if len(predecessor_ids) != 52:
        raise QualificationError(
            f"predecessor union must contain 52 IDs, found {len(predecessor_ids)}"
        )

    cases = inventory.get("cases", [])
    if len(cases) != 5 or len({case["entry_id"] for case in cases}) != 5:
        raise QualificationError("inventory must contain five unique exact cases")
    if {case["entry_id"] for case in cases} != set(EXPECTED_CASE_BINDINGS):
        raise QualificationError("wave-four case set drifted")
    if predecessor_ids & {case["entry_id"] for case in cases}:
        raise QualificationError("wave-four cases overlap predecessor inventories")

    plan_by_pointer = {entry["manifest_pointer"]: entry for entry in plan["entries"]}
    for case in cases:
        pointer, adapter_id, sources = EXPECTED_CASE_BINDINGS[case["entry_id"]]
        if case["manifest_pointer"] != pointer or case["adapter_id"] != adapter_id:
            raise QualificationError(f"case binding drifted: {case['entry_id']}")
        if {lock["path"] for lock in case["source_locks"]} != sources:
            raise QualificationError(f"case source set drifted: {case['entry_id']}")
        gap = plan_by_pointer.get(pointer)
        if gap is None:
            raise QualificationError(f"case pointer absent from gap plan: {pointer}")
        expected_fields = {
            "entry_id": gap["entry_id"],
            "proposed_capability_id": gap["proposed_capability"]["id"],
            "advertised": gap["advertised"],
            "advertised_utf8_sha256": gap["advertised_utf8_sha256"],
            "advertised_canonical_sha256": gap["advertised_canonical_sha256"],
        }
        for field, expected in expected_fields.items():
            if case.get(field) != expected:
                raise QualificationError(f"{pointer} differs from gap plan at {field}")
        if gap["required_oracle"].get("executor_class") != "bounded_lvs_live_workflow":
            raise QualificationError(
                f"{pointer} no longer uses bounded_lvs_live_workflow"
            )
        if gap["required_oracle"].get("status") != "open_unexecuted":
            raise QualificationError(f"{pointer} is no longer open_unexecuted")
        if _resolve_pointer(manifest, pointer) != case["advertised"]:
            raise QualificationError(f"{pointer} differs from manifest literal")
        for lock in case["source_locks"]:
            _verify_sha(lock["path"], lock["sha256"], "source lock")
    return inventory, raw, plan, manifest


def execute(selected: list[str] | None = None) -> dict[str, Any]:
    inventory, raw, _plan, _manifest = _load_inventory()
    cases_by_id = {case["entry_id"]: case for case in inventory["cases"]}
    if selected is None:
        selected_ids = list(cases_by_id)
    else:
        if len(selected) != len(set(selected)):
            raise QualificationError("duplicate --case selections are forbidden")
        unknown = sorted(set(selected) - set(cases_by_id))
        if unknown:
            raise QualificationError(f"unknown case selection: {unknown}")
        selected_ids = selected

    results = []
    for entry_id in selected_ids:
        case = cases_by_id[entry_id]
        assertions, edges, detail = ADAPTERS[case["adapter_id"]]()
        sources = sorted(lock["path"] for lock in case["source_locks"])
        python_sources = sorted(path for path in sources if path.endswith(".py"))
        bounded_configs = sorted(path for path in sources if not path.endswith(".py"))
        semantic_output = {
            "contract_scope": "exact-digest-locked-cross-layer-source-contract-only",
            "call_graph_edges": edges,
            "matched_assertions": sorted(
                set(assertions + [f"detail:{_sha256(_canonical_bytes(detail))}"])
            ),
            "matched_source_files": sources,
            "python_ast_parsed": python_sources,
            "bounded_config_parsed": bounded_configs,
            "runtime_executed": False,
            "workflow_proven": False,
            "service_readiness_proven": False,
            "model_availability_proven": False,
            "real_file_writes": 0,
        }
        results.append(
            {
                "manifest_pointer": case["manifest_pointer"],
                "entry_id": entry_id,
                "proposed_capability_id": case["proposed_capability_id"],
                "advertised": case["advertised"],
                "evidence_scope": case["evidence_scope"],
                "observation": "observed_match",
                "input_sha256": _sha256(_canonical_bytes(case)),
                "semantic_output_sha256": _sha256(_canonical_bytes(semantic_output)),
                "semantic_output": semantic_output,
                "runtime_evidence": [],
                "official_capability_effect": "none_candidate_only",
            }
        )
    result = {
        "schema_version": 1,
        "mode": "candidate_only_cross_layer_executor_tranche_wave4",
        "candidate_only": True,
        "inventory_sha256": _sha256(raw),
        "denominator": inventory["denominator"],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "results": results,
    }
    _validate_schema(result, RESULT_SCHEMA_PATH, "result")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list exact case IDs")
    parser.add_argument(
        "--case", action="append", dest="cases", help="run one exact case (repeatable)"
    )
    args = parser.parse_args()
    if args.list:
        inventory, _raw, _plan, _manifest = _load_inventory()
        for case in inventory["cases"]:
            print(case["entry_id"])
        return 0
    print(json.dumps(execute(args.cases), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
