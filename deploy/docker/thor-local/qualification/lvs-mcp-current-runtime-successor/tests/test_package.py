from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest import mock

import pytest


HERE = Path(__file__).resolve().parents[1]


def _module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EXECUTOR = _module("lvs_mcp_current_runtime_executor", "executor.py")
VERIFY = _module("lvs_mcp_current_runtime_verify", "verify.py")


def test_wrong_acknowledgement_fails_before_runtime_reads() -> None:
    with mock.patch.object(EXECUTOR, "_source_hashes") as source_hashes:
        with pytest.raises(EXECUTOR.QualificationError, match="authorization_required"):
            EXECUTOR.execute("wrong")
    source_hashes.assert_not_called()


def test_contract_is_exact_and_warehouse_free() -> None:
    contract = json.loads((HERE / "contract.json").read_text())
    assert len(contract["expected_tools"]) == 13
    assert len(set(contract["expected_tools"])) == 13
    assert contract["policy"]["warehouse_sample_bundle"] == "excluded"
    assert contract["policy"]["inference_tool_calls"] == 0
    assert contract["policy"]["stream_mutations"] == 0
    assert contract["runtime"]["mcp_url"] == "http://127.0.0.1:38112/sse"
    assert contract["runtime"]["rest_origin"] == "http://127.0.0.1:38111"


def test_all_current_source_locks_match() -> None:
    contract = json.loads((HERE / "contract.json").read_text())
    observed = EXECUTOR._source_hashes(contract)
    assert observed == {row["path"]: row["sha256"] for row in contract["source_locks"]}


def test_child_program_contains_no_inference_call() -> None:
    source = EXECUTOR._child_program(
        "vss-oracle-lvs-mcp-test.mp4",
        "vss-oracle-lvs-mcp-test",
        "http://127.0.0.1:38112/sse",
    ).decode()
    for name in (
        "summarize_video",
        "generate_vlm_captions",
        "generate_captions",
        "stream_summarize",
    ):
        assert f'call("{name}"' not in source
    assert 'call("add_file"' in source
    assert 'call("delete_file"' in source


def test_verifier_rejects_raw_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    if not (HERE / "runtime-receipt.json").exists():
        pytest.skip("runtime receipt not materialized yet")
    original = VERIFY._load

    def altered(path: Path):
        raw, value = original(path)
        if path.name == "runtime-receipt.json":
            value["fixture"]["raw"] = "11111111-1111-4111-8111-111111111111"
            raw = VERIFY._canonical(value) + b"\n"
        return raw, value

    monkeypatch.setattr(VERIFY, "_load", altered)
    with pytest.raises(Exception):
        VERIFY.verify()


def test_retained_receipt_passes_when_present() -> None:
    if not (HERE / "runtime-receipt.json").exists():
        pytest.skip("runtime receipt not materialized yet")
    assert VERIFY.verify()["status"] == "passed"
