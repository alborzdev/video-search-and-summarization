# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from jsonschema import Draft202012Validator, FormatChecker


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "search_semantic_current_runtime_verify", PACKAGE / "verify.py"
)
assert SPEC is not None and SPEC.loader is not None
verify_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_module
SPEC.loader.exec_module(verify_module)


def _json(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text())


def test_retained_package_verifies() -> None:
    result = verify_module.verify()
    assert result["status"] == "passed"
    assert result["promotion_eligible"] is True
    assert result["http_requests"] == 44
    assert result["persistent_mutations"] == 10


def test_schema_rejects_weakened_seed_exclusion() -> None:
    schema = _json("receipt.schema.json")
    receipt = _json("runtime-receipt.json")
    receipt["semantics"]["selected_object_knn"]["seed_excluded"] = False
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt)
    )
    assert errors


def test_semantic_verifier_rejects_object_projection_drift() -> None:
    contract = _json("contract.json")
    receipt = _json("runtime-receipt.json")
    changed = copy.deepcopy(receipt)
    changed["semantics"]["append_multiple_attributes"]["object_id_hashes"][0] = "0" * 64
    with pytest.raises(verify_module.VerificationError):
        verify_module._verify_semantics(contract, changed)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"endpoint":"http://127.0.0.1:1"}',
        b'{"sensor_id":"00000000-0000-4000-8000-000000000001"}',
        b'{"query":"raw semantic text"}',
    ],
)
def test_retention_boundary_rejects_raw_material(payload: bytes) -> None:
    with pytest.raises(verify_module.VerificationError):
        verify_module._verify_retention(payload, b"{}")


def test_artifact_digest_tamper_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(verify_module.EXPECTED, "receipt", "0" * 64)
    with pytest.raises(verify_module.VerificationError):
        verify_module.verify()
