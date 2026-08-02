"""Adversarial tests for the isolated Wave 8 executable candidate."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wave8_executor_tests", HERE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


@pytest.fixture(scope="module")
def result():
    return executor.build_result()


def test_complete_result_is_exact_non_advancing_candidate(result):
    assert [item["entry_id"] for item in result["entries"]] == list(
        executor.EXPECTED_ENTRIES
    )
    assert result["mode"] == "candidate_executable_subset_non_advancing"
    assert result["official_capability_effect"] == "none_candidate_only"
    assert result["runtime_evidence"] == []
    assert result["execution"]["registered_tool_count"] == 13
    assert tuple(result["execution"]["registered_tools"]) == executor.EXPECTED_TOOLS
    assert tuple(result["execution"]["operations"]) == executor.EXPECTED_OPERATIONS
    assert all(
        item["candidate_state"] == "candidate_executable_subset_non_advancing"
        for item in result["entries"]
    )


def test_sse_entry_retains_every_transport_and_runtime_blocker(result):
    entry = result["entries"][0]
    assert entry["entry_id"] == executor.EXPECTED_ENTRIES[0]
    assert set(entry["retained_blockers"]) == {
        "live_sse_connection_not_executed",
        "mcp_transport_and_handshake_not_executed",
        "live_transport_session_cleanup_not_observed",
        "deployed_lvs_not_observed",
        "thor_runtime_readiness_not_observed",
    }
    assert result["safety"]["live_sse_connection"] is False
    assert result["safety"]["mcp_transport_handshake"] is False
    assert result["safety"]["deployed_lvs"] is False
    assert result["safety"]["thor_runtime_readiness"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_evidence", ["invented-live-receipt"]),
        ("official_capability_effect", "passed_current"),
    ],
)
def test_result_schema_rejects_promotion_and_runtime_evidence(result, field, value):
    overclaim = deepcopy(result)
    overclaim[field] = value
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(overclaim, executor.RESULT_SCHEMA_PATH, "overclaim")


def test_schemas_reject_evidence_scope_overclaim_and_cross_entry_swap(result):
    overclaim = deepcopy(result)
    overclaim["entries"][0]["evidence_scope"] = (
        "subset: complete live SSE transport and Thor readiness proven"
    )
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(overclaim, executor.RESULT_SCHEMA_PATH, "overclaim")

    swapped = deepcopy(result)
    swapped["entries"][0]["evidence_scope"] = result["entries"][1]["evidence_scope"]
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(swapped, executor.RESULT_SCHEMA_PATH, "swapped")

    inventory = executor._strict_json_bytes(
        executor.INVENTORY_PATH.read_bytes(), executor.INVENTORY_PATH.name
    )
    inventory["cases"][0]["evidence_scope"] = (
        "subset: complete live SSE transport and Thor readiness proven"
    )
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(
            inventory, executor.INVENTORY_SCHEMA_PATH, "inventory-overclaim"
        )


@pytest.mark.parametrize(
    "field",
    [
        "live_sse_connection",
        "mcp_transport_handshake",
        "deployed_lvs",
        "vlm_inference",
        "thor_runtime_readiness",
        "network_used",
        "socket_used",
        "subprocess_used",
    ],
)
def test_result_schema_rejects_false_safety_claims(result, field):
    overclaim = deepcopy(result)
    overclaim["safety"][field] = True
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(overclaim, executor.RESULT_SCHEMA_PATH, "overclaim")


def test_result_schema_rejects_missing_entry(result):
    incomplete = deepcopy(result)
    incomplete["entries"].pop()
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(incomplete, executor.RESULT_SCHEMA_PATH, "incomplete")


def test_result_schema_rejects_duplicate_or_replaced_entry(result):
    duplicate = deepcopy(result)
    duplicate["entries"][1] = deepcopy(duplicate["entries"][0])
    with pytest.raises(executor.QualificationError, match="schema validation failed"):
        executor._validate_schema(duplicate, executor.RESULT_SCHEMA_PATH, "duplicate")


def test_inventory_and_both_schemas_are_meta_schema_valid():
    inventory = executor._strict_json_bytes(
        executor.INVENTORY_PATH.read_bytes(), executor.INVENTORY_PATH.name
    )
    executor._validate_schema(inventory, executor.INVENTORY_SCHEMA_PATH, "inventory")
    for path in (executor.INVENTORY_SCHEMA_PATH, executor.RESULT_SCHEMA_PATH):
        schema = json.loads(path.read_text(encoding="utf-8"))
        executor.Draft202012Validator.check_schema(schema)


def test_live_source_lock_denominator_covers_transport_cleanup_and_thor_packaging():
    inventory = json.loads(executor.INVENTORY_PATH.read_text(encoding="utf-8"))
    assert {item["path"] for item in inventory["source_locks"]} == {
        "deploy/docker/services/video-summarization/compose.yml",
        "deploy/docker/thor-local/Dockerfile.video-summarization",
        "deploy/docker/thor-local/compose.yml",
        "services/video-summarization/docker/package_file_list.txt",
        "services/video-summarization/src/lvs_mcp.py",
        "services/video-summarization/src/lvs_mcp_sse.py",
        "services/video-summarization/src/rtvi_vlm_client.py",
        "services/video-summarization/src/via_server.py",
        "services/video-summarization/src/via_stream_handler.py",
        "services/video-summarization/tests/test_lvs_delete_cleanup.py",
        "services/video-summarization/tests/test_lvs_mcp.py",
        "services/video-summarization/tests/test_lvs_mcp_sse.py",
    }


def test_live_ledger_locks_are_current_without_advancing_candidates(result):
    assert (
        result["source_digests"][
            "deploy/docker/thor-local/parity/official-capabilities.json"
        ]
        == "61c2a4c0bc9d23940d954311f93824dc55c18cfc58caca002162cc1ef6808098"
    )
    assert (
        result["source_digests"][
            "deploy/docker/thor-local/parity/capability-oracles.json"
        ]
        == "24214553cbd669eb80efa7b4a602ac52328e00bd43241c839b43b10d05e22e8e"
    )
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"


def test_static_wiring_is_bound_without_claiming_live_cleanup(result):
    executor._validate_static_wiring()
    sse, tools = result["entries"]
    assert (
        "session_cleanup_implementation_and_tests_source_locked"
        in sse["matched_assertions"]
    )
    assert "live_transport_session_cleanup_not_observed" in sse["retained_blockers"]
    assert (
        "delete_cleanup_implementation_and_tests_source_locked"
        in tools["matched_assertions"]
    )
    assert "deployed_delete_cleanup_not_observed" in tools["retained_blockers"]
    assert result["safety"]["live_sse_connection"] is False
    assert result["safety"]["mcp_transport_handshake"] is False
    assert result["safety"]["deployed_lvs"] is False


def test_inventory_schema_rejects_callback_or_transport_permission():
    inventory = json.loads(executor.INVENTORY_PATH.read_text(encoding="utf-8"))
    for field in ("caller_supplied_callbacks_allowed", "network_allowed"):
        overclaim = deepcopy(inventory)
        overclaim["policy"][field] = True
        with pytest.raises(
            executor.QualificationError, match="schema validation failed"
        ):
            executor._validate_schema(
                overclaim, executor.INVENTORY_SCHEMA_PATH, "inventory-overclaim"
            )


def test_source_lock_drift_fails_before_semantic_execution(monkeypatch):
    original = executor._read_repo_bytes

    def drift(relative):
        data = original(relative)
        if relative.endswith("advertised-entry-executors-wave3/inventory.json"):
            return data + b"\n"
        return data

    monkeypatch.setattr(executor, "_read_repo_bytes", drift)
    with pytest.raises(executor.QualificationError, match="source lock mismatch"):
        executor._load_inventory()


def test_duplicate_json_and_unsafe_paths_fail_closed():
    with pytest.raises(executor.QualificationError, match="duplicate JSON key"):
        executor._strict_json_bytes(b'{"a":1,"a":2}', "duplicate")
    for path in ("../escape", "/absolute", "nested/../../escape"):
        with pytest.raises(executor.QualificationError, match="unsafe repository path"):
            executor._repo_file(path)


def test_external_execution_guard_denies_network_and_subprocess():
    with executor._deny_external_execution():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(executor.QualificationError, match="prohibited"):
                sock.connect(("127.0.0.1", 1))
        finally:
            sock.close()
        with pytest.raises(executor.QualificationError, match="prohibited"):
            subprocess.run(["true"], check=True)


def test_transport_stubs_make_sse_and_stdio_execution_impossible():
    module = executor._load_production_module()
    backend = executor._FakeLvsBackend()
    server = module.LvsMCPServer(backend)
    with pytest.raises(executor.QualificationError, match="transport construction"):
        asyncio.run(server.run(port=38112))
    with pytest.raises(executor.QualificationError, match="stdio transport"):
        asyncio.run(server.run())


def test_registered_handler_uses_native_call_tool_results_without_error_leakage():
    module = executor._load_production_module()
    backend = executor._FakeLvsBackend()
    server = module.LvsMCPServer(backend)

    with executor._deny_external_execution():
        success = asyncio.run(server._server.call_handler("health_live", {}))
        error = asyncio.run(
            server._server.call_handler(
                "get_file_info", {"file_id": "/sensitive/operator/path"}
            )
        )

    assert server._server.call_handler is server._call_tool_handler
    assert success.isError is False
    assert json.loads(success.content[0].text) == {"status": "alive", "code": 200}
    assert error.isError is True
    assert json.loads(error.content[0].text) == {
        "error": "get_file_info failed; see the LVS service log for details"
    }
    for fragment in ("/sensitive/operator/path", "ValueError", "Traceback"):
        assert fragment not in error.content[0].text


def test_selected_case_is_still_non_advancing():
    result = executor.build_result(executor.EXPECTED_ENTRIES[1])
    assert len(result["entries"]) == 1
    assert result["entries"][0]["entry_id"] == executor.EXPECTED_ENTRIES[1]
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"


def test_unknown_case_fails_closed():
    with pytest.raises(executor.QualificationError, match="unknown Wave 8 entry"):
        executor.build_result("manifest-gap.not-selected")
