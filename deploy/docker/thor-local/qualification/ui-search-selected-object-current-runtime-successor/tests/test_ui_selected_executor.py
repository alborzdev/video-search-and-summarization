"""Offline tests for the bounded UI selected-object qualification executor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("ui_search_selected_executor_test", HERE / "executor.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plan_is_inert_and_source_locked() -> None:
    module = _module()
    contract = module._contract()
    plan = module._plan(contract)
    assert plan == {
        "schema_version": 1,
        "package_id": module.PACKAGE_ID,
        "mode": "plan",
        "status": "ready_inert",
        "network_requests": 0,
        "persistent_mutations": 0,
        "authorization_required": True,
        "source_lock_count": 16,
        "warehouse_sample_bundle": "excluded",
    }


def test_wrong_ack_fails_before_runtime_admission() -> None:
    module = _module()
    with pytest.raises(module.QualificationError, match="authorization_required"):
        module._execute(module._contract(), "offline-test", "wrong")


def test_owned_object_ids_are_stable_distinct_and_plain() -> None:
    module = _module()
    first = module._make_object_ids("offline-test")
    second = module._make_object_ids("offline-test")
    assert first == second
    assert first[0] != first[1]
    assert all(value.isdigit() and 910000 <= int(value) < 990000 for value in first)


def test_bbox_match_is_exact() -> None:
    module = _module()
    expected = [1, 2, 3, 4]
    assert module._bbox_matches(
        {"leftX": 1, "topY": 2, "rightX": 3, "bottomY": 4}, expected
    )
    assert not module._bbox_matches(
        {"leftX": 1, "topY": 2, "rightX": 3, "bottomY": 5}, expected
    )


def test_harness_plan_is_inert() -> None:
    completed = subprocess.run(
        ["/usr/bin/node", str(HERE / "harness.mjs"), "plan"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    value = json.loads(completed.stdout)
    assert value["status"] == "ready_inert"
    assert value["persistent_mutation"] is False
    assert value["warehouse_sample_bundle"] == "excluded"
