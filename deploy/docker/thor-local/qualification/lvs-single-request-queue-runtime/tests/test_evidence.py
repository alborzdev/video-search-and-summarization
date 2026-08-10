from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


executor = _module("lvs_single_request_executor", HERE / "execute.py")
verifier = _module("lvs_single_request_verifier", HERE / "verify.py")
builder = _module("lvs_single_request_builder", HERE / "build_official_evidence.py")


def test_retained_evidence_and_projection_verify() -> None:
    result = verifier.verify()
    assert result["status"] == "passed"
    assert result["capability_id"] == "runtime.lvs.single-request-queue"
    assert result["submitted_requests"] == 2
    assert result["metric_sample_count"] == 130
    assert result["http_request_count"] == 150
    assert result["semantic_action_count"] == 2


def test_official_projection_is_reproducible() -> None:
    retained = json.loads(builder.OUTPUT.read_text(encoding="utf-8"))
    assert retained == builder.build()


def test_plan_is_inert_and_exactly_bounded() -> None:
    with mock.patch.object(executor, "_derive_fixture") as mutation:
        result = executor.plan()
    mutation.assert_not_called()
    assert result["status"] == "passed"
    assert result["execution_bounds"]["max_http_requests"] == 750
    assert result["execution_bounds"]["max_semantic_actions"] == 2
    assert result["writes_or_lifecycle_actions"] is False
    assert result["warehouse_sample_bundle"] is False


def test_retained_receipt_prevents_accidental_rerun_before_commands() -> None:
    with mock.patch.object(executor, "_derive_fixture") as command:
        with pytest.raises(executor.QualificationError) as raised:
            executor.execute(executor.ACK, retain=False)
    command.assert_not_called()
    assert raised.value.code == "evidence_already_retained"


def test_official_contract_and_topology_drift_fail_closed() -> None:
    contract = json.loads((HERE / "contract.json").read_text(encoding="utf-8"))
    drifted = copy.deepcopy(contract)
    drifted["official_contract"]["batch_queue"] = "internal"
    with pytest.raises(executor.QualificationError) as raised:
        executor._verify_static(drifted)
    assert raised.value.code == "configuration_error"

    drifted = copy.deepcopy(contract)
    drifted["runtime_queue_topology"]["environment"]["VLM_BATCH_SIZE"] = "2"
    with pytest.raises(executor.QualificationError) as raised:
        executor._verify_static(drifted)
    assert raised.value.code == "configuration_error"


def test_privacy_guard_rejects_dynamic_identity_url_and_credentials() -> None:
    with pytest.raises(verifier.LvsSingleRequestEvidenceError):
        verifier._privacy_walk(
            {"safe": "00000000-0000-4000-8000-000000000099"}
        )
    with pytest.raises(verifier.LvsSingleRequestEvidenceError):
        verifier._privacy_walk({"safe": "http://127.0.0.1:38111"})
    with pytest.raises(verifier.LvsSingleRequestEvidenceError):
        verifier._privacy_walk({"safe": "Bearer secret"})
