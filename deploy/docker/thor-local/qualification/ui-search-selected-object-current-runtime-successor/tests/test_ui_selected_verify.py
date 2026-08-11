"""Offline tests for retained UI Search-by-Image evidence."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("ui_search_selected_verify_test", HERE / "verify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_retained_evidence_verifies() -> None:
    result = _module().verify()
    assert result["status"] == "passed"
    assert result["promotion_eligible"] is True
    assert result["browser_actions"] == 16


def test_selected_seed_candidate_collapse_is_rejected() -> None:
    module = _module()
    contract = json.loads((HERE / "contract.json").read_text())
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    tampered = deepcopy(receipt)
    tampered["ui_semantics"]["selected_search"]["candidate_object_id_sha256"] = tampered[
        "ui_semantics"
    ]["selected_search"]["seed_object_id_sha256"]
    with pytest.raises(module.VerificationError, match="collapsed"):
        module._verify_ui_semantics(contract, tampered)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"endpoint":"http://127.0.0.1:1"}',
        b'{"sensor":"7f8fcbf4-9e1b-41b9-bf52-1e6ce1ca9f6c"}',
        b'{"query":"raw"}',
    ],
)
def test_retention_rejects_raw_runtime_material(payload: bytes) -> None:
    module = _module()
    with pytest.raises(module.VerificationError):
        module._verify_retention(payload, b"{}")


def test_cleanup_requires_two_absence_checks() -> None:
    module = _module()
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    tampered = deepcopy(receipt)
    tampered["cleanup"]["absence_checks"] = [{"behavior": 404, "raw": 404}]
    with pytest.raises(module.VerificationError, match="absence"):
        module._verify_cleanup(tampered)
