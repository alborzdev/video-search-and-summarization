from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wave1_binding_compiler", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def load_artifact() -> dict:
    return json.loads((PACKAGE / "binding-overlay.json").read_text(encoding="utf-8"))


def test_checked_overlay_is_current_and_exact() -> None:
    result = compiler.check()
    assert result == {
        "admission_grade_bindings": 0,
        "binding_count": 2,
        "binding_rows_canonical_sha256": "b6dc8c0d5c63a21d0baed1a75e392e8c731ea89c92335bfb738ba6395b21b494",
        "overlay_raw_sha256": "aeb8eec139138f45a12a7673abe6f65cca455dbc1717e145e626fc58e70add24",
        "status": "ok",
    }


def test_only_static_service_profile_wiring_is_bound() -> None:
    artifact = load_artifact()
    assert artifact["summary"] == {
        "action_contracts": 0,
        "admission_grade_bindings": 0,
        "binding_count": 2,
        "cleanup_contracts": 0,
        "evidence_contracts": 0,
        "partial_bindings": 2,
        "partial_service_profile_bindings": 2,
        "postcondition_collectors": 0,
        "runtime_evidence_records": 0,
    }
    assert [row["candidate_id"] for row in artifact["bindings"]] == [
        "manifest-entry.video-summarization-live.05-sse-mcp-server",
        "manifest-entry.agent-and-mcp-apis.06-lvs-mcp",
    ]
    for row in artifact["bindings"]:
        assert row["runtime_surface"]["service_role"] == "lvs-server"
        assert row["runtime_surface"]["container_name"] == "vss-lvs"
        assert (
            row["runtime_surface"]["profile_id_source_default"]
            == "bp_developer_thor_full_2d"
        )
        assert row["runtime_surface"]["effective_profile_id"] is None
        assert row["runtime_surface"]["effective_resolved_endpoints"] is None
        assert (
            row["runtime_surface"]["status"]
            == "source_proven_static_wiring_not_deployed"
        )


def test_every_execution_and_admission_field_fails_closed() -> None:
    artifact = load_artifact()
    policy = artifact["policy"]
    assert policy["admission_effect"] == "none"
    assert policy["authorization_consumed"] is False
    assert policy["completion_receipt_consumed"] is False
    assert policy["compiler_can_execute"] is False
    assert policy["deployed_observed"] is False
    assert policy["transport_observed"] is False
    assert policy["observer_evidence_is_runtime_evidence"] is False
    for row in artifact["bindings"]:
        assert row["admission_grade"] is False
        assert row["authorization_consumed"] is False
        assert row["completion_receipt_consumed"] is False
        assert row["deployed_observed"] is False
        assert row["transport_observed"] is False
        assert row["runtime_ready"] is False
        assert row["runtime_evidence"] == []
        assert row["action_contract"] == {
            "action_contract_sha256": None,
            "action_kind": None,
            "argv": None,
            "executor": None,
            "status": "unresolved_fail_closed",
        }
        assert row["input_contract"] == {
            "fixture": None,
            "model": None,
            "runtime_request": None,
            "status": "unresolved_fail_closed",
        }
        assert row["postcondition_contract"] == {
            "collectors": [],
            "contract": None,
            "status": "unresolved_fail_closed",
        }


def test_source_defaults_cannot_be_misread_as_runtime_observation() -> None:
    for row in load_artifact()["bindings"]:
        interface = row["runtime_surface"]["source_declared_interface"]
        assert set(key for key in interface if "endpoint" in key) == {
            "default_health_endpoint",
            "default_mcp_get_endpoint",
            "default_mcp_post_endpoint",
            "health_endpoint_is_mcp_readiness_proof",
        }
        assert interface["health_endpoint_is_mcp_readiness_proof"] is False
        assert interface["media_root_host_bind_expression"] == "${VSS_DATA_DIR}/videos"


def test_semantic_conflicts_remain_explicit() -> None:
    rows = {row["candidate_id"]: row for row in load_artifact()["bindings"]}
    all_blockers = "\n".join(
        blocker for row in rows.values() for blocker in row["retained_blockers"]
    )
    assert "Unknown-tool handling returns normal TextContent error JSON" in all_blockers
    assert "summarize_video stream=true is not safely bindable" in all_blockers
    assert "default_<file_id> Elasticsearch absence check is required" in all_blockers
    assert "whole-stack thor-local.sh restart command is prohibited" in all_blockers
    lvs_blockers = "\n".join(
        rows["manifest-entry.agent-and-mcp-apis.06-lvs-mcp"]["retained_blockers"]
    )
    assert "get_lvs_hitl_state has no production MCP tool" in lvs_blockers


def test_source_hash_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        compiler.EXPECTED_SOURCE_HASHES, compiler.LVS_MCP_PATH, "0" * 64
    )
    with pytest.raises(compiler.BindingError, match="source hash drift"):
        compiler.compile_overlay()


def test_duplicate_json_key_is_rejected() -> None:
    with pytest.raises(compiler.BindingError, match="duplicate key"):
        compiler.strict_json(b'{"x":1,"x":2}', "duplicate fixture")


def test_final_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    real = root / "real"
    real.write_text("source", encoding="utf-8")
    link = root / "link"
    link.symlink_to(real)
    monkeypatch.setattr(compiler, "REPO_ROOT", root)
    with pytest.raises(compiler.BindingError, match="cannot safely open"):
        compiler._read_regular(link, "symlink fixture")


def test_intermediate_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "source").write_text("source", encoding="utf-8")
    (root / "linked-directory").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(compiler, "REPO_ROOT", root)
    with pytest.raises(compiler.BindingError, match="cannot safely open"):
        compiler._read_regular(
            root / "linked-directory" / "source", "directory symlink"
        )


def test_no_execute_mode_is_exposed() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "from subprocess" not in source
    assert "docker compose" not in source
    assert '"--execute"' not in source
    assert '"--write"' not in source
