from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_receipt_validates() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)


def test_full_verifier_passes() -> None:
    assert load("verify").main() == 0


def test_exact_candidate_identity_and_interval_are_preserved() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    pipeline = receipt["pipeline"]
    assert pipeline["observation_order"] == ["cv_raw", "behavior_candidate", "vlm_verification"]
    assert pipeline["observation_ms"] == sorted(pipeline["observation_ms"])
    assert pipeline["same_candidate_document_id"] is True
    assert pipeline["same_source_id"] is True
    assert pipeline["sensor_identity_preserved"] is True
    assert pipeline["evidence_interval_preserved"] is True
    assert pipeline["object_ids_preserved"] is True
    assert pipeline["object_timeline_preserved"] is True


def test_local_base64_transport_and_cleanup_are_proven() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["transport"]["alert_bridge_base64_enabled"] is True
    assert receipt["transport"]["alert_bridge_base64_request_logged"] is True
    assert receipt["transport"]["rtvlm_data_url_logged"] is True
    assert receipt["transport"]["local_chat_completion_200"] is True
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]
    assert receipt["cleanup"]["owned_elastic_documents_absent"] is True
    assert receipt["cleanup"]["owned_temp_files_absent"] is True
    assert receipt["policy"] == {
        "agent_generate_request_count": 0,
        "external_network_requests": 0,
        "numeric_local_endpoints_only": True,
        "warehouse_sample_bundle": "excluded",
    }


def test_main_alert_snapshot_path_uses_shared_inline_transport() -> None:
    enhancer = (HERE.parents[4] / "services/alert/enhance_alert_with_vlm.py").read_text()
    handler = (HERE.parents[4] / "services/alert/handlers/direct_media/direct_media_handler.py").read_text()
    assert "self.direct_media_handler.analyze_image_urls(" in enhancer
    assert "resolve_vlm_media_source_using_base64" in enhancer
    assert "def analyze_image_urls(" in handler
