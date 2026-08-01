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
        "wave8_executor", HERE / "executor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _use(module, monkeypatch, path: Path) -> None:
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    monkeypatch.setattr(module, "EXPECTED_INVENTORY_SHA256", _digest(path))


def test_strict_schemas_and_exact_raw_identities():
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    result = module.build_result()
    for filename, instance, expected in (
        ("inventory.schema.json", inventory, module.EXPECTED_INVENTORY_SCHEMA_SHA256),
        ("result.schema.json", result, module.EXPECTED_RESULT_SCHEMA_SHA256),
    ):
        path = HERE / filename
        schema = json.loads(path.read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(instance)
        assert _digest(path) == expected
    assert _digest(HERE / "inventory.json") == module.EXPECTED_INVENTORY_SHA256


def test_exact_denominator_sets_and_accounting():
    result = _module().build_result()
    assert result["set_digests"] == {
        "prior_56": "0974fe61e1f67d4b4b766e7c56c65c5a65e02e8ae98da585bb00e999bc126315",
        "wave7_remaining_54": "cae70bf8d08a7cf01ddd583e3b20821d1e18678a95418ce4503d7edcb07bf050",
        "wave8_selected_6": "0ab0a6a768ab6b9d89c24404f9d1695d689fa600bef3a2570ff630ecb4018d16",
        "wave8_remaining_48": "e110cc91283d37dd8f789ffef55045dc97bbbadf4ff5eadc9d69532357be97d5",
    }
    assert result["counts"] == {
        "total_planning_requirements": 110,
        "integrated_materialized": 26,
        "live_open": 84,
        "prior_package_selections": 56,
        "prior_materialized_static_bindings": 26,
        "prior_live_open_candidate_selections": 30,
        "remaining_requirements_audited": 54,
        "cases": 6,
        "observed_match": 6,
        "observed_mismatch": 0,
        "negative_contracts_preserved": 6,
        "configuration_subsets": 0,
        "protocol_subsets": 0,
        "remaining_requirements_unselected": 48,
    }


def test_exact_cases_are_disjoint_from_all_predecessors():
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    observed = {
        case["case_id"]: (
            case["planning_requirement_id"],
            case["capability_id"],
            case["evidence_class"],
        )
        for case in inventory["cases"]
    }
    assert observed == module.EXPECTED_CASES
    prior = [
        case["planning_requirement_id"]
        for path in module.PRIOR_INVENTORY_PATHS
        for case in json.loads(path.read_text())["cases"]
    ]
    assert len(prior) == len(set(prior)) == 56
    assert set(observed_case[0] for observed_case in observed.values()).isdisjoint(
        prior
    )


def test_all_sources_and_bindings_match_but_every_requirement_and_oracle_stays_open():
    result = _module().build_result()
    assert {row["outcome"] for row in result["results"]} == {
        "source_subset_match_candidate_only"
    }
    assert all(all(row["binding_checks"].values()) for row in result["results"])
    assert all(
        check["sha256_match"]
        for row in result["results"]
        for check in row["source_checks"]
    )
    assert all(
        item["passed"] and item["detail"] == "missing=[]"
        for row in result["results"]
        for item in row["assertions"]
    )
    assert all(row["runtime_evidence"] == [] for row in result["results"])
    acceptance = json.loads((HERE.parent / "acceptance_inventory.json").read_text())
    open_rows = [
        row
        for row in acceptance["wave3_contracts"]["planning_requirements"]
        if row["materialized"] is False
    ]
    assert len(open_rows) == 84
    assert all(
        row["executor_ready"] is False and row["runtime_evidence"] == []
        for row in open_rows
    )


def test_fifty_four_row_audit_has_six_negative_cases_and_48_unselected():
    rows = _module().build_result()["remaining_requirement_audit"]
    selected = [row for row in rows if row["classification"].startswith("selected_")]
    assert len(rows) == len({row["planning_requirement_id"] for row in rows}) == 54
    assert len(selected) == 6
    assert len(rows) - len(selected) == 48
    assert (
        sum(
            row["classification"] == "selected_static_negative_contract" for row in rows
        )
        == 6
    )
    assert (
        sum(
            row["classification"] == "selected_static_configuration_subset"
            for row in rows
        )
        == 0
    )
    assert (
        sum(row["classification"] == "selected_static_protocol_subset" for row in rows)
        == 0
    )


def test_policy_excludes_runtime_network_docker_credentials_downloads_and_warehouse():
    inventory = json.loads((HERE / "inventory.json").read_text())
    assert inventory["scope"] == "isolated_candidate_only"
    assert not any(inventory["policies"].values())
    assert all(case["runtime_evidence"] == [] for case in inventory["cases"])


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


def test_every_baseline_and_source_lock_fails_closed(tmp_path, monkeypatch):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    mutations = []
    for index in range(10):
        mutations.append(
            lambda doc, index=index: doc["baseline_locks"][index].update(
                sha256="0" * 64
            )
        )
    for case_index, case in enumerate(original["cases"]):
        for source_index in range(len(case["source_locks"])):
            mutations.append(
                lambda doc, case_index=case_index, source_index=source_index: doc[
                    "cases"
                ][case_index]["source_locks"][source_index].update(sha256="0" * 64)
            )
    for mutate in mutations:
        inventory = json.loads(json.dumps(original))
        mutate(inventory)
        _use(module, monkeypatch, _write(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match="lock mismatch"):
            module.build_result()


def test_every_binding_identity_and_evidence_class_fails_closed(tmp_path, monkeypatch):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    for case_index in range(len(original["cases"])):
        for field in (
            "planning_payload_sha256",
            "capability_sha256",
            "contract_sha256",
            "oracle_sha256",
        ):
            inventory = json.loads(json.dumps(original))
            inventory["cases"][case_index][field] = "0" * 64
            _use(module, monkeypatch, _write(tmp_path, inventory))
            with pytest.raises(
                module.QualificationError, match="binding lock mismatch"
            ):
                module.build_result()
        inventory = json.loads(json.dumps(original))
        inventory["cases"][case_index][
            "evidence_class"
        ] = "static_configuration_subset_only"
        _use(module, monkeypatch, _write(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match="binding set drift"):
            module.build_result()


def test_missing_token_unlocked_source_and_duplicate_case_fail_closed(
    tmp_path, monkeypatch
):
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    mutations = (
        (
            lambda doc: doc["cases"][0]["assertions"][0]["expected"].append(
                "absent-token"
            ),
            "source assertion mismatch",
        ),
        (
            lambda doc: doc["cases"][0]["assertions"][0].update(sources=["README.md"]),
            "assertion source is not locked",
        ),
        (
            lambda doc: doc["cases"][1].update(case_id=doc["cases"][0]["case_id"]),
            "duplicate case_id",
        ),
    )
    for mutate, message in mutations:
        inventory = json.loads(json.dumps(original))
        mutate(inventory)
        _use(module, monkeypatch, _write(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match=message):
            module.build_result()


def test_schema_extension_duplicate_json_traversal_and_symlink_are_rejected(
    tmp_path, monkeypatch
):
    module = _module()
    inventory = json.loads((HERE / "inventory.json").read_text())
    inventory["unexpected"] = True
    _use(module, monkeypatch, _write(tmp_path, inventory))
    with pytest.raises(module.QualificationError, match="inventory schema validation"):
        module.build_result()
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(module.QualificationError, match="duplicate JSON key"):
        module._load(duplicate)
    with pytest.raises(module.QualificationError, match="unsafe repository path"):
        module._safe_repo_file("../outside")
    target = tmp_path / "target"
    target.write_text("x", encoding="utf-8")
    (tmp_path / "link").symlink_to(target)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    with pytest.raises(module.QualificationError, match="symlinked repository path"):
        module._safe_repo_file("link")


def test_schema_raw_locks_fail_closed(tmp_path, monkeypatch):
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


def test_executor_ast_has_no_mutation_network_subprocess_or_dynamic_execution():
    tree = ast.parse((HERE / "executor.py").read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(
        {
            "builtins",
            "httpx",
            "os",
            "requests",
            "shutil",
            "socket",
            "subprocess",
            "tempfile",
            "urllib",
        }
    )
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called.intersection({"open", "exec", "eval", "compile", "__import__"})
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attributes.intersection(
        {
            "chmod",
            "hardlink_to",
            "link_to",
            "mkdir",
            "open",
            "rename",
            "replace",
            "rmdir",
            "symlink_to",
            "touch",
            "unlink",
            "write_bytes",
            "write_text",
        }
    )
