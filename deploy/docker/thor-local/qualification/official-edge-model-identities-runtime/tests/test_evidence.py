from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = _module(
    "official_edge_model_identity_builder_evidence", HERE / "build_official_evidence.py"
)
verifier = _module(
    "official_edge_model_identity_verifier_evidence", HERE / "verify.py"
)


def test_retained_evidence_and_canonical_bindings_verify() -> None:
    result = verifier.verify()
    assert result["status"] == "passed"
    assert result["capability_ids"] == list(builder.CAPABILITY_IDS)
    assert result["capability_count"] == 2
    assert result["http_request_count"] == 6
    assert result["semantic_action_count"] == 2
    assert result["warehouse_sample_bundle"] is False


def test_both_official_projections_are_reproducible() -> None:
    rebuilt = builder.build()
    for capability_id, path in builder.OUTPUTS.items():
        assert json.loads(path.read_text(encoding="utf-8")) == rebuilt[capability_id]


@pytest.mark.parametrize(
    "value",
    [
        {"request_id": "dynamic"},
        {"safe": "Bearer secret"},
        {"safe": "nvapi-secret"},
        {"safe": "data:image/png;base64,secret"},
        {"safe": "/home/nvidia/private"},
        {"prompt": "redacted"},
    ],
)
def test_privacy_guard_rejects_sensitive_retention(value: object) -> None:
    with pytest.raises(verifier.OfficialEdgeModelEvidenceError):
        verifier._privacy_walk(value)


def test_receipt_uses_hashes_instead_of_raw_model_inputs_and_outputs() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text(encoding="utf-8"))
    verifier._privacy_walk(receipt)
    assert receipt["sanitization"] == {
        "credential_values_included": False,
        "dynamic_identifiers_included": False,
        "local_paths_included": False,
        "raw_prompts_included": False,
        "response_bodies_included": False,
    }
