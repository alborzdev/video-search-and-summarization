from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
SPEC = importlib.util.spec_from_file_location(
    "nvstreamer_full_config_execute", HERE / "execute.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load(name: str):
    return json.loads((HERE / name).read_text())


def test_complete_official_contract_is_exact_and_unique() -> None:
    contract = load("fixture-contract.json")
    paths = MODULE._documented_paths(contract)
    assert len(paths) == 151
    assert contract["official_source"]["normalized_table_sha256"] == (
        "3c3378c651eaf97c00d451b46877a5643ca63166d78b06877a90e026111315af"
    )
    assert contract["section_parameter_counts"] == {
        "network": 41,
        "onvif": 9,
        "data": 54,
        "notifications": 9,
        "debug": 15,
        "overlay": 14,
        "security": 9,
    }


def test_all_documented_keys_are_consumed_by_current_parser() -> None:
    coverage = MODULE._source_parser_coverage(load("fixture-contract.json"))
    assert coverage["documented_parameter_count"] == 151
    assert coverage["parser_match_count"] == 151
    assert coverage["missing_parser_keys"] == []


def test_derived_config_is_complete_and_local_only(tmp_path: Path) -> None:
    contract = load("fixture-contract.json")
    derived = MODULE._derived_config(tmp_path / "vst_config.json", contract)
    for section, keys in contract["sections"].items():
        assert set(keys) <= set(derived[section])
    assert derived["network"]["server_domain_name"] == "127.0.0.1"
    assert derived["network"]["stunurl_list"] == ["127.0.0.1:3478"]
    assert derived["notifications"]["enable_notification"] is False
    assert derived["notifications"]["enable_notification_consumer"] is False
    assert derived["security"]["use_https"] is False
    assert derived["security"]["nv_org_id"] == ""
    assert derived["security"]["nv_ngc_key"] == ""


def test_executor_has_bounded_isolated_cleanup_contract() -> None:
    source = (HERE / "execute.py").read_text()
    for required in (
        'CONTAINER = "vss-qual-nvstreamer-full-config"',
        '"127.0.0.1:31012:31012/tcp"',
        '"127.0.0.1:31656:31656/tcp"',
        '"127.0.0.1:31656:31656/udp"',
        '"--network"',
        '"bridge"',
        '"--cap-drop"',
        '"ALL"',
        '"exact_container_inventory_restored"',
        '"exact_running_set_restored"',
        '"all_reserved_ports_released"',
        '"agent_generate_called": False',
        '"main_vios_sensor_added": False',
        '"rt_cv_stream_added": False',
    ):
        assert required in source


def test_retained_receipt_if_present() -> None:
    path = HERE / "runtime-receipt.json"
    if not path.exists():
        pytest.skip("official runtime receipt has not been retained yet")
    receipt = json.loads(path.read_text())
    assert receipt["status"] == "passed"
    assert receipt["runtime_evidence"] is True
    assert receipt["capability_results"] == {
        "configuration.nvstreamer.full-contract": "passed_current"
    }
    assert receipt["official_contract"]["explicit_runtime_parameter_count"] == 151
    assert receipt["official_contract"]["missing_runtime_parameters"] == []
    assert receipt["source_parser_coverage"]["parser_match_count"] == 151
    assert receipt["observations"]["reversible_round_trip"]["status"] == "passed"
    assert len(receipt["observations"]["configuration_readback"]["services"]) == 5
    assert receipt["observations"]["request_accounting"]["http_failure_count"] == 0
    assert receipt["cleanup"]["result"] == "passed"


def test_promoted_official_evidence_if_present() -> None:
    path = HERE / "official-runtime-evidence.json"
    if not path.exists():
        pytest.skip("official runtime evidence has not been promoted yet")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "59aa9c7c46bb8ea49398e20a7a9d109597b4115fbd33cb843a9d11bccee695e7"
    )
    evidence = json.loads(raw)
    assert evidence["result"] == "passed_current"
    assert evidence["oracle_sha256"] == (
        "c1433eab90e0d997983b9cb5a292f79f4e6a71115fca182a8b68fa696886fd7a"
    )
    assert [item["id"] for item in evidence["observations"]] == [
        "contract_identity",
        "semantic_result",
        "round_trip",
    ]
    assert all(item["result"] == "pass" for item in evidence["assertions"])
    assert evidence["cleanup"]["result"] == "pass"
