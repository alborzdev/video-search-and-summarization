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
        "wave6_source_executor", HERE / "executor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inventory(tmp_path: Path, inventory: dict) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")
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


def test_inventory_has_exact_raw_identity_owned_by_executor():
    module = _module()
    assert _digest(HERE / "inventory.json") == module.EXPECTED_INVENTORY_SHA256
    assert module.EXPECTED_INVENTORY_SHA256 == (
        "bdcaf973fddf291fc35a0d27ae7a7a9414e5d62367c9100fef6d80f39d86fec7"
    )


def test_both_schemas_have_exact_raw_identities_owned_by_executor():
    module = _module()
    assert _digest(HERE / "inventory.schema.json") == (
        module.EXPECTED_INVENTORY_SCHEMA_SHA256
    )
    assert _digest(HERE / "result.schema.json") == module.EXPECTED_RESULT_SCHEMA_SHA256
    assert module.EXPECTED_INVENTORY_SCHEMA_SHA256 == (
        "a138a02b8e14759327c3b8bd1792252fd6ffc227f130df6451d9cc810ff0288f"
    )
    assert module.EXPECTED_RESULT_SCHEMA_SHA256 == (
        "d5f3ed3fe430f9d86b8cf8ef0f1170821da2885d3d3f509d46aa4ea7d68f786c"
    )


def test_exact_accounting_and_set_digests():
    result = _module().build_result()
    assert result["counts"] == {
        "total_planning_requirements": 110,
        "integrated_materialized": 27,
        "live_open": 83,
        "prior_package_selections": 44,
        "prior_materialized_static_bindings": 26,
        "prior_live_open_candidate_selections": 18,
        "remaining_requirements_audited": 65,
        "cases": 6,
        "observed_match": 6,
        "observed_mismatch": 0,
        "documented_mismatches_preserved": 5,
        "external_optional_boundaries_preserved": 1,
        "remaining_requirements_unselected": 59,
    }
    assert result["set_digests"] == {
        "prior_44": "3a6e3e23bb918167eb2359988416ec84baed1b8402f0b28103c96c28cf93560f",
        "wave5_remaining_65": "69aba6737b9d1815112d7d8d44451d6fdf07d9eefe9b54a89d46850ddc1728b7",
        "wave6_selected_6": "ebed5e3724ad9935e7068974e51b3c7fcdd0506e78e10077a95afc5752d6fcc8",
        "wave6_remaining_59": "88ec60aa61ee86e93e9ee239c008e336c2e7cafbea3940e18e778580542485c6",
    }


def test_exact_six_cases_sources_assertions_and_boundaries():
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    observed = {}
    for case in inventory["cases"]:
        observed[case["case_id"]] = {
            "binding": (
                case["planning_requirement_id"],
                case["capability_id"],
                case["boundary_status"],
            ),
            "sources": {lock["path"] for lock in case["source_locks"]},
            "assertions": {
                assertion["assertion_id"] for assertion in case["assertions"]
            },
        }
    assert observed == module.EXPECTED_CASES


def test_all_source_assertions_match_while_boundaries_remain_explicit():
    results = _module().build_result()["results"]
    assert {item["outcome"] for item in results} == {"observed_match"}
    assert all(
        assertion["passed"] and assertion["detail"] == "missing=[]"
        for item in results
        for assertion in item["assertions"]
    )
    assert (
        sum(
            item["boundary_status"] == "documented_mismatch_preserved"
            for item in results
        )
        == 5
    )
    assert (
        sum(
            item["boundary_status"] == "external_optional_boundary_preserved"
            for item in results
        )
        == 1
    )


def test_exact_65_row_audit_has_six_selected_and_fifty_nine_unselected():
    rows = _module().build_result()["remaining_requirement_audit"]
    assert len(rows) == len({row["planning_requirement_id"] for row in rows}) == 65
    assert "calibration-schema-static" not in {
        row["planning_requirement_id"] for row in rows
    }
    assert sum(row["classification"] == "selected_source_contract" for row in rows) == 6
    assert (
        sum(row["classification"] != "selected_source_contract" for row in rows) == 59
    )


def test_wave5_and_all_prior_inventories_are_locked_without_overlap():
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    baseline = {item["path"]: item["sha256"] for item in inventory["baseline_locks"]}
    wave5 = "deploy/docker/thor-local/qualification/planning-requirement-executors-wave5/inventory.json"
    assert (
        baseline[wave5]
        == "d10a511c482d80e6167b8ac3a7ed97070d758ea709a4635f3a97526c803ef942"
    )
    prior = []
    for path in module.PRIOR_INVENTORY_PATHS:
        prior.extend(
            case["planning_requirement_id"]
            for case in json.loads(path.read_text())["cases"]
        )
    current = {case["planning_requirement_id"] for case in inventory["cases"]}
    assert len(prior) == len(set(prior)) == 44
    assert current.isdisjoint(prior)


def test_candidate_only_policy_and_all_83_requirements_stay_live_open():
    inventory = json.loads((HERE / "inventory.json").read_text())
    assert inventory["policies"] == {
        "advances_live_acceptance": False,
        "runtime_evidence_added": False,
        "network": False,
        "docker": False,
        "subprocess": False,
        "writes": False,
        "lifecycle": False,
        "downloads": False,
        "credentials": False,
        "warehouse_sample_bundle_used": False,
    }
    assert all(case["runtime_evidence"] == [] for case in inventory["cases"])
    acceptance = json.loads((HERE.parent / "acceptance_inventory.json").read_text())
    open_rows = [
        row
        for row in acceptance["wave3_contracts"]["planning_requirements"]
        if row["materialized"] is False
    ]
    assert len(open_rows) == 83
    assert "calibration-schema-static" not in {row["id"] for row in open_rows}
    assert all(
        row["executor_ready"] is False and row["runtime_evidence"] == []
        for row in open_rows
    )


def test_executor_does_not_modify_shared_live_ledgers():
    paths = [
        HERE.parent / "acceptance_inventory.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/capability-oracles.json",
        REPO_ROOT / "deploy/docker/thor-local/parity/manifest.json",
    ]
    before = [_digest(path) for path in paths]
    _module().build_result()
    assert [_digest(path) for path in paths] == before


def test_every_baseline_lock_fails_closed_when_tampered(tmp_path, monkeypatch):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    for index in range(7):
        inventory = json.loads(json.dumps(original))
        inventory["baseline_locks"][index]["sha256"] = "0" * 64
        _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match="baseline lock mismatch"):
            module.build_result()


def test_every_source_lock_fails_closed_when_tampered(tmp_path, monkeypatch):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    for case_index, case in enumerate(original["cases"]):
        for source_index in range(len(case["source_locks"])):
            inventory = json.loads(json.dumps(original))
            inventory["cases"][case_index]["source_locks"][source_index]["sha256"] = (
                "0" * 64
            )
            _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
            with pytest.raises(
                module.QualificationError, match="source .* lock mismatch"
            ):
                module.build_result()


def test_binding_boundary_source_and_assertion_sets_fail_closed(tmp_path, monkeypatch):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    mutations = (
        (
            "planning",
            lambda doc: doc["cases"][0].update(planning_payload_sha256="0" * 64),
            "binding lock mismatch",
        ),
        (
            "boundary",
            lambda doc: doc["cases"][0].update(
                boundary_status="external_optional_boundary_preserved"
            ),
            "binding set drift",
        ),
        (
            "source",
            lambda doc: doc["cases"][0]["source_locks"].pop(),
            "source set drift",
        ),
        (
            "assertion",
            lambda doc: doc["cases"][0]["assertions"][0].update(assertion_id="renamed"),
            "assertion set drift",
        ),
    )
    for _label, mutate, match in mutations:
        inventory = json.loads(json.dumps(original))
        mutate(inventory)
        _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match=match):
            module.build_result()


def test_missing_expected_token_fails_explicitly_before_result_schema(
    tmp_path, monkeypatch
):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["expected"].append("not-present-anywhere")
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="source assertion mismatch"):
        module.build_result()


def test_both_schema_raw_locks_fail_closed_when_tampered(tmp_path, monkeypatch):
    module = _module()
    for attribute, filename, message in (
        (
            "INVENTORY_SCHEMA_PATH",
            "inventory.schema.json",
            "inventory schema identity drifted",
        ),
        ("RESULT_SCHEMA_PATH", "result.schema.json", "result schema identity drifted"),
    ):
        with monkeypatch.context() as scoped:
            path = tmp_path / filename
            path.write_bytes((HERE / filename).read_bytes() + b" ")
            scoped.setattr(module, attribute, path)
            with pytest.raises(module.QualificationError, match=message):
                module.build_result()


def test_unknown_adapter_fails_explicitly_even_without_schema_guard(
    tmp_path, monkeypatch
):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["cases"][0]["assertions"][0]["adapter"] = "execute_shell"
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    monkeypatch.setattr(module, "_validate_schema", lambda *_args, **_kwargs: None)
    with pytest.raises(
        module.QualificationError, match="unsupported assertion adapter"
    ):
        module.build_result()


def test_duplicate_unlocked_traversal_symlink_and_unknown_adapter_are_rejected(
    tmp_path, monkeypatch
):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())

    inventory = json.loads(json.dumps(original))
    inventory["cases"][1]["case_id"] = inventory["cases"][0]["case_id"]
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="duplicate case_id"):
        module.build_result()

    inventory = json.loads(json.dumps(original))
    inventory["cases"][0]["assertions"][0]["sources"] = ["README.md"]
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(
        module.QualificationError, match="assertion source is not locked"
    ):
        module.build_result()

    inventory = json.loads(json.dumps(original))
    inventory["cases"][0]["source_locks"][0]["path"] = "../outside"
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="source set drift"):
        module.build_result()

    target = tmp_path / "target.txt"
    target.write_text("locked", encoding="utf-8")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    with pytest.raises(module.QualificationError, match="symlinked repository path"):
        module._safe_repo_file("linked.txt")

    inventory = json.loads(json.dumps(original))
    inventory["cases"][0]["assertions"][0]["adapter"] = "execute_shell"
    _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="inventory schema validation"):
        module.build_result()


def test_duplicate_json_key_and_schema_extensions_are_rejected(tmp_path, monkeypatch):
    module = _module()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    monkeypatch.setattr(module, "INVENTORY_PATH", duplicate)
    monkeypatch.setattr(module, "EXPECTED_INVENTORY_SHA256", _digest(duplicate))
    with pytest.raises(module.QualificationError, match="duplicate JSON key"):
        module.build_result()

    schema = json.loads((HERE / "inventory.schema.json").read_text())
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(inventory)


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
