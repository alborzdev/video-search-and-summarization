from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_file_rtsp_manifest_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_compiled_receipt_is_exactly_checked_in() -> None:
    assert compiler._load(HERE / "runtime-receipt.json") == compiler.build_receipt()


def test_receipt_is_schema_valid_and_exactly_bound() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    schema = compiler._load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == compiler._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [413]


def test_file_is_republished_and_consumed_over_rtsp() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    proof = receipt["republish"]
    assert proof["automatic_output"] == "RTSP"
    assert proof["rtsp_video_codec"] == "h264"
    assert proof["live_snapshot_decoded"] is True
    assert proof["webrtc_first_frame_observed"] is True
    assert proof["webrtc_clock_advanced"] is True


def test_cleanup_and_policy_boundaries_are_exact() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert all(receipt["cleanup"].values())
    assert receipt["policy"]["main_vios_sensor_additions"] == 0
    assert receipt["policy"]["raw_stream_identifiers_retained"] is False
