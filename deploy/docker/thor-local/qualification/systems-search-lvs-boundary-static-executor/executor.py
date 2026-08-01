#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Execute bounded product-code checks for Search upload and LVS boundaries."""

from __future__ import annotations

import argparse
import ast
import asyncio
import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import threading
import time
import types
import urllib.parse
import uuid
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch

from jsonschema import Draft202012Validator
from pydantic import BaseModel

# Keep this read-only executor from materializing import bytecode beside sources.
sys.dont_write_bytecode = True

LANE = Path(__file__).resolve().parent
REPO_ROOT = LANE.parents[4]
ACCEPTANCE_PATH = "deploy/docker/thor-local/qualification/acceptance_inventory.json"
CAPABILITY_PATH = "deploy/docker/thor-local/parity/official-capabilities.json"
ORACLE_PATH = "deploy/docker/thor-local/parity/capability-oracles.json"
SEARCH_SOURCE = "services/agent/src/vss_agents/api/video_search_ingest.py"
LVS_SOURCE = "services/video-summarization/src/via_stream_handler.py"
UI_SOURCE = "services/ui/packages/common/lib-src/components/UploadFilesDialog.tsx"
MAX_JSON_BYTES = 4 * 1024 * 1024

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
    "systems-search-content-type": "behavior.search-upload.content-type",
    "systems-lvs-queue": "runtime.lvs.single-request-queue",
    "systems-lvs-formats": "runtime.lvs.supported-formats",
}
EXPECTED_CONTRACTS = {
    "behavior.search-upload.content-type": {
        "accepted": ["video/mp4", "video/x-matroska"],
        "missing_or_unsupported_status": 400,
    },
    "runtime.lvs.single-request-queue": {
        "active_requests": 1,
        "additional_requests": "queued",
    },
    "runtime.lvs.supported-formats": {
        "formats": ["MP4", "AVI", "MOV", "MKV", "WebM"],
        "proprietary_where_supported": True,
    },
}
EXPECTED_NEGATIVES = [
    "search-missing-content-type",
    "search-unsupported-content-type",
    "search-parameterized-content-type",
    "search-missing-content-length",
    "search-invalid-content-length",
    "search-empty-body",
    "ui-advertised-format-gap",
    "lvs-handler-concurrent-entry",
]
EXPECTED_LOCKS = {
    "deploy/docker/thor-local/qualification/acceptance_inventory.json": "79001985f9cc9d0dbb64adea2a014aaedacd0b0411d8becb5b311c8697a563a5",
    "deploy/docker/thor-local/parity/official-capabilities.json": "65241b3ad56f5d9bb817ba040c06abdbfe034701be645c845d94e4f065514f0e",
    "deploy/docker/thor-local/parity/capability-oracles.json": "daccf4e9d198ad3fab762a2f0bcab2e06d093ba92dfb50513f7966b4b5c40dff",
    "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json": "0abc81c383a9db122d2ad74c4dbb6c85cc00caf032abd94c4e7d632ce97ff539",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave3/inventory.json": "386047abc54476062635913b9a3fc2ccfb73e3263f7d93c6fac8c6769b567232",
    "deploy/docker/thor-local/qualification/planning-requirement-executors-wave11/inventory.json": "734609e5b1aab27a4d65a2570d3e6a3c366ae9ecf896dd7f0d5e62785e219cdd",
    "services/agent/src/vss_agents/api/video_search_ingest.py": "6598b13e31c637f10b6992ab14a254a6191ba0cea490c91795243fd612019d77",
    "services/agent/tests/unit_test/api/test_video_search_ingest.py": "1ade3f881b57fd8357047c951f500c660cbfc1d67b65fe268c150437f320030e",
    "services/video-summarization/src/via_stream_handler.py": "0e55981fbacb39ec337c1012067475f021168aefce0d72ab14d2368c8803ad8c",
    "services/agent/README.md": "f8bb48cbee282b8f6048ab9220258adcb648e3de761d81b98c34baa747d1740e",
    "services/ui/packages/common/lib-src/components/UploadFilesDialog.tsx": "90487a061cdd8750f24ce17446010b09995c7d0152f1394cbb05201c6e82d2dd",
    "services/ui/packages/common/__tests__/components/UploadFilesDialog.test.tsx": "71da8185445f1ffa3b3d0c5d590f7c5f306038b43eec2529ecdcb0283c506456",
}
REMAINING_LIVE_BLOCKERS = [
    "search endpoint must return canonical HTTP 400 for an unsupported Content-Type or the canonical contract must be reconciled",
    "all five advertised containers/codecs require format-by-format Thor decode and summarization evidence",
    "AVI, MOV, and WebM need an admitted local upload path or a documented API-only path with runtime proof",
    "two live concurrent LVS requests must prove one active and one queued across the LVS and RTVI boundary",
    "successful local VLM inference and output semantics remain unobserved by this provider-free executor",
]


class QualificationError(RuntimeError):
    """The locked contract or a deterministic product observation failed closed."""


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
    observed_locks = {row["path"]: row["sha256"] for row in contract["source_locks"]}
    if observed_locks != EXPECTED_LOCKS or len(contract["source_locks"]) != len(
        EXPECTED_LOCKS
    ):
        raise QualificationError("exact source-lock set drift")
    return contract


def _verify_source_locks(contract: dict[str, Any]) -> dict[str, str]:
    locks = contract["source_locks"]
    if len({row["path"] for row in locks}) != len(EXPECTED_LOCKS):
        raise QualificationError("source lock paths are not unique")
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
    observations = []
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
        observed_contract = copy.deepcopy(capability.get("contract", {}))
        wave = observed_contract.pop("wave3_acceptance", None)
        if observed_contract != EXPECTED_CONTRACTS[capability_id]:
            raise QualificationError("capability contract field drift")
        if wave != {
            "package": "systems",
            "candidate_family": wave.get("candidate_family") if wave else None,
            "planning_requirement_ids": [planning_id],
            "materialized": False,
            "executor_ready": False,
        }:
            raise QualificationError("wave-3 binding drift")

        oracle = _find_one(oracle_set["oracles"], "oracle_id", binding["oracle_id"])
        if oracle.get("capability_id") != capability_id:
            raise QualificationError("oracle capability binding drift")
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
            raise QualificationError("oracle classification drift")

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


class _VideoIngestResponse(BaseModel):
    message: str
    sensor_id: str
    filename: str
    chunks_processed: int = 0


class _TimeMeasure:
    def __init__(self, _label: str) -> None:
        pass

    def __enter__(self) -> "_TimeMeasure":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _module_stub(name: str, *, package: bool = False) -> types.ModuleType:
    module = types.ModuleType(name)
    if package:
        module.__path__ = []  # type: ignore[attr-defined]
    return module


def _load_search_product_module() -> types.ModuleType:
    video_ingest = _module_stub("vss_agents.api.video_ingest")
    video_ingest.DEFAULT_RTVI_CV_TIMEOUT_SECONDS = 60.0
    video_ingest.DEFAULT_RTVI_EMBED_TIMEOUT_SECONDS = 600.0
    video_ingest.DEFAULT_VST_STORAGE_TIMEOUT_SECONDS = 60.0
    video_ingest.DEFAULT_VST_UPLOAD_TIMEOUT_SECONDS = 300.0
    video_ingest.VideoIngestResponse = _VideoIngestResponse
    video_ingest._resolve_video_upload_config = lambda _config: None

    async def _post_upload(**_kwargs: Any) -> _VideoIngestResponse:
        return _VideoIngestResponse(
            message="offline fake complete",
            sensor_id="sensor-offline",
            filename="clip.mp4",
        )

    video_ingest._run_post_upload_processing = _post_upload
    sanitize = _module_stub("vss_agents.utils.sanitize")
    sanitize.quote_path_segment = lambda value: urllib.parse.quote(value, safe="")
    sanitize.scrub_log = lambda value: str(value)
    timer = _module_stub("vss_agents.utils.time_measure")
    timer.TimeMeasure = _TimeMeasure
    stubs = {
        "vss_agents": _module_stub("vss_agents", package=True),
        "vss_agents.api": _module_stub("vss_agents.api", package=True),
        "vss_agents.utils": _module_stub("vss_agents.utils", package=True),
        "vss_agents.api.video_ingest": video_ingest,
        "vss_agents.utils.sanitize": sanitize,
        "vss_agents.utils.time_measure": timer,
    }
    source = _repo_file(SEARCH_SOURCE)
    spec = importlib.util.spec_from_file_location(
        "vss_agents.api.video_search_ingest", source
    )
    if spec is None or spec.loader is None:
        raise QualificationError("could not load Search product module")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs, clear=False):
        spec.loader.exec_module(module)
    return module


class _FakeRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = types.SimpleNamespace(
            get=lambda key: headers.get(str(key).lower())
        )

    async def stream(self):
        yield b"bounded-offline-fixture"


async def _search_case(
    module: types.ModuleType,
    *,
    content_type: str | None,
    content_length: str | None,
    filename: str,
) -> dict[str, Any]:
    upload_calls: list[dict[str, Any]] = []

    class _FakeResponse:
        status_code = 201
        text = "offline fake created"

        @staticmethod
        def json() -> dict[str, str]:
            return {"sensorId": "sensor-offline", "filename": filename}

    class _FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def put(self, url: str, **kwargs: Any) -> _FakeResponse:
            upload_calls.append(
                {
                    "url": url,
                    "headers": kwargs.get("headers"),
                    "stream_is_async": hasattr(kwargs.get("content"), "__aiter__"),
                }
            )
            return _FakeResponse()

    headers = {}
    if content_type is not None:
        headers["content-type"] = content_type
    if content_length is not None:
        headers["content-length"] = content_length
    route = module.create_video_search_ingest_router(
        vst_internal_url="http://offline.invalid:1",
        rtvi_embed_base_url="",
        rtvi_cv_base_url="",
    ).routes[0]
    with patch.object(module.httpx, "AsyncClient", _FakeClient):
        try:
            result = await route.endpoint(
                filename=filename, request=_FakeRequest(headers)
            )
        except module.HTTPException as exc:
            return {
                "content_type": content_type,
                "accepted": False,
                "status": exc.status_code,
                "fake_upload_calls": len(upload_calls),
            }
    if len(upload_calls) != 1 or not upload_calls[0]["stream_is_async"]:
        raise QualificationError("accepted Search upload did not use the fake stream")
    if result.sensor_id != "sensor-offline":
        raise QualificationError("unexpected Search upload response")
    return {
        "content_type": content_type,
        "accepted": True,
        "status": 201,
        "fake_upload_calls": len(upload_calls),
    }


def _exercise_search_upload() -> dict[str, Any]:
    module = _load_search_product_module()
    route = module.create_video_search_ingest_router(
        vst_internal_url="http://offline.invalid:1", rtvi_embed_base_url=""
    ).routes[0]
    if (
        route.path != "/api/v1/videos-for-search/{filename}"
        or route.deprecated is not True
    ):
        raise QualificationError("Search compatibility route metadata drift")
    case_inputs = [
        ("video/mp4", "24", "clip.mp4"),
        ("video/x-matroska", "24", "clip.mkv"),
        (None, "24", "clip.mp4"),
        ("video/avi", "24", "clip.avi"),
        ("video/mp4; charset=binary", "24", "clip.mp4"),
        ("video/mp4", None, "clip.mp4"),
        ("video/mp4", "not-an-integer", "clip.mp4"),
        ("video/mp4", "0", "clip.mp4"),
    ]

    async def _run_cases() -> list[dict[str, Any]]:
        return [
            await _search_case(
                module,
                content_type=content_type,
                content_length=content_length,
                filename=filename,
            )
            for content_type, content_length, filename in case_inputs
        ]

    cases = asyncio.run(_run_cases())
    expected_statuses = [201, 201, 400, 415, 415, 400, 400, 400]
    if [row["status"] for row in cases] != expected_statuses:
        raise QualificationError("Search product behavior drift")
    return {
        "route": route.path,
        "deprecated": route.deprecated,
        "advertised_accepted": ["video/mp4", "video/x-matroska"],
        "advertised_missing_or_unsupported_status": 400,
        "cases": cases,
        "observed_accepted": ["video/mp4", "video/x-matroska"],
        "observed_missing_status": 400,
        "observed_unsupported_status": 415,
        "exact_media_type_match": True,
        "external_network_calls": 0,
        "canonical_match": False,
        "mismatch": "unsupported Content-Type is 415 in product code but 400 in the canonical contract",
    }


class _VlmRequestParams:
    def __init__(self) -> None:
        self.vlm_prompt = ""
        self.vlm_generation_config: dict[str, Any] = {}


class _SilentLogger:
    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: None


class _Gauge:
    def set(self, _value: float) -> None:
        return None


class _Metrics:
    def __init__(self) -> None:
        self.vlm_pipeline_latency_latest = _Gauge()


def _extract_lvs_product_types() -> tuple[type[Any], type[Any], str]:
    source = _repo_file(LVS_SOURCE).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=LVS_SOURCE)
    request_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RequestInfo"
        ),
        None,
    )
    handler_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ViaStreamHandler"
        ),
        None,
    )
    if request_node is None or handler_node is None:
        raise QualificationError("LVS product class denominator missing")
    trigger_node = next(
        (
            node
            for node in handler_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "_trigger_query"
        ),
        None,
    )
    if trigger_node is None:
        raise QualificationError("LVS product trigger method missing")
    ast_digest = _sha256(
        ast.dump(trigger_node, annotate_fields=True, include_attributes=False).encode()
    )
    extracted_handler = ast.ClassDef(
        name="ExtractedViaStreamHandler",
        bases=[],
        keywords=[],
        body=[copy.deepcopy(trigger_node)],
        decorator_list=[],
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            copy.deepcopy(request_node),
            extracted_handler,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    request_exceptions = types.SimpleNamespace(
        ConnectionError=type("OfflineConnectionError", (Exception,), {}),
        Timeout=type("OfflineTimeout", (Exception,), {}),
    )
    namespace: dict[str, Any] = {
        "__name__": "_offline_lvs_product_extract",
        "concurrent": concurrent,
        "Enum": Enum,
        "Event": Event,
        "uuid": uuid,
        "VlmRequestParams": _VlmRequestParams,
        "logger": _SilentLogger(),
        "os": os,
        "time": time,
        "is_tracing_enabled": lambda: False,
        "requests": types.SimpleNamespace(exceptions=request_exceptions),
        "RtviError": type("OfflineRtviError", (Exception,), {}),
    }
    exec(compile(module, LVS_SOURCE, "exec"), namespace)
    return namespace["RequestInfo"], namespace["ExtractedViaStreamHandler"], ast_digest


def _exercise_lvs_queue() -> dict[str, Any]:
    request_type, handler_type, ast_digest = _extract_lvs_product_types()
    request_a = request_type()
    request_b = request_type()
    request_a.source_id = "offline-a"
    request_b.source_id = "offline-b"
    request_a.source_url = "file-a"
    request_b.source_url = "file-b"
    initial = [request_a.status.value, request_b.status.value]

    barrier = threading.Barrier(2)
    state_lock = threading.Lock()
    state = {"active": 0, "peak": 0, "statuses": {}}
    requests_by_id = {
        request_a.source_id: request_a,
        request_b.source_id: request_b,
    }

    class _Pipeline:
        _base_url = "offline-fake"

        @staticmethod
        def get_models_info() -> types.SimpleNamespace:
            return types.SimpleNamespace(id="offline-fake-model")

        @staticmethod
        def generate_captions_stream(**kwargs: Any):
            source_id = kwargs["file_id"]
            with state_lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                state["statuses"][source_id] = requests_by_id[source_id].status.value
            try:
                barrier.wait(timeout=5)
                yield {"chunk_responses": []}
            finally:
                with state_lock:
                    state["active"] -= 1

    handler = handler_type()
    handler._vlm_pipeline = _Pipeline()
    handler._metrics = _Metrics()
    handler._end_vlm_pipeline_span = lambda _req: None
    handler._process_output = lambda *_args: None
    with patch.dict(os.environ, {"ENABLE_DENSE_CAPTION": "false"}, clear=False):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(handler._trigger_query, request_a),
                pool.submit(handler._trigger_query, request_b),
            ]
            for future in futures:
                future.result(timeout=10)
    statuses = [state["statuses"][key] for key in sorted(state["statuses"])]
    if initial != ["queued", "queued"] or statuses != ["processing", "processing"]:
        raise QualificationError("LVS request state transition drift")
    if state["peak"] != 2:
        raise QualificationError("bounded LVS concurrency observation drift")
    return {
        "advertised_active_requests": 1,
        "advertised_additional_requests": "queued",
        "executed_product_method": "ViaStreamHandler._trigger_query",
        "executed_ast_sha256": ast_digest,
        "submitted_requests": 2,
        "initial_statuses": initial,
        "statuses_at_pipeline_entry": statuses,
        "peak_concurrent_fake_pipeline_calls": state["peak"],
        "second_request_observed_queued": False,
        "lvs_handler_serialization_match": False,
        "end_to_end_contract_status": "unqualified_downstream_rtvi_may_queue",
        "external_calls": 0,
    }


def _parse_ui_default_validator() -> tuple[str, list[str], list[str]]:
    source = _repo_file(UI_SOURCE).read_text(encoding="utf-8")
    accept_match = re.search(r"const DEFAULT_ACCEPT = '([^']+)';", source)
    extension_match = re.search(
        r"const allowedExtensions = /\\\.\(([^)]+)\)\$/i;", source
    )
    mime_match = re.search(r"const allowedMimeTypes = \[([^\]]+)\];", source)
    if not accept_match or not extension_match or not mime_match:
        raise QualificationError("UI default validator expression drift")
    extensions = extension_match.group(1).split("|")
    mime_types = re.findall(r"'([^']+)'", mime_match.group(1))
    if extensions != ["mp4", "mkv"] or mime_types != [
        "video/mp4",
        "video/x-matroska",
    ]:
        raise QualificationError("UI default format denominator drift")
    return accept_match.group(1), extensions, mime_types


def _exercise_lvs_formats() -> dict[str, Any]:
    default_accept, extensions, mime_types = _parse_ui_default_validator()
    extension_re = re.compile(r"\.(?:" + "|".join(extensions) + r")$", re.I)
    denominator = [
        ("MP4", ".mp4", "video/mp4"),
        ("AVI", ".avi", "video/x-msvideo"),
        ("MOV", ".mov", "video/quicktime"),
        ("MKV", ".mkv", "video/x-matroska"),
        ("WebM", ".webm", "video/webm"),
    ]
    cases = []
    for format_name, extension, mime_type in denominator:
        admitted = (
            bool(extension_re.search(f"clip{extension}")) or mime_type in mime_types
        )
        cases.append(
            {
                "format": format_name,
                "extension": extension,
                "mime_type": mime_type,
                "ui_default_admitted": admitted,
            }
        )
    admitted_formats = [row["format"] for row in cases if row["ui_default_admitted"]]
    missing_formats = [row["format"] for row in cases if not row["ui_default_admitted"]]
    agent_readme = _repo_file("services/agent/README.md").read_text(encoding="utf-8")
    proprietary_documented = all(
        token in agent_readme
        for token in [
            "does not bundle `opencv-python-headless`",
            "opting in to the proprietary codecs",
            "`INSTALL_PROPRIETARY_CODECS=true`",
        ]
    )
    if admitted_formats != ["MP4", "MKV"] or missing_formats != [
        "AVI",
        "MOV",
        "WebM",
    ]:
        raise QualificationError("UI format boundary observation drift")
    if not proprietary_documented:
        raise QualificationError("proprietary-codec boundary documentation drift")
    return {
        "advertised_formats": ["MP4", "AVI", "MOV", "MKV", "WebM"],
        "proprietary_where_supported": True,
        "ui_default_accept": default_accept,
        "ui_default_extensions": extensions,
        "ui_default_mime_types": mime_types,
        "cases": cases,
        "ui_default_admitted_formats": admitted_formats,
        "ui_default_missing_advertised_formats": missing_formats,
        "proprietary_codec_opt_in_documented": proprietary_documented,
        "capability_status": "not_proven_ui_surface_narrower_than_advertised_contract",
        "live_decode_matrix_executed": False,
    }


def _exercise_observations() -> dict[str, Any]:
    observations = {
        "search_upload": _exercise_search_upload(),
        "lvs_queue": _exercise_lvs_queue(),
        "lvs_formats": _exercise_lvs_formats(),
        "adjacent_negatives": [
            {"case_id": case_id, "observed": True} for case_id in EXPECTED_NEGATIVES
        ],
    }
    return observations


def run() -> dict[str, Any]:
    contract = _load_contract()
    source_hashes = _verify_source_locks(contract)
    bindings = _verify_bindings(contract)
    first = _exercise_observations()
    second = _exercise_observations()
    first_bytes = _canonical_bytes(first)
    second_bytes = _canonical_bytes(second)
    if first_bytes != second_bytes:
        raise QualificationError("independent observation runs differ")
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
            "external_calls": 0,
            "network_calls": 0,
            "subprocess_calls": 0,
            "filesystem_writes": 0,
            "docker_calls": 0,
            "service_lifecycle_calls": 0,
            "model_calls": 0,
            "warehouse_sample_bundle": "excluded",
            "counter_basis": "locked_source_and_replaced_transport_boundary_audit",
        },
        "remaining_live_blockers": REMAINING_LIVE_BLOCKERS,
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "result": "candidate_executable_mismatch_non_advancing",
    }
    schema = _strict_json(LANE / "result.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise QualificationError(f"invalid result: {errors[0].message}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit canonical JSON")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
