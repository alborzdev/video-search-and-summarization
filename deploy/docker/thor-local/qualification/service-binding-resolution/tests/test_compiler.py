from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
REPO_ROOT = HERE.parents[6]
COMPILER_PATH = PACKAGE / "compiler.py"
SPEC = importlib.util.spec_from_file_location("service_binding_compiler", COMPILER_PATH)
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


@pytest.fixture(scope="module")
def plan() -> dict:
    return compiler._load(compiler.PLAN)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _copy_contract(destination: Path, plan: dict) -> None:
    relative_paths = {item["path"] for item in plan["source_bindings"]} | {
        compiler.SCHEMA.relative_to(REPO_ROOT).as_posix(),
        compiler.MAPPING_SCHEMA.relative_to(REPO_ROOT).as_posix(),
    }
    for relative in relative_paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)


def test_checked_plan_is_exact_deterministic_output(plan: dict) -> None:
    compiler.validate_plan(plan)
    assert plan == compiler.build_plan()
    assert compiler.PLAN.read_bytes() == compiler._encoded(plan)
    assert compiler.main(["--check"]) == 0


def test_exact_four_capability_denominator_and_open_result(plan: dict) -> None:
    assert plan["summary"] == {
        "target_capabilities": 4,
        "resolved_unique_runtime_role_sets": 0,
        "open_authoritative_ambiguities": 4,
        "runtime_lanes_updates_allowed": 0,
        "runtime_evidence_records": 0,
    }
    assert {item["capability_id"] for item in plan["resolutions"]} == (
        compiler.EXPECTED_CAPABILITY_IDS
    )


def test_open_bindings_cannot_claim_roles_updates_or_evidence(plan: dict) -> None:
    assert not plan["policy"]["observed_repository_roles_are_authoritative"]
    assert not plan["policy"]["open_bindings_may_update_runtime_lanes"]
    for item in plan["resolutions"]:
        assert item["resolution_state"] == (
            "open_authoritative_contract_does_not_select_unique_runtime_role_set"
        )
        assert item["runtime_service_roles"] == []
        assert item["runtime_lanes_update_allowed"] is False
        assert item["runtime_evidence"] == []
        assert item["observed_non_authoritative_roles"]


def test_only_schema_representation_cases_have_static_tooling_support(
    plan: dict,
) -> None:
    by_id = {item["capability_id"]: item for item in plan["resolutions"]}
    assert (
        by_id["customization.embedding-reindex-validation"]["static_support_roles"]
        == []
    )
    assert by_id["protocol.nvschema.format-selection"]["static_support_roles"] == []
    assert by_id["protocol.nvschema.json-frame"]["static_support_roles"] == [
        "repository-tooling"
    ]
    assert by_id["protocol.nvschema.protobuf-messages"]["static_support_roles"] == [
        "repository-tooling"
    ]


def test_contract_pointers_assertions_and_digests_are_exact(plan: dict) -> None:
    ledger = compiler._load(REPO_ROOT / compiler.LEDGER)
    for item in plan["resolutions"]:
        capability = compiler._pointer(ledger, item["ledger_pointer"])
        assert capability["id"] == item["capability_id"]
        assert item["contract_sha256"] == _canonical_sha256(capability["contract"])
        assert item["source_claims_sha256"] == _canonical_sha256(
            capability["source_claims"]
        )
        for assertion in item["required_contract_assertions"]:
            assert (
                compiler._pointer(capability["contract"], assertion["json_pointer"])
                == assertion["equals"]
            )
        assert not (
            set(item["forbidden_contract_role_keys"]) & set(capability["contract"])
        )


def test_official_document_byte_locks_are_exact(plan: dict) -> None:
    assert {
        item["url"]: item["sha256"] for item in plan["official_document_byte_locks"]
    } == compiler.OFFICIAL_DOC_LOCKS


def test_every_source_binding_is_exact_and_literals_exist(plan: dict) -> None:
    for item in plan["source_bindings"]:
        path = REPO_ROOT / item["path"]
        assert compiler._raw_sha256(path) == item["raw_sha256"]
        text = path.read_text(encoding="utf-8")
        assert all(literal in text for literal in item["required_literals"])


def test_source_byte_drift_fails_closed(tmp_path: Path, plan: dict) -> None:
    _copy_contract(tmp_path, plan)
    target = tmp_path / "tools/message-broker-consumers/base_consumer.py"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(compiler.ResolutionError, match="source drift"):
        compiler.build_plan(tmp_path)


def test_missing_required_literal_fails_even_with_matching_reviewer_digest(
    tmp_path: Path, plan: dict
) -> None:
    _copy_contract(tmp_path, plan)
    mapping_path = tmp_path / compiler.MAPPING.relative_to(REPO_ROOT)
    mapping = compiler._load(mapping_path)
    evidence = mapping["capabilities"][0]["source_evidence"][0]
    evidence["required_literals"].append("literal-that-is-not-present")
    mapping_path.write_bytes(compiler._encoded(mapping))
    with pytest.raises(compiler.ResolutionError, match="required literal absent"):
        compiler.build_plan(tmp_path)


def test_mapping_cannot_inject_runtime_role(tmp_path: Path, plan: dict) -> None:
    _copy_contract(tmp_path, plan)
    mapping_path = tmp_path / compiler.MAPPING.relative_to(REPO_ROOT)
    mapping = compiler._load(mapping_path)
    mapping["capabilities"][0]["runtime_service_roles"] = ["rt-embed"]
    mapping_path.write_bytes(compiler._encoded(mapping))
    with pytest.raises(
        compiler.ResolutionError, match="mapping schema validation failed"
    ):
        compiler.build_plan(tmp_path)


def test_ledger_pointer_identity_tamper_fails_closed(
    tmp_path: Path, plan: dict
) -> None:
    _copy_contract(tmp_path, plan)
    mapping_path = tmp_path / compiler.MAPPING.relative_to(REPO_ROOT)
    mapping = compiler._load(mapping_path)
    mapping["capabilities"][0]["ledger_pointer"] = "/capabilities/0"
    mapping_path.write_bytes(compiler._encoded(mapping))
    with pytest.raises(compiler.ResolutionError, match="pointer identity drift"):
        compiler.build_plan(tmp_path)


def test_new_authoritative_role_key_forces_rereview(
    tmp_path: Path, plan: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_contract(tmp_path, plan)
    ledger_path = tmp_path / compiler.LEDGER
    ledger = compiler._load(ledger_path)
    ledger["capabilities"][28]["contract"]["service_roles"] = ["rt-embed"]
    ledger_path.write_bytes(compiler._encoded(ledger))
    monkeypatch.setattr(compiler, "LEDGER_SHA256", compiler._raw_sha256(ledger_path))
    with pytest.raises(compiler.ResolutionError, match="now selects roles"):
        compiler.build_plan(tmp_path)


def test_plan_tamper_fails_schema_or_determinism(plan: dict) -> None:
    evidence = copy.deepcopy(plan)
    evidence["resolutions"][0]["runtime_evidence"] = [{"claim": "unearned"}]
    with pytest.raises(compiler.ResolutionError, match="schema validation failed"):
        compiler.validate_plan(evidence)

    roles = copy.deepcopy(plan)
    roles["resolutions"][0]["runtime_service_roles"] = ["rt-embed"]
    with pytest.raises(compiler.ResolutionError, match="schema validation failed"):
        compiler.validate_plan(roles)


def test_duplicate_mapping_key_fails_closed(tmp_path: Path, plan: dict) -> None:
    _copy_contract(tmp_path, plan)
    mapping_path = tmp_path / compiler.MAPPING.relative_to(REPO_ROOT)
    text = mapping_path.read_text(encoding="utf-8")
    mapping_path.write_text(
        text.replace(
            '"schema_version": 1,', '"schema_version": 1,\n  "schema_version": 1,'
        ),
        encoding="utf-8",
    )
    with pytest.raises(compiler.ResolutionError, match="duplicate JSON key"):
        compiler.build_plan(tmp_path)


def test_compiler_has_no_runtime_side_effect_imports() -> None:
    tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(
        {"docker", "httpx", "requests", "socket", "subprocess", "urllib"}
    )
