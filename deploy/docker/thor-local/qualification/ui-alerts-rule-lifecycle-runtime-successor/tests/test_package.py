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


def test_regression_source_uses_canonical_sensor_stream_catalog() -> None:
    source = (REPO / "services/ui/packages/nv-metropolis-bp-vss-ui/alerts/lib-src/utils/vstSensorList.ts").read_text()
    assert "Promise.all" in source
    assert "`${base}/v1/live/streams`" in source
    assert "`${base}/v1/sensor/streams`" in source
    assert "canonicalUrlByStreamId.get(stream.streamId)" in source


def test_receipt_retains_no_raw_stream_url_or_runtime_uuid() -> None:
    raw = (HERE / "runtime-receipt.json").read_text()
    assert "http://" not in raw and "https://" not in raw and "rtsp://" not in raw
    assert "3158c02f-c184-45ec-905c-35253ab4119a" not in raw
