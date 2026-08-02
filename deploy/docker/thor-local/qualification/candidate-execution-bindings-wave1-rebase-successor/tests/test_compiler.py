from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "wave1_binding_rebase_scaffold", PACKAGE / "compiler.py"
)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compiler)


def test_final_overlay_is_exact() -> None:
    assert compiler.check() == {
        "admission_grade_bindings": 0,
        "binding_count": 2,
        "binding_rows_canonical_sha256": (
            "f088de43966cb2f1e7a5451f6912be3d6736690eb2c4dc413e38a78e63acba1a"
        ),
        "overlay_raw_sha256": (
            "d0052aaaac394b93d9e13a560411982d1d81690fcd9a2c0ebabdee15a1cbb0c1"
        ),
        "status": "ok",
    }


def test_complete_authority_chain_is_finalized() -> None:
    assert compiler.EXPECTED_SOURCE_HASHES[compiler.AUTHORITY_REGISTRY_PATH] == (
        "954aa42541f715bdbb25148a322e2e3b3380f27fc4f958e8ba0e7378945acdd4"
    )
    assert compiler.EXPECTED_SOURCE_HASHES[compiler.SIGNED_RECEIPT_SET_PATH] == (
        "84ce0c682a49dc930f33fa2bb698e9a7f66a14902cf123e0cba060a8c0f8ed24"
    )
    assert compiler.EXPECTED_SOURCE_HASHES[compiler.AUTHORITY_REGISTRY_SCHEMA_PATH] == (
        "46593bea289de96c0b9fe799f8a6c6c4087b730977dde6bcd26c016bd58dd297"
    )
    assert compiler.EXPECTED_SOURCE_HASHES[compiler.SIGNED_RECEIPT_SET_SCHEMA_PATH] == (
        "05bb7d89d5e0d3648f1ca17a7211540e9083ce0d73ffd073e2a1d5ff0202d27a"
    )
    assert compiler.EXPECTED_SOURCE_HASHES[f"{compiler.AUTHORITY_DIR}/compiler.py"] == (
        "e18fde2f2cad8a5fb74c10688e8f0ef57d15891d3ae175be44dbfe243019e2a3"
    )
    assert (
        compiler.EXPECTED_SOURCE_HASHES[
            f"{compiler.AUTHORITY_DIR}/tests/test_compiler.py"
        ]
        == "c9dd77bdad91177e0e5e1e1c4a1d00d7fdcfb50340de3392725a01f23bd191b5"
    )


def test_reintroduced_pending_hash_fails_before_any_repository_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        compiler.EXPECTED_SOURCE_HASHES,
        compiler.AUTHORITY_REGISTRY_PATH,
        "PENDING_TEST_AUTHORITY_HASH",
    )
    monkeypatch.setattr(
        compiler,
        "_read_regular",
        lambda *_args, **_kwargs: pytest.fail("source read before pending guard"),
    )
    with pytest.raises(compiler.BindingError, match="authority rebase inputs pending"):
        compiler.compile_overlay()


def test_known_finalized_source_locks_match_current_regular_files() -> None:
    for relative, expected in compiler.EXPECTED_SOURCE_HASHES.items():
        if expected.startswith("PENDING_"):
            continue
        payload = compiler._read_regular(compiler._repo_path(relative), relative)
        assert compiler.sha256(payload) == expected


def test_all_historical_and_canonical_files_remain_exact() -> None:
    compiler._assert_immutable_files()
    assert len(compiler.IMMUTABLE_FILES) == 8


def test_historical_overlay_has_exact_fail_closed_semantics() -> None:
    historical = json.loads(
        (
            compiler.REPO_ROOT / compiler.HISTORICAL_DIR / "binding-overlay.json"
        ).read_text(encoding="utf-8")
    )
    assert historical["summary"]["binding_count"] == 2
    for row in historical["bindings"]:
        semantics = compiler._preserved_binding_semantics(row)
        assert semantics["admission_grade"] is False
        assert semantics["authorization_consumed"] is False
        assert semantics["completion_receipt_consumed"] is False
        assert semantics["runtime_evidence"] == []
        assert semantics["action_contract"]["executor"] is None
        assert semantics["action_contract"]["action_contract_sha256"] is None
        assert semantics["cleanup_contract"]["cleanup_executor"] is None
        assert semantics["cleanup_contract"]["cleanup_targets"] == []
        assert semantics["runtime_surface"]["service_role"] == "lvs-server"
        assert semantics["runtime_surface"]["container_name"] == "vss-lvs"
        assert semantics["runtime_surface"]["effective_profile_id"] is None


def test_final_overlay_preserves_every_selected_historical_semantic() -> None:
    historical = json.loads(
        (
            compiler.REPO_ROOT / compiler.HISTORICAL_DIR / "binding-overlay.json"
        ).read_text(encoding="utf-8")
    )
    current = json.loads((PACKAGE / "binding-overlay.json").read_text(encoding="utf-8"))
    assert [
        compiler._preserved_binding_semantics(row) for row in current["bindings"]
    ] == [compiler._preserved_binding_semantics(row) for row in historical["bindings"]]
    assert current["summary"] == {
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
    assert len(current["source_locks"]) == 34
    assert not any(
        lock["raw_sha256"].startswith("PENDING_") for lock in current["source_locks"]
    )


def test_design_schema_is_strict_and_requires_final_authority_hashes() -> None:
    schema = json.loads(
        (PACKAGE / "binding-overlay.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    historical = json.loads(
        (
            compiler.REPO_ROOT / compiler.HISTORICAL_DIR / "binding-overlay.json"
        ).read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(historical)
    mutated["unexpected"] = True
    assert list(Draft202012Validator(schema).iter_errors(mutated))
    assert {
        "authority_registry_raw_sha256",
        "authority_registry_schema_raw_sha256",
    } <= set(schema["properties"]["source_identities"]["required"])


@pytest.mark.parametrize("mode", ["--check", "--emit"])
def test_safe_cli_modes_succeed_without_runtime_effects(mode: str) -> None:
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "compiler.py"), mode],
        cwd=compiler.REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    if mode == "--check":
        assert parsed["status"] == "ok"
    else:
        assert parsed["summary"]["binding_count"] == 2
        assert parsed["summary"]["admission_grade_bindings"] == 0


@pytest.mark.parametrize("mode", ["--execute", "--write", "--run", "--docker"])
def test_runtime_and_write_modes_are_not_exposed(mode: str) -> None:
    result = subprocess.run(
        [sys.executable, str(PACKAGE / "compiler.py"), mode],
        cwd=compiler.REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2


def test_compiler_has_no_runtime_network_or_docker_dependencies() -> None:
    source = (PACKAGE / "compiler.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "from subprocess" not in source
    assert "import socket" not in source
    assert "docker compose" not in source
