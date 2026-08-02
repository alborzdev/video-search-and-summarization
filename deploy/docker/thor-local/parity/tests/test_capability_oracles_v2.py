from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import sys
from typing import Any

import pytest


PARITY = Path(__file__).resolve().parents[1]
REPO_ROOT = PARITY.parents[3]
MIGRATION = (
    REPO_ROOT / "deploy/docker/thor-local/qualification/live-metadata-500-migration"
)
sys.path.insert(0, str(PARITY))

import capability_oracles_v2 as v2  # noqa: E402


@pytest.fixture(scope="module")
def staged() -> dict[str, dict[str, Any]]:
    return {
        name: json.loads((MIGRATION / filename).read_text())
        for name, filename in {
            "plan": "post-state-capability-oracles.json",
            "ledger": "post-state-official-capabilities.json",
            "acceptance": "post-state-acceptance-inventory.json",
            "schema": "post-state-capability-oracles.schema.json",
        }.items()
    }


@pytest.fixture
def documents(staged: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return copy.deepcopy(staged)


@pytest.fixture
def skip_valid_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        v2.v1_oracles,
        "validate",
        lambda plan, ledger: {"capabilities": 289, "oracles": 289},
    )


def _candidate(plan: dict[str, Any], offset: int = 0) -> dict[str, Any]:
    return plan["oracles"][v2.PRESERVED_COUNT + offset]


def _candidate_of_kind(
    plan: dict[str, Any], ledger: dict[str, Any], kinds: set[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    for capability, oracle in zip(
        ledger["capabilities"][v2.PRESERVED_COUNT :],
        plan["oracles"][v2.PRESERVED_COUNT :],
        strict=True,
    ):
        if capability["kind"] in kinds:
            return capability, oracle
    raise AssertionError(f"no candidate with kind in {kinds}")


def test_public_api_and_checked_staged_registry(
    staged: dict[str, dict[str, Any]],
) -> None:
    assert list(inspect.signature(v2.validate).parameters) == [
        "plan",
        "ledger",
        "acceptance",
        "schema",
    ]
    assert v2.validate(staged["plan"], staged["ledger"]) == {
        "capabilities": 500,
        "oracles": 500,
        "preserved_v1": 289,
        "candidates": 211,
        "candidate_evidence": 0,
        "candidate_executor_ready": 0,
        "candidate_protocol_bindings": 23,
        "candidate_workload_bindings": 60,
    }


def test_injected_schema_and_acceptance_validate(
    staged: dict[str, dict[str, Any]],
) -> None:
    counts = v2.validate(
        staged["plan"],
        staged["ledger"],
        staged["acceptance"],
        staged["schema"],
    )
    assert counts["preserved_v1"] == 289
    assert counts["candidates"] == 211


def test_existing_v1_validator_is_invoked_for_exact_prefix(
    documents: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, Any] = {}
    original = v2.v1_oracles.validate

    def recording_validate(
        plan: dict[str, Any], ledger: dict[str, Any]
    ) -> dict[str, int]:
        observed["plan"] = plan
        observed["ledger"] = ledger
        return original(plan, ledger)

    monkeypatch.setattr(v2.v1_oracles, "validate", recording_validate)
    v2.validate(
        documents["plan"],
        documents["ledger"],
        documents["acceptance"],
        documents["schema"],
    )
    assert observed["plan"]["schema_version"] == 1
    assert len(observed["plan"]["oracles"]) == 289
    assert len(observed["ledger"]["capabilities"]) == 289


def test_mutated_v1_prefix_is_rejected_by_existing_validator(
    documents: dict[str, dict[str, Any]],
) -> None:
    documents["plan"]["oracles"][0]["profile"] = "changed-profile"
    with pytest.raises(v2.OracleV2ContractError, match="preserved v1 prefix"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )


def test_exact_order_and_nine_field_binding_are_fail_closed(
    documents: dict[str, dict[str, Any]], skip_valid_prefix: None
) -> None:
    plan = documents["plan"]
    plan["oracles"][-1], plan["oracles"][-2] = (
        plan["oracles"][-2],
        plan["oracles"][-1],
    )
    with pytest.raises(v2.OracleV2ContractError, match="500-row order"):
        v2.validate(
            plan, documents["ledger"], documents["acceptance"], documents["schema"]
        )

    plan["oracles"][-1], plan["oracles"][-2] = (
        plan["oracles"][-2],
        plan["oracles"][-1],
    )
    _candidate(plan)["ledger_binding"]["gap"] += " changed"
    with pytest.raises(v2.OracleV2ContractError, match="nine-field"):
        v2.validate(
            plan, documents["ledger"], documents["acceptance"], documents["schema"]
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.update({"origin": "live"}), "schema violation|identity"),
        (lambda row: row.update({"extra": False}), "schema violation|property set"),
        (
            lambda row: row.update({"can_promote_runtime_state": True}),
            "schema violation|promotion",
        ),
        (
            lambda row: row.update({"evidence": [{"pass": True}]}),
            "schema violation|promotion",
        ),
        (
            lambda row: row["readiness"].update({"executor_ready": True}),
            "schema violation|promotion",
        ),
        (
            lambda row: row["fixture"].update(
                {"materialization": {"path": "fixture.json"}}
            ),
            "schema violation|promotion",
        ),
        (
            lambda row: row["execution_bounds"].update({"executor": "run.py"}),
            "schema violation|activation",
        ),
    ],
)
def test_candidate_discriminator_and_nonactivation_attacks_fail(
    documents: dict[str, dict[str, Any]],
    skip_valid_prefix: None,
    mutation: Any,
    message: str,
) -> None:
    mutation(_candidate(documents["plan"]))
    with pytest.raises(v2.OracleV2ContractError, match=message):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )


def test_boundary_scenario_and_assertion_attacks_fail(
    documents: dict[str, dict[str, Any]], skip_valid_prefix: None
) -> None:
    candidate = _candidate(documents["plan"])
    candidate["execution_bounds"]["network_scope"] = "external"
    with pytest.raises(v2.OracleV2ContractError, match="schema violation|activation"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )

    candidate["execution_bounds"]["network_scope"] = "loopback_or_compose_internal"
    candidate["reviewed_scenario_ids"] = candidate["reviewed_scenario_ids"][1:]
    with pytest.raises(v2.OracleV2ContractError, match="schema violation|identity"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )

    candidate["reviewed_scenario_ids"] = [
        *documents["ledger"]["capabilities"][289]["scenario_ids"],
        candidate["oracle_id"],
    ]
    candidate["assertions"][0]["observation_id"] = "missing-observation"
    with pytest.raises(
        v2.OracleV2ContractError, match="schema violation|assertion coverage"
    ):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )


def test_protocol_and_workload_binding_attacks_fail(
    documents: dict[str, dict[str, Any]], skip_valid_prefix: None
) -> None:
    _, protocol = _candidate_of_kind(
        documents["plan"], documents["ledger"], {"protocol"}
    )
    protocol["protocol_v2_binding"]["activation_supported"] = True
    with pytest.raises(v2.OracleV2ContractError, match="schema violation|protocol"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )

    protocol["protocol_v2_binding"]["activation_supported"] = False
    _, workload = _candidate_of_kind(
        documents["plan"], documents["ledger"], {"api", "deployment"}
    )
    workload["workload_binding"]["candidate_id"] = "wrong.id"
    with pytest.raises(v2.OracleV2ContractError, match="workload"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )


def test_incomplete_acceptance_and_invalid_injected_schema_fail(
    documents: dict[str, dict[str, Any]], skip_valid_prefix: None
) -> None:
    documents["acceptance"]["coverage"]["features"][0]["scenario_ids"] = []
    with pytest.raises(v2.OracleV2ContractError, match="coverage is incomplete"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )

    documents["acceptance"] = json.loads(
        (MIGRATION / "post-state-acceptance-inventory.json").read_text()
    )
    documents["schema"]["$schema"] = "https://json-schema.org/draft/2019-09/schema"
    with pytest.raises(v2.OracleV2ContractError, match="draft 2020-12"):
        v2.validate(
            documents["plan"],
            documents["ledger"],
            documents["acceptance"],
            documents["schema"],
        )
