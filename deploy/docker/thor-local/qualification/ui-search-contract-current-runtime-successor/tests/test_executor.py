"""Offline tests for the complete Search UI contract executor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "ui_search_contract_executor_test", HERE / "executor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plan_is_inert_and_source_locked() -> None:
    module = _module()
    contract = module._contract()
    assert module._plan(contract) == {
        "schema_version": 1,
        "package_id": module.PACKAGE_ID,
        "mode": "plan",
        "status": "ready_inert",
        "network_requests": 0,
        "persistent_mutations": 0,
        "authorization_required": True,
        "source_lock_count": 20,
        "warehouse_sample_bundle": "excluded",
    }


def test_wrong_ack_fails_before_runtime_admission() -> None:
    module = _module()
    with pytest.raises(module.QualificationError, match="authorization required"):
        module._execute(module._contract(), "wrong")


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
    assert value["persistent_mutations"] == 0
    assert value["warehouse_sample_bundle"] == "excluded"


def test_contract_requires_read_only_boundary() -> None:
    module = _module()
    contract = module._contract()
    assert contract["bounds"]["max_persistent_mutations"] == 0
    assert contract["runtime_boundary"]["vss_agent_generate_allowed"] is False
    assert contract["runtime_boundary"]["ambient_proxies_allowed"] is False
    assert "external network request" in contract["forbidden_actions"]
