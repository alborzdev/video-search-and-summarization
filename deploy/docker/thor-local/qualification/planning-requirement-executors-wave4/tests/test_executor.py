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
    spec = importlib.util.spec_from_file_location(
        "wave4_source_executor", HERE / "executor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inventory(tmp_path: Path, inventory: dict) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory))
    return path


def test_inventory_and_result_validate_against_strict_schemas():
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    result = module.build_result()
    inventory_schema = json.loads((HERE / "inventory.schema.json").read_text())
    result_schema = json.loads((HERE / "result.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(inventory_schema)
    jsonschema.Draft202012Validator.check_schema(result_schema)
    jsonschema.Draft202012Validator(inventory_schema).validate(inventory)
    jsonschema.Draft202012Validator(result_schema).validate(result)


def test_exact_six_cases_five_matches_and_preserved_qwen_mismatch():
    result = _module().build_result()
    assert result["counts"] == {
        "total_planning_requirements": 110,
        "integrated_materialized": 27,
        "live_open": 83,
        "cases": 6,
        "observed_match": 5,
        "observed_mismatch": 1,
        "remaining_requirements_audited": 77,
        "remaining_requirements_unselected": 71,
    }
    mismatch = [item for item in result["results"] if item["outcome"] == "observed_mismatch"]
    assert [item["case_id"] for item in mismatch] == [
        "wave4-source-case.alert-vlm-backends"
    ]
    assert [item for item in mismatch[0]["assertions"] if not item["passed"]] == [
        {
            "assertion_id": "cosmos-and-qwen-examples",
            "passed": False,
            "detail": 'missing=["Qwen"]',
        }
    ]


def test_exact_77_row_accounting_with_locked_canonical_identities():
    result = _module().build_result()
    rows = result["remaining_requirement_audit"]
    assert len(rows) == 77
    assert len({row["planning_requirement_id"] for row in rows}) == 77
    assert "calibration-schema-static" not in {
        row["planning_requirement_id"] for row in rows
    }
    assert sum(row["classification"] == "selected_source_executor" for row in rows) == 6
    assert sum(row["classification"] != "selected_source_executor" for row in rows) == 71
    assert all(len(row["planning_payload_sha256"]) == 64 for row in rows)
    assert all(
        row["capability_sha256"] is None or len(row["capability_sha256"]) == 64
        for row in rows
    )
    assert all(
        row["contract_sha256"] is None or len(row["contract_sha256"]) == 64
        for row in rows
    )


def test_no_overlap_with_prior_32_source_executor_cases():
    current = json.loads((HERE / "inventory.json").read_text())
    prior_paths = [
        HERE.parent / "executor-cases/inventory.json",
        HERE.parent / "source-contract-cases/inventory.json",
        HERE.parent / "planning-requirement-executors-wave3/inventory.json",
    ]
    prior = {
        case["planning_requirement_id"]
        for path in prior_paths
        for case in json.loads(path.read_text())["cases"]
    }
    selected = {case["planning_requirement_id"] for case in current["cases"]}
    assert len(prior) == 32
    assert selected.isdisjoint(prior)


def test_candidate_only_policy_and_zero_runtime_evidence():
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
    result = _module().build_result()
    assert all(case["runtime_evidence"] == [] for case in result["results"])


def test_executor_does_not_modify_live_ledgers():
    module = _module()
    paths = [
        HERE.parent / "acceptance_inventory.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/candidates/wave3/systems/candidate.json",
    ]
    before = [_digest(path) for path in paths]
    module.build_result()
    assert [_digest(path) for path in paths] == before


def test_tampered_baseline_lock_fails_closed(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["baseline_locks"][0]["sha256"] = "0" * 64
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="baseline lock mismatch"):
        module.build_result()


def test_tampered_planning_identity_fails_closed(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["planning_payload_sha256"] = "0" * 64
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="binding lock mismatch"):
        module.build_result()


def test_tampered_source_lock_fails_even_on_expected_mismatch(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["source_locks"][0]["sha256"] = "0" * 64
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="source .* lock mismatch"):
        module.build_result()


def test_duplicate_case_id_is_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][1]["case_id"] = inventory["cases"][0]["case_id"]
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="duplicate case_id"):
        module.build_result()


def test_duplicate_baseline_path_is_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["baseline_locks"][1]["path"] = inventory["baseline_locks"][0]["path"]
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="duplicate baseline lock path"):
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
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="unsafe repository path"):
        module.build_result()


def test_unlocked_assertion_source_is_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["sources"] = ["README.md"]
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="assertion source is not locked"):
        module.build_result()


def test_unknown_adapter_is_rejected_by_schema(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["adapter"] = "execute_shell"
    monkeypatch.setattr(module, "INVENTORY_PATH", _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="inventory schema validation"):
        module.build_result()


def test_executor_imports_no_runtime_network_or_credential_modules():
    tree = ast.parse((HERE / "executor.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {
            "subprocess",
            "socket",
            "requests",
            "httpx",
            "urllib",
            "aiohttp",
            "docker",
            "boto3",
            "os",
        }
    )


def test_executor_has_no_file_write_or_lifecycle_calls():
    tree = ast.parse((HERE / "executor.py").read_text())
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert attrs.isdisjoint(
        {
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "replace",
            "mkdir",
            "rmdir",
            "system",
            "run",
            "Popen",
        }
    )


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


def test_result_schema_rejects_incomplete_accounting():
    schema = json.loads((HERE / "result.schema.json").read_text())
    result = _module().build_result()
    result["remaining_requirement_audit"].pop()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(result)
