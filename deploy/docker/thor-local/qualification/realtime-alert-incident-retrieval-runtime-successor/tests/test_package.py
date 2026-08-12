from __future__ import annotations

import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]


def test_receipt_validates_and_restores_exact_state() -> None:
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]


def test_every_filter_and_identity_contract_passed() -> None:
    retrieval = json.loads((HERE / "runtime-receipt.json").read_text())["retrieval"]
    assert retrieval["rule_identity_propagated"] is True
    assert retrieval["generated_incident_count"] >= 1
    assert retrieval["control_incident_count"] == 4
    assert retrieval["all_filters_combined"] is True
    assert retrieval["stable_incident_and_rule_identity"] is True
    assert retrieval["evidence_references_only_for_matching_records"] is True
    assert retrieval["filter_names"] == [
        "alert_rule_id", "stream_id", "sensor_id", "category", "start_time", "end_time",
    ]


def test_adjacent_negative_and_cleanup_passed() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["retrieval"]["unknown_rule_returns_empty"] is True
    assert receipt["retrieval"]["malformed_rule_rejected"] is True
    assert receipt["cleanup"]["owned_artifacts_absent"] is True
    assert receipt["cleanup"]["publisher_stopped"] is True
    assert receipt["cleanup"]["running_container_set_preserved"] is True


def test_verifier_passes() -> None:
    result = subprocess.run(
        ["python3", str(HERE / "verify.py")],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["status"] == "passed"


def test_harness_is_syntax_valid_and_default_inert() -> None:
    subprocess.run(["python3", "-m", "py_compile", str(HERE / "harness.py")], check=True)
    result = subprocess.run(
        ["python3", str(HERE / "harness.py")],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--ack" in result.stderr


def test_receipt_retains_no_raw_url_or_runtime_identity() -> None:
    raw = (HERE / "runtime-receipt.json").read_text()
    assert "http://" not in raw and "https://" not in raw and "rtsp://" not in raw
    assert "thor-incident-" not in raw
