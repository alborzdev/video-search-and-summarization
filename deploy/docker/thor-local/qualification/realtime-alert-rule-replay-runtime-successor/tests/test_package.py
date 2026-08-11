from __future__ import annotations

import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[4]


def test_receipt_validates_and_restores_exact_unrelated_state() -> None:
    schema = json.loads((HERE / "receipt.schema.json").read_text())
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["cleanup"]["before_sha256"] == receipt["cleanup"]["after_sha256"]


def test_replay_semantics_are_literal_and_complete() -> None:
    receipt = json.loads((HERE / "runtime-receipt.json").read_text())
    replay = receipt["replay"]
    assert replay["replay_count"] == replay["replay_success_count"] == 2
    assert replay["immutable_identity_preserved"] is True
    assert replay["immutable_config_preserved"] is True
    assert replay["created_at_preserved"] is True
    assert replay["replay_timestamp_advanced"] is True
    assert replay["one_public_rule_after_each_replay"] is True
    assert replay["one_persisted_rule_after_each_replay"] is True
    assert replay["one_rtvlm_stream_after_each_replay"] is True
    assert replay["one_caption_worker_after_each_replay"] is True
    assert replay["worker_created_counts"] == [2, 3]
    assert replay["worker_removed_counts"] == [1, 2]


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
    subprocess.run(["node", "--check", str(HERE / "harness.mjs")], check=True)
    result = subprocess.run(
        ["node", str(HERE / "harness.mjs")],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "missing_ack" in result.stderr


def test_receipt_retains_no_raw_stream_url_or_runtime_uuid() -> None:
    raw = (HERE / "runtime-receipt.json").read_text()
    assert "http://" not in raw and "https://" not in raw and "rtsp://" not in raw
    assert "20260811e" not in raw
