from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_webrtc_manifest_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_compiled_receipt_is_exactly_checked_in() -> None:
    expected = compiler.build_receipt()
    actual = compiler._load(HERE / "runtime-receipt.json")
    assert actual == expected


def test_receipt_is_schema_valid_and_contract_bound() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    schema = compiler._load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == compiler._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [417]


def test_live_replay_semantics_and_cleanup_are_proven() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert receipt["live"]["decoded_frame_delta"] > 0
    assert receipt["replay"]["frames_continued_after_all_seeks"] is True
    assert receipt["replay"]["invalid_seek_status"] == 501
    assert receipt["separation"]["distinct_route_families"] is True
    assert all(receipt["cleanup"].values())


def test_sanitized_receipt_retains_no_uuid_or_session_payload() -> None:
    raw = (HERE / "runtime-receipt.json").read_text()
    assert re.search(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", raw) is None
    assert "candidate:" not in raw
    assert "mediaSessionId" not in raw
