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
        "wave5_source_executor", HERE / "executor.py"
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


def _use_inventory(module, monkeypatch, path: Path) -> None:
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    monkeypatch.setattr(module, "EXPECTED_INVENTORY_SHA256", _digest(path))


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


def test_inventory_identity_is_code_locked():
    module = _module()
    assert _digest(HERE / "inventory.json") == module.EXPECTED_INVENTORY_SHA256


def test_exact_denominators_one_match_and_five_honest_mismatches():
    result = _module().build_result()
    assert result["counts"] == {
        "total_planning_requirements": 110,
        "integrated_materialized": 27,
        "live_open": 83,
        "prior_candidate_selections": 12,
        "remaining_requirements_audited": 71,
        "cases": 6,
        "observed_match": 1,
        "observed_mismatch": 5,
        "remaining_requirements_unselected": 65,
    }
    assert [
        item["case_id"]
        for item in result["results"]
        if item["outcome"] == "observed_match"
    ] == ["wave5-source-case.smartcity-minimal-map"]


def test_exact_missing_contract_tokens_are_preserved():
    results = {item["case_id"]: item for item in _module().build_result()["results"]}
    expected = {
        "wave5-source-case.smartcity-compose-surface": {
            "official-profile-identity": '["BP_PROFILE=bp_smc"]',
            "integration-surface": '["vss-agent"]',
        },
        "wave5-source-case.smartcity-behavior-config": {
            "exact-seven-anomaly-classes": '["[\\\\\\"Car\\\\\\",\\\\\\"Truck\\\\\\",\\\\\\"Bus\\\\\\",\\\\\\"Motorcycle\\\\\\",\\\\\\"Bicycle\\\\\\",\\\\\\"Scooter\\\\\\",\\\\\\"Emergency Vehicle\\\\\\"]"]'
        },
        "wave5-source-case.smartcity-verification-config": {
            "exact-resolution-and-lookback": '["760x430","lookback_seconds: 15"]'
        },
        "wave5-source-case.smartcity-custom-location": {
            "operator-media-redeploy-and-no-sample-dependency": '["operator_video","operator_rtsp","redeploy_after_change","bundled_sample_required: false"]'
        },
        "wave5-source-case.maps-secret-presence": {
            "official-google-key-and-consumers": '["ROI Refiner"]'
        },
    }
    for case_id, assertions in expected.items():
        failed = {
            item["assertion_id"]: item["detail"].removeprefix("missing=")
            for item in results[case_id]["assertions"]
            if not item["passed"]
        }
        assert failed == assertions


def test_exact_71_row_accounting_and_six_selected_rows():
    rows = _module().build_result()["remaining_requirement_audit"]
    assert len(rows) == len({row["planning_requirement_id"] for row in rows}) == 71
    assert "calibration-schema-static" not in {
        row["planning_requirement_id"] for row in rows
    }
    assert sum(row["classification"] == "selected_source_executor" for row in rows) == 6
    assert (
        sum(row["classification"] != "selected_source_executor" for row in rows) == 65
    )


def test_no_overlap_with_prior_38_cases():
    current = json.loads((HERE / "inventory.json").read_text())
    paths = [
        HERE.parent / "executor-cases/inventory.json",
        HERE.parent / "source-contract-cases/inventory.json",
        HERE.parent / "planning-requirement-executors-wave3/inventory.json",
        HERE.parent / "planning-requirement-executors-wave4/inventory.json",
    ]
    prior = {
        case["planning_requirement_id"]
        for path in paths
        for case in json.loads(path.read_text())["cases"]
    }
    selected = {case["planning_requirement_id"] for case in current["cases"]}
    assert len(prior) == 38
    assert selected.isdisjoint(prior)


def test_candidate_only_policy_and_zero_runtime_evidence():
    inventory = json.loads((HERE / "inventory.json").read_text())
    assert inventory["policies"] == {
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "network": False,
        "subprocess": False,
        "writes": False,
    }
    assert all(case["runtime_evidence"] == [] for case in inventory["cases"])
    result = _module().build_result()
    assert result["advances_live_acceptance"] is False
    assert result["runtime_evidence_added"] is False


def test_executor_does_not_modify_live_ledgers():
    paths = [
        HERE.parent / "acceptance_inventory.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/manifest.json",
    ]
    before = [_digest(path) for path in paths]
    _module().build_result()
    assert [_digest(path) for path in paths] == before


def test_tampered_baseline_planning_and_source_locks_fail_closed(tmp_path, monkeypatch):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    for field, match in [
        ("baseline", "baseline lock mismatch"),
        ("planning", "binding lock mismatch"),
        ("source", "source .* lock mismatch"),
    ]:
        inventory = json.loads(json.dumps(original))
        if field == "baseline":
            inventory["baseline_locks"][0]["sha256"] = "0" * 64
        elif field == "planning":
            inventory["cases"][0]["planning_payload_sha256"] = "0" * 64
        else:
            inventory["cases"][0]["source_locks"][0]["sha256"] = "0" * 64
        _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match=match):
            module.build_result()


def test_duplicate_case_and_unlocked_assertion_source_are_rejected(
    tmp_path, monkeypatch
):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][1]["case_id"] = inventory["cases"][0]["case_id"]
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="duplicate case_id"):
        module.build_result()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["sources"] = ["README.md"]
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(
        module.QualificationError, match="assertion source is not locked"
    ):
        module.build_result()


def test_path_traversal_and_unknown_adapter_are_rejected(tmp_path, monkeypatch):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    old = inventory["cases"][0]["source_locks"][0]["path"]
    inventory["cases"][0]["source_locks"][0]["path"] = "../outside"
    for assertion in inventory["cases"][0]["assertions"]:
        assertion["sources"] = [
            "../outside" if item == old else item for item in assertion["sources"]
        ]
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="unsafe repository path"):
        module.build_result()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["adapter"] = "execute_shell"
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="inventory schema validation"):
        module.build_result()


def test_executor_imports_and_calls_no_runtime_or_mutation_facilities():
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
            "popen",
            "run",
            "call",
        }
    )
