"""Offline-only tests for the future VIOS playback-remediation collector."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "systems_vios_playback_remediation_collector", HERE / "collector.py"
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


OBSERVATIONS = {
    "capture-pre-state": {
        "observation_kind": "fake_prestate",
        "service_state_digest": "a" * 64,
        "config_digest": "b" * 64,
        "non_owned_resource_digest": "c" * 64,
        "owned_resources": [],
        "target_absent": True,
    },
    "measure-vpn-upload-transport": {
        "observation_kind": "fake_transport_classification",
        "classification": "transport",
        "vpn_used": False,
        "network_used": False,
        "upload_measured": False,
    },
    "observe-incompatible-playback": {
        "observation_kind": "fake_incompatible_playback",
        "recipe_id": "tiny-bframe-failing-mp4-v1",
        "bframes": 2,
        "playback": "failed",
        "reason_code": "b_frames_not_supported",
        "retryable_without_transcode": False,
    },
    "reencode-local-fixture": {
        "observation_kind": "fake_repair_intent",
        "operation": "local_transcode",
        "input_recipe_id": "tiny-bframe-failing-mp4-v1",
        "output_recipe_id": "tiny-bframe-reference-mp4-v1",
        "target_bframes": 0,
        "target_keyint": 30,
        "preserve_source": True,
        "process_invoked": False,
    },
    "upload-remediated-fixture": {
        "observation_kind": "fake_ownership_registration",
        "namespace": "vss-oracle-behavior-vios-upload-playback-remediation",
        "resource_id": "vss-oracle-behavior-vios-upload-playback-remediation/derived-01",
        "ownership_admitted": True,
        "fake_source_identity": "1" * 64,
        "fake_derived_identity": "2" * 64,
        "derived_identity_distinct": True,
    },
    "verify-synchronized-playback": {
        "observation_kind": "fake_replay_readback",
        "recipe_id": "tiny-bframe-reference-mp4-v1",
        "playback": "ready",
        "readback": "modeled",
        "synchronized": True,
        "late_effect_window_observed": False,
    },
    "reject-wrong-encode-settings": {
        "observation_kind": "fake_adjacent_negative",
        "bframes": 1,
        "keyint": 29,
        "accepted": False,
        "reason_code": "settings_not_remediated",
    },
    "restore-owned-state": {
        "observation_kind": "fake_cleanup",
        "removed_resource_id": "vss-oracle-behavior-vios-upload-playback-remediation/derived-01",
        "only_owned_resource_removed": True,
        "config_restored": True,
        "foreign_resource_mutated": False,
    },
    "verify-postconditions": {
        "observation_kind": "fake_postcondition",
        "owned_resources_absent": True,
        "source_identity_unchanged": True,
        "service_state_digest_restored": True,
        "config_digest_restored": True,
        "non_owned_resource_digest_restored": True,
        "late_effect_window_observed": False,
    },
}


def scripted_transcript(observations=None):
    return {
        "transport_kind": "offline-test-transcript-v1",
        "observations": copy.deepcopy(observations or OBSERVATIONS),
    }


def test_plan_is_exactly_bound_and_inert():
    plan = collector.compile_plan()
    assert plan["planning_requirement_id"] == "systems-vios-playback-remediation"
    assert plan["capability_id"] == "behavior.vios.upload-playback-remediation"
    assert plan["oracle_id"] == "oracle.behavior.vios.upload-playback-remediation"
    assert plan["canonical_binding"] == {
        "canonical_oracle_index": 233,
        "canonical_oracle_sha256": "c74086cf56aa26713b1b5714bfbfabf1bfb66fa5df5eff3286bcdb010b345a44",
        "integrated_workflow_sha256": "83501e64c2080cbffc596ce2498f675137d29f1ca37c2c5adf85b6c657febfc4",
    }
    assert plan["execution_bounds"]["max_requests"] == 8
    assert plan["execution_bounds"]["max_actions"] == 9
    assert plan["runtime_actions"] == plan["runtime_requests"] == 0
    assert plan["promotion_eligible"] is False
    assert plan["fixture"]["media_materialized"] is False


def test_workflow_matches_canonical_expansion_and_owns_cleanup():
    plan = collector.compile_plan()
    assert [step["id"] for step in plan["workflow"]] == [
        "capture-pre-state",
        "measure-vpn-upload-transport",
        "observe-incompatible-playback",
        "reencode-local-fixture",
        "upload-remediated-fixture",
        "verify-synchronized-playback",
        "reject-wrong-encode-settings",
        "restore-owned-state",
        "verify-postconditions",
    ]
    assert sum(step["request_cost"] for step in plan["workflow"]) == 8
    assert plan["ownership"]["foreign_resource_policy"] == "never mutate"
    assert plan["ownership"]["ambiguous_create_policy"].startswith("fail closed")
    assert plan["cleanup"]["order"] == "lifo"


def test_default_cli_only_compiles_plan(capsys):
    assert collector.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "offline-inert-plan-only"
    assert output["runtime_actions"] == 0
    assert output["runtime_requests"] == 0


def test_cli_has_no_execute_command():
    with pytest.raises(SystemExit) as raised:
        collector.main(["execute"])
    assert raised.value.code == 2


def test_fake_simulation_is_strict_and_non_promoting():
    result = collector.simulate_fake_transport(scripted_transcript())
    assert result["status"] == "pass"
    assert result["mode"] == "offline-fake-simulation"
    assert result["runtime_actions"] == result["runtime_requests"] == 0
    assert result["simulated_actions"] == 9
    assert result["simulated_requests"] == 8
    assert result["promotion_eligible"] is False
    assert len(result["observations"]) == 9
    assert result["observations"][2]["reason_code"] == "b_frames_not_supported"
    assert result["observations"][3]["process_invoked"] is False
    assert result["observations"][4]["ownership_admitted"] is True
    assert result["observations"][6]["accepted"] is False
    assert result["observations"][7]["foreign_resource_mutated"] is False
    assert result["observations"][8]["late_effect_window_observed"] is False


@pytest.mark.parametrize(
    "transcript",
    [
        {},
        {"transport_kind": "wrong", "observations": OBSERVATIONS},
        {"transport_kind": "offline-test-transcript-v1", "observations": []},
        {"transport_kind": "offline-test-transcript-v1", "observations": {}},
    ],
)
def test_non_exact_transcript_is_rejected(transcript):
    with pytest.raises(collector.CollectorError, match="plain-data fake transcript"):
        collector.simulate_fake_transport(transcript)


def test_callback_transport_is_rejected_without_invoking_caller_code():
    class CallbackTrap:
        called = False

        def observe(self, _step):
            self.called = True
            raise AssertionError("callback must not run")

    trap = CallbackTrap()
    with pytest.raises(collector.CollectorError, match="plain-data fake transcript"):
        collector.simulate_fake_transport(trap)
    assert trap.called is False


@pytest.mark.parametrize(
    "step_id,key,bad_value",
    [
        ("capture-pre-state", "target_absent", False),
        ("measure-vpn-upload-transport", "network_used", True),
        ("observe-incompatible-playback", "bframes", 0),
        ("reencode-local-fixture", "process_invoked", True),
        ("upload-remediated-fixture", "ownership_admitted", False),
        ("verify-synchronized-playback", "late_effect_window_observed", True),
        ("reject-wrong-encode-settings", "accepted", True),
        ("restore-owned-state", "foreign_resource_mutated", True),
        ("verify-postconditions", "owned_resources_absent", False),
    ],
)
def test_fake_simulation_rejects_semantic_drift(step_id, key, bad_value):
    observations = copy.deepcopy(OBSERVATIONS)
    observations[step_id][key] = bad_value
    with pytest.raises(collector.CollectorError, match="schema violation"):
        collector.simulate_fake_transport(scripted_transcript(observations))


def test_fake_simulation_rejects_unexpected_observation_property():
    observations = copy.deepcopy(OBSERVATIONS)
    observations["verify-postconditions"]["invented_runtime_proof"] = True
    with pytest.raises(collector.CollectorError, match="schema violation"):
        collector.simulate_fake_transport(scripted_transcript(observations))


def test_locked_fixture_and_manifest_are_exact():
    contract = collector._load_contract()
    sources = collector._load_locked_sources(contract)
    fixture, digest = collector._assert_fixture(contract, sources)
    assert fixture["remediation"] == {
        "operation": "local_transcode",
        "input_recipe_id": "tiny-bframe-failing-mp4-v1",
        "output_recipe_id": "tiny-bframe-reference-mp4-v1",
        "preserve_source": True,
    }
    assert digest == "7899df8025ffc61968888d5b6a7490805794ab2cab9a3e8d24724e83eb7dfaf2"


def test_source_lock_digest_drift_fails_closed():
    contract = collector._load_contract()
    contract = copy.deepcopy(contract)
    contract["source_locks"][0]["sha256"] = "0" * 64
    with pytest.raises(collector.CollectorError, match="source lock digest drift"):
        collector._load_locked_sources(contract)


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(collector.CollectorError, match="duplicate JSON key"):
        collector._strict_json_bytes(b'{"x":1,"x":2}', "test")


def test_collector_source_has_no_live_transport_or_process_adapter():
    source = (HERE / "collector.py").read_text(encoding="utf-8")
    forbidden = [
        "import socket",
        "import subprocess",
        "from urllib",
        "import requests",
        "docker.from_env",
        "os.system(",
    ]
    assert all(token not in source for token in forbidden)
