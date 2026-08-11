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


def test_restart_recovery_replaces_instead_of_stacking_workers() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    always_on = receipt["always_on"]
    assert always_on["initial_start_success"] is True
    assert always_on["duplicate_before_restart_idempotent"] is True
    assert always_on["alert_bridge_restart_performed"] is True
    assert always_on["restart_replay_success"] is True
    assert always_on["restart_replaced_worker_exactly_once"] is True
    assert always_on["duplicate_after_restart_idempotent"] is True
    assert always_on["worker_created_counts"] == [1, 1, 2, 2, 2]
    assert always_on["worker_removed_counts"] == [0, 0, 1, 1, 2]


def test_removal_and_cleanup_are_complete() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    assert receipt["always_on"]["camera_remove_success"] is True
    assert receipt["always_on"]["lifecycle_stream_removed"] is True
    assert receipt["cleanup"]["owned_artifacts_absent"] is True
    assert receipt["cleanup"]["publisher_stopped"] is True
    assert receipt["cleanup"]["running_container_set_preserved"] is True
    assert receipt["cleanup"]["final_caption_worker_count"] == 0


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
    assert "20260811a" not in raw
