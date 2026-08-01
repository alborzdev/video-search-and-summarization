from __future__ import annotations

import ast
from copy import deepcopy
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
        "wave12_executor", HERE / "executor.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inventory(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _use_inventory(module, monkeypatch, path: Path) -> None:
    monkeypatch.setattr(module, "INVENTORY_PATH", path)
    monkeypatch.setattr(module, "EXPECTED_INVENTORY_SHA256", _digest(path))


def test_strict_schemas_and_raw_package_identities() -> None:
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


def test_exact_prior80_remainder30_selected6_and_remainder24_accounting() -> None:
    result = _module().build_result()
    assert result["set_digests"] == {
        "prior_80": "127fd31fa4d7cfc7b84115e08500db2d93137eda3f8160468ae371d1128648e5",
        "wave11_remaining_30": "c75592f2a54340507e4348a80fa17eb21a77f6a0e85170ffdfb05a997ed68813",
        "wave12_selected_6": "0b77dc52e1347fffd454f55519702c72a4637905ee00f868cbdce5fc760d33fe",
        "wave12_remaining_24": "ff8a6b3bfb1c308a3533ca25f05b7b84baa29d08acd699fca3920755681e151e",
    }
    assert result["counts"] == {
        "total_planning_requirements": 110,
        "integrated_materialized": 26,
        "live_open": 84,
        "prior_package_selections": 80,
        "prior_materialized_static_bindings": 26,
        "prior_live_open_candidate_selections": 54,
        "remaining_requirements_audited": 30,
        "cases": 6,
        "observed_match": 6,
        "observed_mismatch": 0,
        "negative_contracts_preserved": 0,
        "configuration_subsets": 3,
        "protocol_subsets": 3,
        "warehouse_cases_selected": 0,
        "remaining_requirements_unselected": 24,
    }


def test_exact_cases_are_required_local_disjoint_and_nonwarehouse() -> None:
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
    assert len(prior) == len(set(prior)) == 80
    assert {row[0] for row in observed.values()}.isdisjoint(prior)
    acceptance = json.loads(module.ACCEPTANCE_PATH.read_text())
    requirements = {
        row["id"]: row for row in acceptance["wave3_contracts"]["planning_requirements"]
    }
    capability_doc = json.loads(module.CAPABILITY_PATH.read_text())
    capabilities = {row["id"]: row for row in capability_doc["capabilities"]}
    assert all(
        requirements[row[0]]["package"] != "calibration-warehouse"
        and capabilities[row[1]]["acceptance_class"] == "required_local"
        for row in observed.values()
    )


def test_every_selected_requirement_and_oracle_remains_open() -> None:
    result = _module().build_result()
    assert {row["outcome"] for row in result["results"]} == {
        "static_subset_match_candidate_only"
    }
    assert all(all(row["binding_checks"].values()) for row in result["results"])
    assert all(row["runtime_evidence"] == [] for row in result["results"])
    assert all(
        row["qualification_boundary"].endswith("requirement and oracle remain open")
        for row in result["results"]
    )
    assert result["advances_live_acceptance"] is False
    assert result["runtime_evidence_added"] is False


def test_all_84_live_open_requirements_remain_unpromoted_and_evidence_empty() -> None:
    module = _module()
    acceptance = json.loads(module.ACCEPTANCE_PATH.read_text())
    requirements = acceptance["wave3_contracts"]["planning_requirements"]
    live_open = [row for row in requirements if row["materialized"] is False]
    assert len(live_open) == 84
    assert all(row["executor_ready"] is False for row in live_open)
    assert all(row["runtime_evidence"] == [] for row in live_open)


def test_remainder_audit_selects_six_local_subsets_and_preserves_boundaries() -> None:
    rows = _module().build_result()["remaining_requirement_audit"]
    selected = [row for row in rows if row["classification"].startswith("selected_")]
    warehouse = [row for row in rows if row["package"] == "calibration-warehouse"]
    external = [
        row
        for row in rows
        if row["planning_requirement_id"]
        in {
            "smartcity-dt-calibration",
            "systems-elk-gpu-external",
            "systems-remote-nim-fetch",
        }
    ]
    assert len(rows) == len({row["planning_requirement_id"] for row in rows}) == 30
    assert len(selected) == 6
    assert len(rows) - len(selected) == 24
    assert len(warehouse) == 7
    assert {row["classification"] for row in warehouse} == {
        "excluded_warehouse_requirement"
    }
    assert len(external) == 3
    assert {row["classification"] for row in external} == {
        "requires_runtime_or_external_evidence"
    }
    assert (
        sum(
            row["classification"] == "selected_static_configuration_subset"
            for row in rows
        )
        == 3
    )
    assert (
        sum(row["classification"] == "selected_static_protocol_subset" for row in rows)
        == 3
    )


def test_policy_forbids_runtime_network_docker_writes_and_warehouse() -> None:
    inventory = json.loads((HERE / "inventory.json").read_text())
    assert inventory["scope"] == "isolated_candidate_only"
    assert not any(inventory["policies"].values())
    assert all(case["runtime_evidence"] == [] for case in inventory["cases"])


def test_executor_does_not_modify_live_ledgers() -> None:
    module = _module()
    paths = [
        module.ACCEPTANCE_PATH,
        module.CAPABILITY_PATH,
        module.ORACLE_PATH,
        REPO_ROOT / "deploy/docker/thor-local/parity/manifest.json",
    ]
    before = [_digest(path) for path in paths]
    module.build_result()
    assert [_digest(path) for path in paths] == before


def test_every_baseline_and_source_lock_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    mutations = []
    for index in range(len(original["baseline_locks"])):
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
        inventory = deepcopy(original)
        mutate(inventory)
        _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match="lock mismatch"):
            module.build_result()


def test_every_binding_identity_and_evidence_class_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    for case_index in range(len(original["cases"])):
        for field in (
            "planning_payload_sha256",
            "capability_sha256",
            "contract_sha256",
            "oracle_sha256",
        ):
            inventory = deepcopy(original)
            inventory["cases"][case_index][field] = "0" * 64
            _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
            with pytest.raises(
                module.QualificationError, match="binding lock mismatch"
            ):
                module.build_result()
        inventory = deepcopy(original)
        inventory["cases"][case_index]["evidence_class"] = (
            "static_protocol_subset_only"
            if original["cases"][case_index]["evidence_class"]
            != "static_protocol_subset_only"
            else "static_configuration_subset_only"
        )
        _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match="binding set drift"):
            module.build_result()


def test_missing_token_unlocked_source_duplicate_and_warehouse_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        (
            lambda doc: doc["cases"][0].update(
                planning_requirement_id="calibration-schema-static"
            ),
            "binding set drift|Warehouse selection",
        ),
    )
    for mutate, message in mutations:
        inventory = deepcopy(original)
        mutate(inventory)
        _use_inventory(module, monkeypatch, _write_inventory(tmp_path, inventory))
        with pytest.raises(module.QualificationError, match=message):
            module.build_result()


def test_schema_extension_duplicate_json_traversal_and_symlink_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original = json.loads((HERE / "inventory.json").read_text())
    extended = deepcopy(original)
    extended["unexpected"] = True
    path = _write_inventory(tmp_path, extended)
    _use_inventory(module, monkeypatch, path)
    with pytest.raises(module.QualificationError, match="schema validation failed"):
        module.build_result()

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"x":1,"x":2}', encoding="utf-8")
    with pytest.raises(module.QualificationError, match="duplicate JSON key"):
        module._load(duplicate)

    with pytest.raises(module.QualificationError, match="unsafe repository path"):
        module._safe_repo_file("../outside")
    target = tmp_path / "target.txt"
    target.write_text("content", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(module.QualificationError, match="non-symlink"):
        module._read_regular(link, "test link")


def test_executor_ast_has_no_external_or_mutating_capabilities() -> None:
    tree = ast.parse((HERE / "executor.py").read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported.isdisjoint(
        {
            "requests",
            "httpx",
            "urllib",
            "socket",
            "subprocess",
            "docker",
            "boto3",
            "os",
            "shutil",
        }
    )
    mutating_methods = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert mutating_methods.isdisjoint(
        {
            "write_bytes",
            "write_text",
            "unlink",
            "mkdir",
            "rename",
            "replace",
            "rmdir",
        }
    )


def test_cli_returns_success_without_promoting_anything(capsys) -> None:
    module = _module()
    assert module.main(["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["observed_match"] == 6
    assert result["advances_live_acceptance"] is False
    assert result["runtime_evidence_added"] is False
