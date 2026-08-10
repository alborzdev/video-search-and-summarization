from __future__ import annotations

import copy
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
    "rt_embed_current_runtime_builder_evidence", HERE / "build_official_evidence.py"
)
verifier = _module("rt_embed_current_runtime_verifier_evidence", HERE / "verify.py")


def test_retained_evidence_and_canonical_bindings_verify() -> None:
    result = verifier.verify()
    assert result["status"] == "passed"
    assert result["capability_ids"] == list(builder.CAPABILITY_IDS)
    assert result["capability_count"] == 4
    assert result["http_request_count"] == 43
    assert result["retained_observation_count"] == 41
    assert result["semantic_action_count"] == 4
    assert result["warehouse_sample_bundle"] is False


def test_all_official_projections_are_reproducible() -> None:
    rebuilt = builder.build()
    for capability_id, path in builder.OUTPUTS.items():
        assert json.loads(path.read_text(encoding="utf-8")) == rebuilt[capability_id]


@pytest.mark.parametrize(
    "value",
    [
        {"request_id": "dynamic"},
        {"safe": "Bearer secret"},
        {"safe": "nvapi-secret"},
        {"safe": "data:video/mp4;base64,secret"},
        {"safe": "rtsp://camera/private"},
        {"safe": "/home/nvidia/private"},
        {"prompt": "redacted"},
        {"text_input": "redacted"},
    ],
)
def test_privacy_guard_rejects_sensitive_retention(value: object) -> None:
    with pytest.raises(verifier.RTEmbedEvidenceError):
        verifier._privacy_walk(value)


def test_receipt_uses_hashes_instead_of_raw_inputs_and_vectors() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text(encoding="utf-8"))
    verifier._privacy_walk(receipt)
    assert receipt["sanitization"] == {
        "credential_values_included": False,
        "dynamic_identifiers_included": False,
        "local_paths_included": False,
        "raw_embedding_vectors_included": False,
        "raw_prompts_included": False,
        "response_bodies_included": False,
        "rtsp_urls_included": False,
    }
    assert all(
        "embeddings" not in observation for observation in receipt["observations"]
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("api_surface", "covered_operation_count"), 23),
        (("duplicate_ids", "camera_transport_status"), 200),
        (("cleanup", "complete_inventory_exact"), False),
        (("video_embeddings", "rfc2397", "vector_sha256_exact"), False),
        (("runtime_identity", "restart_count"), 1),
    ],
)
def test_receipt_verifier_rejects_semantic_drift(
    path: tuple[str, ...], value: object
) -> None:
    contract = json.loads((HERE / "contract.json").read_text(encoding="utf-8"))
    receipt = json.loads((HERE / "runtime-receipt.json").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(receipt)
    cursor = mutated
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(builder.EvidenceProjectionError):
        builder._verify_receipt(mutated, contract)
