from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]
CONTRACT = HERE / "contract.json"
SCHEMA = HERE / "receipt.schema.json"
RECEIPT = HERE / "runtime-receipt.json"
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
    spec = importlib.util.spec_from_file_location("rt_vlm_http_s_execute", HERE / "execute.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_artifact_hashes_and_schema() -> None:
    assert _sha(CONTRACT) == "575b553962a2bd7f1386d6308f9ce1b5e6a066d2c5ef35441f21a3af6b91f7af"
    assert _sha(SCHEMA) == "466c851fe84b50ba55bc35c7785e8f99c6078d219ce175c92391b708ade2971b"
    assert _sha(RECEIPT) == "70939dab6695c5e93e091c68ed1c30840555faf2450c39c3abd8fc3309a90d92"
    schema = _load(SCHEMA)
    receipt = _load(RECEIPT)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)


def test_source_locks_and_plan_are_current() -> None:
    contract = _load(CONTRACT)
    for lock in contract["source_locks"]:
        assert _sha(REPO / lock["path"]) == lock["sha256"]
    plan = _module()._plan(contract)
    assert plan["status"] == "ready"
    assert plan["official_indices"] == [337]
    assert plan["agent_generate_calls"] == 0
    assert plan["stream_mutations"] == 0


def test_exact_advertised_row_binding() -> None:
    ledger = _load(LEDGER)
    row = ledger["capabilities"][337]
    assert row["id"] == "manifest-entry.rt-vlm-media.01-http-s"
    assert row["title"] == "HTTP/S"


def test_runtime_transport_semantics_and_cleanup() -> None:
    receipt = _load(RECEIPT)
    assert receipt["status"] == "passed"
    assert receipt["contract_sha256"] == _sha(CONTRACT)
    assert receipt["budget"] == {
        "container_commands": 3,
        "external_fixture_verification_fetches": 1,
        "local_fixture_requests": 2,
        "max_container_commands": 3,
        "max_external_fixture_verification_fetches": 1,
        "max_local_fixture_requests": 2,
        "max_model_requests": 2,
        "max_rt_vlm_http_requests": 10,
        "model_requests": 2,
        "rt_vlm_http_requests": 10,
    }
    assert receipt["plain_http"]["markers_in_chronological_order"] is True
    assert receipt["https"]["animation_classification_positive"] is True
    assert receipt["https_fixture"]["tls_verification_enabled"] is True
    assert receipt["adjacent_negatives"]["loopback_ssrf"]["http_status"] == 422
    assert receipt["adjacent_negatives"]["redirect_disabled"]["http_status"] == 422
    assert all(value is True for key, value in receipt["cleanup"].items() if key.endswith(("exactly", "stopped", "absent")))


def test_retained_receipt_has_no_sensitive_or_raw_fields() -> None:
    forbidden_keys = {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "request_id",
        "session_id",
        "access_token",
        "refresh_token",
        "sdp",
        "ice",
        "caption_content",
        "prompt",
        "semantic_output",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert key.casefold() not in forbidden_keys
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            lowered = value.casefold()
            assert "nvapi-" not in lowered
            assert "bearer " not in lowered

    walk(_load(RECEIPT))
