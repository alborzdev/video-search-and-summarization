#!/usr/bin/env python3
"""Fake-only tests for the candidate-alert completion scaffold."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
COLLECTOR_PATH = HERE / "collector.py"
SPEC = importlib.util.spec_from_file_location(
    "candidate_alerts_scaffold", COLLECTOR_PATH
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


def sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fixture_pair():
    contract = collector.load_contract()
    descriptors = collector.validate_fixture_descriptors(contract)
    declared = {item["fixture_id"]: item for item in contract["fixtures"]}
    identities = []
    media = {
        "candidate-alert-positive-v1": b"fake-mp4-positive-v1",
        "candidate-alert-negative-v1": b"fake-mp4-negative-v1",
    }
    pair_shas = [item["descriptor_sha256"] for item in contract["fixtures"]]
    for descriptor in descriptors:
        item = declared[descriptor["fixture_id"]]
        identities.append(
            collector.FixtureIdentity.build(
                run_id="offline-test-run-001",
                fixture=descriptor,
                descriptor_sha256=item["descriptor_sha256"],
                media=media[descriptor["fixture_id"]],
                pair_descriptor_sha256=pair_shas,
            )
        )
    return contract, descriptors, identities


def terminal_receipt(identity, *, sink: str, verdict: str):
    correlation_id = f"correlation-{identity.fixture_id}"
    run_marker = "vss-oracle-owner-offline-test-run-001"
    base = {
        "schema_version": 1,
        "correlation_id_sha256": sha(correlation_id),
        "state": "succeeded",
        "terminal": True,
        "fixture": {
            "fixture_id": identity.fixture_id,
            "descriptor_sha256": identity.descriptor_sha256,
            "media_sha256": identity.media_sha256,
        },
        "verification": {
            "verdict": verdict,
            "response_code": 200,
            "visible_identity_token_sha256": identity.visible_identity_token_sha256,
            "result_payload_sha256": sha(f"result-{identity.fixture_id}"),
        },
        "media_fetch": {
            "fixture_server_identity_sha256": identity.fixture_server_identity_sha256,
            "capability_path_sha256": sha(identity.capability_path),
            "request_count": 2,
            "bytes_served": identity.media_bytes,
            "served_artifact_sha256": identity.media_sha256,
            "request_log_sha256": sha(f"request-log-{identity.fixture_id}"),
        },
    }
    if sink == "elasticsearch":
        base["sink"] = {
            "backend": "elasticsearch",
            "delivered": True,
            "run_marker_sha256": sha(run_marker),
            "payload_sha256": sha(f"payload-{identity.fixture_id}"),
            "index_sha256": sha("mdx-vlm-incidents-2099-01-01"),
            "document_id_sha256": sha(f"document-{identity.fixture_id}"),
            "write_result": "created",
        }
    else:
        base["sink"] = {
            "backend": "kafka",
            "delivered": True,
            "run_marker_sha256": sha(run_marker),
            "payload_sha256": sha(f"payload-{identity.fixture_id}"),
            "topic_sha256": sha("oracle-mdx-vlm-incidents"),
            "partition": 0,
            "offset": 42,
            "key_sha256": sha(correlation_id),
        }
    return base, correlation_id, run_marker


def test_default_cli_is_inert_plan_only() -> None:
    completed = subprocess.run(
        [sys.executable, str(COLLECTOR_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"mode": "offline-plan-only"' in completed.stdout
    assert '"runtime_actions": 0' in completed.stdout
    assert '"promotion_eligible": false' in completed.stdout


def test_cli_has_no_execute_command() -> None:
    completed = subprocess.run(
        [sys.executable, str(COLLECTOR_PATH), "execute"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr


def test_plan_retains_all_active_blockers() -> None:
    plan = collector.compile_plan()
    assert plan["fixture_count"] == 2
    assert plan["materialized_media_count"] == 0
    assert plan["expected_verdicts"] == ["confirmed", "rejected"]
    assert plan["kafka_is_separate_lane"] is True
    assert len(plan["active_blockers"]) == 8
    assert "late-publication-not-reversible" in plan["active_blockers"]
    assert "terminal-status-api-not-integrated" in plan["active_blockers"]
    assert "sink-receipt-not-integrated" in plan["active_blockers"]
    assert "terminal-status-api-missing" not in plan["active_blockers"]
    assert "sink-receipt-missing" not in plan["active_blockers"]


def test_exact_request_action_and_cleanup_accounting() -> None:
    contract = collector.load_contract()
    accounting = collector.validate_bound_accounting(contract)
    assert accounting == {
        "max_requests": 53,
        "max_actions": 56,
        "cleanup_reserve_requests": 6,
        "cleanup_reserve_actions": 8,
    }


def test_bound_accounting_drift_fails_closed() -> None:
    contract = collector.load_contract()
    contract["execution_bounds"]["request_accounting"]["polls"] = 39
    with pytest.raises(collector.ScaffoldError, match="bound_accounting_mismatch"):
        collector.validate_bound_accounting(contract)


def test_two_fixture_identity_is_digest_and_run_bound() -> None:
    _, descriptors, identities = fixture_pair()
    positive, negative = identities
    assert positive.fixture_id != negative.fixture_id
    assert positive.media_sha256 != negative.media_sha256
    assert positive.capability_path != negative.capability_path
    assert (
        positive.fixture_server_identity_sha256
        == negative.fixture_server_identity_sha256
    )
    assert {item["expected_verdict"] for item in descriptors} == {
        "confirmed",
        "rejected",
    }

    contract = collector.load_contract()
    declared = contract["fixtures"][0]
    changed_run = collector.FixtureIdentity.build(
        run_id="offline-test-run-002",
        fixture=descriptors[0],
        descriptor_sha256=declared["descriptor_sha256"],
        media=b"fake-mp4-positive-v1",
        pair_descriptor_sha256=[
            item["descriptor_sha256"] for item in contract["fixtures"]
        ],
    )
    assert changed_run.media_sha256 == positive.media_sha256
    assert (
        changed_run.fixture_server_identity_sha256
        != positive.fixture_server_identity_sha256
    )
    assert changed_run.capability_path != positive.capability_path


def test_fixture_identity_rejects_empty_or_oversized_metadata() -> None:
    contract, descriptors, _ = fixture_pair()
    with pytest.raises(collector.ScaffoldError, match="invalid_fixture_identity_input"):
        collector.FixtureIdentity.build(
            run_id="offline-test-run-003",
            fixture=descriptors[0],
            descriptor_sha256=contract["fixtures"][0]["descriptor_sha256"],
            media=b"",
            pair_descriptor_sha256=[
                item["descriptor_sha256"] for item in contract["fixtures"]
            ],
        )


@pytest.mark.parametrize("sink", ["elasticsearch", "kafka"])
def test_terminal_result_and_sink_receipt_schema(sink: str) -> None:
    _, descriptors, identities = fixture_pair()
    for descriptor, identity in zip(descriptors, identities, strict=True):
        receipt, correlation_id, run_marker = terminal_receipt(
            identity,
            sink=sink,
            verdict=descriptor["expected_verdict"],
        )
        collector.validate_terminal_receipt(
            receipt,
            fixture=identity,
            expected_verdict=descriptor["expected_verdict"],
            correlation_id=correlation_id,
            run_marker=run_marker,
            allowed_sink=sink,
        )


def test_failed_terminal_receipt_requires_explicit_no_delivery_receipt() -> None:
    _, _, identities = fixture_pair()
    receipt, _correlation_id, run_marker = terminal_receipt(
        identities[0], sink="elasticsearch", verdict="confirmed"
    )
    receipt["state"] = "failed"
    receipt["verification"]["verdict"] = "verification-failed"
    receipt["verification"]["response_code"] = 503
    receipt["sink"] = {
        "backend": "none",
        "delivered": False,
        "run_marker_sha256": sha(run_marker),
        "payload_sha256": sha("undelivered-payload"),
        "failure_code": "sink_delivery_failed",
    }
    collector._validate(receipt, collector._json(collector.TERMINAL_SCHEMA_PATH))

    receipt["sink"]["delivered"] = True
    with pytest.raises(collector.ScaffoldError, match="schema_validation_failed"):
        collector._validate(receipt, collector._json(collector.TERMINAL_SCHEMA_PATH))


def test_terminal_receipt_rejects_unknown_fields_and_cross_identity_drift() -> None:
    _, descriptors, identities = fixture_pair()
    receipt, correlation_id, run_marker = terminal_receipt(
        identities[0], sink="elasticsearch", verdict="confirmed"
    )
    receipt["unexpected"] = True
    with pytest.raises(collector.ScaffoldError, match="schema_validation_failed"):
        collector.validate_terminal_receipt(
            receipt,
            fixture=identities[0],
            expected_verdict=descriptors[0]["expected_verdict"],
            correlation_id=correlation_id,
            run_marker=run_marker,
            allowed_sink="elasticsearch",
        )

    receipt.pop("unexpected")
    receipt["media_fetch"]["served_artifact_sha256"] = identities[1].media_sha256
    with pytest.raises(
        collector.ScaffoldError,
        match="terminal_receipt_identity_or_semantics_mismatch",
    ):
        collector.validate_terminal_receipt(
            receipt,
            fixture=identities[0],
            expected_verdict="confirmed",
            correlation_id=correlation_id,
            run_marker=run_marker,
            allowed_sink="elasticsearch",
        )


def test_terminal_receipt_rejects_wrong_verdict_and_sink_lane() -> None:
    _, _, identities = fixture_pair()
    receipt, correlation_id, run_marker = terminal_receipt(
        identities[0], sink="elasticsearch", verdict="rejected"
    )
    with pytest.raises(
        collector.ScaffoldError,
        match="terminal_receipt_identity_or_semantics_mismatch",
    ):
        collector.validate_terminal_receipt(
            receipt,
            fixture=identities[0],
            expected_verdict="confirmed",
            correlation_id=correlation_id,
            run_marker=run_marker,
            allowed_sink="elasticsearch",
        )

    receipt, correlation_id, run_marker = terminal_receipt(
        identities[0], sink="kafka", verdict="confirmed"
    )
    with pytest.raises(
        collector.ScaffoldError,
        match="terminal_receipt_identity_or_semantics_mismatch",
    ):
        collector.validate_terminal_receipt(
            receipt,
            fixture=identities[0],
            expected_verdict="confirmed",
            correlation_id=correlation_id,
            run_marker=run_marker,
            allowed_sink="elasticsearch",
        )


def test_canonical_query_has_fixed_order_and_encoding() -> None:
    path = collector.canonical_incident_query(
        sensor_id="vss-oracle-sensor-001",
        category="vss-oracle-owner-001",
        start_time="2099-01-01T00:00:00.123Z",
    )
    assert path == (
        "/api/v1/realtime/incidents?"
        "sensor_id=vss-oracle-sensor-001&"
        "category=vss-oracle-owner-001&"
        "start_time=2099-01-01T00%3A00%3A00.123Z&limit=10&offset=0"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sensor_id", "sensor&offset=999"),
        ("category", "category/../../_all"),
        ("start_time", "2099-01-01T00:00:00Z&limit=1000"),
        ("limit", 101),
        ("offset", 1),
    ],
)
def test_query_rejects_injection_and_scope_expansion(field: str, value) -> None:
    args = {
        "sensor_id": "sensor-001",
        "category": "category-001",
        "start_time": "2099-01-01T00:00:00Z",
        "limit": 10,
        "offset": 0,
    }
    args[field] = value
    with pytest.raises(collector.ScaffoldError):
        collector.canonical_incident_query(**args)


def test_exact_ownership_and_lifo_cleanup_accounting() -> None:
    contract = collector.load_contract()
    registration = contract["ownership"]["registration_order"]
    ledger = collector.OfflineOwnershipLedger(registration)
    for resource in registration:
        ledger.register(resource, ownership_proven=True)

    actions: list[str] = []
    postconditions: list[str] = []
    records = ledger.cleanup(
        lambda resource: actions.append(resource) is None,
        lambda resource: postconditions.append(resource) is None,
    )
    expected_cleanup = contract["ownership"]["cleanup_order"]
    assert actions == expected_cleanup
    assert postconditions == expected_cleanup
    assert [record.resource_type for record in records] == expected_cleanup
    assert all(record.cleanup == "pass" for record in records)
    assert all(record.postcondition == "pass" for record in records)
    assert ledger.transitions == 8
    assert ledger.active_count == 0


def test_ownership_requires_exact_proof_and_failed_postcondition_stays_owned() -> None:
    contract = collector.load_contract()
    ledger = collector.OfflineOwnershipLedger(
        contract["ownership"]["registration_order"]
    )
    with pytest.raises(
        collector.ScaffoldError, match="ownership_registration_rejected"
    ):
        ledger.register("fixture-server", ownership_proven=False)

    ledger.register("fixture-server", ownership_proven=True)
    records = ledger.cleanup(lambda _resource: True, lambda _resource: False)
    assert records[0].cleanup == "pass"
    assert records[0].postcondition == "fail"
    assert ledger.transitions == 2
    assert ledger.active_count == 1


def test_late_publication_is_an_explicit_reversibility_blocker() -> None:
    current = collector.reversibility_assessment(
        terminal_status_observed=False,
        cancellation_available=False,
        sink_receipt_observed=False,
        exact_sink_cleanup_available=False,
    )
    assert current == {
        "promotion_eligible": False,
        "late_publication_possible": True,
        "blocker_id": "late-publication-not-reversible",
        "terminal_status_observed": False,
        "cancellation_available": False,
        "sink_receipt_observed": False,
        "exact_sink_cleanup_available": False,
    }

    hypothetical_terminal = collector.reversibility_assessment(
        terminal_status_observed=True,
        cancellation_available=False,
        sink_receipt_observed=True,
        exact_sink_cleanup_available=True,
    )
    assert hypothetical_terminal["late_publication_possible"] is False
    assert hypothetical_terminal["blocker_id"] is None
    # This package is a design scaffold, not runtime evidence.
    assert hypothetical_terminal["promotion_eligible"] is False


def test_contract_schema_rejects_promoting_or_live_mode() -> None:
    schema = collector._json(collector.CONTRACT_SCHEMA_PATH)
    for field, value in (
        ("promotion_eligible", True),
        ("default_execution_enabled", True),
        ("mode", "authorization-gated-runtime"),
    ):
        contract = collector.load_contract()
        contract[field] = value
        with pytest.raises(collector.ScaffoldError, match="schema_validation_failed"):
            collector._validate(contract, schema)
