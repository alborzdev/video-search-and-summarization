from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_broker_sinks_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [208]


def test_every_advertised_output_uses_every_builtin_sink() -> None:
    receipt = verifier.verify()
    assert set(receipt["backends"]) == {"kafka", "redisStream", "mqtt"}
    assert receipt["cross_backend"]["route_count"] == 21
    for backend in receipt["backends"].values():
        assert set(backend["routes"]) == set(receipt["payload_catalog"])
        assert backend["family_count"] == 7


def test_payload_keys_headers_and_decoded_identities_are_exact() -> None:
    receipt = verifier.verify()
    for family, payload in receipt["payload_catalog"].items():
        assert payload["payload_bytes"] > 0
        assert payload["decoded_identity"]
        for backend in receipt["backends"].values():
            route = backend["routes"][family]
            assert route["payload_sha256"] == payload["payload_sha256"]
            assert route["message_key"] == payload["message_key"]
            assert route["headers_preserved"] is True


def test_exit_integrity_cleanup_and_policy_are_exact() -> None:
    receipt = verifier.verify()
    assert all(value["runtime"]["container"]["exit_code"] == 0 for value in receipt["backends"].values())
    assert all(receipt["cleanup"]["broker_records_absent"].values())
    assert receipt["cleanup"]["failures"] == []
    assert receipt["policy"]["normal_behavior_consumers_stopped"] == 0
    assert receipt["policy"]["warehouse_sample_bundle"] == "excluded"
