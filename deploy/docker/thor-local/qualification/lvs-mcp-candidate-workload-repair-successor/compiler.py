#!/usr/bin/env python3
"""Validate the inert, additive LVS MCP candidate workload repair overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4].resolve(strict=True)
ARTIFACT_PATH = HERE / "repair-overlay.json"
SCHEMA_PATH = HERE / "repair-overlay.schema.json"
MAX_SOURCE_BYTES = 96_000_000

CANDIDATE_ID = "manifest-entry.agent-and-mcp-apis.06-lvs-mcp"
ORACLE_ID = f"oracle.{CANDIDATE_ID}"
MANIFEST_POINTER = "/features/27/advertised/6"
HITL_CAPABILITY_ID = "runtime.agent.base-hitl"
DOC_CAPABILITY_ID = "api.core.lvs-mcp-doc-13-repo-9"
DOC_URL = "https://docs.nvidia.com/vss/3.2.1/long-video-summarization.html"
PRODUCTION_PATH = "services/video-summarization/src/lvs_mcp.py"
PRODUCTION_HELPER_PATH = "services/video-summarization/src/lvs_mcp_sse.py"

ACTIVATION_DIR = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-activation-rebase-successor"
)
MIGRATION_DIR = (
    "deploy/docker/thor-local/qualification/"
    "live-metadata-500-migration-rebase-successor"
)
SELECTOR_PATH = f"{ACTIVATION_DIR}/projected-selector.json"
SELECTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/selector.schema.json"
)
DESCRIPTOR_PATH = f"{ACTIVATION_DIR}/projected-live-ready-descriptor.json"
DESCRIPTOR_TARGET_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/sets/"
    "thor-vss-3.2.1-metadata-500-staged-rebase-"
    "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c.json"
)
DESCRIPTOR_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/metadata_sets/metadata-set.schema.json"
)
MANIFEST_PATH = f"{MIGRATION_DIR}/post-state-manifest.json"
CAPABILITIES_PATH = f"{MIGRATION_DIR}/post-state-official-capabilities.json"
CAPABILITIES_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/official-capabilities.schema.json"
)
ORACLES_PATH = f"{MIGRATION_DIR}/post-state-capability-oracles.json"
ORACLES_SCHEMA_PATH = f"{MIGRATION_DIR}/post-state-capability-oracles.schema.json"
MIGRATION_RECEIPT_PATH = f"{MIGRATION_DIR}/migration.json"
MIGRATION_RECEIPT_SCHEMA_PATH = f"{MIGRATION_DIR}/migration.schema.json"
ACTIVATION_RECEIPT_PATH = f"{ACTIVATION_DIR}/activation-rebase.json"
ACTIVATION_RECEIPT_SCHEMA_PATH = f"{ACTIVATION_DIR}/activation-rebase.schema.json"
WORKLOADS_PATH = (
    "deploy/docker/thor-local/qualification/remaining-entry-workloads/workloads.json"
)
WORKLOADS_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/remaining-entry-workloads/"
    "workload.schema.json"
)
EXPECTED_TOOLS_PATH = "deploy/docker/thor-local/qualification/expected/lvs-mcp.json"
DOC_LOCK_PATH = "deploy/docker/thor-local/parity/source-lock/source-lock.json"
DOC_LOCK_SCHEMA_PATH = (
    "deploy/docker/thor-local/parity/source-lock/source-lock.schema.json"
)
WAVE1_BINDING_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-bindings-wave1-rebase-successor/"
    "binding-overlay.json"
)
WAVE1_BINDING_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-bindings-wave1-rebase-successor/"
    "binding-overlay.schema.json"
)
WAVE1_COMPILER_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-bindings-wave1-rebase-successor/compiler.py"
)
WAVE1_TESTS_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-execution-bindings-wave1-rebase-successor/tests/test_compiler.py"
)
MAPPING_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-approval-mapping-rebase-successor-v2/mapping.json"
)
MAPPING_SCHEMA_PATH = (
    "deploy/docker/thor-local/qualification/"
    "candidate-approval-mapping-rebase-successor-v2/mapping.schema.json"
)
FIXTURE_PATH = "services/alert/warmup/test.mp4"

EXPECTED_SOURCE_HASHES = {
    SELECTOR_PATH: "d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112",
    SELECTOR_SCHEMA_PATH: "16f22fc55e49f6b32d6053f585937688828f0e739ee56429da0bc2c0d5d5377b",
    DESCRIPTOR_PATH: "4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca",
    DESCRIPTOR_SCHEMA_PATH: "23019f9491d945243da785fab2c9ee007708ec1b2d910a9fd5ae625bd822eee4",
    MANIFEST_PATH: "c71f75246fc1e4cbc388f93849d27c3b7dc7edf2d0a516fb3fa13f6d412a4a93",
    CAPABILITIES_PATH: "8a6e14b35ce73362bc8c3dccc84788ab48a2e3f88284b41f1b4a6efc30cd7d13",
    CAPABILITIES_SCHEMA_PATH: "fb817586b9a37ad7975ca820f69a7f2c6e575bca9f8d8686701d5fa0bf505896",
    ORACLES_PATH: "911c38e2db0f92bdcc46938c90bac67626ef1009a4e131f1feee5538dcbee021",
    ORACLES_SCHEMA_PATH: "b24308d9647ff7a4c7b66cc91881749eaaa84c21ab7423677fc30ab4f9c36233",
    WORKLOADS_PATH: "ca4170118a94a659acca600d9ab00dca6504544f062edabd5cef0ed3311e8312",
    WORKLOADS_SCHEMA_PATH: "736f9295e4f89afbb1aaed7c086155e30a09b6dc2c583433b9cb98ad2c005c14",
    EXPECTED_TOOLS_PATH: "6768be993243685b467e185280f9321ea402117a9000df5f8a99d63dc094383c",
    DOC_LOCK_PATH: "fbf21f64f13dc22328c4a01c79e427042c3112885073dc32bb0ebd6700f0fd07",
    DOC_LOCK_SCHEMA_PATH: "c106674641ad573167cba55400e4877bab5d6cfde3413f6854971ebbc93ee0ab",
    WAVE1_BINDING_PATH: "d0052aaaac394b93d9e13a560411982d1d81690fcd9a2c0ebabdee15a1cbb0c1",
    WAVE1_BINDING_SCHEMA_PATH: "6769e0a982d17290b2374d72713b696c74c92117859937164f5aa19b116f4294",
    WAVE1_COMPILER_PATH: "efbcb6eeb86c28144c894ea559cba548f658538285c17812a7727b4168307370",
    WAVE1_TESTS_PATH: "9c91dbf6d33d62cd3f65711f80c2065228cad72d872c9d6f0d594432de683105",
    MAPPING_PATH: "cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f",
    MAPPING_SCHEMA_PATH: "78c118cc062eee15992ad3fcd4fa2d3585e6b80dc5bea7e32806ade1f11ccaba",
    PRODUCTION_PATH: "32a4cc0913025ed34a5e08f751c7d08b97877a047ff72244185a1a9f7d29c211",
    PRODUCTION_HELPER_PATH: "94306d18703a598982fbfe3515dcb3ed7cad31dfb106cb0d5b5c4ef92e6806f8",
    MIGRATION_RECEIPT_PATH: "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c",
    MIGRATION_RECEIPT_SCHEMA_PATH: "45c41fc02b60fa466689ab2ece0e87487287a20e3d247ba0f62293c649a349c0",
    ACTIVATION_RECEIPT_PATH: "93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e",
    ACTIVATION_RECEIPT_SCHEMA_PATH: "5a4d3c481577540b21531ca08fbfe3e814b310a5e428b9fd7af8b02f9c9bb85f",
    FIXTURE_PATH: "f2c16bf02e1d43fa52faf902ff981185c62df092189b41c735c5c27647b44205",
}

EXPECTED_OUTPUT_HASHES = {
    "repair-overlay.json": "a637ee239903683c8c38176b270bc8da831c6e5fbb0a08520455e92ab15a84a7",
    "repair-overlay.schema.json": "6f9444839fc7d90e048b19b0b60b3462def03991d75c00829dd6c2e255268473",
}

EXPECTED_RECORD_HASHES = {
    "candidate": "a20cdc7f85cfb06e26dafe6e477d17075b51b4e97dd04faa1e1a178475516147",
    "candidate_oracle": "e06850f09ddaadfb6ab40324816f2bff0b19eae5341ec3b7df4e1955f431bc3d",
    "predecessor_workload": "2f28f1531c90af4e0f849781e362850776bc1caffda75cecb918d8c4df6633a3",
    "wave1_binding": "5772a873bb2104b6c143a09cd59e614102067689a6bb3859ed9268a047d366a2",
    "mapping": "7e712e8e445e59a6630d1ba980de3fb679d828a696865f7b6f42b88fdf13a6fe",
    "official_doc_capability": "bb80483e53dec3c7b4531b809e076f2f895935356f02df5d1a7695d67071b51d",
    "official_doc_record": "93793488aa47fd9785b9ba7d7ccfc786f1a8e5a294320278cf1580094b1e9f18",
    "agent_hitl": "24b1227d693fe8cc6c0b0023683a4eade33c076cc58c3ac849dab4a71367ce0f",
}
EXPECTED_WAVE1_ROWS_CANONICAL_SHA256 = (
    "f088de43966cb2f1e7a5451f6912be3d6736690eb2c4dc413e38a78e63acba1a"
)

EXPECTED_TOOL_NAMES = [
    "add_file",
    "delete_file",
    "generate_captions",
    "generate_vlm_captions",
    "get_file_info",
    "get_metrics",
    "get_recommended_config",
    "health_live",
    "health_ready",
    "list_files",
    "list_models",
    "stream_summarize",
    "summarize_video",
]
POSITIVE_TOOL_NAMES = ["health_ready", "summarize_video"]
CATALOG_ONLY_TOOL_NAMES = [
    name for name in EXPECTED_TOOL_NAMES if name not in POSITIVE_TOOL_NAMES
]
REJECTED_FACETS = [
    "list_lvs_mcp_tools",
    "get_lvs_readiness",
    "call_lvs_summarize",
    "get_lvs_hitl_state",
]


class RepairError(RuntimeError):
    """A source lock or fail-closed repair invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def strict_json(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RepairError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                RepairError(f"{label}: non-finite JSON token {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError(f"{label}: invalid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RepairError(f"{label}: root must be an object")
    return value


def _resolve_regular(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise RepairError(f"unsafe source path: {relative}")
    current = REPO_ROOT
    for part in pure.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise RepairError(f"source is missing: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RepairError(f"source path traverses a symlink: {relative}")
    if not stat.S_ISREG(current.stat().st_mode):
        raise RepairError(f"source is not a regular file: {relative}")
    return current


def _load_sources() -> tuple[dict[str, Any], list[dict[str, str]]]:
    _require_finalized_wave1_inputs()
    sources: dict[str, Any] = {}
    locks: list[dict[str, str]] = []
    for relative, expected_hash in EXPECTED_SOURCE_HASHES.items():
        payload = _resolve_regular(relative).read_bytes()
        if len(payload) > MAX_SOURCE_BYTES:
            raise RepairError(f"source exceeds size bound: {relative}")
        observed_hash = sha256(payload)
        if observed_hash != expected_hash:
            raise RepairError(f"source raw hash drift: {relative}")
        sources[relative] = (
            strict_json(payload, relative) if relative.endswith(".json") else payload
        )
        locks.append({"path": relative, "raw_sha256": observed_hash})
    return sources, locks


def _require_finalized_wave1_inputs() -> None:
    pending = {
        path: digest
        for path, digest in EXPECTED_SOURCE_HASHES.items()
        if digest.startswith("PENDING_")
    }
    if pending:
        detail = ", ".join(f"{path}={digest}" for path, digest in pending.items())
        raise RepairError(f"Wave 1 rebase inputs pending: {detail}")


def _validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise RepairError(f"{label} schema invalid: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise RepairError(f"{label} schema violation at {location}: {error.message}")


def _one(
    rows: list[dict[str, Any]], key: str, identity: str, label: str
) -> tuple[int, dict[str, Any]]:
    found = [(index, row) for index, row in enumerate(rows) if row.get(key) == identity]
    if len(found) != 1:
        raise RepairError(f"{label}: expected one {identity!r}, found {len(found)}")
    return found[0]


def _assert_record(row: dict[str, Any], expected: str, label: str) -> None:
    if sha256(canonical_bytes(row)) != expected:
        raise RepairError(f"{label}: canonical record drift")


def _validate_selected_metadata(sources: dict[str, Any]) -> None:
    selector = sources[SELECTOR_PATH]
    descriptor = sources[DESCRIPTOR_PATH]
    _validate_schema(selector, sources[SELECTOR_SCHEMA_PATH], "metadata selector")
    _validate_schema(descriptor, sources[DESCRIPTOR_SCHEMA_PATH], "metadata descriptor")
    selected = selector.get("selected_set")
    available = {row.get("set_id"): row for row in selector.get("available_sets", [])}
    selected_row = available.get(selected)
    if (
        selected != "thor-vss-3.2.1-metadata-500-staged"
        or selected_row is None
        or selected_row.get("descriptor_path") != DESCRIPTOR_TARGET_PATH
        or selected_row.get("descriptor_raw_sha256")
        != EXPECTED_SOURCE_HASHES[DESCRIPTOR_PATH]
        or descriptor.get("set_id") != selected
        or descriptor.get("lifecycle") != "live_ready"
        or descriptor.get("target")
        != {
            "main_commit": "7732edf8fb38ef896b20f2a0a6a701a4db10dc57",
            "product_version": "3.2.1",
        }
        or descriptor.get("expected_counts")
        != {"capabilities": 500, "feature_families": 55, "oracles": 500}
    ):
        raise RepairError("selected Metadata-500 identity or lifecycle drift")
    documents = descriptor.get("documents", {})
    expected_documents = {
        "manifest": (MANIFEST_PATH, EXPECTED_SOURCE_HASHES[MANIFEST_PATH]),
        "official_capabilities": (
            CAPABILITIES_PATH,
            EXPECTED_SOURCE_HASHES[CAPABILITIES_PATH],
        ),
        "capability_oracles": (ORACLES_PATH, EXPECTED_SOURCE_HASHES[ORACLES_PATH]),
    }
    for key, (path, digest) in expected_documents.items():
        row = documents.get(key, {})
        if row.get("path") != path or row.get("raw_sha256") != digest:
            raise RepairError(f"selected Metadata-500 {key} document drift")
    migration = sources[MIGRATION_RECEIPT_PATH]
    activation = sources[ACTIVATION_RECEIPT_PATH]
    _validate_schema(
        migration,
        sources[MIGRATION_RECEIPT_SCHEMA_PATH],
        "migration rebase receipt",
    )
    _validate_schema(
        activation,
        sources[ACTIVATION_RECEIPT_SCHEMA_PATH],
        "activation rebase receipt",
    )
    if (
        activation["source_locks"]["migration_proof"]
        != {
            "path": MIGRATION_RECEIPT_PATH,
            "raw_sha256": EXPECTED_SOURCE_HASHES[MIGRATION_RECEIPT_PATH],
        }
        or migration["summary"]["candidate_runtime_evidence_count"] != 0
        or migration["summary"]["candidate_promotable_count"] != 0
        or activation["candidate_boundary"]["runtime_evidence_count"] != 0
        or activation["candidate_boundary"]["promotable_count"] != 0
    ):
        raise RepairError("migration/activation fail-closed chain drift")


def _validate_authoritative_rows(sources: dict[str, Any]) -> dict[str, Any]:
    capabilities = sources[CAPABILITIES_PATH]
    oracles = sources[ORACLES_PATH]
    workloads = sources[WORKLOADS_PATH]
    binding = sources[WAVE1_BINDING_PATH]
    mapping = sources[MAPPING_PATH]
    doc_lock = sources[DOC_LOCK_PATH]

    _validate_schema(capabilities, sources[CAPABILITIES_SCHEMA_PATH], "capabilities")
    _validate_schema(oracles, sources[ORACLES_SCHEMA_PATH], "oracles")
    _validate_schema(workloads, sources[WORKLOADS_SCHEMA_PATH], "workloads")
    _validate_schema(binding, sources[WAVE1_BINDING_SCHEMA_PATH], "Wave 1 binding")
    _validate_schema(mapping, sources[MAPPING_SCHEMA_PATH], "mapping v2")
    _validate_schema(doc_lock, sources[DOC_LOCK_SCHEMA_PATH], "official doc lock")

    candidate_index, candidate = _one(
        capabilities.get("capabilities", []), "id", CANDIDATE_ID, "candidate"
    )
    oracle_index, oracle = _one(
        oracles.get("oracles", []), "oracle_id", ORACLE_ID, "candidate oracle"
    )
    workload_index, workload = _one(
        workloads.get("workloads", []), "candidate_id", CANDIDATE_ID, "workload"
    )
    binding_index, binding_row = _one(
        binding.get("bindings", []), "candidate_id", CANDIDATE_ID, "Wave 1 binding"
    )
    mapping_index, mapping_row = _one(
        mapping.get("mappings", []), "capability_id", CANDIDATE_ID, "mapping"
    )
    doc_cap_index, doc_cap = _one(
        capabilities.get("capabilities", []), "id", DOC_CAPABILITY_ID, "doc capability"
    )
    hitl_index, hitl = _one(
        capabilities.get("capabilities", []), "id", HITL_CAPABILITY_ID, "Agent HITL"
    )
    doc_index, doc_record = _one(
        doc_lock.get("records", []), "url", DOC_URL, "official LVS doc record"
    )

    for label, row in {
        "candidate": candidate,
        "candidate_oracle": oracle,
        "predecessor_workload": workload,
        "wave1_binding": binding_row,
        "mapping": mapping_row,
        "official_doc_capability": doc_cap,
        "official_doc_record": doc_record,
        "agent_hitl": hitl,
    }.items():
        _assert_record(row, EXPECTED_RECORD_HASHES[label], label)

    if (
        candidate_index,
        oracle_index,
        workload_index,
        binding_index,
        mapping_index,
    ) != (
        468,
        468,
        42,
        1,
        179,
    ):
        raise RepairError("candidate/workload/binding/mapping position drift")
    if (doc_cap_index, hitl_index, doc_index) != (127, 163, 44):
        raise RepairError("official documentation or Agent HITL position drift")
    if candidate.get("contract", {}).get("manifest_pointer") != MANIFEST_POINTER:
        raise RepairError("candidate manifest pointer drift")
    if (
        oracle.get("capability_id") != CANDIDATE_ID
        or oracle.get("current_state") != "open_unexecuted"
    ):
        raise RepairError("candidate oracle identity or state drift")
    if workload.get("literal_facets") != REJECTED_FACETS:
        raise RepairError("predecessor fabricated facet set drift")
    if workload.get("runtime_evidence"):
        raise RepairError("predecessor workload unexpectedly contains runtime evidence")
    if (
        binding.get("binding_rows_canonical_sha256")
        != EXPECTED_WAVE1_ROWS_CANONICAL_SHA256
        or binding.get("summary", {}).get("runtime_evidence_records") != 0
        or binding.get("summary", {}).get("admission_grade_bindings") != 0
        or binding.get("summary", {}).get("action_contracts") != 0
        or binding.get("summary", {}).get("cleanup_contracts") != 0
    ):
        raise RepairError("Wave 1 rebase aggregate or fail-closed boundary drift")
    if (
        binding_row.get("admission_grade") is not False
        or binding_row.get("runtime_ready") is not False
        or binding_row.get("runtime_evidence") != []
        or binding_row.get("authorization_consumed") is not False
        or binding_row.get("completion_receipt_consumed") is not False
    ):
        raise RepairError("Wave 1 binding unexpectedly advanced")
    if (
        mapping_row.get("approval_state") != "no_receipt_not_admitted_not_executable"
        or mapping_row.get("required_cloud_inference") is not False
        or mapping_row.get("warehouse_sample_bundle") is not False
    ):
        raise RepairError("candidate mapping state or local boundary drift")
    if (
        doc_record.get("outcome") != "success"
        or doc_record.get("http_status") != 200
        or doc_record.get("sha256")
        != "df081c4955bc546879e899883b38b7f465304bc9f8273c1edb8cc68e1bb0f5ce"
    ):
        raise RepairError("official 3.2.1 LVS documentation lock drift")
    return {
        "candidate": candidate,
        "oracle": oracle,
        "workload": workload,
        "binding": binding_row,
        "mapping": mapping_row,
        "doc_capability": doc_cap,
        "doc_record": doc_record,
        "hitl": hitl,
    }


def _validate_expected_tools(
    sources: dict[str, Any], rows: dict[str, Any]
) -> dict[str, Any]:
    expected = sources[EXPECTED_TOOLS_PATH]
    if set(expected) != {
        "kind",
        "prompt_count",
        "prompts",
        "schema_version",
        "source_files",
        "surface",
        "tool_count",
        "tools",
    }:
        raise RepairError("expected LVS MCP manifest shape drift")
    tools = expected.get("tools", [])
    names = [row.get("name") for row in tools]
    if (
        expected.get("schema_version") != 2
        or expected.get("kind") != "mcp"
        or expected.get("surface") != "lvs-mcp"
        or expected.get("tool_count") != 13
        or expected.get("prompt_count") != 0
        or expected.get("prompts") != []
        or names != EXPECTED_TOOL_NAMES
        or len(set(names)) != 13
    ):
        raise RepairError("expected LVS MCP 13-tool catalog drift")
    for row in tools:
        if set(row) != {"name", "input_schema_hash"}:
            raise RepairError("expected LVS MCP tool row shape drift")
        digest = row.get("input_schema_hash")
        if not isinstance(digest, str) or len(digest) != 64:
            raise RepairError("expected LVS MCP tool schema digest invalid")
    source_files = expected.get("source_files")
    expected_source_files = [
        {"path": PRODUCTION_PATH, "sha256": EXPECTED_SOURCE_HASHES[PRODUCTION_PATH]},
        {
            "path": PRODUCTION_HELPER_PATH,
            "sha256": EXPECTED_SOURCE_HASHES[PRODUCTION_HELPER_PATH],
        },
    ]
    if source_files != expected_source_files:
        raise RepairError("expected LVS MCP production source identity drift")
    binding_locks = {
        row.get("path"): row.get("raw_sha256")
        for row in rows["binding"].get("runtime_surface", {}).get("source_locks", [])
    }
    if binding_locks.get(PRODUCTION_PATH) != EXPECTED_SOURCE_HASHES[PRODUCTION_PATH]:
        raise RepairError("Wave 1 binding production source lock drift")
    if (
        rows["doc_capability"].get("contract", {}).get("docs_tool_count") != 13
        or rows["doc_capability"].get("contract", {}).get("expected_manifest")
        != EXPECTED_TOOLS_PATH
        or rows["doc_capability"].get("contract", {}).get("expected_manifest_sha256")
        != EXPECTED_SOURCE_HASHES[EXPECTED_TOOLS_PATH]
    ):
        raise RepairError("official documentation capability 13-tool linkage drift")
    schema_map = {row["name"]: row["input_schema_hash"] for row in tools}
    return {
        "manifest_canonical_sha256": sha256(canonical_bytes(expected)),
        "tools_canonical_sha256": sha256(canonical_bytes(tools)),
        "names_canonical_sha256": sha256(canonical_bytes(names)),
        "schema_map_canonical_sha256": sha256(canonical_bytes(schema_map)),
        "schema_map": schema_map,
        "source_files": expected_source_files,
    }


def _stable_fixture_contract(sources: dict[str, Any]) -> dict[str, Any]:
    payload = sources[FIXTURE_PATH]
    if (
        not isinstance(payload, bytes)
        or len(payload) != 2_575_454
        or b"ftyp" not in payload[:32]
    ):
        raise RepairError("stable LVS video fixture identity or media signature drift")
    return {
        "path": FIXTURE_PATH,
        "raw_sha256": EXPECTED_SOURCE_HASHES[FIXTURE_PATH],
        "byte_count": len(payload),
        "media_type": "video/mp4",
        "loopback_url": (
            "http://127.0.0.1:38113/lvs-mcp-fixture/"
            f"{EXPECTED_SOURCE_HASHES[FIXTURE_PATH]}.mp4"
        ),
    }


def build_expected(
    sources: dict[str, Any], locks: list[dict[str, str]], rows: dict[str, Any]
) -> dict[str, Any]:
    catalog = _validate_expected_tools(sources, rows)
    fixture = _stable_fixture_contract(sources)
    request_template = {
        "url": fixture["loopback_url"],
        "prompt": "Summarize the visible activity in one concise factual sentence.",
        "model": "${admitted_local_model_id}",
        "chunk_duration": 60,
        "chunk_overlap_duration": 0,
        "stream": False,
        "max_tokens": 128,
        "temperature": 0.0,
        "scenario": "thor-local-lvs-mcp-contract",
        "events": ["visible activity"],
        "override_vlm_prompt": True,
        "enable_vlm_structured_output": False,
    }
    return {
        "schema_version": 1,
        "repair_id": "lvs-mcp-candidate-workload-repair-successor-v1",
        "mode": "static_inert_additive_non_promoting_plan",
        "candidate": {
            "candidate_id": CANDIDATE_ID,
            "oracle_id": ORACLE_ID,
            "manifest_pointer": MANIFEST_POINTER,
            "acceptance_class": "required_local",
            "execution_boundary": "local",
            "required_cloud_inference": False,
            "warehouse_sample_bundle": "excluded",
        },
        "selected_metadata": {
            "set_id": "thor-vss-3.2.1-metadata-500-staged",
            "capability_count": 500,
            "oracle_count": 500,
            "feature_family_count": 55,
            "source_bytes_preserved": True,
            "mutated_source_paths": [],
        },
        "source_locks": locks,
        "source_identities": {
            "candidate": {
                "json_pointer": "/capabilities/468",
                "canonical_sha256": EXPECTED_RECORD_HASHES["candidate"],
            },
            "candidate_oracle": {
                "json_pointer": "/oracles/468",
                "canonical_sha256": EXPECTED_RECORD_HASHES["candidate_oracle"],
            },
            "predecessor_workload": {
                "json_pointer": "/workloads/42",
                "canonical_sha256": EXPECTED_RECORD_HASHES["predecessor_workload"],
            },
            "wave1_binding": {
                "json_pointer": "/bindings/1",
                "canonical_sha256": EXPECTED_RECORD_HASHES["wave1_binding"],
            },
            "mapping_v2": {
                "json_pointer": "/mappings/179",
                "canonical_sha256": EXPECTED_RECORD_HASHES["mapping"],
            },
            "official_3_2_1_lvs_doc": {
                "json_pointer": "/records/44",
                "canonical_sha256": EXPECTED_RECORD_HASHES["official_doc_record"],
                "url": DOC_URL,
                "body_raw_sha256": rows["doc_record"]["sha256"],
            },
            "official_13_tool_capability": {
                "json_pointer": "/capabilities/127",
                "canonical_sha256": EXPECTED_RECORD_HASHES["official_doc_capability"],
            },
        },
        "expected_tool_catalog": {
            "tool_count": 13,
            "tool_names": EXPECTED_TOOL_NAMES,
            "tool_names_canonical_sha256": catalog["names_canonical_sha256"],
            "tools_canonical_sha256": catalog["tools_canonical_sha256"],
            "schema_map": catalog["schema_map"],
            "schema_map_canonical_sha256": catalog["schema_map_canonical_sha256"],
            "expected_manifest_raw_sha256": EXPECTED_SOURCE_HASHES[EXPECTED_TOOLS_PATH],
            "expected_manifest_canonical_sha256": catalog["manifest_canonical_sha256"],
            "comparison_policy": "exact_name_set_and_per_name_canonical_input_schema_hash",
            "positive_tool_count": 2,
            "positive_tool_names": POSITIVE_TOOL_NAMES,
            "catalog_only_tool_count": 11,
            "catalog_only_tool_names": CATALOG_ONLY_TOOL_NAMES,
        },
        "predecessor_rejection": {
            "rejected_literal_facets": REJECTED_FACETS,
            "reason": (
                "These are generated planning labels, not production MCP tool names; "
                "get_lvs_hitl_state has no LVS MCP tool or completion field."
            ),
            "predecessor_source_bytes_preserved": True,
        },
        "repaired_workload": {
            "workload_id": "workload.lvs-mcp.exact-protocol-and-tools-v1",
            "workload_type": "mcp_protocol_and_tool_calls",
            "activation": "future_separately_authorized_local_executor_only",
            "phases": [
                "pre_state",
                "fixture_setup",
                "mcp_session",
                "positive_calls",
                "negative_calls",
                "owned_cleanup",
                "postcondition",
            ],
            "max_requests": 6,
            "max_actions": 7,
            "network_scope": "loopback_only",
            "fixture": fixture,
            "fixture_contract_canonical_sha256": sha256(canonical_bytes(fixture)),
            "operation_units": [
                {
                    "unit_id": "mcp_initialize_and_tools_list",
                    "max_requests": 2,
                    "max_actions": 3,
                    "mutation": False,
                    "steps": [
                        "initialize request",
                        "notifications/initialized notification",
                        "tools/list request",
                    ],
                    "required_observations": [
                        "initialize succeeds and identifies server name lvs-engine",
                        "tools/list returns exactly 13 unique names",
                        "each returned inputSchema canonical hash exactly matches expected_tool_catalog.schema_map",
                    ],
                },
                {
                    "unit_id": "health_ready",
                    "max_requests": 1,
                    "max_actions": 1,
                    "mutation": False,
                    "tool_call": {"name": "health_ready", "arguments": {}},
                    "tool_call_canonical_sha256": "96c873eab738c0074f411256dfa9fc9eaf81ccc4c0c9d873f497c4dd5ee58202",
                    "required_observations": [
                        "CallToolResult.isError is false",
                        "TextContent parses exactly as status=ready and code=200",
                    ],
                },
                {
                    "unit_id": "summarize_video_nonstream",
                    "max_requests": 1,
                    "max_actions": 1,
                    "mutation": True,
                    "created_state": [
                        "server-generated summarization request and source identity",
                        "stream-settings cache entry keyed by source identity",
                        "per-source CA-RAG or Elasticsearch data when configured",
                    ],
                    "request_template": request_template,
                    "request_template_canonical_sha256": sha256(
                        canonical_bytes(request_template)
                    ),
                    "runtime_substitution": {
                        "placeholder": "${admitted_local_model_id}",
                        "source": "future separately admitted local-model runtime receipt",
                        "must_be_nonempty": True,
                    },
                    "required_observations": [
                        "CallToolResult.isError is false",
                        "content is a nonempty list containing nonempty TextContent",
                        "parsed completion choices contain an assistant message with nonempty string content",
                        "the parsed result is correlated to the digest-pinned loopback asset request",
                    ],
                },
                {
                    "unit_id": "rejected_unknown_tool_and_invalid_input",
                    "max_requests": 2,
                    "max_actions": 2,
                    "mutation": False,
                    "tool_calls": [
                        {"name": "thor_local_contract_unknown_tool", "arguments": {}},
                        {
                            "name": "summarize_video",
                            "arguments": {
                                "scenario": "thor-local-lvs-mcp-contract",
                                "events": ["visible activity"],
                            },
                        },
                    ],
                    "required_observations": [
                        "unknown tool returns CallToolResult.isError=true with nonempty sanitized content",
                        "summarize_video input missing required model returns CallToolResult.isError=true with nonempty sanitized content",
                        "neither rejected call starts inference or mutates candidate or unrelated state",
                    ],
                },
            ],
            "cleanup_boundary": {
                "status": "unresolved_fail_closed",
                "cleanup_executor": None,
                "owned_targets": [
                    "loopback fixture server bound to 127.0.0.1:38113",
                    "MCP client session",
                    "server-generated summarization request and source identity",
                    "stream-settings cache entry keyed by source identity",
                    "per-source CA-RAG or Elasticsearch data when configured",
                ],
                "must_preserve": [
                    "already-running LVS profile",
                    "uploaded LVS assets",
                    "unrelated services and state",
                ],
                "postconditions": [
                    "fixture server stopped only if executor-owned",
                    "MCP session closed",
                    "all server-generated state is absent or restored to exact pre-state",
                    "profile pre-state unchanged",
                ],
                "blocker": (
                    "No reviewed candidate-scoped cleanup executor currently removes the "
                    "summarize route's stream-settings cache entry and verifies any per-source "
                    "CA-RAG or Elasticsearch state is absent."
                ),
            },
        },
        "hitl_boundary": {
            "capability_id": HITL_CAPABILITY_ID,
            "json_pointer": "/capabilities/163",
            "canonical_sha256": EXPECTED_RECORD_HASHES["agent_hitl"],
            "relationship": "separate_agent_level_capability_not_an_lvs_mcp_tool",
            "claimed_by_this_repair": False,
            "lvs_hitl_observations": [],
        },
        "production_source_lock": {
            "status": "finalized_direct_and_helper_sources_locked",
            "source_files": catalog["source_files"],
            "source_files_canonical_sha256": sha256(
                canonical_bytes(catalog["source_files"])
            ),
        },
        "scope": {
            "additive_overlay_only": True,
            "sse_candidate_changed": False,
            "related_candidate_ids_changed": [],
            "docker_or_service_lifecycle_performed": False,
            "network_activity_performed": False,
            "runtime_activity_performed": False,
        },
        "qualification_state": {
            "runtime_evidence_count": 0,
            "authorization_receipt_count": 0,
            "completion_receipt_count": 0,
            "admitted_candidate_count": 0,
            "executable_candidate_count": 0,
            "runtime_ready": False,
            "admission_grade": False,
            "can_promote_runtime_state": False,
        },
    }


def compile_artifact() -> dict[str, Any]:
    _require_finalized_wave1_inputs()
    sources, locks = _load_sources()
    _validate_selected_metadata(sources)
    rows = _validate_authoritative_rows(sources)
    expected = build_expected(sources, locks, rows)
    schema = strict_json(SCHEMA_PATH.read_bytes(), str(SCHEMA_PATH))
    _validate_schema(expected, schema, "repair overlay")
    return expected


def validate_artifact(artifact: dict[str, Any]) -> None:
    expected = compile_artifact()
    if canonical_bytes(artifact) != canonical_bytes(expected):
        raise RepairError("repair overlay differs from the exact compiled contract")

    lock_paths = {row["path"] for row in artifact["source_locks"]}
    if not {PRODUCTION_PATH, PRODUCTION_HELPER_PATH} <= lock_paths:
        raise RepairError("final production source locks are incomplete")


def check() -> dict[str, Any]:
    _require_finalized_wave1_inputs()
    payload = ARTIFACT_PATH.read_bytes()
    if sha256(payload) != EXPECTED_OUTPUT_HASHES[ARTIFACT_PATH.name]:
        raise RepairError("repair overlay raw hash drift")
    schema_payload = SCHEMA_PATH.read_bytes()
    if sha256(schema_payload) != EXPECTED_OUTPUT_HASHES[SCHEMA_PATH.name]:
        raise RepairError("repair overlay schema raw hash drift")
    artifact = strict_json(payload, str(ARTIFACT_PATH))
    validate_artifact(artifact)
    if payload != canonical_bytes(artifact) + b"\n":
        raise RepairError("repair overlay bytes are not canonical JSON plus newline")
    return {
        "status": "ok",
        "repair_id": artifact["repair_id"],
        "candidate_id": CANDIDATE_ID,
        "tool_count": artifact["expected_tool_catalog"]["tool_count"],
        "operation_unit_count": len(artifact["repaired_workload"]["operation_units"]),
        "runtime_evidence_count": 0,
        "admitted_candidate_count": 0,
        "executable_candidate_count": 0,
        "production_source_lock": "finalized_direct_and_helper_sources_locked",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="validate the pinned artifact"
    )
    mode.add_argument(
        "--emit", action="store_true", help="emit canonical JSON to stdout"
    )
    args = parser.parse_args(argv)
    try:
        if args.emit:
            print(canonical_bytes(compile_artifact()).decode("ascii"))
            return 0
        result = check()
    except RepairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
