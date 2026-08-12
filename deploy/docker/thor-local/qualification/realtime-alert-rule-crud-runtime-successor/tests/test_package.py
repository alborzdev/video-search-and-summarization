from __future__ import annotations

import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]


def receipt() -> dict:
    return json.loads((HERE / "runtime-receipt.json").read_text())


def test_receipt_validates_and_restores_exact_state() -> None:
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt())
    assert receipt()["cleanup"]["before_sha256"] == receipt()["cleanup"]["after_sha256"]


def test_immutable_replacement_lifecycle_passed() -> None:
    lifecycle = receipt()["lifecycle"]
    assert lifecycle["prompt_source_validation"] is True
    assert lifecycle["unknown_update_no_create"] is True
    assert lifecycle["immutable_distinct_rule_ids"] is True
    assert lifecycle["immutable_config_preserved"] is True
    assert lifecycle["one_shared_stream"] is True
    assert lifecycle["distinct_request_ids"] is True
    assert lifecycle["replacement_active_after_old_delete"] is True
    assert lifecycle["replacement_incident_count"] >= 1
    assert lifecycle["replacement_incident_correlated"] is True


def test_delete_negative_and_cleanup_passed() -> None:
    result = receipt()
    assert result["lifecycle"]["old_rule_absent_after_delete"] is True
    assert result["lifecycle"]["repeated_delete_explicit_not_found"] is True
    assert result["cleanup"]["owned_raw_index_absent"] is True
    assert result["cleanup"]["owned_artifacts_absent"] is True
    assert result["cleanup"]["publisher_stopped"] is True
    assert result["cleanup"]["running_container_set_preserved"] is True


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
    assert "thor-rule-crud-" not in raw
