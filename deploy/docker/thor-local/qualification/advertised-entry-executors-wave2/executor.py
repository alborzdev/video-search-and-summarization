#!/usr/bin/env python3
"""Second candidate-only file executor wave for 21 advertised-entry gaps.

Only digest-locked definitions and data are evaluated.  All filesystem-like
effects used by source bodies are in-memory adapters; this module performs no
network, Docker, subprocess, credential, download, lifecycle, or file-write
operations.  Results are helper/source-contract observations, never runtime
qualification or live acceptance evidence.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import copy
import datetime as datetime_module
import hashlib
import io
import json
import math
import posixpath
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Set, Tuple

import numpy as np
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
INVENTORY_PATH = HERE / "inventory.json"
INVENTORY_SCHEMA_PATH = HERE / "inventory.schema.json"
RESULT_SCHEMA_PATH = HERE / "result.schema.json"
MAX_SOURCE_BYTES = 4_000_000

COMMON = "services/rtvi/rt-vlm/src/api_models/common.py"
LIVE_STREAM = "services/rtvi/rt-vlm/src/api_models/live_stream.py"
ASSET_MANAGER = "services/rtvi/rt-vlm/src/utils/asset_manager.py"
DENSE_SERIALIZER = "services/rtvi/rt-vlm/src/utils/dense_caption_serializer.py"
STREAM_HANDLER = "services/rtvi/rt-vlm/src/server/rtvi_stream_handler.py"
VLM_SERVER = "services/rtvi/rt-vlm/src/server/rtvi_vlm_server.py"
MEDIA_KWARGS = "services/rtvi/rt-vlm/src/utils/media_io_kwargs.py"
FRAME_GETTER = "services/rtvi/rt-vlm/src/vlm_pipeline/video_file_frame_getter.py"
MODEL_MATRIX = "deploy/docker/thor-local/rt-vlm/model-matrix.json"
MODEL_ORACLE = "deploy/docker/thor-local/rt-vlm/official-vss-3.2.1-models.json"
RT_VLM_README = "services/rtvi/rt-vlm/README.md"
BOX_CHECK = "tools/sdg-postprocessing/semantic_labeling/box_check.py"
REMOVE_LABEL = "tools/sdg-postprocessing/semantic_labeling/remove_label.py"
DEPTH_CONVERT = "tools/sdg-postprocessing/data_conversion/convert_npy_to_png_depthmap.py"
H5_CONVERT = "tools/sdg-postprocessing/data_conversion/convert_single_camera_rgb_depth_to_h5.py"
GROUND_TRUTH = "tools/sdg-postprocessing/data_conversion/convert_ground_truth.py"


EXPECTED_CASE_BINDINGS = {
    "manifest-gap.rt-vlm-media.00-file-upload": ("/features/8/advertised/0", "file_upload_helper", {ASSET_MANAGER}),
    "manifest-gap.rt-vlm-media.01-http-s": ("/features/8/advertised/1", "uri_validator", {COMMON}),
    "manifest-gap.rt-vlm-media.02-s3": ("/features/8/advertised/2", "uri_validator", {COMMON}),
    "manifest-gap.rt-vlm-media.03-allowlisted-file-uri": (
        "/features/8/advertised/3", "file_uri_allowlist", {VLM_SERVER}
    ),
    "manifest-gap.rt-vlm-media.04-inline-data-uri": (
        "/features/8/advertised/4", "inline_data_uri", {COMMON, ASSET_MANAGER}
    ),
    "manifest-gap.rt-vlm-media.05-rtsp": ("/features/8/advertised/5", "rtsp_validator", {LIVE_STREAM}),
    "manifest-gap.rt-vlm-media.06-dense-captions": (
        "/features/8/advertised/6", "dense_caption_roundtrip", {DENSE_SERIALIZER}
    ),
    "manifest-gap.rt-vlm-media.07-incidents": (
        "/features/8/advertised/7", "incident_trigger_helper", {STREAM_HANDLER}
    ),
    "manifest-gap.rt-vlm-media.09-reasoning": (
        "/features/8/advertised/9", "reasoning_helpers", {VLM_SERVER, STREAM_HANDLER}
    ),
    "manifest-gap.rt-vlm-performance-observability.00-efficient-video-sampling": (
        "/features/11/advertised/0", "frame_sampling_helper", {MEDIA_KWARGS}
    ),
    "manifest-gap.rt-vlm-performance-observability.01-gop-aware-decode": (
        "/features/11/advertised/1", "gop_selection_helper", {FRAME_GETTER}
    ),
    "manifest-gap.rt-vlm-performance-observability.02-decoder-reuse": (
        "/features/11/advertised/2", "decoder_cache_helper", {FRAME_GETTER}
    ),
    "manifest-gap.rt-vlm-performance-observability.04-asset-limits-and-expiry": (
        "/features/11/advertised/4", "asset_limit_expiry_helpers", {ASSET_MANAGER}
    ),
    "manifest-gap.rt-vlm-performance-observability.07-absolute-timestamp-metadata": (
        "/features/11/advertised/7", "absolute_timestamp_helper", {STREAM_HANDLER}
    ),
    "manifest-gap.rt-vlm-models.00-cosmos-reason-1-2": (
        "/features/10/advertised/0", "model_source_contract", {MODEL_MATRIX, MODEL_ORACLE, RT_VLM_README}
    ),
    "manifest-gap.rt-vlm-models.01-cosmos-3-nano-super": (
        "/features/10/advertised/1", "model_source_contract", {MODEL_MATRIX, MODEL_ORACLE, RT_VLM_README}
    ),
    "manifest-gap.rt-vlm-models.02-nemotron-omni": (
        "/features/10/advertised/2", "model_source_contract", {MODEL_MATRIX, MODEL_ORACLE, RT_VLM_README}
    ),
    "manifest-gap.rt-vlm-models.03-qwen-3-5-and-moe": (
        "/features/10/advertised/3", "model_source_contract", {MODEL_MATRIX, MODEL_ORACLE, RT_VLM_README}
    ),
    "manifest-gap.synthetic-data-tools.00-semantic-label-helpers": (
        "/features/30/advertised/0", "semantic_label_helpers", {BOX_CHECK, REMOVE_LABEL}
    ),
    "manifest-gap.synthetic-data-tools.02-rgb-depth-video-conversion": (
        "/features/30/advertised/2", "rgb_depth_conversion_helpers", {DEPTH_CONVERT, H5_CONVERT}
    ),
    "manifest-gap.synthetic-data-tools.03-ground-truth-conversion": (
        "/features/30/advertised/3", "ground_truth_helpers", {GROUND_TRUTH}
    ),
}


class QualificationError(RuntimeError):
    """A source lock, inventory contract, or semantic fixture did not match."""


def _read_bytes(relative_path: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise QualificationError(f"unsafe repository path: {relative_path}")
    repository = REPO_ROOT.resolve(strict=True)
    try:
        resolved = (repository / path).resolve(strict=True)
        resolved.relative_to(repository)
    except (OSError, ValueError) as exc:
        raise QualificationError(
            f"repository path does not resolve inside the checkout: {relative_path}"
        ) from exc
    data = resolved.read_bytes()
    if len(data) > max_bytes:
        raise QualificationError(f"source exceeds {max_bytes} bytes: {relative_path}")
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _strict_json_bytes(data: bytes, label: str) -> Any:
    def reject_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError(f"duplicate JSON key in {label}: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(data, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid JSON in {label}") from exc


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


def _verify_lock(lock: Dict[str, str]) -> bytes:
    raw = _read_bytes(lock["path"])
    actual = _sha256(raw)
    if actual != lock["sha256"]:
        raise QualificationError(f"source lock mismatch for {lock['path']}: {actual} != {lock['sha256']}")
    return raw


def _extract_symbols(relative_path: str, names: Iterable[str], namespace: Dict[str, Any]) -> Dict[str, Any]:
    wanted = list(names)
    tree = ast.parse(_read_bytes(relative_path), filename=relative_path)
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in wanted
    ]
    found = [node.name for node in selected]
    if len(found) != len(wanted) or set(found) != set(wanted):
        raise QualificationError(f"symbol allowlist mismatch for {relative_path}: wanted={wanted}, found={found}")
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace)
    scope.setdefault("__builtins__", __builtins__)
    exec(compile(module, relative_path, "exec"), scope)  # noqa: S102 - digest-locked selected AST only
    return {name: scope[name] for name in wanted}


def _extract_class_methods(
    relative_path: str, class_name: str, method_names: Iterable[str], namespace: Dict[str, Any]
) -> type:
    wanted = set(method_names)
    tree = ast.parse(_read_bytes(relative_path), filename=relative_path)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name]
    if len(classes) != 1:
        raise QualificationError(f"class allowlist mismatch for {relative_path}: {class_name}")
    source_class = classes[0]
    methods = [
        copy.deepcopy(node)
        for node in source_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    if {node.name for node in methods} != wanted:
        raise QualificationError(f"method allowlist mismatch for {class_name}: {sorted(wanted)}")
    selected = ast.ClassDef(
        name=class_name,
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.Module(body=[selected], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace)
    scope.setdefault("__builtins__", __builtins__)
    exec(compile(module, relative_path, "exec"), scope)  # noqa: S102 - digest-locked selected AST only
    return scope[class_name]


def _extract_assignments(relative_path: str, names: Iterable[str], namespace: Dict[str, Any]) -> Dict[str, Any]:
    wanted = set(names)
    tree = ast.parse(_read_bytes(relative_path), filename=relative_path)
    selected = []
    found: Set[str] = set()
    for node in tree.body:
        targets: Set[str] = set()
        if isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = {node.target.id}
        if targets & wanted:
            selected.append(node)
            found.update(targets & wanted)
    if found != wanted:
        raise QualificationError(f"assignment allowlist mismatch for {relative_path}: {sorted(wanted - found)}")
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    scope = dict(namespace)
    scope.setdefault("__builtins__", __builtins__)
    exec(compile(module, relative_path, "exec"), scope)  # noqa: S102 - digest-locked selected AST only
    return {name: scope[name] for name in wanted}


def _load_and_validate_inventory() -> Tuple[Dict[str, Any], bytes]:
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
        "previously_selected_candidate_entries": 8,
        "prior_open_entries": 79,
        "selected_candidate_entries": 21,
        "entries_left_open": 58,
    }
    if inventory.get("denominator") != expected_denominator:
        raise QualificationError("87/8/79/21/58 denominator is not exact")

    plan_spec = inventory["source_plan"]
    plan_raw = _read_bytes(plan_spec["path"])
    if _sha256(plan_raw) != plan_spec["raw_sha256"]:
        raise QualificationError("advertised-entry gap plan source lock mismatch")
    plan = _strict_json_bytes(plan_raw, plan_spec["path"])
    if plan.get("plan_payload_sha256") != plan_spec["plan_payload_sha256"]:
        raise QualificationError("gap plan payload identity mismatch")

    manifest_spec = inventory["source_manifest"]
    manifest_raw = _read_bytes(manifest_spec["path"])
    if _sha256(manifest_raw) != manifest_spec["raw_sha256"]:
        raise QualificationError("manifest source lock mismatch")
    manifest = _strict_json_bytes(manifest_raw, manifest_spec["path"])

    previous_spec = inventory["previous_candidate_inventory"]
    previous_raw = _read_bytes(previous_spec["path"])
    if _sha256(previous_raw) != previous_spec["raw_sha256"]:
        raise QualificationError("previous candidate inventory source lock mismatch")
    previous = _strict_json_bytes(previous_raw, previous_spec["path"])
    previous_ids = {case["entry_id"] for case in previous.get("cases", [])}
    if len(previous_ids) != 8 or previous.get("denominator", {}).get("entries_left_open") != 79:
        raise QualificationError("previous candidate inventory is not the exact 8/79 predecessor")

    cases = inventory.get("cases", [])
    current_ids = {case["entry_id"] for case in cases}
    if len(cases) != 21 or len(current_ids) != 21 or current_ids != set(EXPECTED_CASE_BINDINGS):
        raise QualificationError("inventory must contain the exact 21-entry wave")
    if current_ids & previous_ids:
        raise QualificationError("wave2 overlaps the eight predecessor candidate entries")

    plan_by_pointer = {entry["manifest_pointer"]: entry for entry in plan["entries"]}
    for case in cases:
        pointer = case["manifest_pointer"]
        expected_pointer, expected_adapter, expected_sources = EXPECTED_CASE_BINDINGS[case["entry_id"]]
        if pointer != expected_pointer or case["adapter_id"] != expected_adapter:
            raise QualificationError(f"bounded adapter binding mismatch for {case['entry_id']}")
        if {lock["path"] for lock in case["source_locks"]} != expected_sources:
            raise QualificationError(f"bounded source set mismatch for {case['entry_id']}")
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
            _verify_lock(lock)
    return inventory, raw


class _PersistentStringIO(io.StringIO):
    def close(self) -> None:
        pass


class _MemoryAsyncWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def write(self, value: bytes) -> None:
        self.data.extend(value)

    async def close(self) -> None:
        return None


class _MemoryUpload:
    def __init__(self, chunks: List[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _AssetRecord:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def _asset_class(methods: Iterable[str], namespace: Optional[Dict[str, Any]] = None) -> type:
    scope = {
        "Optional": Optional,
        "ThreadPoolExecutor": object,
        "logger": SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None),
    }
    scope.update(namespace or {})
    return _extract_class_methods(ASSET_MANAGER, "AssetManager", methods, scope)


def _file_upload_helper() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    writes: Dict[str, _MemoryAsyncWriter] = {}
    made_dirs: List[str] = []

    async def makedirs(path: str) -> None:
        made_dirs.append(path)

    def memory_open(path: str, _mode: str) -> _MemoryAsyncWriter:
        writer = _MemoryAsyncWriter()
        writes[path] = writer
        return writer

    fake_aiofiles = SimpleNamespace(os=SimpleNamespace(makedirs=makedirs), open=memory_open)
    fake_os = SimpleNamespace(path=SimpleNamespace(join=posixpath.join))
    fake_uuid = SimpleNamespace(uuid4=lambda: "generated-id")
    cls = _asset_class(
        ["save_file"],
        {
            "aiofiles": fake_aiofiles,
            "os": fake_os,
            "uuid": fake_uuid,
            "AGE_OUT_THRESHOLD": 0.9,
            "Asset": _AssetRecord,
            "ServiceException": QualificationError,
            "shutil": SimpleNamespace(rmtree=lambda *_a: None),
            "asyncio": asyncio,
        },
    )
    manager = SimpleNamespace(
        _asset_dir="/memory/assets",
        _asset_map={},
        _max_storage_usage_gb=0,
        _storage_usage_cache=17,
    )

    async def storage_usage() -> float:
        return 0.0

    manager._get_storage_usage = storage_usage
    manager._age_out_assets = lambda: None
    fixture = {"file_id": "upload-001", "file_name": "clip.mp4", "chunks": ["abc", "def"]}
    asset_id = asyncio.run(
        cls.save_file(
            manager,
            _MemoryUpload([b"abc", b"def"]),
            fixture["file_name"],
            "vision",
            "video",
            "2026-07-31T12:00:00.000Z",
            fixture["file_id"],
            None,
            "Camera",
        )
    )
    output_path = "/memory/assets/upload-001/clip.mp4"
    output = {
        "asset_id": asset_id,
        "directory": made_dirs,
        "output_path": output_path,
        "bytes_hex": bytes(writes[output_path].data).hex(),
        "registered": sorted(manager._asset_map),
        "storage_cache_invalidated": manager._storage_usage_cache is None,
        "real_file_writes": 0,
    }
    expected = {
        "asset_id": "upload-001",
        "directory": ["/memory/assets/upload-001"],
        "output_path": output_path,
        "bytes_hex": "616263646566",
        "registered": ["upload-001"],
        "storage_cache_invalidated": True,
        "real_file_writes": 0,
    }
    if output != expected:
        raise QualificationError(f"file-upload helper output differs: {output}")
    return fixture, output


def _uri_patterns() -> Dict[str, str]:
    names = [
        "HTTP_URL_PATTERN",
        "HTTP_OR_S3_URL_PATTERN",
        "_DATA_URI_BASE64",
        "_DATA_URI_NON_BASE64",
        "HTTP_S3_OR_DATA_URL_PATTERN",
        "DATA_URL_HEADER_PATTERN",
        "FILE_URL_PATTERN",
        "HTTP_S3_DATA_OR_FILE_URL_PATTERN",
        "AWS_S3_URL_PATTERN",
    ]
    return _extract_assignments(COMMON, names, {})


def _uri_validator(advertised: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    patterns = _uri_patterns()
    if advertised == "HTTP/S":
        fixture = {"accepted": ["http://8.8.8.8/a.mp4", "https://example.com/a.mp4"], "rejected": ["file:///a.mp4", "https://example.com/a b.mp4"]}
        pattern = patterns["HTTP_URL_PATTERN"]
    elif advertised == "S3":
        fixture = {"accepted": ["s3://bucket/path/video.mp4"], "rejected": ["ftp://bucket/video.mp4", "s3://bad path/video.mp4"]}
        pattern = patterns["AWS_S3_URL_PATTERN"]
    else:
        raise QualificationError(f"unsupported URI fixture: {advertised}")
    accepted = [bool(re.fullmatch(pattern, value)) for value in fixture["accepted"]]
    rejected = [not bool(re.fullmatch(pattern, value)) for value in fixture["rejected"]]
    output = {"accepted": accepted, "rejected": rejected, "validator_scope": "request-pattern-only"}
    if not all(accepted + rejected):
        raise QualificationError(f"URI validator result differs for {advertised}: {output}")
    return fixture, output


class _ServiceException(Exception):
    def __init__(self, message: str, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _file_uri_allowlist() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fake_path = SimpleNamespace(
        realpath=lambda value: posixpath.normpath(value),
        isfile=lambda value: value == "/allowed/clip.mp4",
    )
    fake_os = SimpleNamespace(path=fake_path, sep="/", environ={"FILE_URL_ALLOWED_DIRS": "/allowed"})
    cls = _extract_class_methods(
        VLM_SERVER,
        "RTVIServer",
        ["_resolve_file_url"],
        {"os": fake_os, "ServiceException": _ServiceException},
    )
    server = SimpleNamespace()
    allowed = cls._resolve_file_url(server, "file:///allowed/clip.mp4")
    denied_status = None
    missing_status = None
    for url, label in (("file:///allowed/../secret.mp4", "denied"), ("file:///allowed/missing.mp4", "missing")):
        try:
            cls._resolve_file_url(server, url)
        except _ServiceException as exc:
            if label == "denied":
                denied_status = exc.status
            else:
                missing_status = exc.status
    fixture = {"allowed_root": "/allowed", "allowed": "file:///allowed/clip.mp4", "traversal": "file:///allowed/../secret.mp4"}
    output = {"resolved": allowed, "traversal_status": denied_status, "missing_status": missing_status, "real_file_reads": 0}
    if output != {"resolved": "/allowed/clip.mp4", "traversal_status": 403, "missing_status": 400, "real_file_reads": 0}:
        raise QualificationError(f"file URI allowlist helper differs: {output}")
    return fixture, output


def _inline_data_uri() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    patterns = _uri_patterns()
    fixture = {
        "base64": "data:video/mp4;base64,QUJD",
        "url_encoded": "data:text/plain,hello%20world",
        "invalid": "data:video/mp4;base64;base64,QUJD",
    }
    accepted = bool(re.fullmatch(patterns["HTTP_S3_OR_DATA_URL_PATTERN"], fixture["base64"]))
    header_valid = bool(re.fullmatch(patterns["DATA_URL_HEADER_PATTERN"], fixture["base64"].split(",", 1)[0]))
    invalid_rejected = not bool(re.fullmatch(patterns["DATA_URL_HEADER_PATTERN"], fixture["invalid"].split(",", 1)[0]))

    writes: Dict[str, _MemoryAsyncWriter] = {}

    async def makedirs(_path: str) -> None:
        return None

    def memory_open(path: str, _mode: str) -> _MemoryAsyncWriter:
        writer = _MemoryAsyncWriter()
        writes[path] = writer
        return writer

    fake_aiofiles = SimpleNamespace(os=SimpleNamespace(makedirs=makedirs), open=memory_open)
    fake_os = SimpleNamespace(path=SimpleNamespace(join=posixpath.join))
    cls = _asset_class(
        ["save_from_base64"],
        {
            "aiofiles": fake_aiofiles,
            "os": fake_os,
            "Asset": _AssetRecord,
            "ServiceException": _ServiceException,
            "MAX_DOWNLOAD_FILE_SIZE": 1024,
        },
    )
    manager = SimpleNamespace(
        _asset_dir="/memory",
        _asset_map={},
        _storage_usage_cache=1,
        _MIME_TO_EXT={"video/mp4": ".mp4", "text/plain": ".txt"},
    )
    asset_id = asyncio.run(cls.save_from_base64(manager, fixture["base64"], "video", None, "data-001"))
    output_path = "/memory/data-001/base64_media.mp4"
    output = {
        "pattern_accepted": accepted,
        "header_valid": header_valid,
        "duplicate_base64_rejected": invalid_rejected,
        "asset_id": asset_id,
        "decoded_hex": bytes(writes[output_path].data).hex(),
        "real_file_writes": 0,
    }
    expected = {
        "pattern_accepted": True,
        "header_valid": True,
        "duplicate_base64_rejected": True,
        "asset_id": "data-001",
        "decoded_hex": base64.b64decode("QUJD").hex(),
        "real_file_writes": 0,
    }
    if output != expected:
        raise QualificationError(f"inline data URI helper differs: {output}")
    return fixture, output


def _rtsp_validator() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    patterns = _extract_assignments(LIVE_STREAM, ["LIVE_STREAM_URL_PATTERN", "CV_STREAM_URL_PATTERN"], {})
    fixture = {"rtsp": "rtsp://camera/live", "file": "file:///clip.mp4", "http": "https://example.com/live"}
    output = {
        "original_accepts_rtsp": bool(re.match(patterns["LIVE_STREAM_URL_PATTERN"], fixture["rtsp"])),
        "original_rejects_http": not bool(re.match(patterns["LIVE_STREAM_URL_PATTERN"], fixture["http"])),
        "cv_accepts_rtsp": bool(re.match(patterns["CV_STREAM_URL_PATTERN"], fixture["rtsp"])),
        "cv_accepts_file": bool(re.match(patterns["CV_STREAM_URL_PATTERN"], fixture["file"])),
        "validator_scope": "request-pattern-only",
    }
    if not all(value for key, value in output.items() if key != "validator_scope"):
        raise QualificationError(f"RTSP validator helper differs: {output}")
    return fixture, output


class _ChunkInfo:
    pass


class _PipelineChunkResult:
    def __init__(self) -> None:
        self.vlm_model_output = None
        self.frame_times = []
        self.chunk = None


class _VlmModelOutput:
    def __init__(self, output: str = "") -> None:
        self.output = output


def _dense_caption_roundtrip() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    storage: Dict[str, _PersistentStringIO] = {}

    def memory_open(path: str, mode: str, *_args, **_kwargs):
        if "w" in mode:
            storage[path] = _PersistentStringIO()
            return storage[path]
        if "r" in mode:
            return _PersistentStringIO(storage[path].getvalue())
        raise QualificationError(f"unexpected dense-caption mode: {mode}")

    cls = _extract_symbols(
        DENSE_SERIALIZER,
        ["DenseCaptionSerializer"],
        {
            "json": json,
            "ChunkInfo": _ChunkInfo,
            "PipelineChunkResult": _PipelineChunkResult,
            "VlmModelOutput": _VlmModelOutput,
            "logger": SimpleNamespace(warning=lambda *_a, **_k: None),
            "open": memory_open,
        },
    )["DenseCaptionSerializer"]

    def result(index: int, caption: str) -> _PipelineChunkResult:
        item = _PipelineChunkResult()
        item.vlm_model_output = _VlmModelOutput(caption)
        item.frame_times = [index + 0.25]
        item.chunk = SimpleNamespace(
            streamId="stream-1", chunkIdx=index, file="clip.mp4", pts_offset_ns=0,
            start_pts=index * 1_000_000_000, end_pts=(index + 1) * 1_000_000_000,
            start_ntp="", end_ntp="", start_ntp_float=0.0, end_ntp_float=0.0,
            is_first=index == 0, is_last=index == 1, asset_dir="/memory",
        )
        return item

    fixture = {"input_order": [1, 0], "captions": ["second", "first"]}
    cls.to_json([result(1, "second"), result(0, "first")], "dense.jsonl")
    restored = cls.from_json("dense.jsonl")
    output = {
        "jsonl_rows": len(storage["dense.jsonl"].getvalue().splitlines()),
        "restored_order": [item.chunk.chunkIdx for item in restored],
        "captions": [item.vlm_model_output.output for item in restored],
        "frame_times": [item.frame_times for item in restored],
        "real_file_writes": 0,
    }
    expected = {
        "jsonl_rows": 2,
        "restored_order": [0, 1],
        "captions": ["first", "second"],
        "frame_times": [[0.25], [1.25]],
        "real_file_writes": 0,
    }
    if output != expected:
        raise QualificationError(f"dense-caption roundtrip differs: {output}")
    return fixture, output


def _incident_trigger_helper() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    constants = _extract_assignments(
        STREAM_HANDLER,
        ["_INCIDENT_POSITIVE_RE", "_INCIDENT_NEGATIVE_RE", "_RFC3339_TIMESTAMP_RE"],
        {"re": re},
    )
    trigger = _extract_symbols(STREAM_HANDLER, ["_incident_trigger_tokens"], constants)["_incident_trigger_tokens"]
    fixture = {
        "positive": "YES, a person entered",
        "timestamp": "2026-07-31T12:00:01.123Z",
        "negative": "No incident at 2026-07-31T12:00:01Z",
        "substring": "yesterday was quiet",
    }
    output = {key: trigger(value) for key, value in fixture.items()}
    expected = {"positive": ["yes"], "timestamp": ["timestamp"], "negative": [], "substring": []}
    if output != expected:
        raise QualificationError(f"incident trigger helper differs: {output}")
    return fixture, output


def _reasoning_helpers() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    build = _extract_symbols(VLM_SERVER, ["_build_chat_content_with_think_tags"], {})[
        "_build_chat_content_with_think_tags"
    ]
    constants = _extract_assignments(
        STREAM_HANDLER, ["REASONING_INFO_KEY", "REASONING_DESCRIPTION_INFO_KEY"], {}
    )
    add = _extract_symbols(
        STREAM_HANDLER, ["_add_reasoning_to_info"], {**constants, "MutableMapping": MutableMapping}
    )["_add_reasoning_to_info"]
    fixture = {"content": "answer", "reasoning": "  inspect frames  "}
    info: Dict[str, str] = {}
    add(info, fixture["reasoning"].strip())
    output = {"chat_content": build(fixture["content"], fixture["reasoning"]), "info": info}
    expected = {
        "chat_content": "<think>\ninspect frames\n</think>\n\nanswer",
        "info": {"reasoning": "inspect frames", "reasoningDescription": "inspect frames"},
    }
    if output != expected:
        raise QualificationError(f"reasoning helper differs: {output}")
    return fixture, output


def _frame_sampling_helper() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fn = _extract_symbols(
        MEDIA_KWARGS,
        ["get_frame_sampling_params_from_media_io_kwargs"],
        {"Optional": Optional},
    )["get_frame_sampling_params_from_media_io_kwargs"]
    fixture = {
        "fps": {"video": {"fps": 2.5}},
        "all_frames": {"video": {"num_frames": -1}},
        "precedence": {"video": {"fps": 3, "num_frames": 7}},
        "invalid": {"video": "bad"},
    }
    output = {key: fn(value) for key, value in fixture.items()}
    expected = {
        "fps": {"num_frames_per_second_or_fixed_frames_chunk": 2.5, "use_fps_for_chunking": True},
        "all_frames": {"num_frames_per_second_or_fixed_frames_chunk": -1.0, "use_fps_for_chunking": False},
        "precedence": {"num_frames_per_second_or_fixed_frames_chunk": 3.0, "use_fps_for_chunking": True},
        "invalid": {},
    }
    if output != expected:
        raise QualificationError(f"frame sampling helper differs: {output}")
    return fixture, output


class _FakeGst:
    CLOCK_TIME_NONE = -1
    BufferFlags = SimpleNamespace(DELTA_UNIT=1)
    PadProbeReturn = SimpleNamespace(OK="ok", DROP="drop")


class _FakeBuffer:
    def __init__(self, pts: int, delta: bool) -> None:
        self.pts = pts
        self._delta = delta

    def has_flags(self, _flag: int) -> bool:
        return self._delta


def _gop_selection_helper() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cls = _extract_class_methods(
        FRAME_GETTER,
        "VideoFileFrameGetter",
        ["_on_parser_src_buffer"],
        {"Gst": _FakeGst, "logger": SimpleNamespace(debug=lambda *_a, **_k: None)},
    )

    def state(targets: List[int]) -> SimpleNamespace:
        return SimpleNamespace(
            _is_live=False,
            _frame_selector=SimpleNamespace(selects_all_frames=False, _selected_pts_array=deque(targets)),
            _parser_last_i_frame_pts=None,
            _parser_estimated_gop_duration_ns=None,
            _parser_current_gop_has_target=True,
            _frame_duration_ns=0,
        )

    def probe(obj: SimpleNamespace, pts: int, delta: bool) -> str:
        info = SimpleNamespace(get_buffer=lambda: _FakeBuffer(pts, delta))
        return cls._on_parser_src_buffer(obj, None, info)

    keep = state([150])
    probe(keep, 0, False)
    probe(keep, 10, True)
    probe(keep, 100, False)
    keep_result = probe(keep, 110, True)
    drop = state([250])
    probe(drop, 0, False)
    probe(drop, 10, True)
    probe(drop, 100, False)
    drop_result = probe(drop, 110, True)
    fixture = {"estimated_gop_ns": 100, "keep_target_ns": 150, "future_target_ns": 250}
    output = {"target_in_current_gop": keep_result, "target_in_future_gop": drop_result}
    if output != {"target_in_current_gop": "ok", "target_in_future_gop": "drop"}:
        raise QualificationError(f"GOP selection helper differs: {output}")
    return fixture, output


def _decoder_cache_helper() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fake_os = SimpleNamespace(environ={"DISABLE_DECODER_REUSE": "false"})
    cls = _extract_class_methods(
        FRAME_GETTER,
        "VideoFileFrameGetter",
        [
            "_decoder_reuse_enabled",
            "_decoder_cache_key",
            "_is_cached_decodebin",
            "_cache_decodebin",
            "_disconnect_cached_decodebin_from_pipeline",
            "_set_cached_decoders_null",
        ],
        {
            "os": fake_os,
            "logger": SimpleNamespace(debug=lambda *_a, **_k: None),
            "DECODER_TEARDOWN_TIMEOUT_NS": 120,
        },
    )
    removed: List[str] = []
    nulled: List[Tuple[Any, str, int]] = []
    decoder = object()
    obj = SimpleNamespace(
        _frame_width=1920,
        _frame_height=1080,
        _vdecodebin_cache={},
        _vdecodebin_cache_signal_keys={"signal"},
        _pipeline=SimpleNamespace(remove=lambda value: removed.append("decoder" if value is decoder else "other")),
        _vdecodebin=decoder,
        _set_element_null=lambda value, label, timeout_ns: nulled.append((value, label, timeout_ns)),
    )
    obj._is_cached_decodebin = lambda value: cls._is_cached_decodebin(obj, value)
    key = cls._decoder_cache_key(obj, "h264")
    cls._cache_decodebin(obj, key, decoder)
    cached = cls._is_cached_decodebin(obj, decoder)
    cls._disconnect_cached_decodebin_from_pipeline(obj)
    cls._set_cached_decoders_null(obj)
    fixture = {"codec": "h264", "width": 1920, "height": 1080, "disable_env": "false"}
    output = {
        "enabled": cls._decoder_reuse_enabled(obj),
        "cache_key": list(key),
        "cached_identity": cached,
        "detached": removed,
        "nulled_label": nulled[0][1],
        "cache_empty": obj._vdecodebin_cache == {},
        "signals_empty": obj._vdecodebin_cache_signal_keys == set(),
    }
    expected = {
        "enabled": True,
        "cache_key": ["h264", 1920, 1080],
        "cached_identity": True,
        "detached": ["decoder"],
        "nulled_label": "H264 decoder 1920x1080",
        "cache_empty": True,
        "signals_empty": True,
    }
    if output != expected:
        raise QualificationError(f"decoder cache helper differs: {output}")
    return fixture, output


def _asset_limit_expiry_helpers() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    fake_os_for_limit = SimpleNamespace(environ={"ASSET_DOWNLOAD_MAX_FILE_SIZE_GB": "2.5"})
    parse = _extract_symbols(
        ASSET_MANAGER,
        ["_parse_max_download_file_size_bytes"],
        {"os": fake_os_for_limit, "DEFAULT_MAX_DOWNLOAD_FILE_SIZE_GB": 8},
    )["_parse_max_download_file_size_bytes"]

    mtimes = {"/old": 1_000.0, "/new": 9_500.0, "/busy": 1_000.0}

    async def getmtime(path: str) -> float:
        return mtimes[path]

    class _DirectLoop:
        async def run_in_executor(self, _executor, fn, *args):
            return fn(*args)

    fake_asyncio = SimpleNamespace(get_event_loop=lambda: _DirectLoop())
    fake_aiofiles = SimpleNamespace(os=SimpleNamespace(path=SimpleNamespace(getmtime=getmtime)))
    fake_os = SimpleNamespace(path=SimpleNamespace(exists=lambda path: path in mtimes))
    fake_time = SimpleNamespace(time=lambda: 10_000.0)
    cls = _asset_class(
        ["_ttl_expire_assets"],
        {"asyncio": fake_asyncio, "aiofiles": fake_aiofiles, "os": fake_os, "time": fake_time},
    )
    removed: List[str] = []
    assets = {
        "old": SimpleNamespace(asset_dir="/old", use_count=0),
        "new": SimpleNamespace(asset_dir="/new", use_count=0),
        "busy": SimpleNamespace(asset_dir="/busy", use_count=1),
    }

    def cleanup(asset_id: str) -> None:
        removed.append(asset_id)

    manager = SimpleNamespace(
        _max_asset_age_hours=1.0,
        _asset_map=assets,
        _asset_removal_callback=None,
        cleanup_asset=cleanup,
        _aged_out_assets=[],
    )
    asyncio.run(cls._ttl_expire_assets(manager))
    fixture = {"max_size_gb": "2.5", "ttl_hours": 1.0, "ages_seconds": {"old": 9000, "new": 500, "busy": 9000}}
    output = {
        "max_bytes": parse(),
        "removed": removed,
        "aged_out": manager._aged_out_assets,
        "busy_preserved": "busy" not in removed,
        "real_file_deletes": 0,
    }
    expected = {
        "max_bytes": int(2.5 * 1024 * 1024 * 1024),
        "removed": ["old"],
        "aged_out": ["old"],
        "busy_preserved": True,
        "real_file_deletes": 0,
    }
    if output != expected:
        raise QualificationError(f"asset limit/expiry helper differs: {output}")
    return fixture, output


def _absolute_timestamp_helper() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    symbols = _extract_symbols(
        STREAM_HANDLER,
        ["convert_pts_to_absolute_timestamp", "build_media_info_dict_non_streaming"],
        {"datetime": datetime_module.datetime, "timezone": datetime_module.timezone},
    )
    symbols["build_media_info_dict_non_streaming"].__globals__["convert_pts_to_absolute_timestamp"] = symbols[
        "convert_pts_to_absolute_timestamp"
    ]
    fixture = {"creation_time": "2026-07-31T12:00:00.000Z", "start_seconds": 1.25, "end_seconds": 2.5}
    output = symbols["build_media_info_dict_non_streaming"](
        fixture["creation_time"], fixture["start_seconds"], fixture["end_seconds"]
    )
    expected = {
        "type": "timestamp",
        "start_timestamp": "2026-07-31T12:00:01.250Z",
        "end_timestamp": "2026-07-31T12:00:02.500Z",
    }
    if output != expected:
        raise QualificationError(f"absolute timestamp helper differs: {output}")
    return fixture, output


MODEL_FAMILY_KEYS = {
    "Cosmos Reason 1/2": {"Cosmos Reason1", "Cosmos Reason2"},
    "Cosmos 3 Nano/Super": {"Cosmos Reason3"},
    "Nemotron Omni": {"Nemotron Omni"},
    "Qwen 3.5 and MoE": {"Qwen"},
}


def _model_source_contract(advertised: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    matrix = _strict_json_bytes(_read_bytes(MODEL_MATRIX), MODEL_MATRIX)
    oracle = _strict_json_bytes(_read_bytes(MODEL_ORACLE), MODEL_ORACLE)
    readme = _read_bytes(RT_VLM_README).decode("utf-8")
    families = MODEL_FAMILY_KEYS[advertised]
    rows = [row for row in oracle["models"] if row["family"] in families]
    matrix_by_key = {row["key"]: row for row in matrix["advertised_rt_vlm_variants"]}
    if not rows or any(row["key"] not in matrix_by_key for row in rows):
        raise QualificationError(f"model source contract is incomplete for {advertised}")
    mismatched = [
        row["key"]
        for row in rows
        if matrix_by_key[row["key"]]["artifact_id"] != row["model_path"]
        or matrix_by_key[row["key"]]["selector"] != row["selector"]
    ]
    checkout_mentions = sum(
        row["model_path"].removeprefix("git:https://huggingface.co/") in readme for row in rows
    )
    statuses = sorted({matrix_by_key[row["key"]]["thor_status"] for row in rows})
    fixture = {"advertised": advertised, "oracle_release": oracle["authority"]["release"], "families": sorted(families)}
    output = {
        "official_rows": len(rows),
        "matrix_rows": len(rows),
        "identity_mismatches": mismatched,
        "checkout_mentions": checkout_mentions,
        "thor_statuses": statuses,
        "availability_proven": False,
        "readiness_proven": False,
        "contract_scope": "exact-source-listing-only",
    }
    if mismatched or output["official_rows"] < 1 or any("unqualified" not in value for value in statuses):
        raise QualificationError(f"model source contract differs for {advertised}: {output}")
    return fixture, output


class _FakeAttr:
    def __init__(self, captured: List[List[str]]) -> None:
        self.captured = captured

    def Set(self, value: List[str]) -> None:
        self.captured.append(list(value))


class _FakeLabels:
    def __init__(self, captured: List[List[str]]) -> None:
        self.captured = captured

    def __bool__(self) -> bool:
        return True

    def CreateLabelsAttr(self) -> _FakeAttr:
        return _FakeAttr(self.captured)


def _semantic_label_helpers() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    captured: List[List[str]] = []

    class LabelsAPI:
        @staticmethod
        def Get(_prim, _taxonomy):
            return _FakeLabels(captured)

        @staticmethod
        def CanApply(_prim, _taxonomy):
            return True

        @staticmethod
        def Apply(_prim, _taxonomy):
            return _FakeLabels(captured)

        @staticmethod
        def GetDirectTaxonomies(prim):
            return prim.taxonomies

    fake_semantics = SimpleNamespace(LabelsAPI=LabelsAPI)
    constants = _extract_assignments(BOX_CHECK, ["PATTERNS", "EXCLUDED_CRATE_PATTERN"], {"re": re})
    symbols = _extract_symbols(
        BOX_CHECK,
        ["enable_semantics", "_category_for_path", "categorize_boxes"],
        {
            **constants,
            "UsdSemantics": fake_semantics,
            "LegacySemantics": None,
            "Vt": SimpleNamespace(TokenArray=lambda values: list(values)),
            "Usd": SimpleNamespace(Prim=object, Stage=object),
            "DefaultDict": Dict,
            "Dict": Dict,
            "List": List,
            "Optional": Optional,
            "Tuple": Tuple,
            "defaultdict": defaultdict,
            "is_prim_visible": lambda prim: prim.visible,
        },
    )
    for fn in symbols.values():
        fn.__globals__.update(symbols)

    class Prim:
        def __init__(self, path: str, visible: bool = True, taxonomies: Optional[List[str]] = None) -> None:
            self.path = path
            self.visible = visible
            self.taxonomies = taxonomies or []
            self.removed: List[str] = []

        def GetTypeName(self):
            return "Mesh"

        def GetPath(self):
            return self.path

        def RemoveAPI(self, _api, taxonomy):
            self.removed.append(taxonomy)
            return True

        def GetAppliedSchemas(self):
            return []

    visible = Prim("/World/PrintersBox_01/Body")
    hidden = Prim("/World/Crate_01", visible=False)
    stage = SimpleNamespace(Traverse=lambda: [visible, hidden])
    categorized, hidden_paths = symbols["categorize_boxes"](stage, apply_labels=True)

    remove = _extract_symbols(
        REMOVE_LABEL,
        ["remove_all_semantics"],
        {
            "UsdSemantics": fake_semantics,
            "LegacySemantics": None,
            "Usd": SimpleNamespace(Stage=object),
        },
    )["remove_all_semantics"]
    labeled = Prim("/World/Labeled", taxonomies=["class", "instance"])
    removed = remove(SimpleNamespace(Traverse=lambda: [labeled]))
    fixture = {"visible": visible.path, "hidden": hidden.path, "labels": ["class", "instance"]}
    output = {
        "categorized": categorized,
        "hidden": hidden_paths,
        "authored_labels": captured,
        "removed_count": removed,
        "removed_taxonomies": labeled.removed,
        "real_stage_writes": 0,
    }
    expected = {
        "categorized": {"printersbox": [visible.path]},
        "hidden": [hidden.path],
        "authored_labels": [["printersbox"]],
        "removed_count": 2,
        "removed_taxonomies": ["class", "instance"],
        "real_stage_writes": 0,
    }
    if output != expected:
        raise QualificationError(f"semantic label helper differs: {output}")
    return fixture, output


class _DirectFuture:
    def __init__(self, value: Any) -> None:
        self._value = value

    def result(self) -> Any:
        return self._value


class _DirectExecutor:
    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def submit(self, fn, *args):
        return _DirectFuture(fn(*args))


class _FakeGroup:
    def __init__(self) -> None:
        self.datasets: Dict[str, Dict[str, Any]] = {}

    def create_dataset(self, name: str, *, data: np.ndarray, dtype: Any, compression: str) -> None:
        self.datasets[name] = {"shape": list(data.shape), "dtype": np.dtype(dtype).name, "compression": compression}


class _FakeH5:
    def __init__(self, path: str, captured: Dict[str, Any]) -> None:
        self.path = path
        self.groups: Dict[str, _FakeGroup] = {}
        captured[path] = self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def create_group(self, name: str) -> _FakeGroup:
        group = _FakeGroup()
        self.groups[name] = group
        return group


def _rgb_depth_conversion_helpers() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    png_captured: Dict[str, np.ndarray] = {}

    class FakeImage:
        @staticmethod
        def fromarray(data: np.ndarray):
            return SimpleNamespace(save=lambda path: png_captured.__setitem__(path, data.copy()))

    depth_fn = _extract_symbols(
        DEPTH_CONVERT,
        ["npy_to_png"],
        {
            "np": SimpleNamespace(load=lambda _path: np.asarray([[0.0, 1.25], [2.0, 65.535]]), uint16=np.uint16),
            "Image": FakeImage,
            "os": SimpleNamespace(path=SimpleNamespace(basename=posixpath.basename, join=posixpath.join)),
            "print": lambda *_a, **_k: None,
        },
    )["npy_to_png"]
    depth_fn("/memory/depth_000.npy", "/memory/png")

    h5_captured: Dict[str, _FakeH5] = {}
    directories = {
        "/memory/Camera/rgb": ["rgb_001.jpg"],
        "/memory/Camera/distance_to_image_plane_png": ["depth_001.png"],
    }
    fake_os = SimpleNamespace(
        path=SimpleNamespace(
            basename=posixpath.basename,
            dirname=posixpath.dirname,
            join=posixpath.join,
            isdir=lambda path: path in directories,
        ),
        listdir=lambda path: directories[path],
    )
    fake_cv2 = SimpleNamespace(
        imread=lambda path, _mode: np.full((2, 3, 3), 7, dtype=np.uint8)
        if path.endswith(".jpg")
        else np.full((2, 3), 1250, dtype=np.uint16)
    )
    symbols = _extract_symbols(
        H5_CONVERT,
        ["read_image", "convert_camera_to_h5"],
        {
            "Tuple": Tuple,
            "np": np,
            "cv2": fake_cv2,
            "os": fake_os,
            "h5py": SimpleNamespace(File=lambda path, _mode: _FakeH5(path, h5_captured)),
            "ThreadPoolExecutor": _DirectExecutor,
            "as_completed": lambda futures: list(futures),
            "tqdm": lambda values, **_kwargs: values,
            "print": lambda *_a, **_k: None,
        },
    )
    symbols["convert_camera_to_h5"].__globals__.update(symbols)
    symbols["convert_camera_to_h5"]("/memory/Camera")
    h5 = h5_captured["/memory/Camera.h5"]
    fixture = {"depth_meters": [[0.0, 1.25], [2.0, 65.535]], "rgb_files": ["rgb_001.jpg"], "depth_files": ["depth_001.png"]}
    output = {
        "depth_png_values": png_captured["/memory/png/depth_000.png"].tolist(),
        "depth_png_dtype": str(png_captured["/memory/png/depth_000.png"].dtype),
        "h5_groups": sorted(h5.groups),
        "rgb_datasets": h5.groups["rgb"].datasets,
        "depth_datasets": h5.groups["distance_to_image_plane_png"].datasets,
        "video_overlay_executed": False,
        "real_file_writes": 0,
    }
    expected_values = [[0, 1250], [2000, 65535]]
    if output["depth_png_values"] != expected_values or output["depth_png_dtype"] != "uint16":
        raise QualificationError(f"depth conversion helper differs: {output}")
    if output["h5_groups"] != ["distance_to_image_plane_png", "rgb"]:
        raise QualificationError(f"RGB/depth H5 groups differ: {output}")
    return fixture, output


def _ground_truth_helpers() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    method_names = [
        "rename_camera",
        "convert_camera_string",
        "check_for_overflow",
        "box3d_to_corners",
        "compare_dicts_with_tolerance",
        "find_best_bbox_by_clustering",
    ]
    cls = _extract_class_methods(
        GROUND_TRUTH,
        "utils_for_data_parse",
        method_names,
        {
            "Dict": Dict,
            "Any": Any,
            "Tuple": Tuple,
            "List": List,
            "Optional": Optional,
            "Set": Set,
            "np": np,
            "math": math,
            "re": re,
            "Counter": Counter,
            "print": lambda *_a, **_k: None,
        },
    )
    helper = cls()
    repeated = {"x_min": -1.0, "x_max": 1.0, "y_min": -2.0, "y_max": 2.0, "z_min": 0.0, "z_max": 2.0}
    distinct = {**repeated, "x_max": 2.0}
    selected = helper.find_best_bbox_by_clustering([repeated, distinct, dict(repeated)])
    box = np.asarray([[1.0, 2.0, 3.0, 2.0, 4.0, 6.0, 0.0, 0.0, 0.0, 0.0, 0.0]])
    corners = helper.box3d_to_corners(box)
    overflow = {**repeated, "transform": [[1.0, 0.0], [0.0, float("inf")]]}
    fixture = {"camera_ids": ["Camera_0", "Camera_4", "Camera_12"], "folder": "_World_Cameras_Metro_Camera_3", "bbox_count": 3}
    output = {
        "renamed": [helper.rename_camera(value) for value in fixture["camera_ids"]],
        "folder_name": helper.convert_camera_string(fixture["folder"]),
        "selected_bbox_index": selected,
        "corner_shape": list(corners.shape),
        "corner_min": corners.min(axis=1)[0].tolist(),
        "corner_max": corners.max(axis=1)[0].tolist(),
        "overflow_rejected": helper.check_for_overflow(overflow),
        "full_dataset_conversion_executed": False,
        "real_file_writes": 0,
    }
    expected = {
        "renamed": ["Camera", "Camera_04", "Camera_12"],
        "folder_name": "Camera_03",
        "selected_bbox_index": 0,
        "corner_shape": [1, 8, 3],
        "corner_min": [0.0, 0.0, 0.0],
        "corner_max": [2.0, 4.0, 6.0],
        "overflow_rejected": True,
        "full_dataset_conversion_executed": False,
        "real_file_writes": 0,
    }
    if output != expected:
        raise QualificationError(f"ground-truth helper differs: {output}")
    return fixture, output


ADAPTERS = {
    "file_upload_helper": lambda _advertised: _file_upload_helper(),
    "uri_validator": _uri_validator,
    "file_uri_allowlist": lambda _advertised: _file_uri_allowlist(),
    "inline_data_uri": lambda _advertised: _inline_data_uri(),
    "rtsp_validator": lambda _advertised: _rtsp_validator(),
    "dense_caption_roundtrip": lambda _advertised: _dense_caption_roundtrip(),
    "incident_trigger_helper": lambda _advertised: _incident_trigger_helper(),
    "reasoning_helpers": lambda _advertised: _reasoning_helpers(),
    "frame_sampling_helper": lambda _advertised: _frame_sampling_helper(),
    "gop_selection_helper": lambda _advertised: _gop_selection_helper(),
    "decoder_cache_helper": lambda _advertised: _decoder_cache_helper(),
    "asset_limit_expiry_helpers": lambda _advertised: _asset_limit_expiry_helpers(),
    "absolute_timestamp_helper": lambda _advertised: _absolute_timestamp_helper(),
    "model_source_contract": _model_source_contract,
    "semantic_label_helpers": lambda _advertised: _semantic_label_helpers(),
    "rgb_depth_conversion_helpers": lambda _advertised: _rgb_depth_conversion_helpers(),
    "ground_truth_helpers": lambda _advertised: _ground_truth_helpers(),
}


def execute(case_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    inventory, inventory_raw = _load_and_validate_inventory()
    selected = set(case_ids or [])
    known = {case["entry_id"] for case in inventory["cases"]}
    unknown = selected - known
    if unknown:
        raise QualificationError(f"unknown case IDs: {sorted(unknown)}")
    results = []
    for case in inventory["cases"]:
        if selected and case["entry_id"] not in selected:
            continue
        adapter = ADAPTERS.get(case["adapter_id"])
        if adapter is None:
            raise QualificationError(f"unknown adapter: {case['adapter_id']}")
        fixture, semantic_output = adapter(case["advertised"])
        results.append(
            {
                "manifest_pointer": case["manifest_pointer"],
                "entry_id": case["entry_id"],
                "proposed_capability_id": case["proposed_capability_id"],
                "advertised": case["advertised"],
                "evidence_scope": case["evidence_scope"],
                "observation": "observed_match",
                "input_sha256": _sha256(_canonical_bytes(fixture)),
                "semantic_output_sha256": _sha256(_canonical_bytes(semantic_output)),
                "semantic_output": semantic_output,
                "runtime_evidence": [],
                "official_capability_effect": "none_candidate_only",
            }
        )
    report = {
        "schema_version": 1,
        "mode": "candidate_only_file_executor_tranche_wave2",
        "candidate_only": True,
        "inventory_sha256": _sha256(inventory_raw),
        "denominator": inventory["denominator"],
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "results": results,
    }
    _validate_schema(report, RESULT_SCHEMA_PATH, "result")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", default=[], help="exact gap entry_id; repeatable")
    parser.add_argument("--list", action="store_true", help="list exact runnable entry IDs")
    args = parser.parse_args()
    if args.list:
        inventory, _raw = _load_and_validate_inventory()
        print("\n".join(case["entry_id"] for case in inventory["cases"]))
        return 0
    print(json.dumps(execute(args.case), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
