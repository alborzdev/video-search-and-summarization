from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import time
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator


PACKAGE = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE.parents[4]
FUTURE_ORACLES = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/"
    "metadata-500-current-mv3dt-config-utils-successor/"
    "post-state-capability-oracles.json"
)


def load_executor() -> ModuleType:
    path = PACKAGE / "executor.py"
    spec = importlib.util.spec_from_file_location(
        "mv3dt_config_utils_runtime_executor_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


@pytest.fixture(scope="module")
def development_result() -> dict:
    contract = EXECUTOR.load_contract()
    return EXECUTOR.execute(contract, oracle_document=FUTURE_ORACLES, development=True)


def test_contract_schema_exact_capabilities_and_confinement() -> None:
    contract = EXECUTOR.load_contract()
    schema = EXECUTOR.strict_json(PACKAGE / "contract.schema.json")
    Draft202012Validator(schema).validate(contract)
    assert [row["capability_id"] for row in contract["capabilities"]] == (
        EXECUTOR.EXPECTED_CAPABILITIES
    )
    assert contract["policy"]["target_case_actions_per_capability"] == 7
    assert contract["policy"]["supporting_cam_generation_actions"] == {
        "tool.mv3dt.cam-info-generator": 0,
        "tool.mv3dt.pub-sub-generator": 3,
    }
    assert contract["policy"]["aggregate_bounded_capability_actions"] == 17
    assert contract["policy"]["aggregate_requests"] == 14
    assert contract["policy"]["aggregate_imported_helper_invocations"] == 6
    assert (
        contract["policy"]["aggregate_total_imported_source_function_invocations"] == 23
    )
    assert contract["policy"]["adjacent_negative_count_per_capability"] == 5
    assert contract["policy"]["warehouse_sample_bundle"] == "excluded"
    assert all(
        contract["policy"][key] is False
        for key in (
            "network_allowed",
            "docker_allowed",
            "service_lifecycle_allowed",
            "model_access_allowed",
            "downloads_allowed",
            "credentials_allowed",
        )
    )


def test_inert_default_plan_is_schema_valid_and_nonpromoting() -> None:
    result = EXECUTOR.plan(EXECUTOR.load_contract())
    Draft202012Validator(EXECUTOR.strict_json(PACKAGE / "result.schema.json")).validate(
        result
    )
    EXECUTOR.validate_result_exact(result, development=None)
    assert result["status"] == "plan"
    assert result["bindings"]["execution_oracles_executor_ready"] is False
    assert result["promotion"]["aggregate_is_promotable"] is False


def test_current_planning_rows_cannot_authorize_execution() -> None:
    with pytest.raises(EXECUTOR.EvidenceError):
        EXECUTOR.verify_bindings(
            EXECUTOR.load_contract(),
            oracle_document=None,
            require_clean=False,
            require_executor_ready=True,
        )


def test_future_rows_are_exact_executor_ready_authority() -> None:
    bindings = EXECUTOR.verify_bindings(
        EXECUTOR.load_contract(),
        oracle_document=FUTURE_ORACLES,
        require_clean=False,
        require_executor_ready=True,
    )
    assert bindings["execution_oracles_executor_ready"] is True
    assert bindings["execution_oracle_document_sha256"] == (
        "53fe977aa208cdc78604e214817dac7d3683edea4402b160b9d3cf46571b49e3"
    )


def test_native_development_execution_is_exact_and_nonpromoting(
    development_result: dict,
) -> None:
    result = development_result
    assert result["status"] == "pass"
    assert result["promotion"]["development_smoke_only"] is True
    assert result["promotion"]["aggregate_is_promotable"] is False
    assert result["promotion"]["receipt_is_runtime_evidence"] is False
    assert result["environment"]["declared_versions_match_observed"] is False
    assert result["environment"]["normative_scope"] == (
        "observed_current_thor_behavior_only"
    )
    assert result["confinement"]["bounded_capability_actions"] == 17
    assert result["confinement"]["target_case_actions"] == 14
    assert result["confinement"]["supporting_cam_generation_actions"] == 3
    assert result["confinement"]["requests"] == 14
    assert result["confinement"]["imported_helper_invocations"] == 6
    assert result["confinement"]["total_imported_source_function_invocations"] == 23
    assert result["confinement"]["imported_source_function_counts"] == {
        "cam._parse_model_args": 7,
        "cam.generate_cam_info_files": 9,
        "pub.generate_pub_sub_config": 7,
    }
    assert result["confinement"]["product_execution_deadline_seconds"] == 900
    assert all(
        result["confinement"][key] == 0
        for key in (
            "network_calls",
            "docker_calls",
            "service_lifecycle_calls",
            "model_accesses",
            "downloads",
            "warehouse_sample_accesses",
            "product_subprocess_calls",
        )
    )
    assert [row["capability_id"] for row in result["capability_results"]] == (
        EXECUTOR.EXPECTED_CAPABILITIES
    )
    for row in result["capability_results"]:
        assert row["independent_runs"] == 2
        assert row["target_case_actions"] == row["requests"] == 7
        assert (
            row["supporting_cam_generation_actions"]
            == (EXECUTOR.EXPECTED_SUPPORTING_ACTIONS[row["capability_id"]])
        )
        assert (
            row["bounded_capability_actions"]
            == EXECUTOR.EXPECTED_MAX_ACTIONS[row["capability_id"]]
        )
        assert (
            row["imported_helper_invocations"]
            == (
                EXECUTOR.EXPECTED_SUPPORTING_ARGUMENT_PARSER_CALLS[row["capability_id"]]
            )
        )
        assert (
            row["total_imported_source_function_invocations"]
            == (
                EXECUTOR.EXPECTED_IMPORTED_SOURCE_FUNCTION_INVOCATIONS[
                    row["capability_id"]
                ]
            )
        )
        assert (
            row["imported_source_function_counts"]
            == (EXECUTOR.EXPECTED_SOURCE_FUNCTION_COUNTS[row["capability_id"]])
        )
        assert (
            row["runtime_evidence_binding"]["captured_at_utc"]
            == result["captured_at_utc"]
        )
        assert len(row["adjacent_negatives"]) == 5
        assert all(case["rejected"] for case in row["adjacent_negatives"])
        assert row["run_output_sha256"][0] == row["run_output_sha256"][1]
        assert "official_receipt" not in row
        assert row["cleanup"] == {
            "namespace": EXECUTOR.EXPECTED_NAMESPACES[row["capability_id"]],
            "pre_state_captured": "absent",
            "temporary_files_only": True,
            "removed": True,
            "siblings_unchanged": True,
        }


@pytest.mark.parametrize(
    "mutation",
    [
        "top_injection",
        "delete_requests",
        "bad_bounded_actions",
        "bad_target_actions",
        "bad_supporting_actions",
        "bad_runtime_binding",
        "development_official_receipt",
        "bad_cleanup_namespace",
    ],
)
def test_deep_receipt_validation_rejects_deletion_injection_and_drift(
    development_result: dict, mutation: str
) -> None:
    value = copy.deepcopy(development_result)
    if mutation == "top_injection":
        value["unexpected"] = True
    elif mutation == "delete_requests":
        del value["capability_results"][0]["requests"]
    elif mutation == "bad_bounded_actions":
        value["capability_results"][0]["bounded_capability_actions"] = 6
    elif mutation == "bad_target_actions":
        value["capability_results"][0]["target_case_actions"] = 6
    elif mutation == "bad_supporting_actions":
        value["capability_results"][1]["supporting_cam_generation_actions"] = 2
    elif mutation == "bad_runtime_binding":
        value["capability_results"][0]["runtime_evidence_binding"][
            "executor_sha256"
        ] = "0" * 64
    elif mutation == "development_official_receipt":
        value["capability_results"][0]["official_receipt"] = {}
    elif mutation == "bad_cleanup_namespace":
        value["capability_results"][0]["cleanup"]["namespace"] = "other"
    with pytest.raises(EXECUTOR.EvidenceError):
        EXECUTOR.validate_result_exact(
            value,
            development=True,
            oracle_registry=EXECUTOR.strict_json(FUTURE_ORACLES),
        )


def test_promotable_shape_requires_two_canonical_official_receipts(
    development_result: dict,
) -> None:
    value = copy.deepcopy(development_result)
    registry = EXECUTOR.strict_json(FUTURE_ORACLES)
    future = {row["capability_id"]: row for row in registry["oracles"]}
    ledger = EXECUTOR.strict_json(
        REPO_ROOT / "deploy/docker/thor-local/parity/official-capabilities.json"
    )
    ledger_by_id = {row["id"]: row for row in ledger["capabilities"]}
    value["bindings"]["checkout_clean"] = True
    value["bindings"]["checkout_status_porcelain_sha256"] = EXECUTOR.sha_bytes(b"")
    value["promotion"]["receipt_is_runtime_evidence"] = True
    value["promotion"]["aggregate_is_promotable"] = True
    value["promotion"]["development_smoke_only"] = False
    for row in value["capability_results"]:
        capability_id = row["capability_id"]
        row["official_receipt"] = EXECUTOR._official_receipt(
            ledger_by_id[capability_id],
            future[capability_id],
            row["oracle_observations"],
            row["oracle_assertions"],
        )
        row["runtime_evidence_binding"] = EXECUTOR._runtime_evidence_binding(
            row,
            future[capability_id],
            value["bindings"],
            value["captured_at_utc"],
        )
    EXECUTOR.validate_result_exact(value, development=False, oracle_registry=registry)
    del value["capability_results"][1]["official_receipt"]
    with pytest.raises(EXECUTOR.EvidenceError):
        EXECUTOR.validate_result_exact(
            value, development=False, oracle_registry=registry
        )


def test_repo_file_rejects_symlinked_component_and_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    payload = real / "payload.json"
    payload.write_text("{}\n", encoding="utf-8")
    component = tmp_path / "component"
    component.symlink_to(real, target_is_directory=True)
    leaf = tmp_path / "leaf.json"
    leaf.symlink_to(payload)
    monkeypatch.setattr(EXECUTOR, "REPO_ROOT", tmp_path)
    with pytest.raises(EXECUTOR.EvidenceError, match="symlink component"):
        EXECUTOR.repo_file("component/payload.json")
    with pytest.raises(EXECUTOR.EvidenceError, match="symlink component"):
        EXECUTOR.repo_file("leaf.json")


def test_fixture_and_source_locks_are_current() -> None:
    contract = EXECUTOR.load_contract()
    for capability in contract["capabilities"]:
        fixture = capability["fixture_manifest"]
        assert EXECUTOR.sha_file(REPO_ROOT / fixture["path"]) == fixture["sha256"]
        for lock in capability["source_controls"]:
            assert EXECUTOR.sha_file(REPO_ROOT / lock["path"]) == lock["sha256"]


def test_product_execution_deadline_interrupts_deterministically() -> None:
    with pytest.raises(EXECUTOR.EvidenceError, match="exceeded 0.01-second deadline"):
        with EXECUTOR.product_execution_deadline(0.01):
            time.sleep(0.1)


def test_alternate_contract_cannot_be_misattributed(tmp_path: Path) -> None:
    alternate = tmp_path / "contract.json"
    alternate.write_bytes((PACKAGE / "contract.json").read_bytes())
    with pytest.raises(EXECUTOR.EvidenceError, match="canonical contract.json"):
        EXECUTOR.require_default_contract(alternate)
    mutated = copy.deepcopy(EXECUTOR.load_contract())
    mutated["policy"]["fixture_origin"] = "other"
    with pytest.raises(EXECUTOR.EvidenceError, match="in-memory contract differs"):
        EXECUTOR.verify_bindings(
            mutated,
            oracle_document=None,
            require_clean=False,
            require_executor_ready=False,
        )


def test_receipt_publication_is_exclusive_and_rejects_symlink_parent(
    tmp_path: Path,
) -> None:
    output = tmp_path / "receipt.json"
    EXECUTOR.publish_receipt_exclusive(output, "{}\n")
    assert output.read_text(encoding="utf-8") == "{}\n"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(EXECUTOR.EvidenceError, match="already exists"):
        EXECUTOR.publish_receipt_exclusive(output, "changed\n")
    real = tmp_path / "real"
    real.mkdir()
    nested = real / "nested"
    nested.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(EXECUTOR.EvidenceError, match="symlinked"):
        EXECUTOR.publish_receipt_exclusive(linked / "nested" / "receipt.json", "{}\n")
