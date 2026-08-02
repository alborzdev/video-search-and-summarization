#!/usr/bin/env python3
"""Validate the finalized provenance-rebased Wave 1 LVS binding overlay."""

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

REGISTRY_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-binding-registry-rebase-successor"
)
REGISTRY_PATH = f"{REGISTRY_DIR}/registry.json"
ADMISSION_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-admission-receipts-rebase-successor"
)
AUTHORITY_DIR = (
    "deploy/docker/thor-local/qualification/"
    "candidate-authority-registry-rebase-successor"
)
HISTORICAL_DIR = (
    "deploy/docker/thor-local/qualification/candidate-execution-bindings-wave1"
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
AUTHORITY_REGISTRY_PATH = f"{AUTHORITY_DIR}/authority-registry.json"
AUTHORITY_REGISTRY_SCHEMA_PATH = f"{AUTHORITY_DIR}/authority-registry.schema.json"
SIGNED_RECEIPT_SET_PATH = f"{AUTHORITY_DIR}/signed-receipt-set.json"
SIGNED_RECEIPT_SET_SCHEMA_PATH = f"{AUTHORITY_DIR}/signed-receipt-set.schema.json"
ADMISSION_INDEX_PATH = f"{ADMISSION_DIR}/admission-index.json"
ADMISSION_RECEIPT_SET_PATH = f"{ADMISSION_DIR}/receipt-set.json"

EXPECTED_SOURCE_HASHES = {
    REGISTRY_PATH: "af3927c15f9e5c1efb67690ee7ca3f3e6ee9fb77e720767db2264d68a935b6b5",
    f"{REGISTRY_DIR}/registry.schema.json": "8c2f7fa335340ceaf6870236e11fa2f4d290ba0ee3029f101495b6f66dda1f61",
    f"{REGISTRY_DIR}/locator-locks.json": "d1882d4811bd661fd011f8cf91894951cc8af806c56968218ef0100b500b69a0",
    f"{REGISTRY_DIR}/locator-locks.schema.json": "3cad143f04ebb9a80b11e180aed9a6ccb573d247d52b617ea8caeb9805075cb2",
    ADMISSION_INDEX_PATH: "74398a4239cfd13f753924aaf65b5ce16e6f96b44dc9eae8067eddb8a03456ff",
    f"{ADMISSION_DIR}/admission-index.schema.json": "54cef2f2dc7879f817ff21c2b2472b19629d23c028fc25c3cee04fe9f09926d7",
    ADMISSION_RECEIPT_SET_PATH: "e3d3d918bb392d903c00d82687efbf24d7c834019761929304019bbd4930132f",
    f"{ADMISSION_DIR}/receipt-set.schema.json": "63dfd032bb3625fd1d5002f19a10e25f72f1c775c9f2c5ce6ee1121531449c10",
    WAVE1_CONTRACT_PATH: "fae464894d7d565a1078f852776bb005e0426c4280473d551bbec3e727e2d53c",
    f"{WAVE1_DIR}/contract.schema.json": "aeac007e154451fd33bf17f126b561518d7a2a4ff752b2aa683d56896b9bf84b",
    WAVE1_ORACLES_PATH: "1a066029a04bc67bcefd4571f24fce1cda1df275ab48aed48f99ea7e274f10b5",
    f"{WAVE1_DIR}/successor-capability-oracles.schema.json": "ee7391aeb8cb9c433df77df378adcd7cfb0a91c070a1940132e9ab77cdeadbca",
    WAVE1_RECEIPT_PATH: "ab07eac3e5c240f55d2480fe34aa5128be0cd62b3a64027e3ae689cb27bd0396",
    f"{WAVE1_DIR}/execution-receipt.schema.json": "f4071b29a45a5d487a241914ef7023fed39f52bc3103704f27ad76a86b3b4618",
    ROOT_COMPOSE_PATH: "aed3eb17a594eb278f8a3ec8c4e3a3590a1314504c28be646d28231d07a1f77e",
    SERVICES_COMPOSE_PATH: "6e901bde4e67d19d0a0a78b6dffbcb1bb05b60253d2c945025f7d3adc444822c",
    DEVELOPER_PROFILES_COMPOSE_PATH: "7e419ba68db50aae4cd581bd0d789169c0bcff3f07f40b2ca2c9813b347dfdb2",
    THOR_PROFILE_COMPOSE_PATH: "1c847e7c526c3444a64f9df04c35df303a2fed8fb0a95bbb450a22687aeaecca",
    LVS_COMPOSE_PATH: "6bf986735bb6971c03df50ec1cfa15fe2024ba213574f08ed767517e85b18e74",
    THOR_COMPOSE_PATH: "b3f8b8d94f05e0edfbe0e1652457c80bd821d0dc93271fb75e2bc40b188c12ce",
    THOR_WRAPPER_PATH: "2b67c0b0ee25582ef5acd45ddf12dc02279700ffad065299e6577082fd189df5",
    THOR_PROFILE_ENV_PATH: "a80aa33ed97ea2947caff05402e6a049d2aeec81b4152857063d178163cff718",
    LVS_MCP_PATH: "32a4cc0913025ed34a5e08f751c7d08b97877a047ff72244185a1a9f7d29c211",
    VIA_SERVER_PATH: "2f95a82460a932cc3aac0161ed227eac12f2ac080dc7e44ef1641841730d5e6d",
    VIA_STREAM_HANDLER_PATH: "fa10dadab32da7b6800e0acd84176f955f86adf08c4e018bfa4651c0f33e7f60",
    LVS_EXPECTED_PATH: "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
    PROTOCOL_PATH: "cea6cf41109654fa040f120c74a17b253c019b38cfb1a1e8229d370c2f10d5f7",
    WORKLOAD_PATH: "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    AUTHORITY_REGISTRY_PATH: "954aa42541f715bdbb25148a322e2e3b3380f27fc4f958e8ba0e7378945acdd4",
    AUTHORITY_REGISTRY_SCHEMA_PATH: "46593bea289de96c0b9fe799f8a6c6c4087b730977dde6bcd26c016bd58dd297",
    SIGNED_RECEIPT_SET_PATH: "84ce0c682a49dc930f33fa2bb698e9a7f66a14902cf123e0cba060a8c0f8ed24",
    SIGNED_RECEIPT_SET_SCHEMA_PATH: "05bb7d89d5e0d3648f1ca17a7211540e9083ce0d73ffd073e2a1d5ff0202d27a",
    f"{AUTHORITY_DIR}/compiler.py": "e18fde2f2cad8a5fb74c10688e8f0ef57d15891d3ae175be44dbfe243019e2a3",
    f"{AUTHORITY_DIR}/tests/test_compiler.py": "c9dd77bdad91177e0e5e1e1c4a1d00d7fdcfb50340de3392725a01f23bd191b5",
}

IMMUTABLE_FILES = {
    f"{HISTORICAL_DIR}/README.md": "162acfd58db2ee3479aeb368d4c7dc5ba80b9d25db76f7f05c17b7fdf2fcb5dc",
    f"{HISTORICAL_DIR}/EVIDENCE.md": "5e531ea666e5bbeec9bb67f999c64870cf20ca398e4c37785ea1e8a08160ab0e",
    f"{HISTORICAL_DIR}/compiler.py": "ff3ecc822bc3b9f58c17c67cd36feaabbe5d3c515a0c3aa14d46fd02fdef6414",
    f"{HISTORICAL_DIR}/binding-overlay.json": "aeb8eec139138f45a12a7673abe6f65cca455dbc1717e145e626fc58e70add24",
    f"{HISTORICAL_DIR}/binding-overlay.schema.json": "64c3a26b9fc50067b1842b9309b6ec3649fd52e35b7f24169f8657e6858c9bef",
    f"{HISTORICAL_DIR}/tests/test_compiler.py": "3bca46194f6f865197700ceae6cc247670375a4d6ac39d6c92e3d93d310a809b",
    "deploy/docker/thor-local/parity/metadata_sets/selector.json": "8021efc4684b106539a627b3ddfd82937c7ecf1d6111a3c87538fc5ea7360bec",
    "deploy/docker/thor-local/parity/metadata_sets/sets/thor-vss-3.2.1-metadata-500-staged.json": "56ed8f555c0814e80a39c15198a33c80d400c991a4857a27b4609ea88b5750f9",
}

CANDIDATES = (
    (
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
        "oracle.manifest-entry.video-summarization-live.05-sse-mcp-server",
        310,
        "b523becd0b511f975d38eb3947504e8185c8fe38b12b323838d32b514d664c07",
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


def _require_finalized_authority_inputs() -> None:
    pending = {
        path: digest
        for path, digest in EXPECTED_SOURCE_HASHES.items()
        if digest.startswith("PENDING_")
    }
    if pending:
        detail = ", ".join(f"{path}={digest}" for path, digest in pending.items())
        raise BindingError(f"authority rebase inputs pending: {detail}")


def _assert_immutable_files() -> None:
    for relative, expected in IMMUTABLE_FILES.items():
        payload = _read_regular(_repo_path(relative), relative)
        if sha256(payload) != expected:
            raise BindingError(f"immutable historical/canonical drift: {relative}")


def _locked_sources() -> tuple[dict[str, bytes], list[dict[str, str]]]:
    _require_finalized_authority_inputs()
    _assert_immutable_files()
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
            'SessionCleaningSseServerTransport("/messages")',
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
            'else {"error": str(error), "type": type(error).__name__}',
            'raise ValueError(f"Unknown tool: {name}")',
            "return response.json()",
            "return await self._call_sse_api(",
        ],
    )
    _require_text(
        payloads,
        VIA_SERVER_PATH,
        [
            "drop_result = self._stream_handler.drop_collection_for_asset(file_id)",
            "_require_collection_drop_success(file_id, drop_result)",
            'logger.error("Elasticsearch cleanup failed for file %s: %s", file_id, e)',
            'return {"id": file_id, "object": "file", "deleted": True}',
        ],
    )
    _require_text(
        payloads,
        VIA_STREAM_HANDLER_PATH,
        [
            "def drop_collection_for_asset(",
            'raise ViaException(user_message, "DependencyError", http_status) from ex',
            "default_<asset_id>",
        ],
    )


def _source_locks_for(paths: list[str]) -> list[dict[str, str]]:
    return [
        {"path": path, "raw_sha256": EXPECTED_SOURCE_HASHES[path]} for path in paths
    ]


def _preserved_binding_semantics(row: dict[str, Any]) -> dict[str, Any]:
    """Select the historical action/executor/service/profile/cleanup meaning."""
    surface = row["runtime_surface"]
    return {
        "action_contract": row["action_contract"],
        "admission_grade": row["admission_grade"],
        "authorization_consumed": row["authorization_consumed"],
        "candidate_id": row["candidate_id"],
        "cleanup_contract": row["cleanup_contract"],
        "completion_receipt_consumed": row["completion_receipt_consumed"],
        "deployed_observed": row["deployed_observed"],
        "evidence_status": row["evidence_contract"]["status"],
        "evidence_destination": row["evidence_contract"]["evidence_destination"],
        "evidence_records": row["evidence_contract"]["evidence_records"],
        "input_contract": row["input_contract"],
        "oracle_id": row["oracle_id"],
        "oracle_index": row["oracle_index"],
        "overlay_state": row["overlay_state"],
        "postcondition_contract": row["postcondition_contract"],
        "runtime_evidence": row["runtime_evidence"],
        "runtime_ready": row["runtime_ready"],
        "runtime_surface": {
            key: surface[key]
            for key in (
                "container_name",
                "effective_profile_id",
                "effective_resolved_endpoints",
                "network_mode",
                "profile_id_source_default",
                "profile_paths",
                "service_definition_include_chain",
                "service_role",
                "status",
                "top_level_compose_inputs",
            )
        },
        "transport_observed": row["transport_observed"],
        "unresolved_fields": row["unresolved_fields"],
        "warehouse_sample_bundle": row["warehouse_sample_bundle"],
    }


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
                    "Unknown-tool handling remains an in-process TextContent observation; live JSON-RPC transport behavior and no-route telemetry are not observed.",
                    "The bounded summarize_video SSE adapter is source-locked but has not been observed through a live MCP transport/session.",
                    "delete_file cleanup is source-level fail-closed, but deployed default_<file_id> Elasticsearch absence has not been observed.",
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
    for instance, schema_path, label in (
        (registry, f"{REGISTRY_DIR}/registry.schema.json", "binding registry"),
        (wave1_contract, f"{WAVE1_DIR}/contract.schema.json", "Wave1 contract"),
        (
            wave1_oracles,
            f"{WAVE1_DIR}/successor-capability-oracles.schema.json",
            "Wave1 successor",
        ),
        (
            wave1_receipt,
            f"{WAVE1_DIR}/execution-receipt.schema.json",
            "Wave1 receipt",
        ),
        (authority_registry, AUTHORITY_REGISTRY_SCHEMA_PATH, "authority registry"),
        (
            signed_receipts,
            SIGNED_RECEIPT_SET_SCHEMA_PATH,
            "signed receipt set",
        ),
        (
            admission_index,
            f"{ADMISSION_DIR}/admission-index.schema.json",
            "admission index",
        ),
        (
            admission_receipts,
            f"{ADMISSION_DIR}/receipt-set.schema.json",
            "admission receipt set",
        ),
    ):
        _validate_schema(
            instance,
            strict_json(payloads[schema_path], f"{label} schema"),
            label,
        )

    if (
        registry.get("registry_id")
        != "thor-vss-3.2.1-candidate-execution-binding-registry-rebase-successor"
    ):
        raise BindingError("unexpected source registry identity")
    if (
        registry.get("binding_rows_canonical_sha256")
        != "0d8b334e25330d8f5142a6fff91cc13fc3ebf0c013a371e1f6b41334530c0924"
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
    historical = strict_json(
        _read_regular(
            _repo_path(f"{HISTORICAL_DIR}/binding-overlay.json"),
            "historical binding overlay",
        ),
        "historical binding overlay",
    )
    if [_preserved_binding_semantics(row) for row in bindings] != [
        _preserved_binding_semantics(row) for row in historical["bindings"]
    ]:
        raise BindingError(
            "historical binding/action/executor/service/profile/cleanup semantics drifted"
        )

    return {
        "binding_rows_canonical_sha256": sha256(canonical_bytes(bindings)),
        "bindings": bindings,
        "mode": "inert_read_only_source_proven_partial_binding_overlay",
        "overlay_id": (
            "thor-vss-3.2.1-candidate-execution-bindings-wave1-rebase-successor"
        ),
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
            "historical_overlay_raw_sha256": IMMUTABLE_FILES[
                f"{HISTORICAL_DIR}/binding-overlay.json"
            ],
            "authority_registry_raw_sha256": EXPECTED_SOURCE_HASHES[
                AUTHORITY_REGISTRY_PATH
            ],
            "authority_registry_schema_raw_sha256": EXPECTED_SOURCE_HASHES[
                AUTHORITY_REGISTRY_SCHEMA_PATH
            ],
            "signed_receipt_set_raw_sha256": EXPECTED_SOURCE_HASHES[
                SIGNED_RECEIPT_SET_PATH
            ],
            "signed_receipt_set_schema_raw_sha256": EXPECTED_SOURCE_HASHES[
                SIGNED_RECEIPT_SET_SCHEMA_PATH
            ],
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
