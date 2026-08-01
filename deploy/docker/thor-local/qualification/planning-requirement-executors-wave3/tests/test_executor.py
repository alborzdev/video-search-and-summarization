from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parents[1]
REPO_ROOT = HERE.parents[4]


def _module():
    spec = importlib.util.spec_from_file_location("wave3_source_executor", HERE / "executor.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_inventory_and_result_validate_against_schemas():
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    result = module.build_result()
    jsonschema.Draft202012Validator(json.loads((HERE / "inventory.schema.json").read_text())).validate(inventory)
    jsonschema.Draft202012Validator(json.loads((HERE / "result.schema.json").read_text())).validate(result)


def test_exact_six_nonoverlapping_open_requirements_and_expected_outcomes():
    module = _module()
    result = module.build_result()
    assert result["counts"] == {
        "total_planning_requirements": 110,
        "integrated_materialized": 27,
        "live_open": 83,
        "cases": 6,
        "observed_match": 5,
        "observed_mismatch": 1,
        "open_requirements_audited": 83,
        "open_requirements_unselected": 77,
    }
    assert len({item["planning_requirement_id"] for item in result["results"]}) == 6
    mismatch = [item for item in result["results"] if item["outcome"] == "observed_mismatch"]
    assert [item["case_id"] for item in mismatch] == ["wave3-source-case.search-upload-content-type"]
    failed = [item for item in mismatch[0]["assertions"] if not item["passed"]]
    assert failed == [{"assertion_id": "unsupported-content-type-contract-is-400", "passed": False, "detail": "observed='415'"}]


def test_no_overlap_with_prior_twenty_six_cases():
    current = json.loads((HERE / "inventory.json").read_text())
    prior_paths = [
        HERE.parent / "executor-cases/inventory.json",
        HERE.parent / "source-contract-cases/inventory.json",
    ]
    prior = {
        case["planning_requirement_id"]
        for path in prior_paths
        for case in json.loads(path.read_text())["cases"]
    }
    selected = {case["planning_requirement_id"] for case in current["cases"]}
    assert selected.isdisjoint(prior)
    assert len(prior) == 26


def test_all_cases_are_candidate_only_and_have_zero_runtime_evidence():
    inventory = json.loads((HERE / "inventory.json").read_text())
    assert inventory["scope"] == "isolated_candidate_only"
    assert inventory["policies"] == {
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "network": False,
        "subprocess": False,
        "writes": False,
    }
    assert all(case["runtime_evidence"] == [] for case in inventory["cases"])


def test_executor_does_not_modify_live_ledgers():
    module = _module()
    paths = [
        HERE.parent / "acceptance_inventory.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json",
    ]
    before = [_digest(path) for path in paths]
    module.build_result()
    assert [_digest(path) for path in paths] == before


def test_tampered_planning_payload_fails_result_contract(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["planning_payload_sha256"] = "0" * 64
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    with pytest.raises(module.QualificationError, match="result schema validation failed"):
        module.build_result()


def test_tampered_source_lock_fails_result_contract(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["source_locks"][0]["sha256"] = "0" * 64
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    with pytest.raises(module.QualificationError, match="result schema validation failed"):
        module.build_result()


def test_duplicate_case_binding_is_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][1]["case_id"] = inventory["cases"][0]["case_id"]
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    with pytest.raises(module.QualificationError, match="duplicate case_id"):
        module.build_result()


def test_duplicate_json_key_is_rejected(tmp_path, monkeypatch):
    module = _module()
    raw = (HERE / "inventory.json").read_text()
    duplicate = raw.replace(
        '"schema_version": 1,',
        '"schema_version": 1,\n  "schema_version": 1,',
        1,
    )
    path = tmp_path / "inventory.json"
    path.write_text(duplicate)
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    with pytest.raises(module.QualificationError, match="duplicate JSON key"):
        module.build_result()


def test_path_traversal_is_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    original = inventory["cases"][0]["source_locks"][0]["path"]
    inventory["cases"][0]["source_locks"][0]["path"] = "../outside"
    for assertion in inventory["cases"][0]["assertions"]:
        assertion["sources"] = [
            "../outside" if source == original else source
            for source in assertion["sources"]
        ]
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    with pytest.raises(ValueError, match="unsafe source path"):
        module.build_result()


def test_unknown_adapter_is_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["adapter"] = "execute_shell"
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    with pytest.raises(module.QualificationError, match="inventory schema validation"):
        module.build_result()


def test_executor_imports_no_network_subprocess_or_credential_modules():
    tree = ast.parse((HERE / "executor.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"subprocess", "socket", "requests", "httpx", "urllib", "aiohttp", "docker", "boto3"})


def test_executor_has_no_file_write_calls():
    tree = ast.parse((HERE / "executor.py").read_text())
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert attrs.isdisjoint({"write_text", "write_bytes", "unlink", "rename", "replace", "mkdir", "rmdir"})


def test_result_schema_rejects_runtime_evidence_and_live_promotion():
    schema = json.loads((HERE / "result.schema.json").read_text())
    result = _module().build_result()
    result["results"][0]["runtime_evidence"] = [{"status": "pass"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(result)
    result = _module().build_result()
    result["advances_live_acceptance"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(result)


def test_exact_83_open_before_candidate_and_77_remain_unselected():
    acceptance = json.loads((HERE.parent / "acceptance_inventory.json").read_text())
    open_ids = {
        item["id"]
        for item in acceptance["wave3_contracts"]["planning_requirements"]
        if not item["materialized"]
    }
    selected = {
        item["planning_requirement_id"]
        for item in json.loads((HERE / "inventory.json").read_text())["cases"]
    }
    assert len(open_ids) == 83
    assert "calibration-schema-static" not in open_ids
    assert selected <= open_ids
    assert len(open_ids - selected) == 77


def test_machine_audit_classifies_every_open_requirement_exactly_once():
    result = _module().build_result()
    rows = result["open_requirement_audit"]
    assert len(rows) == 83
    assert len({row["planning_requirement_id"] for row in rows}) == 83
    assert sum(row["classification"] == "selected_source_executor" for row in rows) == 6
    assert sum(row["classification"] != "selected_source_executor" for row in rows) == 77
