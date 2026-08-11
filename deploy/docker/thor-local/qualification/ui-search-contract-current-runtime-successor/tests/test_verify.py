"""Offline tests for retained complete Search UI evidence."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_retained_evidence_verifies() -> None:
    result = _module("ui_search_contract_verify_test", "verify.py").verify()
    assert result["status"] == "passed"
    assert result["promotion_eligible"] is True
    assert result["browser_actions"] == 12
    assert result["persistent_mutations"] == 0


def test_official_evidence_is_exact_builder_projection() -> None:
    builder = _module("ui_search_contract_builder_test", "build_official_evidence.py")
    retained = json.loads((HERE / "official-runtime-evidence.json").read_text())
    assert retained == builder.build()


def test_critic_sort_order_tamper_is_rejected() -> None:
    module = _module("ui_search_contract_verify_sort_test", "verify.py")
    contract = json.loads((HERE / "contract.json").read_text())
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    tampered = deepcopy(receipt)
    tampered["ui_semantics"]["critic_contract"]["rendered_order"] = [
        "rejected",
        "unverified",
        "confirmed",
    ]
    with pytest.raises(module.VerificationError, match="critic ordering"):
        module._verify_semantics(contract, tampered)


def test_top_k_minimum_tamper_is_rejected() -> None:
    module = _module("ui_search_contract_verify_topk_test", "verify.py")
    contract = json.loads((HERE / "contract.json").read_text())
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    tampered = deepcopy(receipt)
    tampered["ui_semantics"]["filter_contract"]["top_k_minimum"] = 0
    with pytest.raises(module.VerificationError, match="filter contract"):
        module._verify_semantics(contract, tampered)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"endpoint":"http://127.0.0.1:1"}',
        b'{"sensor":"7f8fcbf4-9e1b-41b9-bf52-1e6ce1ca9f6c"}',
        b'{"query":"raw"}',
    ],
)
def test_retention_rejects_raw_runtime_material(payload: bytes) -> None:
    module = _module("ui_search_contract_verify_retention_test", "verify.py")
    with pytest.raises(module.VerificationError):
        module._verify_retention(payload, b"{}")


def test_cleanup_requires_exact_read_only_postcondition() -> None:
    module = _module("ui_search_contract_verify_cleanup_test", "verify.py")
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    tampered = deepcopy(receipt)
    tampered["cleanup"]["runtime_unchanged"] = False
    with pytest.raises(module.VerificationError, match="cleanup"):
        module._verify_cleanup(tampered)
