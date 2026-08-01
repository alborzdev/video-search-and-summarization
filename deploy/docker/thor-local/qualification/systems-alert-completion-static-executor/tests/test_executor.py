# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Adversarial tests for the isolated systems-alert static candidate."""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

LANE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "systems_alert_static_executor", LANE / "executor.py"
)
assert SPEC is not None and SPEC.loader is not None
EXECUTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXECUTOR
SPEC.loader.exec_module(EXECUTOR)


@pytest.fixture(scope="module")
def result() -> dict:
    return EXECUTOR.execute()


def test_complete_candidate_passes_without_advancing_canonical_state(
    result: dict,
) -> None:
    assert result["result"] == "candidate_static_pass_non_advancing"
    assert result["runtime_evidence"] == []
    assert result["official_capability_effect"] == "none_candidate_only"
    assert [row["canonical_state_advanced"] for row in result["bindings"]] == [
        False
    ] * 3


def test_exact_three_canonical_bindings_are_covered(result: dict) -> None:
    assert [
        (row["planning_requirement_id"], row["capability_id"])
        for row in result["bindings"]
    ] == list(EXECUTOR.EXPECTED_BINDINGS.items())


def test_every_direct_media_mode_has_success_and_ack(result: dict) -> None:
    rows = result["observations"]["workflow_modes"]
    assert [row["mode"] for row in rows] == [
        "verification",
        "context",
        "classification",
    ]
    assert all(row["verificationResponseCode"] == "200" for row in rows)
    assert all(row["sinkDelivery"]["outcome"] == "acknowledged" for row in rows)
    assert rows[0]["verdict"] == "confirmed"
    assert rows[1]["vlm_response_present"] is False
    assert rows[2]["vlm_response"] == {"label": "entry", "confidence": 0.98}


def test_nvschema_round_trips_both_messages_and_alias(result: dict) -> None:
    rows = result["observations"]["nvschema_round_trips"]
    assert [row["message"] for row in rows] == ["nv.Incident", "nv.Behavior"]
    assert all(row["round_trip"] for row in rows)
    assert rows[0]["analytics_alias_field_number"] == 7
    assert rows[0]["released_wire_name_supported"] is True


def test_terminal_receipts_do_not_overclaim(result: dict) -> None:
    persistence = result["observations"]["persistence"]
    assert {row["outcome"] for row in persistence["elastic"].values()} == {
        "acknowledged",
        "unconfirmed",
        "failed",
    }
    assert (
        persistence["kafka"]["submitted_unconfirmed"]["outcome"]
        == "submitted_unconfirmed"
    )
    assert persistence["kafka"]["failed"]["outcome"] == "failed"
    assert {
        key: row["state"] for key, row in persistence["terminal_states"].items()
    } == {
        "acknowledged": "completed",
        "failed": "failed",
        "unconfirmed": "completed",
        "submitted_unconfirmed": "completed",
    }
    assert persistence["cancel_publish_gate"]["sink_calls"] == 0


def test_all_adjacent_negatives_are_rejected(result: dict) -> None:
    rows = result["observations"]["adjacent_negatives"]
    assert [row["case_id"] for row in rows] == EXECUTOR.EXPECTED_NEGATIVES
    assert all(row["rejected"] is True for row in rows)


def test_contract_schema_rejects_unknown_fields() -> None:
    schema = json.loads((LANE / "contract.schema.json").read_text())
    value = json.loads((LANE / "contract.json").read_text())
    value["unbounded_escape_hatch"] = True
    errors = list(Draft202012Validator(schema).iter_errors(value))
    assert errors


def test_source_lock_tampering_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = deepcopy(EXECUTOR._load_contract())
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(EXECUTOR.QualificationError, match="source lock mismatch"):
        EXECUTOR._verify_source_locks(contract)


def test_policy_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = EXECUTOR._strict_json

    def drift(path: Path) -> dict:
        value = original(path)
        if path == LANE / "contract.json":
            value["policy"]["network_allowed"] = True
        return value

    monkeypatch.setattr(EXECUTOR, "_strict_json", drift)
    with pytest.raises(
        EXECUTOR.QualificationError, match="invalid contract|policy drift"
    ):
        EXECUTOR._load_contract()
