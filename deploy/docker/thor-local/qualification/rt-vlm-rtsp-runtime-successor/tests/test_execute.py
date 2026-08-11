from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
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
UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("rt_vlm_rtsp_execute", EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "d68d055983a1b3a8ba971b965317e2f061090453b18895e2738299b5867a5516"
    assert _sha(SCHEMA) == "4abb1c0aea75210f262974fe288a94302bdcc3a3e0ee91f702f910e6e93454c2"
    assert _sha(RECEIPT) == "b91da01061bb02573a4cf9adfe3e1ed6d9e61b3f1b2eb17261947536cc64160f"
    assert _sha(EXECUTOR) == "7576cd569a5c506e8f88501e9aeea8a2369b1d6ce3168b3281a838054e167223"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == _sha(CONTRACT)


def test_source_locks_and_plan_are_current() -> None:
    contract = _load(CONTRACT)
    for lock in contract["source_locks"]:
        assert _sha(REPO / lock["path"]) == lock["sha256"]
    support = contract["rtsp_support"]
    assert _sha(Path(support["ffmpeg_path"])) == support["ffmpeg_sha256"]
    plan = _module()._plan(contract)
    assert plan["status"] == "ready"
    assert plan["official_indices"] == [341]
    assert plan["agent_generate_calls"] == 0
    assert plan["main_vios_stream_mutations"] == 0
    assert plan["rt_cv_stream_mutations"] == 0


def test_exact_advertised_row_binding() -> None:
    ledger = _load(LEDGER)
    row = ledger["capabilities"][341]
    assert row["id"] == "manifest-entry.rt-vlm-media.05-rtsp"
    assert row["title"] == "RTSP"
    assert row["contract"]["advertised_literal"] == "RTSP"


def test_runtime_semantics_and_exact_cleanup() -> None:
    receipt = _load(RECEIPT)
    assert receipt["status"] == "passed"
    assert receipt["budget"]["model_requests"] == 1
    assert receipt["budget"]["rt_vlm_http_requests"] == 14
    assert receipt["rtsp_support"]["codec_h264"] is True
    assert receipt["rtsp_support"]["tcp_probe_passed"] is True
    assert receipt["live_caption_sse"]["primary_markers_present"] is True
    assert receipt["live_caption_sse"]["markers_in_chronological_order"] is True
    assert receipt["non_rtsp_scheme_negative"]["http_status"] == 422
    assert receipt["cleanup"]["stream_catalog_before_count"] == 0
    assert receipt["cleanup"]["stream_catalog_after_count"] == 0
    assert receipt["cleanup"]["failures"] == []
    assert all(
        receipt["cleanup"][key] is True
        for key in (
            "stream_catalog_restored_exactly",
            "asset_statistics_restored_exactly",
            "model_inventory_restored_exactly",
            "health_contract_restored_exactly",
            "publisher_stopped",
            "support_container_absent",
            "temporary_fixture_root_absent",
            "owned_stream_absent",
        )
    )


def test_retained_receipt_is_privacy_safe() -> None:
    raw = RECEIPT.read_text()
    lowered = raw.casefold()
    assert UUID_PATTERN.search(raw) is None
    assert "rtsp://" not in lowered
    assert "nvapi-" not in lowered
    assert "bearer " not in lowered
    for forbidden in (
        '"prompt"',
        '"semantic_output"',
        '"request_id"',
        '"session_id"',
        '"sdp"',
        '"ice"',
    ):
        assert forbidden not in lowered
