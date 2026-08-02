from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
import pytest


HERE = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "runtime_approval_bundle_rebase_successor_test", HERE / "compiler.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def checked_contract() -> dict:
    return json.loads((HERE / "contract.json").read_text(encoding="utf-8"))


def source_context():
    checked = MODULE._checked_source_bytes()
    return MODULE._validate_bound_sources(checked)


def validate_semantics(value: dict) -> None:
    predecessor, mapping, oracle = source_context()
    MODULE._validate_semantics(value, predecessor, mapping, oracle)


def test_check_and_emit_are_deterministic_and_inert(capsys):
    assert MODULE.main(["--check"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "admitted_bundle_count": 0,
        "approval_count": 0,
        "bundle_count": 16,
        "contract_sha256": MODULE.EXPECTED_PACKAGE_HASHES["contract.json"],
        "executable_bundle_count": 0,
        "extension_bundle_count": 2,
        "inherited_bundle_count": 14,
        "ok": True,
        "receipt_count": 0,
        "runtime_evidence_count": 0,
        "warehouse_sample_bundle": "excluded",
    }
    assert MODULE.main(["--emit"]) == 0
    emitted_once = json.loads(capsys.readouterr().out)
    assert MODULE.main(["--emit"]) == 0
    emitted_twice = json.loads(capsys.readouterr().out)
    assert emitted_once == emitted_twice == checked_contract()


def test_cli_exposes_only_required_check_or_emit_modes():
    parser = MODULE._parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--check", "--emit"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--execute"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--write"])


def test_exact_inherited_prefix_and_extension_order():
    contract = MODULE._load_checked_contract()
    predecessor, _, _ = source_context()
    assert contract["bundles"][:14] == predecessor["bundles"]
    assert contract["bundles"][14:] == MODULE.EXTENSION_BUNDLES
    assert [item["id"] for item in contract["bundles"][-2:]] == [
        MODULE.INSPECTION_ID,
        MODULE.CONFIGURATION_ID,
    ]
    assert contract["predecessor"]["inherited_prefix_canonical_sha256"] == (
        MODULE._canonical_sha256(predecessor["bundles"])
    )


def test_firewall_approval_scopes_are_exact_and_noninheriting():
    contract = MODULE._load_checked_contract()
    inspection, configuration = contract["bundles"][-2:]
    assert inspection["approval_placeholder"] == (
        "<APPROVE_ONLY_READ_ONLY_PHYSICAL_INTERFACE_FIREWALL_INSPECTION>"
    )
    assert inspection["acknowledgement_token"] == (
        "I_ACCEPT_READ_ONLY_VSS_PHYSICAL_INTERFACE_FIREWALL_INSPECTION"
    )
    assert inspection["depends_on"] == []
    assert inspection["flags"] == {
        "host_inspection": True,
        "subprocess": True,
        "network": False,
        "docker": False,
        "writes": False,
        "downloads": False,
        "credentials": False,
        "lifecycle": False,
        "destructive": False,
    }
    assert configuration["approval_placeholder"] == (
        "<APPROVE_ONLY_EXACT_PHYSICAL_INTERFACE_FIREWALL_TRANSACTION>"
    )
    assert configuration["acknowledgement_token"] == (
        "I_AUTHORIZE_VSS_PHYSICAL_INTERFACE_FIREWALL_APPLY_AND_EXACT_OWNED_ROLLBACK"
    )
    assert configuration["recovery_acknowledgement_token"] == (
        "I_AUTHORIZE_VSS_PHYSICAL_INTERFACE_FIREWALL_FAILURE_RECOVERY"
    )
    assert configuration["depends_on"] == [MODULE.INSPECTION_ID]
    assert configuration["flags"] == {
        "host_inspection": True,
        "subprocess": True,
        "network": False,
        "docker": False,
        "writes": True,
        "downloads": False,
        "credentials": False,
        "lifecycle": True,
        "destructive": True,
    }
    assert contract["successor_policy"]["approval_inheritance"] is False
    assert contract["successor_policy"]["placeholder_is_not_approval"] is True


def test_unique_placeholders_tokens_and_exact_dag():
    bundles = MODULE._load_checked_contract()["bundles"]
    ids = [item["id"] for item in bundles]
    placeholders = [item["approval_placeholder"] for item in bundles]
    tokens = [
        value
        for item in bundles
        for key in ("acknowledgement_token", "recovery_acknowledgement_token")
        if (value := item.get(key)) is not None
    ]
    assert len(ids) == len(set(ids)) == 16
    assert len(placeholders) == len(set(placeholders)) == 16
    assert len(tokens) == len(set(tokens)) == 4
    positions = {bundle_id: index for index, bundle_id in enumerate(ids)}
    for bundle in bundles:
        assert len(bundle["depends_on"]) == len(set(bundle["depends_on"]))
        assert all(
            positions[dependency] < positions[bundle["id"]]
            for dependency in bundle["depends_on"]
        )


def test_zero_activation_and_warehouse_exclusion_are_strict():
    contract = MODULE._load_checked_contract()
    assert contract["authorization_state"] == {
        "approval_count": 0,
        "receipt_count": 0,
        "admitted_bundle_count": 0,
        "executable_bundle_count": 0,
        "runtime_evidence_count": 0,
    }
    assert contract["default_policy"]["approvals_granted"] is False
    assert contract["default_policy"]["warehouse_sample_bundle"] == "excluded"
    assert contract["candidate_binding"]["warehouse_sample_bundle"] == "excluded"
    assert contract["boundary"] == (
        "contract_only_no_approval_receipt_admission_execution_or_host_evidence"
    )


def test_legacy_firewall_is_explicitly_not_authorization_safe():
    boundary = MODULE._load_checked_contract()["firewall_transaction_boundary"]
    assert boundary == {
        "existing_thor_local_apply_remove_authorization_safe": False,
        "prior_table_deleted_before_replacement": True,
        "prior_table_preserved_for_exact_rollback": False,
        "failure_path_restores_exact_prior_state": False,
        "configuration_state": (
            "blocked_pending_future_transaction_executor_and_receipt_schema"
        ),
        "transaction_executor_implemented": False,
        "receipt_schema_implemented": False,
        "authorized_mutation_commands_published": False,
    }


def test_firewall_bundles_publish_no_legacy_or_mutation_commands():
    extension = MODULE._load_checked_contract()["bundles"][-2:]
    assert all("authorized_command" not in item for item in extension)
    payload = json.dumps(extension, sort_keys=True)
    assert "sudo nft" not in payload
    assert "firewall-apply" not in payload
    assert "firewall-remove" not in payload
    assert "action_command" not in payload
    assert "recovery_command" not in payload


def test_candidate_and_oracle_remain_unexecuted_and_unadmitted():
    checked = MODULE._checked_source_bytes()
    _, mapping, oracle = MODULE._validate_bound_sources(checked)
    candidate = next(
        item
        for item in mapping["mappings"]
        if item["capability_id"] == MODULE.FIREWALL_CAPABILITY_ID
    )
    assert candidate["mapping_state"] == "unmapped_scope_gap"
    assert candidate["leaf_bundle_id"] is None
    assert candidate["approval_state"] == "no_receipt_not_admitted_not_executable"
    adapter = oracle["candidate_adapters_by_capability_id"][
        MODULE.FIREWALL_CAPABILITY_ID
    ]
    assert adapter["current_state"] == "open_unexecuted"
    assert adapter["runtime_state"] == "not_qualified"
    assert adapter["can_promote_runtime_state"] is False
    assert adapter["evidence"] == []
    assert adapter["execution_bounds"]["executor"] is None


def test_mapping_activation_migration_chain_is_exact_and_inert():
    checked = MODULE._checked_source_bytes()
    _, mapping, _ = MODULE._validate_bound_sources(checked)
    mapping_locks = {
        item["path"]: item["raw_sha256"] for item in mapping["source_locks"]
    }
    activation_path = f"{MODULE.ACTIVATION_DIR}/activation-rebase.json"
    migration_path = f"{MODULE.MIGRATION_DIR}/migration.json"
    assert mapping_locks[activation_path] == MODULE.EXPECTED_SOURCE_LOCKS[
        activation_path
    ]
    activation = MODULE._strict_json(checked[activation_path], activation_path)
    migration = MODULE._strict_json(checked[migration_path], migration_path)
    assert activation["source_locks"]["migration_proof"] == {
        "path": migration_path,
        "raw_sha256": MODULE.EXPECTED_SOURCE_LOCKS[migration_path],
    }
    assert activation["candidate_boundary"]["runtime_evidence_count"] == 0
    assert activation["candidate_boundary"]["promotable_count"] == 0
    assert migration["summary"]["candidate_runtime_evidence_count"] == 0
    assert migration["summary"]["candidate_promotable_count"] == 0
    assert migration["policy"]["runtime_execution"] == "forbidden"
    assert migration["policy"]["warehouse_sample_bundle"] == "excluded"


def test_historical_contract_diff_is_provenance_only():
    contract = MODULE._load_checked_contract()
    MODULE._validate_historical_equivalence(contract)
    historical_path = f"{MODULE.HISTORICAL_DIR}/contract.json"
    historical = MODULE._strict_json(
        MODULE._repo_file(historical_path).read_bytes(), historical_path
    )
    assert contract["bundles"] == historical["bundles"]
    assert contract["default_policy"] == historical["default_policy"]
    assert contract["approval_policy"] == historical["approval_policy"]
    assert contract["successor_policy"] == historical["successor_policy"]
    assert contract["firewall_transaction_boundary"] == historical[
        "firewall_transaction_boundary"
    ]
    assert contract["authorization_state"] == historical["authorization_state"]


def test_historical_and_canonical_byte_locks_fail_closed(tmp_path, monkeypatch):
    MODULE._assert_immutable_files()
    drift = tmp_path / "drift"
    drift.write_text("drift", encoding="utf-8")
    first = next(iter(MODULE.IMMUTABLE_FILES))
    original = MODULE._repo_file
    with monkeypatch.context() as scoped:
        scoped.setattr(
            MODULE,
            "_repo_file",
            lambda relative: drift if relative == first else original(relative),
        )
        with pytest.raises(MODULE.SuccessorError, match="immutable historical"):
            MODULE._assert_immutable_files()


def test_historical_equivalence_rejects_nonprovenance_drift():
    value = copy.deepcopy(checked_contract())
    value["bundles"][-1]["depends_on"] = []
    with pytest.raises(MODULE.SuccessorError, match="historical contract semantic drift"):
        MODULE._validate_historical_equivalence(value)


def test_strict_schema_package_hashes_and_source_locks():
    contract = checked_contract()
    schema = json.loads((HERE / "contract.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(contract)
    for name, expected in MODULE.EXPECTED_PACKAGE_HASHES.items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == expected
    assert len(contract["source_locks"]) == len(MODULE.EXPECTED_SOURCE_LOCKS) == 15
    assert {item["path"]: item["sha256"] for item in contract["source_locks"]} == (
        MODULE.EXPECTED_SOURCE_LOCKS
    )
    assert set(MODULE._checked_source_bytes()) == set(MODULE.EXPECTED_SOURCE_LOCKS)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["bundles"].__setitem__(0, value["bundles"][1]),
            "inherited 14-bundle prefix drift",
        ),
        (
            lambda value: value["bundles"][-2].update(
                depends_on=[value["bundles"][0]["id"]]
            ),
            "firewall extension bundle order or content drift",
        ),
        (
            lambda value: value["bundles"][-1].update(
                approval_placeholder=value["bundles"][-2]["approval_placeholder"]
            ),
            "firewall extension bundle order or content drift",
        ),
        (
            lambda value: value["bundles"][-1].update(
                acknowledgement_token=value["bundles"][-2]["acknowledgement_token"]
            ),
            "firewall extension bundle order or content drift",
        ),
        (
            lambda value: value["authorization_state"].update(approval_count=1),
            "authorization, receipt, admission, and evidence counts must be zero",
        ),
        (
            lambda value: value["bundles"][-1]["flags"].update(network=True),
            "firewall extension bundle order or content drift",
        ),
        (
            lambda value: value["bundles"][-1].update(
                authorized_command="sudo nft delete table inet cti_vss"
            ),
            "firewall extension bundle order or content drift",
        ),
        (
            lambda value: value["firewall_transaction_boundary"].update(
                transaction_executor_implemented=True
            ),
            "firewall transaction safety boundary drift",
        ),
    ],
)
def test_adversarial_semantic_drift_fails_closed(mutate, message):
    value = copy.deepcopy(checked_contract())
    mutate(value)
    with pytest.raises(MODULE.SuccessorError, match=message):
        validate_semantics(value)


def test_schema_rejects_unknown_fields_and_false_activation_claims():
    schema = MODULE._strict_json(
        (HERE / "contract.schema.json").read_bytes(), "contract schema"
    )
    value = checked_contract()
    value["unexpected"] = True
    with pytest.raises(MODULE.SuccessorError, match="schema violation"):
        MODULE._validate_schema(value, schema, "successor contract")
    value = checked_contract()
    value["authorization_state"]["receipt_count"] = 1
    with pytest.raises(MODULE.SuccessorError, match="schema violation"):
        MODULE._validate_schema(value, schema, "successor contract")


def test_duplicate_nonfinite_package_and_source_drift_fail(tmp_path, monkeypatch):
    with pytest.raises(MODULE.SuccessorError, match="duplicate JSON key"):
        MODULE._strict_json(b'{"schema_version":1,"schema_version":1}', "duplicate")
    with pytest.raises(MODULE.SuccessorError, match="non-finite"):
        MODULE._strict_json(b'{"value":NaN}', "nan")
    with monkeypatch.context() as scoped:
        scoped.setitem(MODULE.EXPECTED_PACKAGE_HASHES, "contract.json", "0" * 64)
        with pytest.raises(MODULE.SuccessorError, match="package identity drift"):
            MODULE._load_checked_contract()
    drift = tmp_path / "drift"
    drift.write_text("drift", encoding="utf-8")
    first = next(iter(MODULE.EXPECTED_SOURCE_LOCKS))
    original = MODULE._repo_file
    with monkeypatch.context() as scoped:
        scoped.setattr(
            MODULE,
            "_repo_file",
            lambda relative: drift if relative == first else original(relative),
        )
        with pytest.raises(MODULE.SuccessorError, match="source lock mismatch"):
            MODULE._checked_source_bytes()


def test_symlinked_sources_and_package_artifacts_fail_closed(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.write_text("content", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with monkeypatch.context() as scoped:
        scoped.setattr(MODULE, "REPO_ROOT", tmp_path)
        with pytest.raises(MODULE.SuccessorError, match="symlinked repository path"):
            MODULE._repo_file("link")
    with monkeypatch.context() as scoped:
        scoped.setattr(MODULE, "HERE", tmp_path)
        with pytest.raises(MODULE.SuccessorError, match="non-symlink"):
            MODULE._package_file("link")


def test_compiler_has_no_action_network_write_or_execute_surface():
    tree = ast.parse((HERE / "compiler.py").read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports.intersection(
        {
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "docker",
            "shutil",
            "tempfile",
            "os",
        }
    )
    attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not attributes.intersection(
        {
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "mkdir",
            "rmdir",
            "link",
            "symlink_to",
            "run",
            "Popen",
            "request",
            "urlopen",
            "system",
        }
    )
    parser_source = (HERE / "compiler.py").read_text(encoding="utf-8")
    assert '"--check"' in parser_source and '"--emit"' in parser_source
    assert '"--execute"' not in parser_source and '"--write"' not in parser_source
