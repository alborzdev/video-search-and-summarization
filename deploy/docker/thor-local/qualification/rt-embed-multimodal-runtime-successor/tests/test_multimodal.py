from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
CONTRACT = HERE / "contract.json"
SCHEMA = HERE / "receipt.schema.json"
RECEIPT = HERE / "runtime-receipt.json"
EXECUTOR = HERE / "execute.py"
LEDGER = (
    REPO
    / "deploy/docker/thor-local/qualification/metadata-500-current-lvs-rest-runtime-successor/post-state-official-capabilities.json"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rt_embed_multimodal_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "9579b84b2d88816bf0ece6bc9f19fbbade902d76e424b9419778fe1c8c68f4a7"
    assert _sha(EXECUTOR) == "10959f5850058beb659839b3a3acc99ef7c7210a0fe893909e155b4b25d27aed"
    assert _sha(SCHEMA) == "cbc2627e0858db3789c070e86dcc6230f33219a2b6574c7472b78a1068b09987"
    assert _sha(RECEIPT) == "33e7dd3be73b5eaf33b06059842ee4d46459e7cd57daa3a2e46f3927182b5737"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == _sha(CONTRACT)


def test_default_is_inert_and_wrong_ack_is_rejected() -> None:
    plan = subprocess.run(
        [sys.executable, str(EXECUTOR)], check=True, capture_output=True, text=True
    )
    value = json.loads(plan.stdout)
    assert value["status"] == "inert_rt_embed_multimodal_plan_valid"
    assert value["writes_or_lifecycle_actions"] is False
    denied = subprocess.run(
        [sys.executable, str(EXECUTOR), "execute", "--ack", "wrong"],
        capture_output=True,
        text=True,
    )
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["status"] == "failed"


def test_source_locks_and_exact_advertised_rows() -> None:
    contract = _load(CONTRACT)
    _module()._verify_static(contract)
    ledger = _load(LEDGER)["capabilities"]
    assert [ledger[index]["id"] for index in (368, 371)] == contract["capability_ids"]
    assert ledger[368]["contract"]["advertised_literal"] == "video/image/text embedding"
    assert ledger[371]["contract"]["advertised_literal"] == "Cosmos-Embed1"


def test_all_three_modalities_and_cosmos_model_passed() -> None:
    receipt = _load(RECEIPT)
    assert receipt["model"]["embedding_dimension"] == 768
    assert receipt["model"]["cosmos_embed1_source_exact"] is True
    assert receipt["text_embedding"]["vector_dimension"] == 768
    assert receipt["image_embedding"]["inference"]["chunk_count"] == 1
    assert receipt["video_embedding"]["inference"]["chunk_count"] == 2
    assert receipt["multimodal_space"] == {
        "cross_modal_cosines_finite": True,
        "modal_vectors_distinct": True,
        "same_embedding_dimension": True,
    }
    assert all(receipt["cleanup"].values())


def test_retained_receipt_contains_no_raw_semantic_or_resource_data() -> None:
    raw = RECEIPT.read_text().casefold()
    uuid_pattern = re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
    )
    assert uuid_pattern.search(raw) is None
    for forbidden in (
        "nvapi-",
        "bearer ",
        "thor-local-multimodal-embedding-proof",
        '"embeddings"',
        '"text_input"',
        '"session_id"',
        '"request_id"',
        '"file_id"',
    ):
        assert forbidden not in raw
