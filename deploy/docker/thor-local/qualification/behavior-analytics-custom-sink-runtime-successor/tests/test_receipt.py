from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("behavior_custom_sink_verifier", HERE / "verifier.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_receipt_is_schema_valid_source_locked_and_contract_bound() -> None:
    receipt = verifier.verify()
    assert receipt["contract_sha256"] == verifier._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [210]


def test_custom_sink_concretely_implements_the_advertised_interface() -> None:
    receipt = verifier.verify()
    assert receipt["interface"] == {
        "base_class": "Sink",
        "concrete": True,
        "implemented_methods": ["write", "write_msg", "close"],
    }


def test_batch_single_protobuf_keys_headers_and_routing_are_exercised() -> None:
    receipt = verifier.verify()
    assert receipt["batch_write"]["json_bytes_serializer"] is True
    assert receipt["batch_write"]["binary_header_preserved"] is True
    assert receipt["single_write"]["opaque_bytes_preserved"] is True
    assert receipt["protobuf_write"]["proto_bytes_serializer"] is True
    assert receipt["outputs"]["destinations"] == ["events", "incidents"]
    assert receipt["outputs"]["event_records"] == 3
    assert receipt["outputs"]["incident_records"] == 1


def test_runtime_cleanup_and_nonclaim_boundary_are_exact() -> None:
    receipt = verifier.verify()
    assert receipt["runtime"]["container"] == {
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": 0,
    }
    assert receipt["cleanup"]["disposable_container_absent"] is True
    assert receipt["cleanup"]["failures"] == []
    assert receipt["integration_boundary"]["factory_registration_claimed"] is False
