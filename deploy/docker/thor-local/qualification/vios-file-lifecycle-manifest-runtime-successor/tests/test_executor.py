from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vios_manifest_executor", HERE / "executor.py")
assert SPEC is not None and SPEC.loader is not None
executor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = executor
SPEC.loader.exec_module(executor)


def test_contract_binds_three_exact_manifest_rows() -> None:
    contract = executor._load(HERE / "contract.json")
    assert contract["official_indices"] == [412, 415, 416]
    assert contract["capability_ids"] == executor.CAPABILITY_IDS
    assert len(executor._source_locks(contract)) == 2


def test_retained_receipt_is_schema_valid_and_contract_bound() -> None:
    receipt = executor._load(HERE / "runtime-receipt.json")
    schema = executor._load(HERE / "receipt.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["contract_sha256"] == executor._sha(HERE / "contract.json")


def test_receipt_proves_upload_clip_snapshot_and_cleanup() -> None:
    receipt = executor._load(HERE / "runtime-receipt.json")
    assert receipt["upload_registration"]["stable_file_sensor_stream_identifiers"] is True
    assert receipt["downloads"]["full_file"]["byte_identical_to_upload"] is True
    assert receipt["downloads"]["clip"]["distinct_from_full_file"] is True
    assert receipt["downloads"]["clip"]["duration_seconds"] == 1.2
    assert receipt["snapshot"]["visual_marker_correlated"] is True
    assert receipt["snapshot"]["source_rgb_mean_absolute_error"] <= 20.0
    assert receipt["cleanup"]["exact_file_list_restored"] is True
    assert receipt["cleanup"]["exact_sensor_list_restored"] is True


def test_receipt_retains_no_raw_uuid() -> None:
    raw = (HERE / "runtime-receipt.json").read_text()
    assert re.search(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        raw,
    ) is None
