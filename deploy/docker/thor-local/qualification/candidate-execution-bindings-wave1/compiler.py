#!/usr/bin/env python3
"""Compile and validate the source-proven Wave 1 LVS binding overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "binding-overlay.json"
SCHEMA_PATH = HERE / "binding-overlay.schema.json"
MAX_BYTES = 32_000_000

REGISTRY_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-binding-registry-successor/registry.json"
)
WAVE1_DIR = (
    "deploy/docker/thor-local/qualification/successor-500-executable-subsets-wave1"
)
WAVE1_CONTRACT_PATH = f"{WAVE1_DIR}/contract.json"
WAVE1_ORACLES_PATH = f"{WAVE1_DIR}/successor-capability-oracles.json"
WAVE1_RECEIPT_PATH = f"{WAVE1_DIR}/execution-receipt.json"
ROOT_COMPOSE_PATH = "deploy/docker/compose.yml"
SERVICES_COMPOSE_PATH = "deploy/docker/services/compose.yml"
DEVELOPER_PROFILES_COMPOSE_PATH = "deploy/docker/developer-profiles/compose.yml"
THOR_PROFILE_COMPOSE_PATH = (
    "deploy/docker/developer-profiles/dev-profile-thor-full/compose.yml"
)
LVS_COMPOSE_PATH = "deploy/docker/services/video-summarization/compose.yml"
THOR_COMPOSE_PATH = "deploy/docker/thor-local/compose.yml"
THOR_WRAPPER_PATH = "deploy/docker/scripts/thor-local.sh"
THOR_PROFILE_ENV_PATH = "deploy/docker/developer-profiles/dev-profile-thor-full/.env"
LVS_MCP_PATH = "services/video-summarization/src/lvs_mcp.py"
VIA_SERVER_PATH = "services/video-summarization/src/via_server.py"
VIA_STREAM_HANDLER_PATH = "services/video-summarization/src/via_stream_handler.py"
LVS_EXPECTED_PATH = "deploy/docker/thor-local/qualification/expected/lvs-mcp.json"
PROTOCOL_PATH = (
    "deploy/docker/thor-local/qualification/"
    "protocol-cases-v2-candidates/protocol-cases-v2-candidate.json"
)
WORKLOAD_PATH = (
    "deploy/docker/thor-local/qualification/remaining-entry-workloads/workloads.json"
)
AUTHORITY_REGISTRY_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-authority-registry-successor/authority-registry.json"
)
SIGNED_RECEIPT_SET_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-authority-registry-successor/signed-receipt-set.json"
)
ADMISSION_INDEX_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-admission-receipts-successor/admission-index.json"
)
ADMISSION_RECEIPT_SET_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-admission-receipts-successor/receipt-set.json"
)

EXPECTED_SOURCE_HASHES = {
    REGISTRY_PATH: "59600e64e818b553039dd3d623d1a174714f6f51563da08251560c2994c7f544",
    WAVE1_CONTRACT_PATH: "3284d9f8bdc8c4b344940333174444431f1f100d2097f38c4e7288b18e79050e",
    WAVE1_ORACLES_PATH: "845abf01e25f0d5cf4e43c0c543132744a7009d8d401b4459a7cdfca014da47a",
    WAVE1_RECEIPT_PATH: "0bf0167de20896260a7ca962665d5088385866ed6d272cf62f51d05c6c18b3f9",
    ROOT_COMPOSE_PATH: "aed3eb17a594eb278f8a3ec8c4e3a3590a1314504c28be646d28231d07a1f77e",
    SERVICES_COMPOSE_PATH: "6e901bde4e67d19d0a0a78b6dffbcb1bb05b60253d2c945025f7d3adc444822c",
    DEVELOPER_PROFILES_COMPOSE_PATH: "7e419ba68db50aae4cd581bd0d789169c0bcff3f07f40b2ca2c9813b347dfdb2",
    THOR_PROFILE_COMPOSE_PATH: "1c847e7c526c3444a64f9df04c35df303a2fed8fb0a95bbb450a22687aeaecca",
    LVS_COMPOSE_PATH: "4bf61024fc548a56f0b8e8b01611609daed47b7201eba93878268ec06193a97f",
    THOR_COMPOSE_PATH: "1943cc40645c6b41d61f28dc9262aa3793149cc3f4c6aac8a91ee47fd2842352",
    THOR_WRAPPER_PATH: "2b67c0b0ee25582ef5acd45ddf12dc02279700ffad065299e6577082fd189df5",
    THOR_PROFILE_ENV_PATH: "a80aa33ed97ea2947caff05402e6a049d2aeec81b4152857063d178163cff718",
    LVS_MCP_PATH: "2d7f5fcf1b88119a60a75c71ee5560d7ecbd2872bd341fa906521ed859ec1de0",
    VIA_SERVER_PATH: "80192bc98f7c501839ec2d561e8e9bedfce6673d1459276aa7b653d75dc3dd96",
    VIA_STREAM_HANDLER_PATH: "0e55981fbacb39ec337c1012067475f021168aefce0d72ab14d2368c8803ad8c",
    LVS_EXPECTED_PATH: "2e4eeb61c98688ed2cb7d5e0662513edd3b5ee8db470c61a90b8e91001ff598e",
    PROTOCOL_PATH: "886151fee9ce27b24601499011151e827c4742b32d400c609c8c0b149851db62",
    WORKLOAD_PATH: "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    AUTHORITY_REGISTRY_PATH: "4b3b806509d7dc0c50edcf8dadeec38b4b8aaab3a9d7404f3358922b029abcc2",
    SIGNED_RECEIPT_SET_PATH: "7d891821c71bf9bd3c12eff1913134882f4cf3d0dd656aba29c5de0eceff8ffc",
    ADMISSION_INDEX_PATH: "6dc6345f9b057c164929a1046b8ebcfb08fdfbedaa1b7a66180f344915d7d7eb",
    ADMISSION_RECEIPT_SET_PATH: "7bfeb7e70f9a7c3a2bbbb007c785286146dbfe70e4f63245168cf382b62ec805",
}

CANDIDATES = (
    (
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
        "oracle.manifest-entry.video-summarization-live.05-sse-mcp-server",
        310,
        "daf6d4a628c8e972d2eb996b3d56f2d6f814d584a378be06f80a3e7a50cc0974",
        21,
        "A reviewed bounded MCP initialize/list-tools client and exact transport-session cleanup contract do not exist.",
    ),
    (
        "manifest-entry.agent-and-mcp-apis.06-lvs-mcp",
        "oracle.manifest-entry.agent-and-mcp-apis.06-lvs-mcp",
        468,
        "e06850f09ddaadfb6ab40324816f2bff0b19eae5341ec3b7df4e1955f431bc3d",
        178,
        "No candidate-specific tool request, expected result, bounded client, cleanup contract, or evidence collector has been reviewed; planned get_lvs_hitl_state has no production MCP tool or completion field and requires oracle/workload repair.",
    ),
)

EXPECTED_TOOL_NAMES = [
    "health_ready",
    "health_live",
    "list_models",
    "add_file",
    "list_files",
    "get_file_info",
    "delete_file",
    "summarize_video",
    "generate_vlm_captions",
    "generate_captions",
    "stream_summarize",
    "get_recommended_config",
    "get_metrics",
]


class BindingError(RuntimeError):
    """A source, projection, schema, or fail-closed invariant failed."""


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _repo_path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.as_posix() != relative
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
    ):
        raise BindingError(f"unsafe repository path: {relative!r}")
    path = REPO_ROOT / pure
    current = REPO_ROOT
    for part in pure.parts:
        current = current / part
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise BindingError(f"source path contains a symlink: {relative}")
    return path


def _read_regular(path: Path, label: str) -> bytes:
    try:
        relative = path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise BindingError(f"{label} escapes the repository root") from exc
    parts = relative.parts
    if not parts:
        raise BindingError(f"{label} cannot be the repository root")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    opened_directories: list[int] = []
    try:
        directory_fd = os.open(REPO_ROOT, directory_flags)
        opened_directories.append(directory_fd)
        for part in parts[:-1]:
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened_directories.append(directory_fd)
        descriptor = os.open(parts[-1], file_flags, dir_fd=directory_fd)
    except OSError as exc:
        for opened in reversed(opened_directories):
            os.close(opened)
        raise BindingError(f"cannot safely open {label}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BindingError(f"{label} must be a regular non-symlink file")
        if before.st_size > MAX_BYTES:
            raise BindingError(f"{label} exceeds {MAX_BYTES} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1_048_576, MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                raise BindingError(f"{label} exceeds {MAX_BYTES} bytes")
        after = os.fstat(descriptor)
        path_after = os.stat(parts[-1], dir_fd=directory_fd, follow_symlinks=False)
    finally:
        os.close(descriptor)
        for opened in reversed(opened_directories):
            os.close(opened)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    path_identity = (
        path_after.st_dev,
        path_after.st_ino,
        path_after.st_size,
        path_after.st_mtime_ns,
    )
    if identity_before != identity_after or identity_after != path_identity:
        raise BindingError(f"{label} changed while being read")
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise BindingError(f"{label} returned a short or long read")
    return payload


def strict_json(payload: bytes, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise BindingError(f"{label} contains invalid JSON constant {value}")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise BindingError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"{label} is not strict UTF-8 JSON: {exc}") from exc


def _validate_schema(instance: Any, schema: Any, label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise BindingError(f"invalid JSON schema for {label}: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        raise BindingError(f"{label} schema failure at {pointer}: {error.message}")


def _locked_sources() -> tuple[dict[str, bytes], list[dict[str, str]]]:
    payloads: dict[str, bytes] = {}
    locks: list[dict[str, str]] = []
    for path, expected_hash in EXPECTED_SOURCE_HASHES.items():
        payload = _read_regular(_repo_path(path), f"source {path}")
        actual_hash = sha256(payload)
        if actual_hash != expected_hash:
            raise BindingError(
                f"source hash drift for {path}: expected {expected_hash}, got {actual_hash}"
            )
        payloads[path] = payload
        locks.append({"path": path, "raw_sha256": actual_hash})
    return payloads, locks


def _require_text(payloads: dict[str, bytes], path: str, snippets: list[str]) -> str:
    text = payloads[path].decode("utf-8")
    for snippet in snippets:
        if snippet not in text:
            raise BindingError(f"source contract missing in {path}: {snippet!r}")
    return text


def _prove_sources(payloads: dict[str, bytes]) -> None:
    _require_text(payloads, ROOT_COMPOSE_PATH, ["- path: ./services/compose.yml"])
    _require_text(
        payloads,
        SERVICES_COMPOSE_PATH,
        ["- path: ./video-summarization/compose.yml"],
    )
    _require_text(
        payloads,
        ROOT_COMPOSE_PATH,
        ["- path: ./developer-profiles/compose.yml"],
    )
    _require_text(
        payloads,
        DEVELOPER_PROFILES_COMPOSE_PATH,
        ["- path: ./dev-profile-thor-full/compose.yml"],
    )
    _require_text(
        payloads,
        THOR_PROFILE_COMPOSE_PATH,
        ['profiles: ["bp_developer_thor_full_2d"]'],
    )
    _require_text(
        payloads,
        LVS_COMPOSE_PATH,
        [
            "  lvs-server:",
            "container_name: vss-lvs",
            'profiles: ["bp_developer_lvs_2d", "bp_developer_thor_full_2d"]',
            "network_mode: host",
            "- LVS_MCP_PORT=${LVS_MCP_PORT:-38112}",
            "- LVS_MCP_HOST=${LVS_MCP_HOST:-127.0.0.1}",
            "- LVS_MCP_MEDIA_ROOT=${LVS_MCP_MEDIA_ROOT:-}",
            "- LVS_MCP_MAX_FILE_BYTES=${LVS_MCP_MAX_FILE_BYTES:-8589934592}",
            "- LVS_ENABLE_MCP=${LVS_ENABLE_MCP:-false}",
            'test: ["CMD", "curl", "-f", "http://localhost:${BACKEND_PORT:-38111}/v1/ready"]',
        ],
    )
    _require_text(
        payloads,
        THOR_COMPOSE_PATH,
        [
            "  lvs-server:",
            "LVS_MCP_HOST: 127.0.0.1",
            "LVS_MCP_MEDIA_ROOT: /opt/nvidia/via/mcp-media",
            "LVS_MCP_MAX_FILE_BYTES: ${LVS_MCP_MAX_FILE_BYTES:-8589934592}",
            "- ${VSS_DATA_DIR}/videos:/opt/nvidia/via/mcp-media:ro",
        ],
    )
    _require_text(
        payloads,
        THOR_WRAPPER_PATH,
        [
            'export COMPOSE_FILE="${deployment_dir}/compose.yml:${deployment_dir}/thor-local/compose.yml"',
            'export LVS_MCP_PORT="${LVS_MCP_PORT:-38112}"',
            'export LVS_ENABLE_MCP="${LVS_ENABLE_MCP:-true}"',
            'export COMPOSE_PROFILES="${THOR_LOCAL_COMPOSE_PROFILES:-bp_developer_thor_full_2d,bp_developer_thor_search_perception_2d}"',
        ],
    )
    _require_text(
        payloads,
        THOR_PROFILE_ENV_PATH,
        [
            "BACKEND_PORT=38111",
            "LVS_MCP_PORT=38112",
            "LVS_MCP_HOST=127.0.0.1",
            "LVS_MCP_MEDIA_ROOT=/opt/nvidia/via/mcp-media",
            "LVS_MCP_MAX_FILE_BYTES=8589934592",
            "LVS_ENABLE_MCP=true",
        ],
    )
    mcp_source = _require_text(
        payloads,
        LVS_MCP_PATH,
        [
            'SseServerTransport("/messages")',
            'if path == "/messages" and method == "POST":',
            'if path == "/sse" and method == "GET":',
            'os.environ.get("LVS_MCP_HOST", "127.0.0.1")',
            'raise ValueError("LVS_MCP_HOST must be a loopback IP address")',
            'os.environ.get("LVS_MCP_PORT", "").strip()',
        ],
    )
    tool_names = re.findall(r"\bTool\(\s*name=\"([^\"]+)\"", mcp_source)
    if tool_names != EXPECTED_TOOL_NAMES:
        raise BindingError(f"LVS MCP tool catalog drift: {tool_names!r}")

    expected = strict_json(payloads[LVS_EXPECTED_PATH], "expected LVS MCP manifest")
    expected_names = [tool["name"] for tool in expected.get("tools", [])]
    if (
        sorted(expected_names) != sorted(EXPECTED_TOOL_NAMES)
        or len(expected_names) != 13
    ):
        raise BindingError(
            "expected LVS MCP manifest does not match the 13-tool source catalog"
        )

    protocol = strict_json(payloads[PROTOCOL_PATH], "protocol candidate source")
    protocol_case = protocol["cases"][9]
    if (
        protocol_case.get("capability_id")
        != "manifest-entry.video-summarization-live.05-sse-mcp-server"
        or protocol_case.get("candidate_contract", {})
        .get("oracle_plan", {})
        .get("adjacent_negative")
        != [
            "An unknown MCP tool must return a protocol error without invoking an LVS route."
        ]
    ):
        raise BindingError("SSE MCP protocol adjacent-negative source drifted")
    workload = strict_json(payloads[WORKLOAD_PATH], "LVS workload source")
    workload_row = workload["workloads"][42]
    if workload_row.get(
        "candidate_id"
    ) != "manifest-entry.agent-and-mcp-apis.06-lvs-mcp" or workload_row.get(
        "literal_facets"
    ) != [
        "list_lvs_mcp_tools",
        "get_lvs_readiness",
        "call_lvs_summarize",
        "get_lvs_hitl_state",
    ]:
        raise BindingError("LVS planning-workload facet source drifted")
    if any(name in EXPECTED_TOOL_NAMES for name in workload_row["literal_facets"]):
        raise BindingError(
            "planning workload labels unexpectedly became MCP tool names"
        )

    _require_text(
        payloads,
        LVS_MCP_PATH,
        [
            'else {"error": str(e), "type": type(e).__name__}',
            'raise ValueError(f"Unknown tool: {name}")',
            "return response.json()",
        ],
    )
    _require_text(
        payloads,
        VIA_SERVER_PATH,
        [
            "drop_result = self._stream_handler.drop_collection_for_asset(file_id)",
            'logger.warning("drop_collection_for_asset failed for %s: %s", file_id, e)',
            'return {"id": file_id, "object": "file", "deleted": True}',
        ],
    )
    _require_text(
        payloads,
        VIA_STREAM_HANDLER_PATH,
        [
            "def drop_collection_for_asset(",
            'return {"error": str(ex)}',
            "default_<asset_id>",
        ],
    )


def _source_locks_for(paths: list[str]) -> list[dict[str, str]]:
    return [
        {"path": path, "raw_sha256": EXPECTED_SOURCE_HASHES[path]} for path in paths
    ]


def _compile_binding(
    registry_row: dict[str, Any], annotation: dict[str, Any], spec: tuple[Any, ...]
) -> dict[str, Any]:
    candidate_id, oracle_id, oracle_index, row_hash, position, blocker = spec
    if registry_row["oracle_id"] != oracle_id:
        raise BindingError(f"oracle mismatch for {candidate_id}")
    if registry_row["oracle_index"] != oracle_index:
        raise BindingError(f"oracle index mismatch for {candidate_id}")
    if registry_row["candidate_record_canonical_sha256"] != row_hash:
        raise BindingError(f"candidate row hash mismatch for {candidate_id}")
    if registry_row["registry_position"] != position:
        raise BindingError(f"registry position mismatch for {candidate_id}")
    if registry_row["admission_grade"] is not False:
        raise BindingError(f"source registry unexpectedly admits {candidate_id}")
    if any(
        value not in (None, [], {})
        for value in registry_row["authoritative_executable_binding"].values()
    ):
        raise BindingError(
            f"source registry gained an unreviewed binding for {candidate_id}"
        )
    if annotation["oracle_index"] != oracle_index:
        raise BindingError(f"Wave 1 oracle index mismatch for {candidate_id}")
    if annotation["oracle_row_canonical_sha256"] != row_hash:
        raise BindingError(f"Wave 1 oracle hash mismatch for {candidate_id}")
    if annotation["runtime_evidence"] != []:
        raise BindingError(
            f"Wave 1 observer evidence became runtime evidence for {candidate_id}"
        )
    admission = annotation["admission_effect"]
    if admission["full_oracle_executor_ready"] or admission["operator_gate_satisfied"]:
        raise BindingError(f"Wave 1 annotation unexpectedly advanced {candidate_id}")

    common_sources = _source_locks_for(
        [
            ROOT_COMPOSE_PATH,
            SERVICES_COMPOSE_PATH,
            DEVELOPER_PROFILES_COMPOSE_PATH,
            THOR_PROFILE_COMPOSE_PATH,
            LVS_COMPOSE_PATH,
            THOR_COMPOSE_PATH,
            THOR_WRAPPER_PATH,
            THOR_PROFILE_ENV_PATH,
            LVS_MCP_PATH,
            VIA_SERVER_PATH,
            VIA_STREAM_HANDLER_PATH,
            LVS_EXPECTED_PATH,
            PROTOCOL_PATH,
            WORKLOAD_PATH,
        ]
    )
    unresolved = [
        "action_contract.action_contract_sha256",
        "action_contract.argv",
        "action_contract.executor",
        "cleanup_contract.cleanup_executor",
        "cleanup_contract.cleanup_rollback_contract_sha256",
        "evidence_contract.evidence_destination",
        "evidence_contract.evidence_records",
        "input_contract.fixture",
        "input_contract.model",
        "input_contract.runtime_request",
        "postcondition_contract.contract",
        "postcondition_contract.collectors",
        "runtime_surface.effective_profile_id",
        "runtime_surface.effective_resolved_endpoints",
        "runtime_evidence",
    ]
    return {
        "action_contract": {
            "action_contract_sha256": None,
            "action_kind": None,
            "argv": None,
            "executor": None,
            "status": "unresolved_fail_closed",
        },
        "admission_grade": False,
        "authorization_consumed": False,
        "candidate_id": candidate_id,
        "candidate_record_canonical_sha256": row_hash,
        "completion_receipt_consumed": False,
        "cleanup_contract": {
            "cleanup_executor": None,
            "cleanup_rollback_contract_sha256": None,
            "cleanup_targets": [],
            "status": "unresolved_fail_closed",
        },
        "evidence_contract": {
            "evidence_destination": None,
            "evidence_records": [],
            "observer_receipt_id": annotation["receipt_id"],
            "observer_receipt_is_runtime_evidence": False,
            "status": "unresolved_fail_closed",
        },
        "input_contract": {
            "fixture": None,
            "model": None,
            "runtime_request": None,
            "status": "unresolved_fail_closed",
        },
        "oracle_id": oracle_id,
        "oracle_index": oracle_index,
        "overlay_state": "partial_source_proven_non_admission",
        "deployed_observed": False,
        "postcondition_contract": {
            "collectors": [],
            "contract": None,
            "status": "unresolved_fail_closed",
        },
        "retained_blockers": sorted(
            set(
                annotation["retained_blockers"]
                + [
                    blocker,
                    "Effective resolved endpoints, profile selection, image digest, and media-root path require a future runtime receipt.",
                    "The whole-stack thor-local.sh restart command is prohibited as a candidate executor.",
                    "Candidate authorization must not imply profile lifecycle authority; a future action must consume an already-running separately authorized profile and preserve its pre-state.",
                    "Unknown-tool handling returns normal TextContent error JSON rather than a proven JSON-RPC protocol error or no-route telemetry.",
                    "summarize_video stream=true is not safely bindable because the MCP HTTP adapter always parses JSON while the route emits SSE.",
                    "delete_file success is insufficient cleanup proof because collection-drop failures are swallowed; an independent default_<file_id> Elasticsearch absence check is required.",
                ]
            )
        ),
        "runtime_evidence": [],
        "runtime_ready": False,
        "runtime_surface": {
            "service_definition_include_chain": [
                ROOT_COMPOSE_PATH,
                SERVICES_COMPOSE_PATH,
                LVS_COMPOSE_PATH,
            ],
            "top_level_compose_inputs": [ROOT_COMPOSE_PATH, THOR_COMPOSE_PATH],
            "container_name": "vss-lvs",
            "effective_profile_id": None,
            "effective_resolved_endpoints": None,
            "network_mode": "host",
            "profile_id_source_default": "bp_developer_thor_full_2d",
            "profile_paths": [
                THOR_PROFILE_COMPOSE_PATH,
                THOR_PROFILE_ENV_PATH,
            ],
            "service_role": "lvs-server",
            "source_declared_interface": {
                "default_health_endpoint": "http://127.0.0.1:38111/v1/ready",
                "default_maximum_media_bytes": 8589934592,
                "default_mcp_get_endpoint": "http://127.0.0.1:38112/sse",
                "default_mcp_post_endpoint": "http://127.0.0.1:38112/messages",
                "health_endpoint_is_mcp_readiness_proof": False,
                "media_root_container_path": "/opt/nvidia/via/mcp-media",
                "media_root_host_bind_expression": "${VSS_DATA_DIR}/videos",
                "media_root_read_only": True,
                "tool_names": EXPECTED_TOOL_NAMES,
            },
            "source_locks": common_sources,
            "status": "source_proven_static_wiring_not_deployed",
        },
        "unresolved_fields": unresolved,
        "transport_observed": False,
        "warehouse_sample_bundle": "excluded",
    }


def compile_overlay() -> dict[str, Any]:
    payloads, locks = _locked_sources()
    _prove_sources(payloads)
    registry = strict_json(payloads[REGISTRY_PATH], "execution-binding registry")
    wave1_contract = strict_json(payloads[WAVE1_CONTRACT_PATH], "Wave 1 contract")
    wave1_oracles = strict_json(payloads[WAVE1_ORACLES_PATH], "Wave 1 annotations")
    wave1_receipt = strict_json(payloads[WAVE1_RECEIPT_PATH], "Wave 1 receipt")
    authority_registry = strict_json(
        payloads[AUTHORITY_REGISTRY_PATH], "empty authority registry"
    )
    signed_receipts = strict_json(
        payloads[SIGNED_RECEIPT_SET_PATH], "empty signed receipt set"
    )
    admission_index = strict_json(
        payloads[ADMISSION_INDEX_PATH], "candidate admission index"
    )
    admission_receipts = strict_json(
        payloads[ADMISSION_RECEIPT_SET_PATH], "empty admission receipt set"
    )

    if (
        registry.get("registry_id")
        != "thor-vss-3.2.1-candidate-execution-binding-registry-successor"
    ):
        raise BindingError("unexpected source registry identity")
    if (
        registry.get("binding_rows_canonical_sha256")
        != "25b6dc3b2046895b926df837b93560e8f367cc672afdd479eb31438e94cea96c"
    ):
        raise BindingError("unexpected 208-row registry payload identity")
    if registry.get("summary", {}).get("binding_count") != 208:
        raise BindingError("source registry denominator is not 208")
    if (
        wave1_contract.get("contract_id")
        != "successor-500-executable-subsets-wave1-2026-08-01"
    ):
        raise BindingError("unexpected Wave 1 contract identity")
    if (
        wave1_receipt.get("receipt_id")
        != "successor-500-executable-subsets-wave1-receipt-2026-08-01"
    ):
        raise BindingError("unexpected Wave 1 receipt identity")
    if wave1_receipt.get("official_capability_effect") != "none_candidate_only":
        raise BindingError("Wave 1 receipt advanced official capability state")
    if wave1_receipt.get("runtime_evidence") != []:
        raise BindingError("Wave 1 receipt contains runtime evidence")
    expected_safety = {
        "caller_supplied_callback_used": False,
        "credentials_used": False,
        "deployed_lvs": False,
        "docker_used": False,
        "downloads_used": False,
        "live_sse_connection": False,
        "mcp_transport_handshake": False,
        "models_used": False,
        "network_used": False,
        "service_lifecycle_used": False,
        "socket_used": False,
        "subprocess_used": False,
        "temporary_files_cleaned": True,
        "thor_runtime_readiness": False,
        "vlm_inference": False,
        "warehouse_sample_used": False,
    }
    safety = wave1_receipt.get("safety", {})
    if safety != expected_safety:
        raise BindingError("Wave 1 observer receipt overclaims a live/runtime effect")

    empty_authority_fields = [
        "active_keys",
        "authorities",
        "max_ttl_policies",
        "not_required_edge_policies",
        "revocations",
        "revoked_keys",
        "role_policies",
        "scope_policies",
        "spent_receipt_ledger",
        "threshold_policies",
        "trusted_roots",
    ]
    if any(authority_registry.get(field) != [] for field in empty_authority_fields):
        raise BindingError("authority registry is no longer checked-empty")
    if authority_registry.get("summary") != {
        "active_key_count": 0,
        "authority_count": 0,
        "receipt_count": 0,
        "revocation_count": 0,
        "trusted_root_count": 0,
    }:
        raise BindingError("authority registry summary is no longer empty")
    for count_field in (
        "accepted_receipt_count",
        "authorization_envelope_count",
        "completion_receipt_envelope_count",
        "consumed_receipt_count",
    ):
        if signed_receipts.get(count_field) != 0:
            raise BindingError("signed receipt boundary is no longer empty")
    if any(
        signed_receipts.get(field) != []
        for field in (
            "accepted_receipt_ids",
            "authorization_envelopes",
            "completion_receipt_envelopes",
            "consumed_receipt_ids",
        )
    ):
        raise BindingError("signed receipt boundary contains records")
    admission_summary = admission_index.get("summary", {})
    if any(
        admission_summary.get(field) != 0
        for field in ("admitted_candidates", "executable_candidates", "receipt_count")
    ):
        raise BindingError("candidate admission boundary is no longer empty")
    if admission_receipts.get("receipts") != [] or any(
        admission_receipts.get(field) != 0
        for field in (
            "admitted_candidate_count",
            "executable_candidate_count",
            "receipt_count",
        )
    ):
        raise BindingError("candidate admission receipt set is no longer empty")

    registry_index = {row["candidate_id"]: row for row in registry["bindings"]}
    annotation_index = {
        row["capability_id"]: row for row in wave1_oracles["annotations"]
    }
    expected_ids = {spec[0] for spec in CANDIDATES}
    if set(annotation_index) != expected_ids:
        raise BindingError("Wave 1 annotation set is not the exact two-candidate set")
    bindings = [
        _compile_binding(registry_index[spec[0]], annotation_index[spec[0]], spec)
        for spec in CANDIDATES
    ]
    if any(row["admission_grade"] for row in bindings):
        raise BindingError("partial binding overlay must not admit a candidate")
    if any(row["runtime_evidence"] for row in bindings):
        raise BindingError("partial binding overlay must not carry runtime evidence")
    if any(row["action_contract"]["executor"] is not None for row in bindings):
        raise BindingError("partial binding overlay must not declare an executor")

    return {
        "binding_rows_canonical_sha256": sha256(canonical_bytes(bindings)),
        "bindings": bindings,
        "mode": "inert_read_only_source_proven_partial_binding_overlay",
        "overlay_id": "thor-vss-3.2.1-candidate-execution-bindings-wave1",
        "policy": {
            "admission_effect": "none",
            "authorization_consumed": False,
            "cloud_inference_required": False,
            "completion_receipt_consumed": False,
            "compiler_can_execute": False,
            "deployed_observed": False,
            "observer_evidence_is_runtime_evidence": False,
            "service_lifecycle_mutation": False,
            "transport_observed": False,
            "warehouse_sample_bundle": "excluded",
        },
        "schema_version": 1,
        "source_identities": {
            "registry_binding_rows_canonical_sha256": registry[
                "binding_rows_canonical_sha256"
            ],
            "registry_id": registry["registry_id"],
            "registry_raw_sha256": EXPECTED_SOURCE_HASHES[REGISTRY_PATH],
            "wave1_contract_id": wave1_contract["contract_id"],
            "wave1_receipt_id": wave1_receipt["receipt_id"],
        },
        "source_locks": locks,
        "summary": {
            "action_contracts": 0,
            "admission_grade_bindings": 0,
            "binding_count": 2,
            "cleanup_contracts": 0,
            "evidence_contracts": 0,
            "partial_bindings": 2,
            "partial_service_profile_bindings": 2,
            "postcondition_collectors": 0,
            "runtime_evidence_records": 0,
        },
        "target": {
            "hardware": "NVIDIA Jetson Thor",
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "product_version": "3.2.1",
        },
    }


def check() -> dict[str, Any]:
    expected = compile_overlay()
    artifact_payload = _read_regular(ARTIFACT_PATH, "binding overlay")
    schema_payload = _read_regular(SCHEMA_PATH, "binding overlay schema")
    artifact = strict_json(artifact_payload, "binding overlay")
    schema = strict_json(schema_payload, "binding overlay schema")
    _validate_schema(artifact, schema, "binding overlay")
    canonical = (
        json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if artifact != expected or artifact_payload != canonical:
        raise BindingError("checked binding overlay is stale or non-canonical")
    return {
        "admission_grade_bindings": 0,
        "binding_count": 2,
        "binding_rows_canonical_sha256": artifact["binding_rows_canonical_sha256"],
        "overlay_raw_sha256": sha256(artifact_payload),
        "status": "ok",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate checked overlay")
    parser.add_argument(
        "--emit", action="store_true", help="print the compiled overlay to stdout"
    )
    args = parser.parse_args(argv)
    if args.check == args.emit:
        parser.error("choose exactly one of --check or --emit")
    try:
        result = compile_overlay() if args.emit else check()
        print(json.dumps(result, indent=2, sort_keys=True))
    except (KeyError, OSError, BindingError) as exc:
        print(f"Wave 1 binding validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
