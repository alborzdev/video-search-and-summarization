import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lvs_offsets_execute", PACKAGE / "execute.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Base:
    @staticmethod
    def _json_response(response):
        return json.loads(response.body)

    @staticmethod
    def _decode(raw):
        return json.loads(raw)


def _positive(start=3.0, end=6.0, semantic="green in-range phase"):
    content = json.dumps({"events": [{"start_time": start, "end_time": end, "type": semantic, "description": semantic}], "total_events": 1, "uuids": ["owned"], "video_summary": semantic})
    value = {"id": "8381fdc7-1fb7-4fa4-8f97-59c3170fb232", "video_id": "owned", "model": "nim_nvidia_cosmos3-nano-reasoner_bf16-final", "media_info": {"type": "offset", "start_offset": 3, "end_offset": 6}, "choices": [{"message": {"content": content}}], "usage": {"total_chunks_processed": 1}}
    return SimpleNamespace(status=200, body=json.dumps(value).encode(), content_type="application/json")


def test_default_plan_is_inert():
    result = subprocess.run([sys.executable, str(PACKAGE / "execute.py"), "plan"], check=True, capture_output=True, text=True)
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "inert_offsets_plan_valid"
    assert receipt["actions"] == 0
    assert receipt["writes_or_lifecycle_actions"] is False


def test_source_locks_are_current():
    MODULE._verify_static(MODULE._load_json(PACKAGE / "contract.json"))


def test_positive_request_contains_exact_offset_selector():
    body = json.loads(MODULE._request("owned", "model", {"type": "offset", "start_offset": 3, "end_offset": 6}))
    assert body["media_info"] == {"type": "offset", "start_offset": 3, "end_offset": 6}


def test_negative_request_contains_reversed_range():
    body = json.loads(MODULE._request("owned", "model", {"type": "offset", "start_offset": 6, "end_offset": 3}))
    assert body["media_info"]["start_offset"] >= body["media_info"]["end_offset"]


def test_positive_oracle_accepts_only_in_range_event():
    result = MODULE._validate_positive(Base, _positive(), "owned", MODULE._load_json(PACKAGE / "contract.json"))
    assert result["original_timeline_timestamps"] is True
    assert result["out_of_range_markers_absent"] is True


@pytest.mark.parametrize("start,end", [(0, 3), (3, 7), (0, 9)])
def test_out_of_range_timestamps_are_rejected(start, end):
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_positive(Base, _positive(start=start, end=end), "owned", MODULE._load_json(PACKAGE / "contract.json"))


@pytest.mark.parametrize("semantic", ["blue outside before", "red outside after"])
def test_out_of_range_semantics_are_rejected(semantic):
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_positive(Base, _positive(semantic=semantic), "owned", MODULE._load_json(PACKAGE / "contract.json"))


def test_reversed_range_422_is_accepted():
    response = SimpleNamespace(status=422, body=json.dumps({"code": "InvalidParameters", "message": "invalid range"}).encode(), content_type="application/json")
    assert MODULE._validate_negative(Base, response)["reversed_range_rejected"] is True


def test_non_422_negative_is_rejected():
    response = SimpleNamespace(status=200, body=json.dumps({"code": "none", "message": "none"}).encode(), content_type="application/json")
    with pytest.raises(MODULE.QualificationError):
        MODULE._validate_negative(Base, response)
