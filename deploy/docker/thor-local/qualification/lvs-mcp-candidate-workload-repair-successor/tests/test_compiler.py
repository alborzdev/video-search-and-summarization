from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location("lvs_mcp_workload_repair", COMPILER_PATH)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def canonical_sha256(value) -> str:
    return hashlib.sha256(compiler.canonical_bytes(value)).hexdigest()


@pytest.fixture(scope="module")
def artifact() -> dict:
    return json.loads(compiler.ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_checked_in_artifact_is_exact_compiler_output(artifact) -> None:
    assert compiler.compile_artifact() == artifact
    compiler.validate_artifact(artifact)
    assert compiler.check()["status"] == "ok"
    assert (
        compiler.ARTIFACT_PATH.read_bytes()
        == compiler.canonical_bytes(artifact) + b"\n"
    )


def test_final_wave1_overlay_schema_compiler_and_tests_are_locked() -> None:
    expected = {
        compiler.WAVE1_BINDING_PATH: "d0052aaaac394b93d9e13a560411982d1d81690fcd9a2c0ebabdee15a1cbb0c1",
        compiler.WAVE1_BINDING_SCHEMA_PATH: "6769e0a982d17290b2374d72713b696c74c92117859937164f5aa19b116f4294",
        compiler.WAVE1_COMPILER_PATH: "efbcb6eeb86c28144c894ea559cba548f658538285c17812a7727b4168307370",
        compiler.WAVE1_TESTS_PATH: "9c91dbf6d33d62cd3f65711f80c2065228cad72d872c9d6f0d594432de683105",
    }
    for path, digest in expected.items():
        assert compiler.EXPECTED_SOURCE_HASHES[path] == digest
        assert hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest() == digest


def test_final_production_sources_and_manifest_are_exactly_bound(artifact) -> None:
    manifest = json.loads((REPO_ROOT / compiler.EXPECTED_TOOLS_PATH).read_text())
    source_files = [
        {
            "path": compiler.PRODUCTION_PATH,
            "sha256": compiler.EXPECTED_SOURCE_HASHES[compiler.PRODUCTION_PATH],
        },
        {
            "path": compiler.PRODUCTION_HELPER_PATH,
            "sha256": compiler.EXPECTED_SOURCE_HASHES[compiler.PRODUCTION_HELPER_PATH],
        },
    ]
    assert manifest["source_files"] == source_files
    assert (
        canonical_sha256(manifest)
        == "939cdcea457f2aeaa163fb24307c2a53d0bc61fd5d094ac74a423afceadad865"
    )
    assert artifact["production_source_lock"] == {
        "status": "finalized_direct_and_helper_sources_locked",
        "source_files": source_files,
        "source_files_canonical_sha256": canonical_sha256(source_files),
    }


def test_rebased_metadata_receipts_and_mapping_are_exactly_locked() -> None:
    locks = compiler.EXPECTED_SOURCE_HASHES
    assert (
        locks[compiler.SELECTOR_PATH]
        == "d44bb521d56f87e32396b619b70ee0b2c645e79bc6d78ebd8c6a380575f25112"
    )
    assert (
        locks[compiler.DESCRIPTOR_PATH]
        == "4c343433c56daa87e418752de37e51d733037183d8296e1d7692a3dcaccd82ca"
    )
    assert (
        locks[compiler.MIGRATION_RECEIPT_PATH]
        == "771336f0f843686ee380467a2772a0e6ad4bef9155fe9d511ce738f9e822189c"
    )
    assert (
        locks[compiler.ACTIVATION_RECEIPT_PATH]
        == "93baf20b5bdb0e46d61595613dac778ffe8a3eb4e1a76a31dc943d2b46e4037e"
    )
    assert (
        locks[compiler.MAPPING_PATH]
        == "cb9bea95b4cfeab7c44441854e331a7093667d6b379fe0555692e5105ce4507f"
    )


def test_workload_preserves_exact_four_six_seven_semantics(artifact) -> None:
    workload = artifact["repaired_workload"]
    assert workload["max_requests"] == 6
    assert workload["max_actions"] == 7
    assert len(workload["operation_units"]) == 4
    assert sum(row["max_requests"] for row in workload["operation_units"]) == 6
    assert sum(row["max_actions"] for row in workload["operation_units"]) == 7
    assert [row["unit_id"] for row in workload["operation_units"]] == [
        "mcp_initialize_and_tools_list",
        "health_ready",
        "summarize_video_nonstream",
        "rejected_unknown_tool_and_invalid_input",
    ]


def test_only_two_tools_are_positive_and_eleven_catalog_only(artifact) -> None:
    catalog = artifact["expected_tool_catalog"]
    assert catalog["positive_tool_names"] == ["health_ready", "summarize_video"]
    assert catalog["positive_tool_count"] == 2
    assert catalog["catalog_only_tool_count"] == 11
    assert len(catalog["catalog_only_tool_names"]) == 11
    assert set(
        catalog["positive_tool_names"] + catalog["catalog_only_tool_names"]
    ) == set(catalog["tool_names"])
    assert (
        canonical_sha256(catalog["schema_map"])
        == catalog["schema_map_canonical_sha256"]
    )


def test_fabricated_facets_are_rejected_and_negative_calls_are_bounded(
    artifact,
) -> None:
    assert (
        artifact["predecessor_rejection"]["rejected_literal_facets"]
        == compiler.REJECTED_FACETS
    )
    negative = artifact["repaired_workload"]["operation_units"][3]
    assert negative["tool_calls"][0]["name"] == "thor_local_contract_unknown_tool"
    assert negative["tool_calls"][1]["name"] == "summarize_video"
    assert "model" not in negative["tool_calls"][1]["arguments"]
    assert negative["mutation"] is False


def test_fixture_and_request_template_are_digest_pinned(artifact) -> None:
    workload = artifact["repaired_workload"]
    fixture = workload["fixture"]
    assert fixture["byte_count"] == 2_575_454
    assert (
        fixture["raw_sha256"] == compiler.EXPECTED_SOURCE_HASHES[compiler.FIXTURE_PATH]
    )
    assert canonical_sha256(fixture) == workload["fixture_contract_canonical_sha256"]
    request = workload["operation_units"][2]["request_template"]
    assert request["url"] == fixture["loopback_url"]
    assert request["model"] == "${admitted_local_model_id}"
    assert (
        canonical_sha256(request)
        == workload["operation_units"][2]["request_template_canonical_sha256"]
    )


def test_cleanup_is_unresolved_and_all_qualification_state_is_zero(artifact) -> None:
    cleanup = artifact["repaired_workload"]["cleanup_boundary"]
    assert cleanup["status"] == "unresolved_fail_closed"
    assert cleanup["cleanup_executor"] is None
    assert "No reviewed candidate-scoped cleanup executor" in cleanup["blocker"]
    assert artifact["qualification_state"] == {
        "runtime_evidence_count": 0,
        "authorization_receipt_count": 0,
        "completion_receipt_count": 0,
        "admitted_candidate_count": 0,
        "executable_candidate_count": 0,
        "runtime_ready": False,
        "admission_grade": False,
        "can_promote_runtime_state": False,
    }


def test_hitl_and_scope_remain_separate_and_inert(artifact) -> None:
    assert artifact["hitl_boundary"]["claimed_by_this_repair"] is False
    assert artifact["hitl_boundary"]["lvs_hitl_observations"] == []
    assert artifact["scope"] == {
        "additive_overlay_only": True,
        "sse_candidate_changed": False,
        "related_candidate_ids_changed": [],
        "docker_or_service_lifecycle_performed": False,
        "network_activity_performed": False,
        "runtime_activity_performed": False,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("candidate", "required_cloud_inference"), True),
        (("repaired_workload", "max_requests"), 7),
        (("qualification_state", "runtime_ready"), True),
        (("production_source_lock", "status"), "deferred"),
    ],
)
def test_semantic_mutations_fail_exact_contract(path, value, artifact) -> None:
    changed = copy.deepcopy(artifact)
    changed[path[0]][path[1]] = value
    with pytest.raises(compiler.RepairError):
        compiler.validate_artifact(changed)


def test_source_drift_fails_closed(monkeypatch) -> None:
    original = compiler.EXPECTED_SOURCE_HASHES[compiler.PRODUCTION_PATH]
    monkeypatch.setitem(
        compiler.EXPECTED_SOURCE_HASHES, compiler.PRODUCTION_PATH, "0" * 64
    )
    with pytest.raises(compiler.RepairError, match="source raw hash drift"):
        compiler.compile_artifact()
    assert original != "0" * 64


def test_output_hash_pins_and_emit_are_deterministic(capsys) -> None:
    for path in (compiler.ARTIFACT_PATH, compiler.SCHEMA_PATH):
        assert (
            hashlib.sha256(path.read_bytes()).hexdigest()
            == compiler.EXPECTED_OUTPUT_HASHES[path.name]
        )
    assert compiler.main(["--emit"]) == 0
    emitted = capsys.readouterr().out.encode("ascii")
    assert emitted == compiler.ARTIFACT_PATH.read_bytes()


def test_schema_is_strict_and_exactly_27_sources() -> None:
    schema = json.loads(compiler.SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    source_locks = schema["properties"]["source_locks"]
    assert source_locks["minItems"] == source_locks["maxItems"] == 27
    assert len(compiler.EXPECTED_SOURCE_HASHES) == 27


def test_no_obsolete_identity_runtime_network_docker_or_write_surface() -> None:
    source = COMPILER_PATH.read_text()
    schema = compiler.SCHEMA_PATH.read_text()
    for obsolete in (
        "deferred_drift_detected_not_baked",
        "historical_expected_manifest_sha256",
        "HISTORICAL_PRODUCTION_SHA256",
    ):
        assert obsolete not in source
        assert obsolete not in schema
    tree = ast.parse(source)
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports.isdisjoint(
        {"docker", "os", "requests", "shutil", "socket", "subprocess", "urllib"}
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(
        {
            "mkdir",
            "open",
            "rename",
            "replace",
            "run",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )


def test_strict_json_and_unsafe_paths_fail_closed() -> None:
    with pytest.raises(compiler.RepairError, match="duplicate JSON key"):
        compiler.strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(compiler.RepairError, match="unsafe source path"):
        compiler._resolve_regular("../outside")
