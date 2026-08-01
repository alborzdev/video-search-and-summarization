from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cpu_multimedia_ledger_successor_executor", PACKAGE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
EXECUTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXECUTOR)


def _contract() -> dict:
    return json.loads((PACKAGE / "contract.json").read_text())


def _write_contract(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value, sort_keys=True))
    return path


def test_successor_runs_twice_deterministically_and_is_schema_valid():
    first = EXECUTOR.execute()
    second = EXECUTOR.execute()
    assert first == second
    schema = json.loads((PACKAGE / "result.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(first)
    assert first["status"] == "successor_mapping_verified_non_advancing"
    assert first["predecessor"]["historical_inventory_source_lock_count"] == 125


def test_contract_and_schemas_are_strict_and_valid():
    contract = _contract()
    schema = json.loads((PACKAGE / "contract.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(contract)
    jsonschema.Draft202012Validator.check_schema(
        json.loads((PACKAGE / "result.schema.json").read_text())
    )
    extended = copy.deepcopy(contract)
    extended["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(extended)


def test_exact_87_to_86_cpu_only_partition():
    result = EXECUTOR.execute()
    assert result["predecessor"]["advertised_gap_count"] == 87
    assert result["successor"]["advertised_gap_count"] == 86
    assert result["successor"]["historical_candidate_count"] == 83
    assert result["successor"]["still_open_historical_candidate_count"] == 82
    assert result["successor"]["removed_gap_ids"] == [EXECUTOR.CPU_GAP_ID]
    assert result["successor"]["retired_to_canonical_ids"] == [
        EXECUTOR.CPU_GAP_ID
    ]
    assert result["successor"]["added_gap_ids"] == []
    assert len(result["successor"]["external_blocker_ids"]) == 4


def test_exact_predecessor_wave3_and_all_wave_tree_identities():
    result = EXECUTOR.execute()
    checks = result["predecessor"]["wave_checks"]
    assert [row["wave"] for row in checks] == list(range(1, 9))
    assert [row["case_count"] for row in checks] == EXECUTOR.WAVE_CASE_COUNTS
    assert checks[2] == {
        "wave": 3,
        "path": EXECUTOR.WAVE_PATHS[2],
        "tree_oid": "931bd3762063c3ead93310ab37b6ad871d3aa7ee",
        "inventory_sha256": (
            "0b7056eafce7686fc2b7315fef8ae491ddef03d2e52f41e7c7861247933f90ab"
        ),
        "case_count": 23,
    }
    assert result["integrity"]["predecessor_chain_verified"] is True
    assert result["integrity"]["historical_inventory_source_locks_verified"] is True


def test_all_additional_frozen_packages_are_separate_and_exact():
    result = EXECUTOR.execute()
    frozen = result["frozen_packages"]
    assert frozen["package_count"] == 17
    assert frozen["category_counts"] == {
        "wave3_candidate": 4,
        "static_integration": 2,
        "offline_tool_observation": 1,
        "planning_requirement_wave": 8,
        "parity_source_lock": 1,
        "recursive_coverage": 1,
    }
    assert frozen["embedded_source_lock_count"] == 245
    assert frozen["execution_state"] == "identity_verified_not_reexecuted"
    assert [row["id"] for row in frozen["checks"]] == EXECUTOR.FROZEN_PACKAGE_IDS
    assert [row["path"] for row in frozen["checks"]] == EXECUTOR.FROZEN_PACKAGE_PATHS
    assert all(
        row["execution_state"] == "identity_verified_not_reexecuted"
        for row in frozen["checks"]
    )


def test_frozen_receipt_inventory_and_source_lock_identities_are_reported():
    result = EXECUTOR.execute()
    checks = {row["id"]: row for row in result["frozen_packages"]["checks"]}
    assert checks["wave3-bundle"]["embedded_source_lock_count"] == 11
    assert checks["lvs-mcp-static-adapter-integration"][
        "embedded_source_lock_count"
    ] == 15
    assert checks["calibration-schema-static-integration"][
        "embedded_source_lock_count"
    ] == 10
    assert len(
        checks["calibration-schema-static-integration"]["key_artifact_sha256"]
    ) == 2
    assert checks["offline-mv3dt-tools"] == {
        "id": "offline-mv3dt-tools",
        "category": "offline_tool_observation",
        "path": "deploy/docker/thor-local/qualification/offline-mv3dt-tools",
        "tree_oid": "79f745f149d015b23e1f1943657b6c025c7b22cd",
        "key_artifact_sha256": {
            "deploy/docker/thor-local/qualification/offline-mv3dt-tools/contract.json": (
                "070d8d89c0d38e2127da53478a5f093a460cc65b6a7ec4de1a45b79c36949984"
            ),
            "deploy/docker/thor-local/qualification/offline-mv3dt-tools/execution-receipt.json": (
                "b01ae4fe7d6007ca89ce819462c44e04407ba0cedb20bb306067038091f38063"
            ),
        },
        "embedded_source_lock_count": 5,
        "execution_state": "identity_verified_not_reexecuted",
    }
    assert checks["planning-requirement-executors-wave12"][
        "embedded_source_lock_count"
    ] == 36
    assert checks["parity-source-lock"]["embedded_source_lock_count"] == 3
    assert checks["wave3-recursive-coverage"]["embedded_source_lock_count"] == 6
    assert len(checks["wave3-recursive-coverage"]["key_artifact_sha256"]) == 3
    assert result["integrity"]["frozen_package_trees_verified"] is True
    assert result["integrity"]["frozen_key_artifacts_verified"] is True
    assert result["integrity"]["frozen_embedded_source_locks_bound"] is True
    assert (
        result["integrity"][
            "frozen_embedded_source_paths_present_in_predecessor"
        ]
        is True
    )


def test_current_core_and_cpu_ledger_identity_are_exact():
    result = EXECUTOR.execute()
    assert result["successor"]["official_capability_count"] == 277
    assert result["successor"]["capability_oracle_count"] == 277
    assert result["cpu"] == {
        "gap_id": EXECUTOR.CPU_GAP_ID,
        "capability_id": EXECUTOR.CPU_CAPABILITY_ID,
        "oracle_id": EXECUTOR.CPU_ORACLE_ID,
        "acceptance_class": "required_local",
        "thor_state": "wired",
        "runtime_state": "not_qualified",
        "oracle_current_state": "open_unexecuted",
        "evidence": [],
    }


def test_policy_is_nonadvancing_and_only_local_git_subprocess_is_used():
    result = EXECUTOR.execute()
    assert result["policy"] == {
        "candidate_only": True,
        "can_mark_passed_current": False,
        "runtime_evidence": [],
        "network_allowed": False,
        "docker_allowed": False,
        "downloads_allowed": False,
        "runtime_allowed": False,
        "file_writes_allowed": False,
        "local_git_object_reads_allowed": True,
    }
    assert result["effects"] == {
        "runtime_evidence": [],
        "official_capability_effect": "none_candidate_only",
        "network_used": False,
        "docker_used": False,
        "downloads_used": False,
        "runtime_used": False,
        "file_writes_used": False,
        "subprocess_used": True,
        "subprocess_scope": "read_only_local_git_objects_only",
    }


def test_executor_source_has_no_network_docker_or_write_apis():
    source = (PACKAGE / "executor.py").read_text()
    tree = ast.parse(source)
    imports = {
        node.names[0].name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert not imports & {
        "docker",
        "httpx",
        "requests",
        "socket",
        "urllib",
        "shutil",
        "tempfile",
    }
    forbidden_attributes = {
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
    assert not {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    } & forbidden_attributes
    subprocess_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert len(subprocess_calls) == 1
    assert subprocess_calls[0].func.attr == "run"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["predecessor"].__setitem__("commit", "0" * 40),
            "predecessor commit",
        ),
        (
            lambda value: value["predecessor"]["wave_packages"][2].__setitem__(
                "tree_oid", "0" * 40
            ),
            "Wave 3 tree identity",
        ),
        (
            lambda value: value["successor"]["current_objects"][0].__setitem__(
                "sha256", "0" * 64
            ),
            "current source lock mismatch",
        ),
        (
            lambda value: value["frozen_packages"][3].__setitem__(
                "tree_oid", "0" * 40
            ),
            "frozen package tree identity drifted",
        ),
        (
            lambda value: value["frozen_packages"][4]["key_artifacts"][0].__setitem__(
                "sha256", "0" * 64
            ),
            "frozen key artifact identity drifted",
        ),
        (
            lambda value: value["frozen_packages"][13].__setitem__(
                "embedded_source_lock_count", 35
            ),
            "embedded source-lock denominator drifted",
        ),
    ],
)
def test_contract_identity_tamper_fails_closed(tmp_path, mutate, message):
    contract = _contract()
    mutate(contract)
    with pytest.raises(EXECUTOR.QualificationError, match=message):
        EXECUTOR.execute(_write_contract(tmp_path, contract))


def test_result_schema_rejects_runtime_or_promotion_tamper():
    result = EXECUTOR.execute()
    schema = json.loads((PACKAGE / "result.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for mutate in (
        lambda value: value["effects"].__setitem__("runtime_used", True),
        lambda value: value["effects"].__setitem__(
            "official_capability_effect", "passed_current"
        ),
        lambda value: value["cpu"].__setitem__("evidence", ["fabricated"]),
        lambda value: value["successor"].__setitem__("added_gap_ids", ["fake"]),
        lambda value: value["frozen_packages"].__setitem__(
            "execution_state", "reexecuted"
        ),
        lambda value: value["frozen_packages"]["checks"][0].__setitem__(
            "execution_state", "reexecuted"
        ),
    ):
        changed = copy.deepcopy(result)
        mutate(changed)
        assert list(validator.iter_errors(changed))


def test_duplicate_and_nonfinite_json_are_rejected():
    with pytest.raises(EXECUTOR.QualificationError, match="duplicate JSON key"):
        EXECUTOR._strict_json(b'{"a":1,"a":2}', "duplicate")
    with pytest.raises(EXECUTOR.QualificationError, match="non-finite"):
        EXECUTOR._strict_json(b'{"a":NaN}', "nonfinite")


def test_execution_does_not_modify_current_core_or_package_files():
    paths = [PACKAGE / name for name in ("contract.json", "executor.py")]
    paths.extend(EXECUTOR.REPO_ROOT / path for path in EXECUTOR.CORE_PATHS)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    EXECUTOR.execute()
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert after == before


def test_cli_prints_one_valid_json_document(capsys):
    assert EXECUTOR.main([]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["status"] == "successor_mapping_verified_non_advancing"
