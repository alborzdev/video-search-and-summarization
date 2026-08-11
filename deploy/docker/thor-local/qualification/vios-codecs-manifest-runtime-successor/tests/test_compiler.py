from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_codecs_manifest_compiler", HERE / "compiler.py")
assert SPEC is not None and SPEC.loader is not None
compiler = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compiler
SPEC.loader.exec_module(compiler)


def test_compiled_receipt_is_exactly_checked_in() -> None:
    assert compiler._load(HERE / "runtime-receipt.json") == compiler.build_receipt()


def test_receipt_is_strict_schema_valid_and_exactly_bound() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    schema = compiler._load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == compiler._sha(HERE / "contract.json")
    assert receipt["official_indices"] == [420, 421, 422, 424]


def test_four_literal_semantics_are_independently_proven() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert receipt["b_frame_handling"]["input_b_frames"] == 2
    assert receipt["b_frame_handling"]["decoded_frames"] == 120
    assert receipt["hevc_multislice_rfc7798"]["slices_per_picture"] == 4
    assert receipt["hevc_multislice_rfc7798"]["rtsp_decoded_frames"] == 120
    assert all(value is True for key, value in receipt["h264_h265"].items() if key != "software_output_b_frames")
    assert receipt["h264_h265"]["software_output_b_frames"] == 0
    assert receipt["audio_rtsp_republish"]["working_transcode_substitute"] is True


def test_cleanup_and_unclaimed_audio_recording_boundary() -> None:
    receipt = compiler._load(HERE / "runtime-receipt.json")
    assert all(receipt["cleanup"].values())
    assert receipt["policy"]["audio_recording_claimed"] is False
    assert receipt["policy"]["main_vios_sensor_additions"] == 0
